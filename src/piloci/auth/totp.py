from __future__ import annotations

import base64
import hashlib
import io
import secrets
import string

import pyotp


def generate_totp_secret() -> str:
    """32자 base32 random secret 생성"""
    return pyotp.random_base32(length=32)


def get_totp_uri(secret: str, email: str, issuer: str = "piLoci") -> str:
    """otpauth:// URI 반환 (Google Authenticator 호환)"""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=issuer)


def get_qr_base64(secret: str, email: str) -> str:
    """QR 코드 PNG를 base64 data URI로 반환 — data:image/png;base64,..."""
    uri = get_totp_uri(secret, email)
    try:
        import qrcode

        img = qrcode.make(uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except ImportError:
        return uri


def verify_totp(secret: str, code: str) -> bool:
    """6자리 OTP 검증. valid_window=1 (앞뒤 30초 허용)"""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_backup_codes(count: int = 10) -> list[str]:
    """8자리 random 백업 코드 count개 생성 (예: 'A3F7-K9P2')"""
    alphabet = string.ascii_uppercase + string.digits
    codes: list[str] = []
    for _ in range(count):
        part1 = "".join(secrets.choice(alphabet) for _ in range(4))
        part2 = "".join(secrets.choice(alphabet) for _ in range(4))
        codes.append(f"{part1}-{part2}")
    return codes


def hash_backup_codes(codes: list[str]) -> list[str]:
    """백업 코드를 sha256으로 해싱 (DB 저장용)"""
    return [hashlib.sha256(code.encode()).hexdigest() for code in codes]


def verify_backup_code(plain: str, hashed_codes: list[str]) -> str | None:
    """사용된 코드의 해시 반환 (없으면 None) — 사용 후 해시 삭제용"""
    candidate = hashlib.sha256(plain.encode()).hexdigest()
    if candidate in hashed_codes:
        return candidate
    return None
