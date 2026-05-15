from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from piloci.mcp.session_state import mcp_auth_ctx, mcp_session_ctx
from piloci.mcp.sse import create_sse_app


class _FakeSseTransport:
    instances: list[_FakeSseTransport] = []

    def __init__(self, msg_path: str):
        self.msg_path = msg_path
        self.connect_calls: list[tuple[dict[str, Any], object, object]] = []

        async def _handle_post_message(scope: object, receive: object, send: object) -> None:
            return None

        self.handle_post_message = _handle_post_message
        self.__class__.instances.append(self)

    @asynccontextmanager
    async def connect_sse(self, scope: dict[str, Any], receive: object, send: object):
        self.connect_calls.append((scope, receive, send))
        yield "read-stream", "write-stream"


def test_create_sse_app_registers_expected_routes_and_prefix():
    _FakeSseTransport.instances.clear()
    mock_server = MagicMock()

    with patch("piloci.mcp.sse.SseServerTransport", _FakeSseTransport):
        app = create_sse_app(mock_server, debug=True, prefix="/mcp")

    transport = _FakeSseTransport.instances[-1]
    assert transport.msg_path == "/mcp/messages/"
    assert callable(app)


def test_healthz_endpoint():
    mock_server = MagicMock()
    app = create_sse_app(mock_server, debug=True, prefix="/mcp")
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_handle_sse_verifies_bearer_sets_context_and_runs_server():
    _FakeSseTransport.instances.clear()
    mcp_server = MagicMock()
    mcp_server.run = AsyncMock()
    mcp_server.create_initialization_options.return_value = {"server": "ready"}
    settings = SimpleNamespace(telegram_bot_token=None, telegram_chat_id=None)
    auth_payload = {"sub": "user-1", "project_id": "project-1", "jti": "session-1"}

    responses: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        responses.append(msg)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/sse",
        "headers": [(b"authorization", b"Bearer test-token")],
        "query_string": b"",
    }

    send_summary = AsyncMock(return_value=False)

    assert mcp_auth_ctx.get() is None
    assert mcp_session_ctx.get() is None

    with patch("piloci.mcp.sse.SseServerTransport", _FakeSseTransport):
        app = create_sse_app(mcp_server, prefix="/mcp")

    with (
        patch("piloci.mcp.sse.get_settings", return_value=settings),
        patch("piloci.mcp.sse.verify_token", return_value=auth_payload) as verify,
        patch("piloci.mcp.sse._validate_bearer_user", AsyncMock(return_value=auth_payload)),
        patch("piloci.mcp.sse.send_session_summary", send_summary),
    ):
        await app(scope, receive, send)

    verify.assert_called_once_with("test-token", settings)
    mcp_server.run.assert_awaited_once_with(
        "read-stream",
        "write-stream",
        {"server": "ready"},
    )
    assert send_summary.await_args is not None
    tracker = send_summary.await_args.args[0]
    assert tracker.user_id == "user-1"
    assert tracker.project_id == "project-1"
    assert tracker.session_id == "session-1"
    assert send_summary.await_args.args[1] is settings
    assert _FakeSseTransport.instances[-1].connect_calls[0][0]["path"] == "/sse"
    assert mcp_auth_ctx.get() is None
    assert mcp_session_ctx.get() is None


@pytest.mark.asyncio
async def test_handle_sse_swallows_summary_errors_and_resets_context():
    _FakeSseTransport.instances.clear()
    mcp_server = MagicMock()
    mcp_server.run = AsyncMock()
    mcp_server.create_initialization_options.return_value = {"server": "ready"}
    settings = SimpleNamespace(telegram_bot_token="bot", telegram_chat_id="chat")
    auth_payload = {"sub": "user-2", "project_id": "project-9", "jti": "session-9"}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        pass

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/sse",
        "headers": [(b"authorization", b"Bearer good-token")],
        "query_string": b"",
    }

    with patch("piloci.mcp.sse.SseServerTransport", _FakeSseTransport):
        app = create_sse_app(mcp_server)

    with (
        patch("piloci.mcp.sse.get_settings", return_value=settings),
        patch("piloci.mcp.sse.verify_token", return_value=auth_payload),
        patch("piloci.mcp.sse._validate_bearer_user", AsyncMock(return_value=auth_payload)),
        patch(
            "piloci.mcp.sse.send_session_summary",
            AsyncMock(side_effect=RuntimeError("telegram down")),
        ),
    ):
        await app(scope, receive, send)

    mcp_server.run.assert_awaited_once()
    assert mcp_auth_ctx.get() is None
    assert mcp_session_ctx.get() is None
