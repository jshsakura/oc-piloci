from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from piloci.auth.middleware import AuthMiddleware
from piloci.config import Settings


def _session_cm(session: MagicMock) -> AsyncMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _settings() -> Settings:
    return Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
    )


def _build_app() -> Starlette:
    async def endpoint(request: Request) -> PlainTextResponse:
        if request.url.path in {"/healthz", "/readyz"}:
            return PlainTextResponse("skip" if request.state.user is None else "unexpected")

        user = request.state.user
        if user is None:
            return PlainTextResponse("Unauthorized", status_code=401)

        return PlainTextResponse(str(user.get("sub") or user.get("user_id")))

    return Starlette(
        routes=[
            Route("/", endpoint),
            Route("/healthz", endpoint),
            Route("/readyz", endpoint),
        ],
        middleware=[Middleware(AuthMiddleware, settings=_settings())],
    )


def test_dispatch_skips_health_checks_without_auth() -> None:
    app = _build_app()

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.text == "skip"


def test_dispatch_sets_user_from_valid_bearer_jwt(monkeypatch) -> None:
    verify_token_mock = MagicMock(return_value={"sub": "user-123", "scope": "user"})
    get_session_store_mock = MagicMock()

    monkeypatch.setattr("piloci.auth.middleware.verify_token", verify_token_mock)
    monkeypatch.setattr("piloci.auth.middleware.get_session_store", get_session_store_mock)

    with TestClient(_build_app()) as client:
        response = client.get("/", headers={"Authorization": "Bearer good-token"})

    assert response.status_code == 200
    assert response.text == "user-123"
    verify_token_mock.assert_called_once()
    get_session_store_mock.assert_not_called()


def test_dispatch_rejects_invalid_bearer_jwt(monkeypatch) -> None:
    verify_token_mock = MagicMock(side_effect=ValueError("bad token"))
    decode_token_unsafe_mock = MagicMock(return_value={"sub": "user-123", "jti": "token-1"})

    monkeypatch.setattr("piloci.auth.middleware.verify_token", verify_token_mock)
    monkeypatch.setattr("piloci.auth.middleware.decode_token_unsafe", decode_token_unsafe_mock)

    with TestClient(_build_app()) as client:
        response = client.get("/", headers={"Authorization": "Bearer bad-token"})

    assert response.status_code == 401
    assert response.text == "Unauthorized"
    verify_token_mock.assert_called_once()
    decode_token_unsafe_mock.assert_called_once_with("bad-token")


def test_dispatch_sets_user_from_valid_session_cookie(monkeypatch) -> None:
    session_store = MagicMock()
    session_store.get_session = AsyncMock(return_value={"user_id": "session-user-1"})

    monkeypatch.setattr("piloci.auth.middleware.verify_token", MagicMock())
    monkeypatch.setattr(
        "piloci.auth.middleware.get_session_store", MagicMock(return_value=session_store)
    )

    with TestClient(_build_app()) as client:
        response = client.get("/", cookies={"piloci_session": "session-abc"})

    assert response.status_code == 200
    assert response.text == "session-user-1"
    session_store.get_session.assert_awaited_once_with("session-abc")


def test_dispatch_rejects_invalid_session_cookie(monkeypatch) -> None:
    session_store = MagicMock()
    session_store.get_session = AsyncMock(return_value=None)

    monkeypatch.setattr("piloci.auth.middleware.verify_token", MagicMock())
    monkeypatch.setattr(
        "piloci.auth.middleware.get_session_store", MagicMock(return_value=session_store)
    )

    with TestClient(_build_app()) as client:
        response = client.get("/", cookies={"piloci_session": "missing-session"})

    assert response.status_code == 401
    assert response.text == "Unauthorized"
    session_store.get_session.assert_awaited_once_with("missing-session")


def test_dispatch_rejects_requests_without_auth(monkeypatch) -> None:
    verify_token_mock = MagicMock()
    get_session_store_mock = MagicMock()

    monkeypatch.setattr("piloci.auth.middleware.verify_token", verify_token_mock)
    monkeypatch.setattr("piloci.auth.middleware.get_session_store", get_session_store_mock)

    with TestClient(_build_app()) as client:
        response = client.get("/")

    assert response.status_code == 401
    assert response.text == "Unauthorized"
    verify_token_mock.assert_not_called()
    get_session_store_mock.assert_not_called()


@pytest.mark.asyncio
async def test_validate_bearer_user_rejects_revoked_token(monkeypatch) -> None:
    from piloci.auth.middleware import _validate_bearer_user

    api_token = MagicMock(revoked=True, expires_at=None)
    db_user = MagicMock(is_active=True, approval_status="approved", is_admin=False)
    result = MagicMock()
    result.one_or_none.return_value = (api_token, db_user)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    monkeypatch.setattr(
        "piloci.auth.middleware.async_session", MagicMock(return_value=_session_cm(session))
    )

    validated = await _validate_bearer_user({"sub": "user-1", "jti": "token-1"})

    assert validated is None


@pytest.mark.asyncio
async def test_validate_bearer_user_refreshes_current_user_flags(monkeypatch) -> None:
    from piloci.auth.middleware import _validate_bearer_user

    api_token = MagicMock(
        revoked=False,
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5),
    )
    db_user = MagicMock(is_active=True, approval_status="approved", is_admin=True)
    result = MagicMock()
    result.one_or_none.return_value = (api_token, db_user)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(
        "piloci.auth.middleware.async_session", MagicMock(return_value=_session_cm(session))
    )

    payload = {"sub": "user-1", "jti": "token-1", "is_admin": False}
    validated = await _validate_bearer_user(payload)

    assert validated is payload
    assert validated["is_admin"] is True
    assert validated["approval_status"] == "approved"


@pytest.mark.asyncio
async def test_validate_session_user_rejects_inactive_user(monkeypatch) -> None:
    from piloci.auth.middleware import _validate_session_user

    result = MagicMock()
    result.scalar_one_or_none.return_value = MagicMock(
        is_active=False, approval_status="approved", is_admin=False
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(
        "piloci.auth.middleware.async_session", MagicMock(return_value=_session_cm(session))
    )

    validated = await _validate_session_user(
        {"user_id": "user-1", "approval_status": "approved", "is_admin": False}
    )

    assert validated is None
