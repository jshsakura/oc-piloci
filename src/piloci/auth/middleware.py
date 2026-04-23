from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from piloci.auth.jwt_utils import verify_token, decode_token_unsafe
from piloci.auth.session import get_session_store

if TYPE_CHECKING:
    from starlette.types import ASGIApp
    from piloci.config import Settings

logger = logging.getLogger(__name__)

_SKIP_PATHS = frozenset(["/healthz", "/readyz"])


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _SKIP_PATHS:
            request.state.user = None
            return await call_next(request)

        user = None

        # 1. Try Bearer JWT
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
            try:
                user = verify_token(token, self._settings)
            except ValueError:
                try:
                    unsafe = decode_token_unsafe(token)
                    logger.warning(
                        "Invalid JWT for sub=%s jti=%s",
                        unsafe.get("sub"),
                        unsafe.get("jti"),
                    )
                except Exception:
                    logger.warning("Received malformed JWT token")
                user = None

        # 2. Try session cookie if no JWT
        if user is None:
            session_id = request.cookies.get("piloci_session")
            if session_id:
                try:
                    store = get_session_store(self._settings)
                    session_data = await store.get_session(session_id)
                    if session_data is not None:
                        user = session_data
                except Exception:
                    logger.exception("Error retrieving session from Redis")
                    user = None

        request.state.user = user
        return await call_next(request)
