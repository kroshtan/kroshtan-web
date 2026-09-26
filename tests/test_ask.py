from collections.abc import AsyncIterator, Iterator
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from app import ask
from app.limits import Limits, RateLimiter

QUESTION = {"question": "We have a working churn model in a notebook and want it running on GCP."}


class FakeStream:
    def __init__(self, chunks: list[str], stop_reason: str = "end_turn", fail: Exception | None = None) -> None:
        self.chunks, self.stop_reason, self.fail = chunks, stop_reason, fail

    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    @property
    async def text_stream(self) -> AsyncIterator[str]:
        for chunk in self.chunks:
            yield chunk
        if self.fail:
            raise self.fail

    async def get_final_message(self) -> SimpleNamespace:
        return SimpleNamespace(stop_reason=self.stop_reason)


class FakeClient:
    def __init__(self, stream: FakeStream) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(stream=self._stream)
        self._next = stream

    def _stream(self, **kwargs: Any) -> FakeStream:
        self.calls.append(kwargs)
        return self._next


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeClient]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ask, "limiter", RateLimiter(limits=Limits(per_hour=5, per_day=20, daily_cap=100)))
    client = FakeClient(FakeStream(["**Yes, good fit.** ", "From notebook to production."]))
    monkeypatch.setattr(ask, "client", lambda: client)
    yield client


def test_answer_is_streamed(client: TestClient, fake: FakeClient) -> None:
    response = client.post("/api/ask", json=QUESTION)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "**Yes, good fit.** From notebook to production."


def test_request_shape(client: TestClient, fake: FakeClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "claude-test-model")
    monkeypatch.setenv("LLM_MAX_TOKENS", "321")
    client.post("/api/ask", json=QUESTION)
    call = fake.calls[0]
    assert call["model"] == "claude-test-model"
    assert call["max_tokens"] == 321
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "<public_site_content>" in call["system"][0]["text"]
    user = call["messages"][0]["content"]
    assert user.startswith("<visitor_question>") and QUESTION["question"] in user


def test_default_model_is_sonnet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert ask.llm_model() == "claude-sonnet-5"


def test_rate_limited_after_five(client: TestClient, fake: FakeClient) -> None:
    for _ in range(5):
        assert client.post("/api/ask", json=QUESTION).status_code == 200
    response = client.post("/api/ask", json=QUESTION)
    assert response.status_code == 429
    assert "freelancing@kroshtan.com" in response.json()["message"]
    assert len(fake.calls) == 5


def test_daily_cap_message(client: TestClient, fake: FakeClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ask, "limiter", RateLimiter(limits=Limits(daily_cap=2)))
    for i in range(2):
        client.post("/api/ask", json=QUESTION, headers={"X-Forwarded-For": f"10.0.0.{i}"})
    response = client.post("/api/ask", json=QUESTION, headers={"X-Forwarded-For": "10.0.0.9"})
    assert response.status_code == 503
    assert "freelancing@kroshtan.com" in response.json()["message"]
    assert len(fake.calls) == 2


@pytest.mark.parametrize("question", ["", "   short  ", "x" * 1501])
def test_invalid_questions(client: TestClient, fake: FakeClient, question: str) -> None:
    response = client.post("/api/ask", json={"question": question})
    assert response.status_code == 422
    assert response.json()["message"]
    assert fake.calls == []


def test_disabled_without_api_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.post("/api/ask", json=QUESTION).status_code == 503
    assert "data-ask-form" not in client.get("/").text


def test_box_shown_with_api_key(client: TestClient, fake: FakeClient) -> None:
    for path in ("/", "/contact"):
        html = client.get(path).text
        assert "data-ask-form" in html
        assert "external AI service" in html


def test_upstream_error_falls_back_to_email(client: TestClient, fake: FakeClient) -> None:
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    fake._next = FakeStream(["**Yes"], fail=error)
    response = client.post("/api/ask", json=QUESTION)
    assert response.status_code == 200
    assert response.text.startswith("**Yes\n\n")
    assert "freelancing@kroshtan.com" in response.text


def test_truncated_answer_points_to_email(client: TestClient, fake: FakeClient) -> None:
    fake._next = FakeStream(["Partial"], stop_reason="max_tokens")
    assert "freelancing@kroshtan.com" in client.post("/api/ask", json=QUESTION).text


def test_question_is_not_logged(client: TestClient, fake: FakeClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("DEBUG"):
        client.post("/api/ask", json=QUESTION)
    assert QUESTION["question"] not in caplog.text
    assert "question 1 of" in caplog.text
