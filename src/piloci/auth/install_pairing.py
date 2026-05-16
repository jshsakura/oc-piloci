"""One-time install codes for token bootstrap.

When an API token is created in the web UI we also generate a short-lived
install code stored in Redis. The user runs::

    curl -sSL <base>/install/<code> | bash

The ``/install/<code>`` route atomically consumes the code (single-use) and
returns a bash installer with the real token inlined. Code is invalidated
after first use; idle codes auto-expire after ``INSTALL_CODE_TTL_SEC``.

Why this matters
----------------
- Token never appears in a URL the user types or copies (the *code* does,
  but it expires in 10 minutes and can be used only once).
- No plaintext token in shell history or browser history.
- Sharing install commands accidentally is harmless after first use.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import orjson
from redis.asyncio import Redis

if TYPE_CHECKING:
    from piloci.config import Settings

_INSTALL_PREFIX = "install:"
INSTALL_CODE_TTL_SEC = 10 * 60  # 10 minutes


def _generate_code() -> str:
    """Return a URL-safe install code (~128 bits entropy, ~22 chars).

    Raised from 8 bytes (64 bits) to 16 bytes (128 bits) so brute-force is
    infeasible even without rate-limiting — the code is single-use inside a
    10-minute TTL, but it doubles as the credential for an authenticated
    install. /install/{code} also has a per-IP rate limit applied at the
    route layer to slow online attackers further.
    """
    return secrets.token_urlsafe(16)


class InstallPairingStore:
    """Redis-backed store mapping one-time install codes to token payloads."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def create(self, *, token: str, base_url: str) -> str:
        """Generate a fresh install code and store its payload."""
        code = _generate_code()
        payload = orjson.dumps({"token": token, "base_url": base_url})
        await self._redis.set(
            f"{_INSTALL_PREFIX}{code}",
            payload,
            ex=INSTALL_CODE_TTL_SEC,
        )
        return code

    async def consume(self, code: str) -> dict[str, str] | None:
        """Atomically retrieve and delete a code's payload (single use)."""
        if not code:
            return None
        key = f"{_INSTALL_PREFIX}{code}"

        raw: bytes | None = None
        used_getdel = False
        getdel = getattr(self._redis, "getdel", None)
        if getdel is not None:
            try:
                raw = await getdel(key)
                used_getdel = True
            except Exception:
                # getdel call failed (older server or mock) — fall back below.
                used_getdel = False

        if not used_getdel:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.get(key)
                pipe.delete(key)
                results = await pipe.execute()
            raw = results[0] if results else None

        if raw is None:
            return None
        try:
            data = orjson.loads(raw)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return {"token": str(data.get("token", "")), "base_url": str(data.get("base_url", ""))}


_store: InstallPairingStore | None = None


def get_install_pairing_store(settings: Settings) -> InstallPairingStore:
    """Return a singleton InstallPairingStore (Redis client reused per process)."""
    global _store
    if _store is None:
        redis = Redis.from_url(settings.redis_url, decode_responses=False)
        _store = InstallPairingStore(redis=redis)
    return _store


def reset_install_pairing_store_for_testing() -> None:
    """Reset the module-level singleton (tests only)."""
    global _store
    _store = None
