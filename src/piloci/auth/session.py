from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import orjson
from redis.asyncio import Redis

if TYPE_CHECKING:
    from piloci.config import Settings

_SESSION_PREFIX = "session:"
_USER_SESSIONS_PREFIX = "user_sessions:"
_LOGIN_FAIL_PREFIX = "login_fail:"
_RATELIMIT_LOGIN_PREFIX = "ratelimit:login:"

_LOGIN_FAIL_TTL = 60 * 15  # 15 minutes
_RATELIMIT_TTL = 60  # 60 seconds


class SessionStore:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings
        self._session_ttl = settings.session_expire_days * 86400

    async def create_session(self, user_id: str, ip: str, user_agent: str) -> str:
        """Create a new session, enforcing max sessions per user via LRU eviction."""
        session_id = secrets.token_hex(32)
        now = datetime.now(tz=timezone.utc).isoformat()

        data = orjson.dumps(
            {
                "user_id": user_id,
                "created_at": now,
                "ip": ip,
                "user_agent": user_agent,
            }
        )

        session_key = f"{_SESSION_PREFIX}{session_id}"
        user_sessions_key = f"{_USER_SESSIONS_PREFIX}{user_id}"

        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.set(session_key, data, ex=self._session_ttl)
            pipe.sadd(user_sessions_key, session_id)
            await pipe.execute()

        # Enforce max sessions per user (LRU: remove oldest by creation time)
        await self._enforce_session_limit(user_id)

        return session_id

    async def _enforce_session_limit(self, user_id: str) -> None:
        """Remove oldest sessions if user exceeds session_max_per_user."""
        max_sessions = self._settings.session_max_per_user
        user_sessions_key = f"{_USER_SESSIONS_PREFIX}{user_id}"

        session_ids = await self._redis.smembers(user_sessions_key)
        if len(session_ids) <= max_sessions:
            return

        # Fetch creation times to determine LRU order
        sessions_with_time: list[tuple[str, str]] = []
        for sid in session_ids:
            raw = await self._redis.get(f"{_SESSION_PREFIX}{sid}")
            if raw is None:
                # Stale reference — clean up
                await self._redis.srem(user_sessions_key, sid)
                continue
            payload = orjson.loads(raw)
            sessions_with_time.append((sid, payload.get("created_at", "")))

        sessions_with_time.sort(key=lambda x: x[1])
        excess = len(sessions_with_time) - max_sessions
        for sid, _ in sessions_with_time[:excess]:
            await self._redis.delete(f"{_SESSION_PREFIX}{sid}")
            await self._redis.srem(user_sessions_key, sid)

    async def get_session(self, session_id: str) -> dict | None:
        """Return session data dict or None if not found / expired."""
        raw = await self._redis.get(f"{_SESSION_PREFIX}{session_id}")
        if raw is None:
            return None
        return orjson.loads(raw)

    async def delete_session(self, session_id: str, user_id: str) -> None:
        """Delete a session and remove it from the user's session set."""
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.delete(f"{_SESSION_PREFIX}{session_id}")
            pipe.srem(f"{_USER_SESSIONS_PREFIX}{user_id}", session_id)
            await pipe.execute()

    async def get_user_sessions(self, user_id: str) -> list[str]:
        """Return a list of active session IDs for a user."""
        members = await self._redis.smembers(f"{_USER_SESSIONS_PREFIX}{user_id}")
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    async def delete_all_user_sessions(self, user_id: str) -> None:
        """Delete all sessions for a user."""
        session_ids = await self.get_user_sessions(user_id)
        if not session_ids:
            return
        async with self._redis.pipeline(transaction=True) as pipe:
            for sid in session_ids:
                pipe.delete(f"{_SESSION_PREFIX}{sid}")
            pipe.delete(f"{_USER_SESSIONS_PREFIX}{user_id}")
            await pipe.execute()

    async def record_login_fail(self, email: str) -> int:
        """Increment the login failure counter for an email. Returns the new count."""
        key = f"{_LOGIN_FAIL_PREFIX}{email}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, _LOGIN_FAIL_TTL)
        return count

    async def clear_login_fails(self, email: str) -> None:
        """Reset the login failure counter for an email."""
        await self._redis.delete(f"{_LOGIN_FAIL_PREFIX}{email}")

    async def get_login_fails(self, email: str) -> int:
        """Return the current login failure count for an email."""
        val = await self._redis.get(f"{_LOGIN_FAIL_PREFIX}{email}")
        if val is None:
            return 0
        return int(val)

    async def record_ratelimit(self, ip: str) -> int:
        """Increment the IP-based rate limit counter. Returns the new count."""
        key = f"{_RATELIMIT_LOGIN_PREFIX}{ip}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, _RATELIMIT_TTL)
        return count


_store: SessionStore | None = None


def get_session_store(settings: Settings) -> SessionStore:
    """Return a singleton SessionStore instance."""
    global _store
    if _store is None:
        redis = Redis.from_url(settings.redis_url, decode_responses=False)
        _store = SessionStore(redis=redis, settings=settings)
    return _store
