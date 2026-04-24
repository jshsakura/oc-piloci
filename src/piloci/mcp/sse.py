from __future__ import annotations

import contextvars
import logging

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from piloci.auth.jwt_utils import verify_token
from piloci.config import get_settings

logger = logging.getLogger(__name__)

# ContextVar carries auth info from SSE connection → tool call handlers
mcp_auth_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "mcp_auth_ctx", default=None
)


def create_sse_app(mcp_server: Server, *, debug: bool = False, prefix: str = "") -> Starlette:
    """Create SSE sub-app for MCP.

    Args:
        prefix: Mount prefix (e.g. "/mcp"). Used to build the correct
                message-post path for SseServerTransport.
    """
    msg_path = f"{prefix}/messages/" if prefix else "/messages/"
    sse = SseServerTransport(msg_path)

    async def handle_sse(request: Request) -> None:
        # Extract and verify JWT from Authorization header
        auth_payload: dict | None = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                settings = get_settings()
                auth_payload = verify_token(token, settings)
            except ValueError as e:
                logger.warning("MCP SSE auth failed: %s", e)
                # Return 401 — SSE endpoint requires valid token
                from starlette.responses import Response
                return Response("Unauthorized", status_code=401)

        token_ctx = mcp_auth_ctx.set(auth_payload)
        try:
            async with sse.connect_sse(
                request.scope,
                request.receive,
                request._send,  # noqa: SLF001
            ) as (read_stream, write_stream):
                await mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp_server.create_initialization_options(),
                )
        finally:
            mcp_auth_ctx.reset(token_ctx)

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return Starlette(
        debug=debug,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
            Route("/healthz", endpoint=healthz),
        ],
    )
