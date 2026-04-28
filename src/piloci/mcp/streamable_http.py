from __future__ import annotations

import logging
from collections.abc import Callable

import anyio
from mcp.server import Server
from mcp.server.streamable_http import StreamableHTTPServerTransport
from starlette.responses import Response

from piloci.auth.jwt_utils import verify_token
from piloci.config import get_settings
from piloci.mcp.session_state import build_session_tracker, mcp_auth_ctx, mcp_session_ctx

logger = logging.getLogger(__name__)


def create_streamable_http_app(mcp_server: Server) -> Callable:
    """Pure ASGI app for MCP Streamable HTTP — compatible with Claude Code type:'http'."""

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return

        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()

        if not auth_header.startswith("Bearer "):
            logger.warning("MCP HTTP missing bearer auth")
            await Response("Unauthorized", status_code=401)(scope, receive, send)
            return

        token = auth_header[7:]
        try:
            settings = get_settings()
            auth_payload = verify_token(token, settings)
        except ValueError as e:
            logger.warning("MCP HTTP auth failed: %s", e)
            await Response("Unauthorized", status_code=401)(scope, receive, send)
            return

        http_transport = StreamableHTTPServerTransport(mcp_session_id=None)

        async def _run_server(*, task_status=anyio.TASK_STATUS_IGNORED):
            async with http_transport.connect() as (read, write):
                task_status.started()
                await mcp_server.run(
                    read,
                    write,
                    mcp_server.create_initialization_options(),
                    stateless=True,
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

    return app
