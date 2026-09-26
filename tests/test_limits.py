import pytest
from starlette.requests import Request

from app.limits import DAY, HOUR, Limits, RateLimiter, Verdict, client_ip


class Clock:
    def __init__(self, start: float = 1_790_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        """The current fake time."""
        return self.now


def make(per_hour: int = 5, per_day: int = 20, cap: int = 1000) -> tuple[RateLimiter, Clock]:
    clock = Clock()
    return RateLimiter(limits=Limits(per_hour=per_hour, per_day=per_day, daily_cap=cap), clock=clock), clock


def test_five_per_hour_then_limited() -> None:
    limiter, _ = make()
    assert [limiter.check_and_record("1.2.3.4") for _ in range(5)] == [Verdict.ALLOWED] * 5
    assert limiter.check_and_record("1.2.3.4") is Verdict.IP_LIMITED


def test_limit_is_per_ip() -> None:
    limiter, _ = make()
    for _ in range(5):
        limiter.check_and_record("1.2.3.4")
    assert limiter.check_and_record("5.6.7.8") is Verdict.ALLOWED


def test_hourly_window_slides() -> None:
    limiter, clock = make()
    for _ in range(5):
        limiter.check_and_record("1.2.3.4")
    clock.now += HOUR + 1
    assert limiter.check_and_record("1.2.3.4") is Verdict.ALLOWED


def test_twenty_per_day() -> None:
    limiter, clock = make()
    allowed = 0
    for _ in range(10):  # 10 hours, 5 attempts each: only 20 may pass
        for _ in range(5):
            allowed += limiter.check_and_record("1.2.3.4") is Verdict.ALLOWED
        clock.now += HOUR + 1
    assert allowed == 20
    clock.now += DAY
    assert limiter.check_and_record("1.2.3.4") is Verdict.ALLOWED


def test_refused_requests_do_not_count() -> None:
    limiter, clock = make()
    for _ in range(5):
        limiter.check_and_record("1.2.3.4")
    for _ in range(50):
        limiter.check_and_record("1.2.3.4")
    clock.now += HOUR + 1
    assert limiter.check_and_record("1.2.3.4") is Verdict.ALLOWED


def test_global_daily_cap() -> None:
    limiter, _ = make(cap=3)
    assert [limiter.check_and_record(f"10.0.0.{i}") for i in range(3)] == [Verdict.ALLOWED] * 3
    assert limiter.check_and_record("10.0.0.99") is Verdict.CAPPED
    assert limiter.count_today == 3


def test_daily_cap_resets_at_utc_midnight() -> None:
    limiter, clock = make(cap=1)
    limiter.check_and_record("10.0.0.1")
    assert limiter.check_and_record("10.0.0.2") is Verdict.CAPPED
    clock.now = (clock.now // DAY + 1) * DAY  # next midnight UTC
    assert limiter.check_and_record("10.0.0.2") is Verdict.ALLOWED


def test_cap_takes_precedence_over_ip_limit() -> None:
    limiter, _ = make(per_hour=1, cap=1)
    limiter.check_and_record("1.2.3.4")
    assert limiter.check_and_record("1.2.3.4") is Verdict.CAPPED


def test_addresses_are_not_stored_in_clear() -> None:
    limiter, _ = make()
    limiter.check_and_record("1.2.3.4")
    assert "1.2.3.4" not in repr(limiter._hits)


def test_limits_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILY_REQUEST_CAP", "7")
    monkeypatch.setenv("RATE_LIMIT_PER_HOUR", "2")
    limits = Limits.from_env()
    assert (limits.daily_cap, limits.per_hour, limits.per_day) == (7, 2, 20)


def _request(headers: dict[str, str], peer: str = "10.1.1.1") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (peer, 1234)})


def test_client_ip_uses_rightmost_forwarded_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLIENT_IP_HEADER", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    # A client-supplied spoofed entry on the left must not win.
    assert client_ip(_request({"X-Forwarded-For": "6.6.6.6, 1.2.3.4"})) == "1.2.3.4"


def test_client_ip_hops_and_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    assert client_ip(_request({"X-Forwarded-For": "6.6.6.6, 1.2.3.4, 9.9.9.9"})) == "1.2.3.4"
    monkeypatch.setenv("CLIENT_IP_HEADER", "CF-Connecting-IP")
    assert client_ip(_request({"CF-Connecting-IP": "8.8.8.8", "X-Forwarded-For": "1.1.1.1"})) == "8.8.8.8"


def test_client_ip_falls_back_to_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLIENT_IP_HEADER", raising=False)
    assert client_ip(_request({})) == "10.1.1.1"
