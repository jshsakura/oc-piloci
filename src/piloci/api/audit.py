from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

import orjson

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    SIGNUP = "SIGNUP"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    TOKEN_CREATED = "TOKEN_CREATED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    PROJECT_CREATED = "PROJECT_CREATED"
    PROJECT_DELETED = "PROJECT_DELETED"
    SESSION_REVOKED = "SESSION_REVOKED"


async def log_event(
    action: AuditAction,
    user_id: str | None,
    ip: str | None,
    user_agent: str | None,
    metadata: dict[str, Any] | None,
    db_session: AsyncSession | None,
) -> None:
    """Insert an audit log row. Never raises — failures are logged only."""
    if db_session is None:
        logger.debug("audit.log_event: no db_session, skipping (action=%s)", action.value)
        return

    try:
        from sqlalchemy import text

        metadata_json: str | None = (
            orjson.dumps(metadata).decode() if metadata is not None else None
        )
        now = datetime.now(tz=timezone.utc)
        await db_session.execute(
            text(
                "INSERT INTO audit_logs (user_id, action, ip_address, user_agent, metadata, created_at)"
                " VALUES (:user_id, :action, :ip, :ua, :meta, :created_at)"
            ),
            {
                "user_id": user_id,
                "action": action.value,
                "ip": ip,
                "ua": user_agent,
                "meta": metadata_json,
                "created_at": now,
            },
        )
        await db_session.commit()
    except Exception:
        logger.exception("audit.log_event failed (action=%s, user_id=%s)", action, user_id)
