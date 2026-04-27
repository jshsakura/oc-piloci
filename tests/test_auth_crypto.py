"""Tests for auth/crypto.py — Fernet-based token encryption."""

import pytest

from piloci.auth import crypto


def _settings():
    """Minimal settings-like object with jwt_secret."""
    from types import SimpleNamespace

    return SimpleNamespace(jwt_secret="test-secret-32-characters-minimum!")


class TestBuildFernet:
    def test_produces_valid_fernet(self):
        f = crypto._build_fernet(_settings())
        assert f is not None

        assert f._signing_key is not None

    def test_deterministic_key(self):
        f1 = crypto._build_fernet(_settings())
        f2 = crypto._build_fernet(_settings())
        assert f1._signing_key == f2._signing_key


class TestEncryptDecryptToken:
    def test_roundtrip(self):
        s = _settings()
        plain = "my-secret-access-token"
        encrypted = crypto.encrypt_token(plain, s)
        assert encrypted != plain
        assert isinstance(encrypted, str)
        decrypted = crypto.decrypt_token(encrypted, s)
        assert decrypted == plain

    def test_different_secrets_produce_different_ciphertext(self):
        from types import SimpleNamespace

        s1 = SimpleNamespace(jwt_secret="secret-one-aaaaaaaaaaaaaaaaaaa!")
        s2 = SimpleNamespace(jwt_secret="secret-two-bbbbbbbbbbbbbbbbbbb!")
        encrypted1 = crypto.encrypt_token("token", s1)
        encrypted2 = crypto.encrypt_token("token", s2)
        assert encrypted1 != encrypted2

    def test_encrypt_empty_string(self):
        s = _settings()
        encrypted = crypto.encrypt_token("", s)
        assert crypto.decrypt_token(encrypted, s) == ""

    def test_decrypt_invalid_token_raises(self):
        from cryptography.fernet import InvalidToken

        s = _settings()
        with pytest.raises(InvalidToken):
            crypto.decrypt_token("not-valid-fernet-token", s)
