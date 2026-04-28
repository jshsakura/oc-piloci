from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from piloci.auth.jwt_utils import verify_token
from piloci.config import get_settings
from piloci.mcp.session_state import build_session_tracker, mcp_auth_ctx, mcp_session_ctx

logger = logging.getLogger(__name__)


def create_streamable_http_app(mcp_server: Server, *, debug: bool = False) -> Starlette:
    """MCP Streamable HTTP transport — compatible with Claude Code type:'http'."""

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        stateless=True,
        json_response=False,
    )

    async def handle_mcp(request: Request) -> Response | None:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("MCP HTTP missing bearer auth")
            return Response("Unauthorized", status_code=401)

        token = auth_header[7:]
        try:
            settings = get_settings()
            auth_payload = verify_token(token, settings)
        except ValueError as e:
            logger.warning("MCP HTTP auth failed: %s", e)
            return Response("Unauthorized", status_code=401)

        token_ctx = mcp_auth_ctx.set(auth_payload)
        session_ctx = mcp_session_ctx.set(build_session_tracker(auth_payload))
        try:
            await session_manager.handle_request(
                request.scope, request.receive, request._send  # noqa: SLF001
            )
        finally:
            mcp_auth_ctx.reset(token_ctx)
            mcp_session_ctx.reset(session_ctx)
        return None

    @asynccontextmanager
    async def lifespan(app):  # noqa: ARG001
        async with session_manager.run():
            yield

    return Starlette(
        debug=debug,
        routes=[
            Route("/", endpoint=handle_mcp, methods=["GET", "POST", "DELETE"]),
        ],
        lifespan=lifespan,
    )
