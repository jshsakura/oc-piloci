"""OAuth 2.0 device-flow style pairing for ``piloci login`` (CLI/headless).

Three Redis records back a single pairing session:

  ``device:{device_code}`` → {status, user_code, token?, expires_at}
  ``device_user:{user_code}`` → device_code  (so the web form maps the
                                              short human code back to
                                              the long device code)

State machine:
  pending  → approved (terminal: token issued)
           → denied   (terminal)
           → (expired by TTL)

The CLI polls ``/auth/device/poll`` with ``device_code`` while the user
opens ``/device`` in a browser, types the ``user_code``, logs in, and
approves the device. Tokens are minted at approval time so the CLI never
sees a "preview" credential.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Literal

import orjson
from redis.asyncio import Redis

if TYPE_CHECKING:
    from piloci.config import Settings

DEVICE_PREFIX = "device:"
USER_CODE_PREFIX = "device_user:"
DEVICE_TTL_SEC = 10 * 60  # 10 minutes

# Avoid 0/O, 1/I/L, V/U etc. so a typo'd code is unambiguous on paper.
_USER_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTWXYZ23456789"

DeviceStatus = Literal["pending", "approved", "denied"]


def _gen_device_code() -> str:
    """Long opaque code returned to the CLI. ~64 bits entropy."""
    return secrets.token_urlsafe(24)


def _gen_user_code() -> str:
    """Short human-typeable code, format ``ABCD-1234``."""
    pick = lambda n: "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(n))  # noqa: E731
    return f"{pick(4)}-{pick(4)}"


class DevicePairingStore:
    """Redis-backed store for in-flight device pairings."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def create(self) -> tuple[str, str]:
        """Allocate a new pairing. Returns (device_code, user_code)."""
        # On the astronomically rare chance of a user_code collision we retry
        # rather than overwrite an in-flight session.
        for _ in range(8):
            device_code = _gen_device_code()
            user_code = _gen_user_code()
            existed = await self._redis.set(
                f"{USER_CODE_PREFIX}{user_code}",
                device_code.encode(),
                ex=DEVICE_TTL_SEC,
                nx=True,
            )
            if existed:
                payload = orjson.dumps({"status": "pending", "user_code": user_code})
                await self._redis.set(f"{DEVICE_PREFIX}{device_code}", payload, ex=DEVICE_TTL_SEC)
                return device_code, user_code
        raise RuntimeError("could not allocate user_code after 8 attempts")

    async def lookup_user_code(self, user_code: str) -> dict[str, str] | None:
        """Resolve a user_code to its device record. Used by the /device page."""
        if not user_code:
            return None
        raw = await self._redis.get(f"{USER_CODE_PREFIX}{user_code}")
        if raw is None:
            return None
        device_code = raw.decode() if isinstance(raw, bytes) else str(raw)
        record = await self._read(device_code)
        if record is None:
            return None
        return {"device_code": device_code, **record}

    async def approve(self, device_code: str, *, token: str) -> bool:
        """Mark a pairing approved and attach the issued JWT."""
        record = await self._read(device_code)
        if record is None or record.get("status") != "pending":
            return False
        record["status"] = "approved"
        record["token"] = token
        await self._redis.set(
            f"{DEVICE_PREFIX}{device_code}",
            orjson.dumps(record),
            ex=DEVICE_TTL_SEC,
        )
        return True

    async def deny(self, device_code: str) -> bool:
        """Mark a pairing denied. The CLI poll then returns 'denied' once."""
        record = await self._read(device_code)
        if record is None or record.get("status") != "pending":
            return False
        record["status"] = "denied"
        await self._redis.set(
            f"{DEVICE_PREFIX}{device_code}",
            orjson.dumps(record),
            ex=DEVICE_TTL_SEC,
        )
        return True

    async def poll(self, device_code: str) -> dict[str, str] | None:
        """Read the pairing state. Once a terminal state is delivered the
        records are deleted so the CLI cannot re-poll for the same token."""
        record = await self._read(device_code)
        if record is None:
            return None
        status = record.get("status", "pending")
        if status in ("approved", "denied"):
            user_code = record.get("user_code")
            await self._redis.delete(f"{DEVICE_PREFIX}{device_code}")
            if user_code:
                await self._redis.delete(f"{USER_CODE_PREFIX}{user_code}")
        return record

    async def _read(self, device_code: str) -> dict[str, str] | None:
        if not device_code:
            return None
        raw = await self._redis.get(f"{DEVICE_PREFIX}{device_code}")
        if raw is None:
            return None
        try:
            data = orjson.loads(raw)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return data


_store: DevicePairingStore | None = None


def get_device_pairing_store(settings: Settings) -> DevicePairingStore:
    """Process-wide singleton (Redis client reused)."""
    global _store
    if _store is None:
        redis = Redis.from_url(settings.redis_url, decode_responses=False)
        _store = DevicePairingStore(redis=redis)
    return _store


def reset_device_pairing_store_for_testing() -> None:
    global _store
    _store = None
