from __future__ import annotations

import base64
import hashlib
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet

if TYPE_CHECKING:
    from piloci.config import Settings


def _build_fernet(settings: Settings) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode()).digest())
    return Fernet(key)


def encrypt_token(plain: str, settings: Settings) -> str:
    return _build_fernet(settings).encrypt(plain.encode()).decode()


def decrypt_token(encrypted: str, settings: Settings) -> str:
    return _build_fernet(settings).decrypt(encrypted.encode()).decode()
