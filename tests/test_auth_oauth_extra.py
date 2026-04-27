"""Tests for auth/oauth.py — revoke_provider_token (266-318)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from piloci.auth import oauth


def _mock_response(status_code: int = 200, text: str = "ok"):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


class TestRevokeProviderToken:
    @pytest.mark.asyncio
    async def test_google_revoke_success(self):
        resp = _mock_response(200)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("piloci.auth.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await oauth.revoke_provider_token("google", "access_tok", "cid", "csec")
        assert result is True
        mock_client.post.assert_called_once_with(
            "https://oauth2.googleapis.com/revoke",
            data={"token": "access_tok"},
        )

    @pytest.mark.asyncio
    async def test_github_revoke_success(self):
        resp = _mock_response(204)
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("piloci.auth.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await oauth.revoke_provider_token("github", "access_tok", "cid", "csec")
        assert result is True
        mock_client.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_naver_revoke_success(self):
        resp = _mock_response(200)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("piloci.auth.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await oauth.revoke_provider_token("naver", "access_tok", "cid", "csec")
        assert result is True
        call_data = mock_client.post.call_args[1]["data"]
        assert call_data["grant_type"] == "delete"

    @pytest.mark.asyncio
    async def test_kakao_revoke_success(self):
        resp = _mock_response(200)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("piloci.auth.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await oauth.revoke_provider_token("kakao", "access_tok", "cid", "csec")
        assert result is True
        headers = mock_client.post.call_args[1]["headers"]
        assert "Bearer" in headers["Authorization"]

    @pytest.mark.asyncio
    async def test_http_error_returns_false(self):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.HTTPError("network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("piloci.auth.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await oauth.revoke_provider_token("google", "access_tok", "cid", "csec")
        assert result is False

    @pytest.mark.asyncio
    async def test_non_200_status_returns_false(self):
        resp = _mock_response(400, "bad request")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("piloci.auth.oauth.httpx.AsyncClient", return_value=mock_client):
            result = await oauth.revoke_provider_token("google", "access_tok", "cid", "csec")
        assert result is False

    @pytest.mark.asyncio
    async def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown OAuth provider"):
            await oauth.revoke_provider_token("unknown_provider", "access_tok", "cid", "csec")
