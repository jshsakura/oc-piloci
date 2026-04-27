from __future__ import annotations

import pytest

from piloci.config import Settings
from piloci.notify.telegram import send_admin_notification


def _settings(token="bot-token", chat_id="chat-id"):
    return Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
    )


@pytest.mark.asyncio
async def test_send_admin_notification_no_config():
    settings = _settings(token=None, chat_id=None)
    result = await send_admin_notification("hello", settings)
    assert result is False


@pytest.mark.asyncio
async def test_send_admin_notification_sends_message(monkeypatch):
    settings = _settings()
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("piloci.notify.telegram.httpx.AsyncClient", FakeClient)
    result = await send_admin_notification("admin msg", settings)
    assert result is True
    assert captured["json"]["text"] == "admin msg"
    assert captured["json"]["chat_id"] == "chat-id"


@pytest.mark.asyncio
async def test_send_admin_notification_truncates_long_text(monkeypatch):
    settings = _settings()
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            captured["text"] = json["text"]
            return FakeResponse()

    monkeypatch.setattr("piloci.notify.telegram.httpx.AsyncClient", FakeClient)
    long_text = "x" * 5000
    await send_admin_notification(long_text, settings)
    assert len(captured["text"]) == 4096
