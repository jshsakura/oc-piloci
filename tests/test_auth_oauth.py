"""Tests for Google OAuth helper functions."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_build_auth_url():
    from piloci.auth.oauth import build_auth_url

    url = build_auth_url(
        client_id="test-client",
        redirect_uri="http://localhost/auth/google/callback",
        state="random-state",
    )
    assert "accounts.google.com" in url
    assert "test-client" in url
    assert "random-state" in url
    assert "openid" in url


def test_generate_state():
    from piloci.auth.oauth import generate_state

    s1 = generate_state()
    s2 = generate_state()
    assert isinstance(s1, str)
    assert len(s1) > 20
    assert s1 != s2


@pytest.mark.asyncio
async def test_exchange_code_calls_google():
    from piloci.auth.oauth import exchange_code

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"access_token": "tok123"})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("piloci.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        result = await exchange_code(
            code="auth-code",
            client_id="cid",
            client_secret="csecret",
            redirect_uri="http://localhost/callback",
        )
    assert result["access_token"] == "tok123"


@pytest.mark.asyncio
async def test_get_userinfo_calls_google():
    from piloci.auth.oauth import get_userinfo

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"email": "u@test.com", "sub": "123"})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("piloci.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        result = await get_userinfo("access-token")
    assert result["email"] == "u@test.com"


@pytest.mark.asyncio
async def test_upsert_google_user_creates_new():
    from piloci.auth.oauth import upsert_google_user

    userinfo = {"email": "new@test.com", "sub": "g-sub-999", "name": "New User"}

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    user = await upsert_google_user(mock_db, userinfo)
    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()
    assert user is not None


@pytest.mark.asyncio
async def test_upsert_google_user_links_existing():
    from piloci.auth.oauth import upsert_google_user
    from unittest.mock import MagicMock

    userinfo = {"email": "existing@test.com", "sub": "g-sub-777", "name": "Existing"}

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

    user = await upsert_google_user(mock_db, userinfo)
    assert existing_user.oauth_provider == "google"
    assert existing_user.oauth_sub == "g-sub-777"
    assert user is existing_user
