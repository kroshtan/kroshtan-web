"""
``POST /api/ask``, the "Can I help with this?" box.

The visitor's question is wrapped in the fixed system prompt (``prompts/assess.md`` plus the site's content and
the private notes) and sent to the Anthropic API; the answer streams back as plain text.

Privacy: the question is held in memory for the duration of the request and never written anywhere. Logs carry
counts only (see ``app/limits.py``). The API key lives only in the server's environment.
"""

import logging
import os
from collections.abc import AsyncIterator
from functools import cache

import anthropic
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app import content
from app.context import system_prompt
from app.limits import Limits, RateLimiter, Verdict, client_ip

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 1500
MIN_QUESTION_CHARS = 10

router = APIRouter()
limiter = RateLimiter(limits=Limits.from_env())


def llm_model() -> str:
    """The model to ask; overridable with ``LLM_MODEL``."""
    return os.environ.get("LLM_MODEL") or "claude-sonnet-5"


def llm_max_tokens() -> int:
    """
    Output ceiling per answer, ``LLM_MAX_TOKENS``.

    The prompt asks for at most ~150 words (~250 tokens). The ceiling leaves room for adaptive thinking on top of
    that while still capping what one question can cost.

    :return: the ceiling
    """
    return int(os.environ.get("LLM_MAX_TOKENS", "1200"))


def ask_enabled() -> bool:
    """The question box is shown only when an API key is configured."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@cache
def client() -> anthropic.AsyncAnthropic:
    """
    One shared async client for the process.

    :return: the client
    """
    return anthropic.AsyncAnthropic(timeout=60.0, max_retries=1)


class Question(BaseModel):
    question: str = Field(max_length=MAX_QUESTION_CHARS)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        """
        Trim and require a question of some substance.

        :param value: the submitted text
        :return: the trimmed text
        :raises ValueError: when it is too short to assess
        """
        value = value.strip()
        if len(value) < MIN_QUESTION_CHARS:
            raise ValueError(f"Please describe your problem in at least {MIN_QUESTION_CHARS} characters.")
        return value


def _refusal(status: int, message: str) -> JSONResponse:
    return JSONResponse({"message": message}, status_code=status, headers={"Cache-Control": "no-store"})


def _fallback(email: str) -> str:
    return f"Something went wrong on my side. Please email me directly at {email}."


async def _stream_answer(question: str) -> AsyncIterator[str]:
    """
    Stream the model's answer as text chunks.

    Errors after the response has started cannot change the status code any more, so they end the stream with
    a plain-text pointer to email instead.

    :param question: the validated visitor question
    :yield: text chunks
    """
    email = content.site_config().email
    started = False
    try:
        async with client().messages.stream(
            model=llm_model(),
            max_tokens=llm_max_tokens(),
            system=[{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"<visitor_question>\n{question}\n</visitor_question>"}],
            output_config={"effort": "low"},
        ) as stream:
            async for text in stream.text_stream:
                started = True
                yield text
            final = await stream.get_final_message()
    except anthropic.APIError as exc:
        # The exception carries status and type, never the prompt, so it is safe to log.
        logger.warning("ask: upstream error %s", type(exc).__name__)
        yield ("\n\n" if started else "") + _fallback(email)
        return

    if final.stop_reason == "refusal":
        yield f"\n\nI can't assess this one here. Please email me at {email}."
    elif final.stop_reason == "max_tokens":
        yield f"…\n\nThe rest is better discussed by email: {email}."


@router.post("/api/ask")
async def ask(payload: Question, request: Request) -> Response:
    """
    Assess whether Floris can help with the visitor's problem.

    :param payload: the visitor's question
    :param request: the incoming request, for the client address
    :return: a streamed plain-text answer, or a JSON ``{"message": ...}`` with 429/503
    """
    email = content.site_config().email
    if not ask_enabled():
        return _refusal(503, f"This feature isn't available right now. Please email me at {email}.")

    verdict = limiter.check_and_record(client_ip(request))
    if verdict is Verdict.CAPPED:
        return _refusal(
            503,
            f"I've had a lot of questions today and the assistant is resting until tomorrow. "
            f"Please email me directly at {email}.",
        )
    if verdict is Verdict.IP_LIMITED:
        return _refusal(
            429,
            f"You've asked a few questions already. To keep this free for everyone there's a limit per visitor; "
            f"please email me at {email} and we can talk it through.",
        )

    return StreamingResponse(
        _stream_answer(payload.question),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
