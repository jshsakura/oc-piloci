from __future__ import annotations

import time
import uuid

import jwt
import pytest

from piloci.auth.jwt_utils import create_token, decode_token_unsafe, verify_token
from piloci.config import Settings


def _make_settings(**overrides) -> Settings:
    defaults = {
        "jwt_secret": "a-very-long-dev-secret-that-is-at-least-32-chars",
        "jwt_algorithm": "HS256",
        "jwt_expire_days": 90,
        "session_secret": "a-very-long-dev-secret-that-is-at-least-32-chars",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _token_id() -> str:
    return str(uuid.uuid4())


class TestCreateAndVerifyToken:
    def test_roundtrip_user_scope(self):
        settings = _make_settings()
        token = create_token(
            user_id="uid-123",
            email="user@example.com",
            project_id=None,
            project_slug=None,
            scope="user",
            settings=settings,
            token_id=_token_id(),
        )
        payload = verify_token(token, settings)
        assert payload["sub"] == "uid-123"
        assert payload["email"] == "user@example.com"
        assert payload["scope"] == "user"
        assert payload["project_id"] is None
        assert payload["project_slug"] is None
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload

    def test_roundtrip_project_scope(self):
        settings = _make_settings()
        token = create_token(
            user_id="uid-456",
            email="dev@example.com",
            project_id="proj-abc",
            project_slug="webapp-dev",
            scope="project",
            settings=settings,
            token_id=_token_id(),
        )
        payload = verify_token(token, settings)
        assert payload["scope"] == "project"
        assert payload["project_id"] == "proj-abc"
        assert payload["project_slug"] == "webapp-dev"

    def test_verify_wrong_secret_raises(self):
        settings = _make_settings()
        token = create_token(
            user_id="uid-789",
            email="x@example.com",
            project_id=None,
            project_slug=None,
            scope="user",
            settings=settings,
            token_id=_token_id(),
        )
        bad_settings = _make_settings(jwt_secret="another-very-long-dev-secret-at-least-32chars")
        with pytest.raises(ValueError):
            verify_token(token, bad_settings)

    def test_verify_expired_token_raises(self):
        settings = _make_settings()
        # Manually craft an already-expired token
        now = int(time.time())
        payload = {
            "sub": "uid-exp",
            "email": "exp@example.com",
            "project_id": None,
            "project_slug": None,
            "scope": "user",
            "iat": now - 200,
            "exp": now - 100,
            "jti": _token_id(),
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        with pytest.raises(ValueError, match="expired"):
            verify_token(token, settings)

    def test_verify_malformed_token_raises(self):
        settings = _make_settings()
        with pytest.raises(ValueError):
            verify_token("not.a.valid.token", settings)


class TestDecodeTokenUnsafe:
    def test_returns_payload_without_verification(self):
        settings = _make_settings()
        tid = _token_id()
        token = create_token(
            user_id="uid-unsafe",
            email="u@example.com",
            project_id=None,
            project_slug=None,
            scope="user",
            settings=settings,
            token_id=tid,
        )
        payload = decode_token_unsafe(token)
        assert payload["sub"] == "uid-unsafe"
        assert payload["jti"] == tid

    def test_decodes_token_signed_with_different_secret(self):
        settings = _make_settings()
        token = create_token(
            user_id="uid-diff",
            email="d@example.com",
            project_id=None,
            project_slug=None,
            scope="user",
            settings=settings,
            token_id=_token_id(),
        )
        # Should not raise even if we "don't know" the secret
        payload = decode_token_unsafe(token)
        assert payload["sub"] == "uid-diff"
