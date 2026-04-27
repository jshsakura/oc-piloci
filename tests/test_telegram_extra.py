import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from piloci.mcp.session_state import McpSessionTracker
from piloci.notify import telegram


def _tracker(**overrides):
    defaults = dict(
        tool_calls=5,
        memory_saves=2,
        memory_forgets=0,
        recall_calls=1,
        list_projects_calls=0,
        whoami_calls=0,
        project_id="proj-1",
        tags={"tag-a"},
        session_id="sess-1",
    )
    defaults.update(overrides)
    t = McpSessionTracker(
        **{k: v for k, v in defaults.items() if k in McpSessionTracker.__dataclass_fields__}
    )
    t.tool_calls = defaults.get("tool_calls", 5)
    t.memory_saves = defaults.get("memory_saves", 2)
    t.memory_forgets = defaults.get("memory_forgets", 0)
    t.recall_calls = defaults.get("recall_calls", 1)
    t.list_projects_calls = defaults.get("list_projects_calls", 0)
    t.whoami_calls = defaults.get("whoami_calls", 0)
    t.project_id = defaults.get("project_id")
    t.tags = defaults.get("tags", set())
    t.session_id = defaults.get("session_id")
    t.started_at = time.monotonic() - 125
    return t


def _settings(**overrides):
    defaults = dict(
        telegram_bot_token="bot-token",
        telegram_chat_id="chat-id",
        telegram_min_duration_sec=60,
        telegram_min_memory_ops=1,
        telegram_timeout_sec=5,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestShouldSendSessionSummary:
    def test_false_when_no_tracker(self):
        assert telegram.should_send_session_summary(None, _settings()) is False

    def test_false_when_zero_tool_calls(self):
        t = McpSessionTracker()
        t.tool_calls = 0
        assert telegram.should_send_session_summary(t, _settings()) is False

    def test_false_when_no_bot_token(self):
        t = _tracker()
        assert telegram.should_send_session_summary(t, _settings(telegram_bot_token="")) is False

    def test_true_when_duration_met(self):
        t = _tracker()
        t.started_at = time.monotonic() - 120
        assert telegram.should_send_session_summary(t, _settings()) is True

    def test_true_when_memory_ops_met(self):
        t = McpSessionTracker()
        t.tool_calls = 5
        t.memory_saves = 5
        assert telegram.should_send_session_summary(t, _settings()) is True


class TestFormatSessionSummary:
    def test_basic_format(self):
        t = _tracker()
        t.started_at = time.monotonic() - 125
        text = telegram.format_session_summary(t)
        assert "📋" in text
        assert "save" in text
        assert "recall" in text

    def test_all_stats(self):
        t = _tracker(
            memory_saves=5,
            memory_forgets=1,
            recall_calls=3,
            list_projects_calls=2,
            whoami_calls=4,
        )
        t.started_at = time.monotonic() - 300
        text = telegram.format_session_summary(t)
        assert "5 save" in text
        assert "3 recall" in text
        assert "1 forget" in text
        assert "2 projects" in text
        assert "4 whoami" in text

    def test_truncation(self):
        t = _tracker(tags={f"tag-{i}" for i in range(100)}, memory_saves=0, recall_calls=0)
        text = telegram.format_session_summary(t)
        assert len(text) <= 4096


class TestSendSessionSummary:
    @pytest.mark.asyncio
    async def test_returns_false_when_should_not_send(self):
        t = McpSessionTracker()
        result = await telegram.send_session_summary(t, _settings(telegram_bot_token=""))
        assert result is False

    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        t = _tracker()
        with patch("piloci.notify.telegram.httpx.AsyncClient", return_value=mock_client):
            result = await telegram.send_session_summary(t, _settings())
        assert result is True

    @pytest.mark.asyncio
    async def test_retry_on_429(self):
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.json.return_value = {"parameters": {"retry_after": 0}}

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[resp_429, resp_ok])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        t = _tracker()
        with (
            patch("piloci.notify.telegram.httpx.AsyncClient", return_value=mock_client),
            patch("piloci.notify.telegram.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await telegram.send_session_summary(t, _settings())
        assert result is True

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.json.return_value = {"parameters": {"retry_after": 0}}
        resp_429.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Too Many Requests", request=MagicMock(), response=resp_429
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp_429)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        t = _tracker()
        with (
            patch("piloci.notify.telegram.httpx.AsyncClient", return_value=mock_client),
            patch("piloci.notify.telegram.asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await telegram.send_session_summary(t, _settings())


class TestSendAdminNotification:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_config(self):
        result = await telegram.send_admin_notification("test", _settings(telegram_bot_token=""))
        assert result is False

    @pytest.mark.asyncio
    async def test_sends_notification(self):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("piloci.notify.telegram.httpx.AsyncClient", return_value=mock_client):
            result = await telegram.send_admin_notification("hello", _settings())
        assert result is True
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["text"] == "hello"

    @pytest.mark.asyncio
    async def test_truncates_long_text(self):
        long_text = "x" * 5000
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("piloci.notify.telegram.httpx.AsyncClient", return_value=mock_client):
            result = await telegram.send_admin_notification(long_text, _settings())
        assert result is True
        sent_text = mock_client.post.call_args[1]["json"]["text"]
        assert len(sent_text) == 4096
