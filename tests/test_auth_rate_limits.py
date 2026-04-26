from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from piloci.api.ratelimit import limiter, setup_ratelimit
from piloci.api.routes import get_routes


@asynccontextmanager
async def _fake_async_session():
    yield SimpleNamespace()


def _make_app(monkeypatch: pytest.MonkeyPatch) -> Starlette:
    import piloci.api.routes as routes

    async def _signup(*args, **kwargs):
        return SimpleNamespace(id="user-1", email="user@test.com")

    async def _login(*args, **kwargs):
        return SimpleNamespace(id="user-1", email="user@test.com"), "session-1"

    async def _create_reset_token(*args, **kwargs):
        return "reset-token"

    async def _reset_password(*args, **kwargs):
        return None

    monkeypatch.setattr(routes, "async_session", _fake_async_session)
    monkeypatch.setattr(routes, "signup", _signup)
    monkeypatch.setattr(routes, "login", _login)
    monkeypatch.setattr(routes, "create_reset_token", _create_reset_token)
    monkeypatch.setattr(routes, "reset_password", _reset_password)
    monkeypatch.setattr(routes, "get_session_store", lambda settings: SimpleNamespace())
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(session_expire_days=14))

    app = Starlette(routes=get_routes())
    setup_ratelimit(app)
    return app


@pytest.fixture(autouse=True)
def _reset_limiter_storage():
    limiter._storage.reset()
    yield
    limiter._storage.reset()


def test_signup_route_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(_make_app(monkeypatch), client=("signup-client", 50001)) as client:
        payload = {"email": "user@test.com", "password": "SecurePass1!x", "name": "User"}
        statuses = [client.post("/auth/signup", json=payload).status_code for _ in range(4)]

    assert statuses[0] == 201
    assert statuses[-1] == 429


def test_login_route_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(_make_app(monkeypatch), client=("login-client", 50002)) as client:
        payload = {"email": "user@test.com", "password": "SecurePass1!x"}
        statuses = [client.post("/auth/login", json=payload).status_code for _ in range(11)]

    assert statuses[0] == 200
    assert statuses[-1] == 429


def test_forgot_password_route_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(_make_app(monkeypatch), client=("forgot-client", 50003)) as client:
        payload = {"email": "user@test.com"}
        statuses = [
            client.post("/auth/forgot-password", json=payload).status_code for _ in range(4)
        ]

    assert statuses[0] == 200
    assert statuses[-1] == 429


def test_reset_password_route_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    import piloci.api.routes as routes

    route = next(item for item in get_routes() if item.path == "/auth/reset-password")

    assert route.endpoint is not routes.route_reset_password
    assert getattr(route.endpoint, "__wrapped__", None) is routes.route_reset_password


def test_auth_providers_route_reports_configured_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    import piloci.api.routes as routes
    import piloci.auth.oauth as oauth

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(
        oauth,
        "get_provider_credentials",
        lambda settings, name: (
            ("client-id", "client-secret") if name in {"kakao", "google"} else None
        ),
    )

    with TestClient(_make_app(monkeypatch), client=("providers-client", 50004)) as client:
        response = client.get("/api/auth/providers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["providers"] == [
        {"name": "google", "configured": True, "login_path": "/auth/google/login"},
        {"name": "github", "configured": False, "login_path": "/auth/github/login"},
        {"name": "kakao", "configured": True, "login_path": "/auth/kakao/login"},
        {"name": "naver", "configured": False, "login_path": "/auth/naver/login"},
    ]
