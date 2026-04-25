"""Tests for local authentication (signup, login, password policy)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from piloci.auth.local import (
    AccountLockedError,
    EmailExistsError,
    InvalidCredentialsError,
    TOTPRequiredError,
    WeakPasswordError,
    _validate_password,
    login,
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
