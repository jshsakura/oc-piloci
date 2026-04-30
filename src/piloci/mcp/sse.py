from __future__ import annotations

import logging
from collections.abc import Callable

import anyio
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http import StreamableHTTPServerTransport
from starlette.responses import JSONResponse, Response

from piloci.auth.jwt_utils import verify_token
from piloci.config import get_settings
from piloci.mcp.session_state import build_session_tracker, mcp_auth_ctx, mcp_session_ctx
from piloci.notify.telegram import send_session_summary

logger = logging.getLogger(__name__)


def _auth(headers_raw: list) -> tuple[dict, str | None]:
    """Extract and verify Bearer token. Returns (auth_payload, error_msg)."""
    headers = {k: v for k, v in headers_raw}
    auth_header = headers.get(b"authorization", b"").decode()
    if not auth_header.startswith("Bearer "):
        return {}, "missing bearer token"
    token = auth_header[7:]
    try:
        settings = get_settings()
        payload = verify_token(token, settings)
        payload["_raw_token"] = token
        return payload, None
    except ValueError as e:
        return {}, str(e)


def create_sse_app(mcp_server: Server, *, debug: bool = False, prefix: str = "") -> Callable:
    """Pure ASGI app for MCP — routes /sse (SSE), /messages/ (SSE post), /http (Streamable HTTP)."""
    msg_path = f"{prefix}/messages/" if prefix else "/messages/"
    sse_transport = SseServerTransport(msg_path)

    async def _handle_sse(scope, receive, send) -> None:
        auth_payload, err = _auth(scope.get("headers", []))
        if err:
            logger.warning("MCP SSE auth failed: %s", err)
            await Response("Unauthorized", status_code=401)(scope, receive, send)
            return

        token_ctx = mcp_auth_ctx.set(auth_payload)
        session_ctx = mcp_session_ctx.set(build_session_tracker(auth_payload))
        try:
            async with sse_transport.connect_sse(scope, receive, send) as (read, write):
                await mcp_server.run(read, write, mcp_server.create_initialization_options())
        finally:
            tracker = mcp_session_ctx.get()
            if tracker is not None:
                try:
                    await send_session_summary(tracker, get_settings())
                except Exception as e:
                    logger.warning("Telegram MCP session notify failed: %s", e)
            mcp_session_ctx.reset(session_ctx)
            mcp_auth_ctx.reset(token_ctx)

    async def _handle_streamable_http(scope, receive, send) -> None:
        auth_payload, err = _auth(scope.get("headers", []))
        if err:
            logger.warning("MCP HTTP auth failed: %s", err)
            await Response("Unauthorized", status_code=401)(scope, receive, send)
            return

        http_transport = StreamableHTTPServerTransport(mcp_session_id=None)

        async def _run_server(*, task_status=anyio.TASK_STATUS_IGNORED):
            async with http_transport.connect() as (read, write):
                task_status.started()
                await mcp_server.run(
                    read, write, mcp_server.create_initialization_options(), stateless=True
                )

        token_ctx = mcp_auth_ctx.set(auth_payload)
        session_ctx = mcp_session_ctx.set(build_session_tracker(auth_payload))
        try:
            async with anyio.create_task_group() as tg:
                await tg.start(_run_server)
                await http_transport.handle_request(scope, receive, send)
                await http_transport.terminate()
        finally:
            mcp_auth_ctx.reset(token_ctx)
            mcp_session_ctx.reset(session_ctx)

    async def app(scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return
        if scope["type"] != "http":
            return

        raw_path = scope.get("path", "")
        # Normalize: strip any mount prefix so both "/sse" and "/mcp/sse" work
        path = raw_path.rstrip("/")
        for suffix in ("/http", "/sse", "/messages", "/healthz"):
            if path.endswith(suffix):
                path = suffix
                break

        method = scope.get("method", "GET")

        if path == "/http":
            await _handle_streamable_http(scope, receive, send)
        elif path == "/sse" and method == "GET":
            await _handle_sse(scope, receive, send)
        elif raw_path.find("/messages/") != -1 and method == "POST":
            await sse_transport.handle_post_message(scope, receive, send)
        elif path == "/healthz":
            await JSONResponse({"status": "ok"})(scope, receive, send)
        else:
            await Response("Not Found", status_code=404)(scope, receive, send)

    return app
