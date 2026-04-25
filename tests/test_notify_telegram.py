from __future__ import annotations

import httpx
import pytest

from piloci.config import Settings
from piloci.mcp.session_state import McpSessionTracker, record_tool_call
from piloci.notify.telegram import (
    format_session_summary,
    send_session_summary,
    should_send_session_summary,
)


def make_settings(
    *,
    telegram_bot_token: str | None = "bot-token",
    telegram_chat_id: str | None = "chat-id",
    telegram_min_duration_sec: int = 300,
    telegram_min_memory_ops: int = 3,
    telegram_timeout_sec: float = 5.0,
) -> Settings:
    return Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        telegram_min_duration_sec=telegram_min_duration_sec,
        telegram_min_memory_ops=telegram_min_memory_ops,
        telegram_timeout_sec=telegram_timeout_sec,
    )


def test_record_tool_call_tracks_counts_and_tags() -> None:
    tracker = McpSessionTracker(project_id="proj-a", session_id="sess-1")

    record_tool_call(tracker, "memory", {"action": "save", "tags": ["auth", "deploy"]})
    record_tool_call(tracker, "recall", {"query": "auth", "tags": ["auth"]})
    record_tool_call(tracker, "memory", {"action": "forget"})
    record_tool_call(tracker, "listProjects", {})
    record_tool_call(tracker, "whoAmI", {})

    assert tracker.tool_calls == 5
    assert tracker.memory_saves == 1
    assert tracker.memory_forgets == 1
    assert tracker.recall_calls == 1
    assert tracker.list_projects_calls == 1
    assert tracker.whoami_calls == 1
    assert tracker.tags == {"auth", "deploy"}


def test_should_send_session_summary_uses_thresholds() -> None:
    settings = make_settings()
    tracker = McpSessionTracker(tool_calls=1, memory_saves=2)
    tracker.started_at -= 10
    assert should_send_session_summary(tracker, settings) is False

    tracker.memory_saves = 3
    assert should_send_session_summary(tracker, settings) is True


def test_format_session_summary_includes_key_fields() -> None:
    tracker = McpSessionTracker(
        project_id="proj-a",
        session_id="sess-1",
        tool_calls=3,
        memory_saves=2,
        recall_calls=1,
        tags={"auth", "deploy"},
    )
    text = format_session_summary(tracker)
    assert "piLoci MCP session" in text
    assert "proj-a" in text
    assert "auth" in text
    assert "deploy" in text


def test_format_session_summary_truncates_long_text() -> None:
    tracker = McpSessionTracker(
        project_id="p" * 5000,
        session_id="sess-1",
        tool_calls=1,
        memory_saves=1,
        tags={"auth"},
    )
    text = format_session_summary(tracker)
    assert len(text) == 4096
    assert text.endswith("...")


@pytest.mark.asyncio
async def test_send_session_summary_posts_to_telegram(monkeypatch) -> None:
    tracker = McpSessionTracker(project_id="proj-a", tool_calls=1, memory_saves=3)
    settings = make_settings()
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict[str, object]):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("piloci.notify.telegram.httpx.AsyncClient", FakeClient)

    sent = await send_session_summary(tracker, settings)

    assert sent is True
    assert captured["timeout"] == 5.0
    assert str(captured["url"]).endswith("/botbot-token/sendMessage")
    assert captured["json"] == {
        "chat_id": "chat-id",
        "text": format_session_summary(tracker),
        "disable_notification": True,
    }


@pytest.mark.asyncio
async def test_send_session_summary_retries_on_rate_limit(monkeypatch) -> None:
    tracker = McpSessionTracker(project_id="proj-a", tool_calls=1, memory_saves=3)
    settings = make_settings()
    attempts = {"count": 0}
    sleeps: list[float] = []

    class FakeResponse:
        def __init__(self, status_code: int, data: dict[str, object]) -> None:
            self.status_code = status_code
            self._data = data

        def json(self) -> dict[str, object]:
            return self._data

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "boom",
                    request=httpx.Request("POST", "https://api.telegram.org"),
                    response=httpx.Response(self.status_code),
                )

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict[str, object]):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return FakeResponse(429, {"parameters": {"retry_after": 1}})
            return FakeResponse(200, {"ok": True})

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("piloci.notify.telegram.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("piloci.notify.telegram.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("piloci.notify.telegram.random.uniform", lambda a, b: 0.0)

    sent = await send_session_summary(tracker, settings)

    assert sent is True
    assert attempts["count"] == 2
    assert sleeps == [1.0]
