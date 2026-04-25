from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

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
) -> str:
    """Create a signed JWT token with the standard piLoci payload."""
    now = datetime.now(tz=timezone.utc)
    expire = now + timedelta(days=settings.jwt_expire_days)

    payload: dict = {
        "sub": user_id,
        "email": email,
        "project_id": project_id,
        "project_slug": project_slug,
        "scope": scope,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": token_id,
    }

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
    except JWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc


def decode_token_unsafe(token: str) -> dict:
    """Decode a JWT token without verifying the signature (for logging purposes only)."""
    return jwt.get_unverified_claims(token)
