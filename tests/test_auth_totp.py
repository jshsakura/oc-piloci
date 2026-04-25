from __future__ import annotations

import re

import pyotp
import pytest

from piloci.auth.totp import (
    generate_backup_codes,
    generate_totp_secret,
    get_qr_base64,
    get_totp_uri,
    hash_backup_codes,
    verify_backup_code,
    verify_totp,
)


class TestGenerateTotpSecret:
    def test_length_is_32(self) -> None:
        secret = generate_totp_secret()
        assert len(secret) == 32

    def test_is_valid_base32(self) -> None:
        secret = generate_totp_secret()
        # base32 문자: A-Z, 2-7
        assert re.fullmatch(r"[A-Z2-7]{32}", secret), f"Not valid base32: {secret}"

    def test_secrets_are_unique(self) -> None:
        secrets = {generate_totp_secret() for _ in range(10)}
        assert len(secrets) == 10


class TestVerifyTotp:
    def test_valid_current_code(self) -> None:
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret)
        current_code = totp.now()
        assert verify_totp(secret, current_code) is True

    def test_invalid_code_fails(self) -> None:
        secret = generate_totp_secret()
        assert verify_totp(secret, "000000") is False

    def test_wrong_format_fails(self) -> None:
        secret = generate_totp_secret()
        assert verify_totp(secret, "abc") is False

    def test_empty_code_fails(self) -> None:
        secret = generate_totp_secret()
        assert verify_totp(secret, "") is False


class TestGetTotpUri:
    def test_returns_otpauth_uri(self) -> None:
        secret = generate_totp_secret()
        uri = get_totp_uri(secret, "test@example.com")
        assert uri.startswith("otpauth://totp/")

    def test_contains_issuer(self) -> None:
        secret = generate_totp_secret()
        uri = get_totp_uri(secret, "test@example.com", issuer="piLoci")
        assert "piLoci" in uri

    def test_contains_email(self) -> None:
        secret = generate_totp_secret()
        uri = get_totp_uri(secret, "user@test.com")
        assert "user" in uri


class TestGetQrBase64:
    def test_returns_data_uri_or_otpauth(self) -> None:
        secret = generate_totp_secret()
        result = get_qr_base64(secret, "test@example.com")
        assert result.startswith("data:image/png;base64,") or result.startswith("otpauth://")

    def test_data_uri_format_when_qrcode_available(self) -> None:
        try:
            import qrcode  # noqa: F401

            secret = generate_totp_secret()
            result = get_qr_base64(secret, "test@example.com")
            assert result.startswith("data:image/png;base64,")
        except ImportError:
            pytest.skip("qrcode package not available")


class TestGenerateBackupCodes:
    def test_generates_10_codes_by_default(self) -> None:
        codes = generate_backup_codes()
        assert len(codes) == 10

    def test_custom_count(self) -> None:
        codes = generate_backup_codes(5)
        assert len(codes) == 5

    def test_format_is_xxxx_xxxx(self) -> None:
        codes = generate_backup_codes()
        pattern = re.compile(r"^[A-Z0-9]{4}-[A-Z0-9]{4}$")
        for code in codes:
            assert pattern.match(code), f"Bad format: {code}"

    def test_codes_are_unique(self) -> None:
        codes = generate_backup_codes(10)
        assert len(set(codes)) == 10


class TestVerifyBackupCode:
    def test_finds_correct_code(self) -> None:
        codes = generate_backup_codes(10)
        hashed = hash_backup_codes(codes)
        # 첫 번째 코드로 검증
        result = verify_backup_code(codes[0], hashed)
        assert result is not None
        assert result == hashed[0]

    def test_returns_none_for_unknown_code(self) -> None:
        codes = generate_backup_codes(10)
        hashed = hash_backup_codes(codes)
        result = verify_backup_code("XXXX-XXXX", hashed)
        assert result is None

    def test_finds_middle_code(self) -> None:
        codes = generate_backup_codes(10)
        hashed = hash_backup_codes(codes)
        result = verify_backup_code(codes[5], hashed)
        assert result == hashed[5]

    def test_hash_removal_pattern(self) -> None:
        """사용된 코드 해시를 삭제하는 패턴 검증"""
        codes = generate_backup_codes(10)
        hashed = hash_backup_codes(codes)
        used_hash = verify_backup_code(codes[0], hashed)
        # 삭제
        remaining = [h for h in hashed if h != used_hash]
        assert len(remaining) == 9
        # 다시 같은 코드는 통과하면 안 됨
        assert verify_backup_code(codes[0], remaining) is None
