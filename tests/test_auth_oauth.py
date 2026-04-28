"""Tests for multi-provider OAuth helper functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from piloci.config import Settings


@pytest.mark.parametrize(
    ("provider", "expected_host", "expected_scope", "extra_params"),
    [
        (
            "google",
            "accounts.google.com",
            "openid email profile",
            {"access_type": "online", "prompt": "select_account"},
        ),
        ("github", "github.com", "user:email", {}),
        ("kakao", "kauth.kakao.com", "profile_nickname account_email", {}),
        ("naver", "nid.naver.com", None, {}),
    ],
)
def test_build_auth_url_for_each_provider(
    provider: str,
    expected_host: str,
    expected_scope: str | None,
    extra_params: dict[str, str],
):
    from piloci.auth.oauth import build_auth_url

    url = build_auth_url(
        provider=provider,
        client_id="test-client",
        redirect_uri=f"http://localhost/auth/{provider}/callback",
        state="random-state",
    )

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert expected_host in parsed.netloc
    assert params["client_id"] == ["test-client"]
    assert params["state"] == ["random-state"]
    assert params["response_type"] == ["code"]
    if expected_scope is None:
        assert "scope" not in params
    else:
        assert params["scope"] == [expected_scope]
    for key, value in extra_params.items():
        assert params[key] == [value]


def test_generate_state():
    from piloci.auth.oauth import generate_state

    s1 = generate_state()
    s2 = generate_state()
    assert isinstance(s1, str)
    assert len(s1) > 20
    assert s1 != s2


def test_settings_reads_base_url_from_base_url_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BASE_URL", "https://piloci.opencourse.kr")
    monkeypatch.delenv("PILOCI_PUBLIC_URL", raising=False)

    settings = Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
    )

    assert settings.base_url == "https://piloci.opencourse.kr"


def test_settings_reads_base_url_from_piloci_public_url_alias(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.setenv("PILOCI_PUBLIC_URL", "https://piloci.opencourse.kr")

    settings = Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
    )

    assert settings.base_url == "https://piloci.opencourse.kr"


@pytest.mark.asyncio
async def test_exchange_code_calls_provider_token_endpoint():
    from piloci.auth.oauth import PROVIDERS, exchange_code

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"access_token": "tok123"})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("piloci.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        result = await exchange_code(
            provider="github",
            code="auth-code",
            client_id="cid",
            client_secret="csecret",
            redirect_uri="http://localhost/callback",
        )

    assert result == {"access_token": "tok123"}
    mock_client.post.assert_awaited_once_with(
        PROVIDERS["github"].token_url,
        data={
            "code": "auth-code",
            "client_id": "cid",
            "client_secret": "csecret",
            "redirect_uri": "http://localhost/callback",
            "grant_type": "authorization_code",
        },
        headers={"Accept": "application/json"},
    )


@pytest.mark.parametrize(
    ("provider", "payload", "expected"),
    [
        (
            "google",
            {"email": "google@test.com", "sub": "g-123", "name": "Google User"},
            {"email": "google@test.com", "sub": "g-123", "name": "Google User"},
        ),
        (
            "github",
            {"email": "github@test.com", "id": 123, "name": "GitHub User", "login": "ghuser"},
            {"email": "github@test.com", "sub": "123", "name": "GitHub User"},
        ),
        (
            "kakao",
            {
                "id": 456,
                "kakao_account": {
                    "email": "kakao@test.com",
                    "profile": {"nickname": "Kakao User"},
                },
            },
            {"email": "kakao@test.com", "sub": "456", "name": "Kakao User"},
        ),
        (
            "naver",
            {
                "response": {
                    "email": "naver@test.com",
                    "id": "naver-789",
                    "nickname": "Naver User",
                }
            },
            {"email": "naver@test.com", "sub": "naver-789", "name": "Naver User"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_get_userinfo_normalizes_provider_payload(
    provider: str, payload: dict[str, object], expected: dict[str, str]
):
    from piloci.auth.oauth import PROVIDERS, get_userinfo

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=payload)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("piloci.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        result = await get_userinfo(provider, "access-token")

    assert result == expected
    mock_client.get.assert_awaited_once_with(
        PROVIDERS[provider].userinfo_url,
        headers={
            "Authorization": "Bearer access-token",
            **PROVIDERS[provider].userinfo_headers,
        },
    )


@pytest.mark.asyncio
async def test_upsert_oauth_user_creates_new():
    from piloci.auth.oauth import upsert_oauth_user

    userinfo = {"email": "new@test.com", "sub": "gh-sub-999", "name": "New User"}

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    user = await upsert_oauth_user(mock_db, "github", userinfo)

    mock_db.add.assert_called_once_with(user)
    mock_db.commit.assert_awaited_once()
    mock_db.refresh.assert_awaited_once_with(user)
    assert user.email == "new@test.com"
    assert user.oauth_provider == "github"
    assert user.oauth_sub == "gh-sub-999"
    assert user.email_verified is True


@pytest.mark.asyncio
async def test_upsert_oauth_user_links_existing_local_account():
    from piloci.auth.oauth import upsert_oauth_user

    userinfo = {"email": "existing@test.com", "sub": "kakao-sub-777", "name": "Existing"}

    existing_user = MagicMock()
    existing_user.oauth_sub = None
    existing_user.name = ""

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_user
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    user = await upsert_oauth_user(mock_db, "kakao", userinfo)

    assert existing_user.oauth_provider == "kakao"
    assert existing_user.oauth_sub == "kakao-sub-777"
    assert existing_user.email_verified is True
    assert existing_user.name == "Existing"
    mock_db.add.assert_not_called()
    mock_db.commit.assert_awaited_once()
    mock_db.refresh.assert_awaited_once_with(existing_user)
    assert user is existing_user


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("google", ("google-id", "google-secret")),
        ("github", ("github-id", "github-secret")),
        ("kakao", ("kakao-id", "kakao-secret")),
        ("naver", ("naver-id", "naver-secret")),
    ],
)
def test_get_provider_credentials_returns_configured_values(
    provider: str, expected: tuple[str, str]
):
    from piloci.auth.oauth import get_provider_credentials

    settings = Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
        google_client_id="google-id",
        google_client_secret="google-secret",
        github_client_id="github-id",
        github_client_secret="github-secret",
        kakao_client_id="kakao-id",
        kakao_client_secret="kakao-secret",
        naver_client_id="naver-id",
        naver_client_secret="naver-secret",
    )

    assert get_provider_credentials(settings, provider) == expected


def test_get_provider_credentials_returns_none_when_not_configured(monkeypatch: pytest.MonkeyPatch):
    from piloci.auth.oauth import get_provider_credentials

    monkeypatch.setenv("GITHUB_CLIENT_ID", "")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "")

    settings = Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
        google_client_id="google-id",
        google_client_secret="google-secret",
        github_client_id="",
        github_client_secret="",
    )

    assert get_provider_credentials(settings, "github") is None


@pytest.mark.parametrize(
    "func,args",
    [
        ("build_auth_url", ("discord", "cid", "http://localhost/callback", "state")),
        ("get_provider_credentials", (None, "discord")),
    ],
)
def test_invalid_provider_raises_value_error(func: str, args: tuple[object, ...]):
    from piloci.auth import oauth

    if func == "get_provider_credentials":
        settings = Settings(
            jwt_secret="test-secret-32-characters-minimum!",
            session_secret="test-secret-32-characters-minimum!",
        )
        args = (settings, "discord")

    with pytest.raises(ValueError, match="Unknown OAuth provider"):
        getattr(oauth, func)(*args)


# ---------------------------------------------------------------------------
# verify_naver_unlink_signature
# ---------------------------------------------------------------------------


def test_verify_naver_unlink_signature_valid():
    import hashlib
    import hmac

    from piloci.auth.oauth import verify_naver_unlink_signature

    client_secret = "my-secret-key"
    client_id = "naver-client-id"
    user_id = "12345678"
    timestamp = "1700000000"

    message = f"{client_id}{user_id}{timestamp}"
    sig = hmac.new(client_secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    assert verify_naver_unlink_signature(
        client_id=client_id,
        user_id=user_id,
        timestamp=timestamp,
        signature=sig,
        client_secret=client_secret,
    )


def test_verify_naver_unlink_signature_with_svc_id():
    import hashlib
    import hmac

    from piloci.auth.oauth import verify_naver_unlink_signature

    client_secret = "my-secret-key"
    client_id = "naver-client-id"
    svc_id = "svc-001"
    user_id = "12345678"
    timestamp = "1700000000"

    message = f"{client_id}_{svc_id}{user_id}{timestamp}"
    sig = hmac.new(client_secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    assert verify_naver_unlink_signature(
        client_id=client_id,
        user_id=user_id,
        timestamp=timestamp,
        signature=sig,
        client_secret=client_secret,
        svc_id=svc_id,
    )


def test_verify_naver_unlink_signature_invalid():
    from piloci.auth.oauth import verify_naver_unlink_signature

    assert not verify_naver_unlink_signature(
        client_id="naver-client-id",
        user_id="12345678",
        timestamp="1700000000",
        signature="badsignature",
        client_secret="my-secret-key",
    )


# ---------------------------------------------------------------------------
# route_naver_unlink_callback integration tests
# ---------------------------------------------------------------------------


def _make_naver_app():
    from starlette.applications import Starlette

    from piloci.api.routes import get_routes

    routes = get_routes()
    return Starlette(routes=routes)


@pytest.fixture
def naver_settings(monkeypatch):
    from piloci.config import Settings

    s = Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
        naver_client_id="test-naver-id",
        naver_client_secret="test-naver-secret",
    )
    import piloci.api.routes as routes_mod

    monkeypatch.setattr(routes_mod, "get_settings", lambda: s)
    return s


@pytest.mark.asyncio
async def test_naver_unlink_callback_success(naver_settings, monkeypatch):
    import hashlib
    import hmac
    from contextlib import asynccontextmanager

    from starlette.testclient import TestClient

    mock_user = MagicMock()
    mock_user.oauth_provider = "naver"
    mock_user.oauth_sub = "naver-user-123"
    mock_user.oauth_access_token = "encrypted-token"
    mock_user.oauth_refresh_token = None

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()

    @asynccontextmanager
    async def _fake_session():
        yield mock_db

    import piloci.api.routes as routes_mod

    monkeypatch.setattr(routes_mod, "async_session", _fake_session)

    app = _make_naver_app()
    client = TestClient(app)

    client_id = "test-naver-id"
    user_id = "naver-user-123"
    timestamp = "1700000000"
    client_secret = "test-naver-secret"
    message = f"{client_id}{user_id}{timestamp}"
    sig = hmac.new(client_secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    response = client.post(
        "/auth/naver/unlink-callback",
        data={
            "client_id": client_id,
            "user_id": user_id,
            "timestamp": timestamp,
            "signature": sig,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "ok"
    assert mock_user.oauth_provider is None
    assert mock_user.oauth_sub is None


@pytest.mark.asyncio
async def test_naver_unlink_callback_invalid_signature(naver_settings, monkeypatch):
    from starlette.testclient import TestClient

    app = _make_naver_app()
    client = TestClient(app)

    response = client.post(
        "/auth/naver/unlink-callback",
        data={
            "client_id": "test-naver-id",
            "user_id": "naver-user-123",
            "timestamp": "1700000000",
            "signature": "invalidsig",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_naver_unlink_callback_missing_params(naver_settings, monkeypatch):
    from starlette.testclient import TestClient

    app = _make_naver_app()
    client = TestClient(app)

    response = client.post("/auth/naver/unlink-callback", data={})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_naver_unlink_callback_wrong_client_id(naver_settings, monkeypatch):
    import hashlib
    import hmac

    from starlette.testclient import TestClient

    app = _make_naver_app()
    client = TestClient(app)

    client_id = "wrong-id"
    user_id = "naver-user-123"
    timestamp = "1700000000"
    message = f"{client_id}{user_id}{timestamp}"
    sig = hmac.new("test-naver-secret".encode(), message.encode(), hashlib.sha256).hexdigest()

    response = client.post(
        "/auth/naver/unlink-callback",
        data={
            "client_id": client_id,
            "user_id": user_id,
            "timestamp": timestamp,
            "signature": sig,
        },
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# verify_kakao_unlink_auth
# ---------------------------------------------------------------------------


def test_verify_kakao_unlink_auth_valid():
    from piloci.auth.oauth import verify_kakao_unlink_auth

    admin_key = "test-admin-key-12345"
    assert verify_kakao_unlink_auth(f"KakaoAK {admin_key}", admin_key)


def test_verify_kakao_unlink_auth_invalid_key():
    from piloci.auth.oauth import verify_kakao_unlink_auth

    assert not verify_kakao_unlink_auth("KakaoAK wrong-key", "correct-admin-key")


def test_verify_kakao_unlink_auth_bad_header():
    from piloci.auth.oauth import verify_kakao_unlink_auth

    assert not verify_kakao_unlink_auth("Bearer token", "admin-key")
    assert not verify_kakao_unlink_auth("", "admin-key")


# ---------------------------------------------------------------------------
# route_kakao_unlink_callback integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def kakao_settings(monkeypatch):
    from piloci.config import Settings

    s = Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
        kakao_client_id="test-kakao-id",
        kakao_client_secret="test-kakao-secret",
        kakao_admin_key="test-kakao-admin-key",
    )
    import piloci.api.routes as routes_mod

    monkeypatch.setattr(routes_mod, "get_settings", lambda: s)
    return s


@pytest.mark.asyncio
async def test_kakao_unlink_callback_post_success(kakao_settings, monkeypatch):
    from contextlib import asynccontextmanager

    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    mock_user = MagicMock()
    mock_user.oauth_provider = "kakao"
    mock_user.oauth_sub = "kakao-user-456"
    mock_user.oauth_access_token = "encrypted-token"
    mock_user.oauth_refresh_token = None

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()

    @asynccontextmanager
    async def _fake_session():
        yield mock_db

    import piloci.api.routes as routes_mod

    monkeypatch.setattr(routes_mod, "async_session", _fake_session)

    from piloci.api.routes import get_routes

    app = Starlette(routes=get_routes())
    client = TestClient(app)

    response = client.post(
        "/auth/kakao/unlink-callback",
        data={
            "app_id": "test-kakao-id",
            "user_id": "kakao-user-456",
            "referrer_type": "UNLINK_FROM_APPS",
        },
        headers={"Authorization": "KakaoAK test-kakao-admin-key"},
    )
    assert response.status_code == 200
    assert response.json()["result"] == "ok"
    assert mock_user.oauth_provider is None
    assert mock_user.oauth_sub is None


@pytest.mark.asyncio
async def test_kakao_unlink_callback_get_success(kakao_settings, monkeypatch):
    from contextlib import asynccontextmanager

    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def _fake_session():
        yield mock_db

    import piloci.api.routes as routes_mod

    monkeypatch.setattr(routes_mod, "async_session", _fake_session)

    from piloci.api.routes import get_routes

    app = Starlette(routes=get_routes())
    client = TestClient(app)

    response = client.get(
        "/auth/kakao/unlink-callback?app_id=test-kakao-id&user_id=999&referrer_type=ACCOUNT_DELETE",
        headers={"Authorization": "KakaoAK test-kakao-admin-key"},
    )
    assert response.status_code == 200
    assert response.json()["result"] == "ok"


@pytest.mark.asyncio
async def test_kakao_unlink_callback_invalid_auth(kakao_settings, monkeypatch):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from piloci.api.routes import get_routes

    app = Starlette(routes=get_routes())
    client = TestClient(app)

    response = client.post(
        "/auth/kakao/unlink-callback",
        data={
            "app_id": "test-kakao-id",
            "user_id": "kakao-user-456",
            "referrer_type": "UNLINK_FROM_APPS",
        },
        headers={"Authorization": "KakaoAK wrong-key"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_kakao_unlink_callback_missing_auth(kakao_settings, monkeypatch):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from piloci.api.routes import get_routes

    app = Starlette(routes=get_routes())
    client = TestClient(app)

    response = client.post(
        "/auth/kakao/unlink-callback",
        data={
            "app_id": "test-kakao-id",
            "user_id": "kakao-user-456",
            "referrer_type": "UNLINK_FROM_APPS",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_kakao_unlink_callback_missing_user_id(kakao_settings, monkeypatch):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from piloci.api.routes import get_routes

    app = Starlette(routes=get_routes())
    client = TestClient(app)

    response = client.post(
        "/auth/kakao/unlink-callback",
        data={"app_id": "test-kakao-id", "referrer_type": "UNLINK_FROM_APPS"},
        headers={"Authorization": "KakaoAK test-kakao-admin-key"},
    )
    assert response.status_code == 400
