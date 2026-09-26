"""
Rate limiting and the global daily cap for ``/api/ask``.

Everything is in process memory. That is correct for the single Render instance this site runs on; with more
than one instance each would enforce its own limits, and a restart resets them. Neither matters much at this
scale, and the global cap still bounds the worst case per instance.

Nothing here stores what anyone asked. Per-IP buckets are keyed by a salted hash of the address, the salt is
random per process, and the only thing ever logged is a count.
"""

import hashlib
import logging
import os
import secrets
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from starlette.requests import Request

logger = logging.getLogger(__name__)

HOUR = 3600
DAY = 24 * HOUR


class Verdict(Enum):
    ALLOWED = "allowed"
    IP_LIMITED = "ip_limited"
    CAPPED = "capped"


@dataclass
class Limits:
    per_hour: int = 5
    per_day: int = 20
    daily_cap: int = 100

    @classmethod
    def from_env(cls) -> "Limits":
        """
        Read the limits from the environment, falling back to the defaults.

        :return: the configured limits
        """
        return cls(
            per_hour=int(os.environ.get("RATE_LIMIT_PER_HOUR", cls.per_hour)),
            per_day=int(os.environ.get("RATE_LIMIT_PER_DAY", cls.per_day)),
            daily_cap=int(os.environ.get("DAILY_REQUEST_CAP", cls.daily_cap)),
        )


@dataclass
class RateLimiter:
    """
    Sliding-window per-IP limits plus a global cap per UTC calendar day.

    The per-IP windows slide (the last hour, the last 24 hours) so there is no burst at a boundary. The global
    cap resets at midnight UTC because it is a budget, and a budget is easiest to reason about per day.
    """

    limits: Limits = field(default_factory=Limits)
    clock: Callable[[], float] = time.time
    _salt: bytes = field(default_factory=lambda: secrets.token_bytes(16))
    _hits: dict[str, deque[float]] = field(default_factory=dict)
    _day: str = ""
    _day_count: int = 0

    def _key(self, ip: str) -> str:
        return hashlib.blake2b(ip.encode(), key=self._salt, digest_size=16).hexdigest()

    def _today(self, now: float) -> str:
        return datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")

    def _prune(self, now: float) -> None:
        # Drop buckets whose newest hit is older than a day, so memory stays bounded by one day's visitors.
        stale = [k for k, hits in self._hits.items() if not hits or hits[-1] <= now - DAY]
        for k in stale:
            del self._hits[k]

    def check_and_record(self, ip: str) -> Verdict:
        """
        Decide whether a question from ``ip`` may go through, and count it if so.

        A refused request is not counted, so hitting a limit does not extend it.

        :param ip: the client's address
        :return: the verdict
        """
        now = self.clock()
        today = self._today(now)
        if today != self._day:
            if self._day:
                logger.info("ask: %d questions on %s", self._day_count, self._day)
            self._day, self._day_count = today, 0
            self._prune(now)

        hits = self._hits.setdefault(self._key(ip), deque())
        while hits and hits[0] <= now - DAY:
            hits.popleft()

        if self._day_count >= self.limits.daily_cap:
            return Verdict.CAPPED
        last_hour = sum(1 for t in hits if t > now - HOUR)
        if last_hour >= self.limits.per_hour or len(hits) >= self.limits.per_day:
            return Verdict.IP_LIMITED

        hits.append(now)
        self._day_count += 1
        logger.info("ask: question %d of %d today", self._day_count, self.limits.daily_cap)
        return Verdict.ALLOWED

    @property
    def count_today(self) -> int:
        """Questions accepted so far today (UTC)."""
        return self._day_count if self._day == self._today(self.clock()) else 0


def client_ip(request: Request) -> str:
    """
    Work out the visitor's address behind Render's proxy.

    ``X-Forwarded-For`` is a list each proxy appends to, and its leftmost entries are whatever the client sent,
    so trusting those would let anyone pick a fresh address per request. The entry ``TRUSTED_PROXY_HOPS`` from
    the right is the one our own proxy chain wrote. ``CLIENT_IP_HEADER`` names a single header set by the edge
    instead (e.g. ``cf-connecting-ip``), for when the platform provides one that clients cannot forge.

    :param request: the incoming request
    :return: the best available client address
    """
    header = os.environ.get("CLIENT_IP_HEADER", "").strip().lower()
    if header and (value := request.headers.get(header)):
        return value.strip()

    forwarded = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    hops = max(1, int(os.environ.get("TRUSTED_PROXY_HOPS", "1")))
    if forwarded:
        return forwarded[-hops] if len(forwarded) >= hops else forwarded[0]
    return request.client.host if request.client else "unknown"
