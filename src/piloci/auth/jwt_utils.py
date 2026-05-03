from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal

import jwt
from jwt.exceptions import ExpiredSignatureError, PyJWTError

if TYPE_CHECKING:
    from piloci.config import Settings


def create_token(
    user_id: str,
    email: str,
    project_id: str | None,
    project_slug: str | None,
    scope: Literal["project", "user"],
    settings: Settings,
    token_id: str,
    expire_days: int | None = None,
) -> str:
    """Create a signed JWT token. expire_days=None means no expiry."""
    now = datetime.now(tz=timezone.utc)
    days = expire_days if expire_days is not None else settings.jwt_expire_days

    payload: dict = {
        "sub": user_id,
        "email": email,
        "project_id": project_id,
        "project_slug": project_slug,
        "scope": scope,
        "iat": int(now.timestamp()),
        "jti": token_id,
    }
    if days > 0:
        payload["exp"] = int((now + timedelta(days=days)).timestamp())

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_token(token: str, settings: Settings) -> dict:
    """Verify and decode a JWT token. Raises ValueError on any failure."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except ExpiredSignatureError as exc:
        raise ValueError("Token has expired") from exc
    except PyJWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc


def decode_token_unsafe(token: str) -> dict:
    """Decode a JWT token without verifying the signature (for logging purposes only)."""
    return jwt.decode(token, options={"verify_signature": False})
