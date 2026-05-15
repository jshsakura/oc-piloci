from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from piloci.auth.jwt_utils import decode_token_unsafe, verify_token
from piloci.auth.session import get_session_store
from piloci.db.models import ApiToken, User
from piloci.db.session import async_session

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
            token = auth_header[len("Bearer ") :]
            try:
                user = verify_token(token, self._settings)
                user = await _validate_bearer_user(user)
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
                        user = await _validate_session_user(session_data)
                except Exception:
                    logger.exception("Error retrieving session from Redis")
                    user = None

        request.state.user = user
        return await call_next(request)


async def _validate_bearer_user(payload: dict) -> dict | None:
    token_id = payload.get("jti")
    user_id = payload.get("sub")
    if not token_id or not user_id:
        return payload

    async with async_session() as db:
        result = await db.execute(
            select(ApiToken, User)
            .join(User, User.id == ApiToken.user_id)
            .where(ApiToken.token_id == token_id, ApiToken.user_id == user_id)
        )
        row = result.one_or_none()

    if row is None:
        return None

    api_token, db_user = row
    if api_token.revoked:
        return None
    if api_token.expires_at is not None and api_token.expires_at < datetime.now(
        timezone.utc
    ).replace(tzinfo=None):
        return None
    if not db_user.is_active or db_user.approval_status != "approved":
        return None

    payload["is_admin"] = db_user.is_admin
    payload["approval_status"] = db_user.approval_status
    return payload


async def _validate_session_user(session_data: dict) -> dict | None:
    user_id = session_data.get("user_id")
    if not user_id or "approval_status" not in session_data or "is_admin" not in session_data:
        return session_data

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        db_user = result.scalar_one_or_none()

    if db_user is None or not db_user.is_active or db_user.approval_status != "approved":
        return None

    session_data["is_admin"] = db_user.is_admin
    session_data["approval_status"] = db_user.approval_status
    return session_data
