from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import orjson

from piloci.auth.password import hash_password, needs_rehash, verify_password
from piloci.auth.session import SessionStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from piloci.config import Settings
    from piloci.db.models import User


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class AuthError(Exception):
    """Base class for authentication errors."""


class AccountLockedError(AuthError):
    """Raised when an account is locked due to too many failed login attempts."""


class InvalidCredentialsError(AuthError):
    """Raised when email/password combination is incorrect."""


class WeakPasswordError(AuthError):
    """Raised when a password does not meet the complexity requirements."""


class EmailExistsError(AuthError):
    """Raised when attempting to register with an already-used email address."""


class TOTPRequiredError(AuthError):
    """Raised when 2FA is enabled but no TOTP code was provided."""


class InvalidTOTPError(AuthError):
    """Raised when the provided TOTP code is invalid."""


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------

_MIN_PASSWORD_LEN = 12
_RE_UPPERCASE = re.compile(r"[A-Z]")
_RE_LOWERCASE = re.compile(r"[a-z]")
_RE_DIGIT = re.compile(r"\d")

_MAX_LOGIN_ATTEMPTS = 5


def _validate_password(password: str) -> None:
    if len(password) < _MIN_PASSWORD_LEN:
        raise WeakPasswordError(
            f"Password must be at least {_MIN_PASSWORD_LEN} characters long."
        )
    if not _RE_UPPERCASE.search(password):
        raise WeakPasswordError("Password must contain at least one uppercase letter.")
    if not _RE_LOWERCASE.search(password):
        raise WeakPasswordError("Password must contain at least one lowercase letter.")
    if not _RE_DIGIT.search(password):
        raise WeakPasswordError("Password must contain at least one digit.")


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------


async def signup(
    email: str,
    password: str,
    name: str,
    db_session: AsyncSession,
    settings: Settings,
) -> User:
    """Register a new local user.

    Raises:
        EmailExistsError: if the email is already taken.
        WeakPasswordError: if the password does not meet policy requirements.
    """
    from sqlalchemy import select
    from piloci.db.models import User, AuditLog  # type: ignore[attr-defined]

    _validate_password(password)

    result = await db_session.execute(
        select(User).where(User.email == email)
    )
    if result.scalar_one_or_none() is not None:
        raise EmailExistsError(f"Email already registered: {email}")

    hashed = hash_password(password)
    now = datetime.now(timezone.utc)
    user = User(id=str(uuid.uuid4()), email=email, name=name, password_hash=hashed, created_at=now)
    db_session.add(user)
    await db_session.flush()

    audit = AuditLog(
        user_id=user.id,
        action="signup",
        meta_data=orjson.dumps({"email": email}).decode(),
        created_at=now,
    )
    db_session.add(audit)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def login(
    email: str,
    password: str,
    ip: str,
    user_agent: str,
    db_session: AsyncSession,
    redis_session: SessionStore,
    settings: Settings,
    totp_code: str | None = None,
) -> tuple[User, str]:
    """Authenticate a local user and issue a session.

    Returns:
        (User, session_id) on success.

    Raises:
        AccountLockedError: if the account has exceeded the max failed attempts.
        InvalidCredentialsError: if credentials are wrong.
    """
    from sqlalchemy import select
    from piloci.db.models import User, AuditLog  # type: ignore[attr-defined]

    fails = await redis_session.get_login_fails(email)
    if fails >= _MAX_LOGIN_ATTEMPTS:
        raise AccountLockedError(
            f"Account locked after {_MAX_LOGIN_ATTEMPTS} failed attempts. "
            "Please wait 15 minutes before trying again."
        )

    result = await db_session.execute(
        select(User).where(User.email == email)
    )
    user: User | None = result.scalar_one_or_none()

    if user is None or not verify_password(password, user.password_hash or ""):
        new_count = await redis_session.record_login_fail(email)

        if user is not None:
            audit = AuditLog(
                user_id=user.id,
                action="login_fail",
                ip_address=ip,
                user_agent=user_agent,
                meta_data=orjson.dumps({"attempt": new_count}).decode(),
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(audit)
            await db_session.commit()

        raise InvalidCredentialsError("Invalid email or password.")

    # TOTP check
    if user.totp_enabled:
        if not totp_code:
            raise TOTPRequiredError("2FA code required")
        from piloci.auth.totp import verify_totp
        if not verify_totp(user.totp_secret, totp_code):
            new_count = await redis_session.record_login_fail(email)
            audit = AuditLog(
                user_id=user.id,
                action="login_fail_totp",
                ip_address=ip,
                user_agent=user_agent,
                meta_data=orjson.dumps({"attempt": new_count}).decode(),
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(audit)
            await db_session.commit()
            raise InvalidTOTPError("Invalid 2FA code")

    # Success path
    await redis_session.clear_login_fails(email)

    now = datetime.now(timezone.utc)
    if needs_rehash(user.password_hash or ""):
        user.password_hash = hash_password(password)
        db_session.add(user)

    session_id = await redis_session.create_session(
        user_id=str(user.id),
        ip=ip,
        user_agent=user_agent,
    )

    audit = AuditLog(
        user_id=user.id,
        action="login_success",
        ip_address=ip,
        user_agent=user_agent,
        meta_data=None,
        created_at=now,
    )
    db_session.add(audit)
    await db_session.commit()

    return user, session_id
