from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from piloci.api import audit


def _db_session() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


def test_audit_action_enum_values() -> None:
    assert audit.AuditAction.LOGIN.value == "LOGIN"
    assert audit.AuditAction.LOGIN_FAILED.value == "LOGIN_FAILED"
    assert audit.AuditAction.LOGOUT.value == "LOGOUT"
    assert audit.AuditAction.SIGNUP.value == "SIGNUP"
    assert audit.AuditAction.PASSWORD_CHANGED.value == "PASSWORD_CHANGED"
    assert audit.AuditAction.TOKEN_CREATED.value == "TOKEN_CREATED"
    assert audit.AuditAction.TOKEN_REVOKED.value == "TOKEN_REVOKED"
    assert audit.AuditAction.PROJECT_CREATED.value == "PROJECT_CREATED"
    assert audit.AuditAction.PROJECT_DELETED.value == "PROJECT_DELETED"
    assert audit.AuditAction.SESSION_REVOKED.value == "SESSION_REVOKED"


@pytest.mark.asyncio
async def test_log_event_inserts_and_commits() -> None:
    db_session = _db_session()

    await audit.log_event(
        action=audit.AuditAction.LOGIN,
        user_id="user-1",
        ip="127.0.0.1",
        user_agent="pytest",
        metadata={"source": "web"},
        db_session=db_session,
    )

    db_session.execute.assert_awaited_once()
    statement, params = db_session.execute.await_args.args
    assert "INSERT INTO audit_logs" in statement.text
    assert params["user_id"] == "user-1"
    assert params["action"] == "LOGIN"
    assert params["ip"] == "127.0.0.1"
    assert params["ua"] == "pytest"
    assert params["meta"] == '{"source":"web"}'
    assert params["created_at"].tzinfo is not None
    db_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_log_event_is_noop_without_db_session(monkeypatch: pytest.MonkeyPatch) -> None:
    debug = MagicMock()
    monkeypatch.setattr(audit.logger, "debug", debug)

    await audit.log_event(
        action=audit.AuditAction.LOGOUT,
        user_id="user-1",
        ip=None,
        user_agent=None,
        metadata=None,
        db_session=None,
    )

    debug.assert_called_once()


@pytest.mark.asyncio
async def test_log_event_swallows_commit_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    db_session = _db_session()
    db_session.commit.side_effect = RuntimeError("db down")
    logged = MagicMock()
    monkeypatch.setattr(audit.logger, "exception", logged)

    await audit.log_event(
        action=audit.AuditAction.TOKEN_CREATED,
        user_id="user-1",
        ip="127.0.0.1",
        user_agent="pytest",
        metadata={"token_id": "tok-1"},
        db_session=db_session,
    )

    db_session.execute.assert_awaited_once()
    db_session.commit.assert_awaited_once()
    logged.assert_called_once()
