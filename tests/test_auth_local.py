"""Tests for local authentication (signup, login, password policy)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from piloci.auth.local import (
    AccountLockedError,
    EmailExistsError,
    InvalidCredentialsError,
    TokenExpiredError,
    TokenInvalidError,
    TokenUsedError,
    TOTPRequiredError,
    WeakPasswordError,
    _validate_password,
    create_reset_token,
    login,
    reset_password,
    signup,
)

# ---------------------------------------------------------------------------
# _validate_password
# ---------------------------------------------------------------------------


def test_strong_password_passes():
    _validate_password("SecurePass1!")


def test_short_password_raises():
    with pytest.raises(WeakPasswordError):
        _validate_password("Short1!")


def test_no_uppercase_raises():
    with pytest.raises(WeakPasswordError):
        _validate_password("nouppercase1!")


def test_no_lowercase_raises():
    with pytest.raises(WeakPasswordError):
        _validate_password("NOLOWERCASE1!")


def test_no_digit_raises():
    with pytest.raises(WeakPasswordError):
        _validate_password("NoDigitHere!")


def test_exactly_minimum_length_passes():
    _validate_password("SecurePass1!x")


# ---------------------------------------------------------------------------
# signup
# ---------------------------------------------------------------------------


def _make_db_session(existing_user=None):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_user
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_settings():
    s = MagicMock()
    s.session_expire_days = 14
    s.session_max_per_user = 10
    return s


@pytest.mark.asyncio
async def test_signup_success():
    db = _make_db_session(existing_user=None)
    settings = _make_settings()

    await signup("new@test.com", "SecurePass1!", "New User", db, settings)
    db.add.assert_called()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_signup_duplicate_email_raises():
    existing = MagicMock()
    db = _make_db_session(existing_user=existing)
    settings = _make_settings()

    with pytest.raises(EmailExistsError):
        await signup("taken@test.com", "SecurePass1!", "Dup", db, settings)


@pytest.mark.asyncio
async def test_signup_weak_password_raises():
    db = _make_db_session(existing_user=None)
    settings = _make_settings()

    with pytest.raises(WeakPasswordError):
        await signup("user@test.com", "weak", "User", db, settings)


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


def _make_session_store(fail_count=0):
    store = AsyncMock()
    store.get_login_fails = AsyncMock(return_value=fail_count)
    store.record_login_fail = AsyncMock(return_value=fail_count + 1)
    store.clear_login_fails = AsyncMock()
    store.create_session = AsyncMock(return_value="session-id-xyz")
    return store


@pytest.mark.asyncio
async def test_login_account_locked_raises():
    db = _make_db_session()
    store = _make_session_store(fail_count=5)
    settings = _make_settings()

    with pytest.raises(AccountLockedError):
        await login("locked@test.com", "AnyPass1!", "127.0.0.1", "", db, store, settings)


@pytest.mark.asyncio
async def test_login_unknown_email_raises():
    db = _make_db_session(existing_user=None)
    store = _make_session_store(fail_count=0)
    settings = _make_settings()

    with pytest.raises(InvalidCredentialsError):
        await login("ghost@test.com", "SecurePass1!", "127.0.0.1", "", db, store, settings)


@pytest.mark.asyncio
async def test_login_wrong_password_raises():
    from piloci.db.models import User

    user = MagicMock(spec=User)
    user.totp_enabled = False
    user.password_hash = "invalid-hash"
    user.id = str(uuid.uuid4())
    user.email = "user@test.com"

    db = _make_db_session(existing_user=user)
    store = _make_session_store(fail_count=0)
    settings = _make_settings()

    with pytest.raises(InvalidCredentialsError):
        await login("user@test.com", "WrongPass1!", "127.0.0.1", "", db, store, settings)


@pytest.mark.asyncio
async def test_login_success():
    from piloci.auth.password import hash_password
    from piloci.db.models import User

    pw = "SecurePass1!"
    user = MagicMock(spec=User)
    user.totp_enabled = False
    user.password_hash = hash_password(pw)
    user.id = str(uuid.uuid4())
    user.email = "user@test.com"
    user.name = "Test"
    user.last_login_at = None
    user.last_login_ip = None

    db = _make_db_session(existing_user=user)
    db.add = MagicMock()
    db.commit = AsyncMock()

    store = _make_session_store(fail_count=0)
    settings = _make_settings()

    result_user, sid = await login("user@test.com", pw, "127.0.0.1", "UA", db, store, settings)
    assert sid == "session-id-xyz"
    store.clear_login_fails.assert_awaited_once()


@pytest.mark.asyncio
async def test_login_totp_required_raises():
    from piloci.auth.password import hash_password
    from piloci.db.models import User

    pw = "SecurePass1!"
    user = MagicMock(spec=User)
    user.totp_enabled = True
    user.totp_secret = None
    user.password_hash = hash_password(pw)
    user.id = str(uuid.uuid4())
    user.email = "mfa@test.com"

    db = _make_db_session(existing_user=user)
    store = _make_session_store(fail_count=0)
    settings = _make_settings()

    with pytest.raises(TOTPRequiredError):
        await login("mfa@test.com", pw, "127.0.0.1", "", db, store, settings)


@pytest.fixture
async def auth_db_session():
    from piloci.db.session import init_db

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine=engine)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


async def _create_local_user(db_session, *, email: str = "reset@test.com"):
    from piloci.auth.password import hash_password
    from piloci.db.models import User

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        name="Reset User",
        password_hash=hash_password("SecurePass1!x"),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_create_reset_token_scopes_token_with_user_id(auth_db_session):
    user = await _create_local_user(auth_db_session)

    token = await create_reset_token(user.email, auth_db_session)

    assert token is not None
    assert token.startswith(f"{user.id}.")


@pytest.mark.asyncio
async def test_reset_password_updates_password_and_marks_token_used(auth_db_session):
    from piloci.db.models import PasswordResetToken

    user = await _create_local_user(auth_db_session)
    token = await create_reset_token(user.email, auth_db_session)
    assert token is not None

    updated_user = await reset_password(token, "NewSecurePass1", auth_db_session)

    assert updated_user.id == user.id
    result = await auth_db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    stored_token = result.scalar_one()
    assert stored_token.used is True


@pytest.mark.asyncio
async def test_reset_password_reused_token_raises_used(auth_db_session):
    user = await _create_local_user(auth_db_session)
    token = await create_reset_token(user.email, auth_db_session)
    assert token is not None

    await reset_password(token, "NewSecurePass1", auth_db_session)

    with pytest.raises(TokenUsedError):
        await reset_password(token, "AnotherSecurePass1", auth_db_session)


@pytest.mark.asyncio
async def test_reset_password_expired_token_raises(auth_db_session):
    from piloci.db.models import PasswordResetToken

    user = await _create_local_user(auth_db_session)
    token = await create_reset_token(user.email, auth_db_session)
    assert token is not None

    result = await auth_db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    stored_token = result.scalar_one()
    stored_token.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await auth_db_session.commit()

    with pytest.raises(TokenExpiredError):
        await reset_password(token, "NewSecurePass1", auth_db_session)


@pytest.mark.asyncio
async def test_reset_password_invalid_token_raises_without_table_scan(auth_db_session):
    await _create_local_user(auth_db_session)

    with pytest.raises(TokenInvalidError):
        await reset_password("not-a-valid-reset-token", "NewSecurePass1", auth_db_session)
