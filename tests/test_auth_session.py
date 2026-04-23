"""Tests for SessionStore using a mock Redis."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import orjson
import pytest

from piloci.auth.session import SessionStore


def _make_settings(max_sessions: int = 10, expire_days: int = 14):
    s = MagicMock()
    s.session_max_per_user = max_sessions
    s.session_expire_days = expire_days
    s.redis_url = "redis://localhost:6379/0"
    return s


def _make_pipeline_ctx(results=None):
    """Return a mock async context manager for redis.pipeline()."""
    pipe = AsyncMock()
    pipe.set = AsyncMock()
    pipe.sadd = AsyncMock()
    pipe.delete = AsyncMock()
    pipe.srem = AsyncMock()
    pipe.execute = AsyncMock(return_value=results or [True, 1])
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=pipe)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, pipe


@pytest.mark.asyncio
async def test_create_session_returns_hex_token():
    settings = _make_settings()
    redis = AsyncMock()
    cm, pipe = _make_pipeline_ctx()
    redis.pipeline = MagicMock(return_value=cm)
    redis.smembers = AsyncMock(return_value=set())

    store = SessionStore(redis=redis, settings=settings)
    sid = await store.create_session("user-1", "127.0.0.1", "TestAgent/1.0")

    assert isinstance(sid, str)
    assert len(sid) == 64  # 32 bytes hex


@pytest.mark.asyncio
async def test_create_session_stores_data_in_pipeline():
    settings = _make_settings()
    redis = AsyncMock()
    cm, pipe = _make_pipeline_ctx()
    redis.pipeline = MagicMock(return_value=cm)
    redis.smembers = AsyncMock(return_value=set())

    store = SessionStore(redis=redis, settings=settings)
    await store.create_session("user-abc", "10.0.0.1", "curl/7.0")

    pipe.set.assert_called_once()
    pipe.sadd.assert_called_once()


@pytest.mark.asyncio
async def test_get_session_returns_parsed_data():
    settings = _make_settings()
    redis = AsyncMock()
    payload = orjson.dumps({"user_id": "u1", "ip": "127.0.0.1", "created_at": "2026-01-01T00:00:00+00:00", "user_agent": ""})
    redis.get = AsyncMock(return_value=payload)

    store = SessionStore(redis=redis, settings=settings)
    data = await store.get_session("some-session-id")

    assert data is not None
    assert data["user_id"] == "u1"


@pytest.mark.asyncio
async def test_get_session_returns_none_when_missing():
    settings = _make_settings()
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    store = SessionStore(redis=redis, settings=settings)
    assert await store.get_session("missing") is None


@pytest.mark.asyncio
async def test_delete_session_calls_pipeline():
    settings = _make_settings()
    redis = AsyncMock()
    cm, pipe = _make_pipeline_ctx()
    redis.pipeline = MagicMock(return_value=cm)

    store = SessionStore(redis=redis, settings=settings)
    await store.delete_session("sid-123", "user-1")

    pipe.delete.assert_called_once()
    pipe.srem.assert_called_once()


@pytest.mark.asyncio
async def test_record_login_fail_returns_count():
    settings = _make_settings()
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock()

    store = SessionStore(redis=redis, settings=settings)
    count = await store.record_login_fail("user@test.com")

    assert count == 1
    redis.expire.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_login_fail_no_expire_on_subsequent():
    settings = _make_settings()
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=3)
    redis.expire = AsyncMock()

    store = SessionStore(redis=redis, settings=settings)
    count = await store.record_login_fail("user@test.com")

    assert count == 3
    redis.expire.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_login_fails():
    settings = _make_settings()
    redis = AsyncMock()
    redis.delete = AsyncMock()

    store = SessionStore(redis=redis, settings=settings)
    await store.clear_login_fails("user@test.com")
    redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_login_fails_returns_zero_when_missing():
    settings = _make_settings()
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    store = SessionStore(redis=redis, settings=settings)
    assert await store.get_login_fails("nobody@test.com") == 0


@pytest.mark.asyncio
async def test_get_login_fails_returns_count():
    settings = _make_settings()
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b"4")

    store = SessionStore(redis=redis, settings=settings)
    assert await store.get_login_fails("user@test.com") == 4


@pytest.mark.asyncio
async def test_get_user_sessions_decodes_bytes():
    settings = _make_settings()
    redis = AsyncMock()
    redis.smembers = AsyncMock(return_value={b"sid1", b"sid2"})

    store = SessionStore(redis=redis, settings=settings)
    sessions = await store.get_user_sessions("user-1")
    assert set(sessions) == {"sid1", "sid2"}


@pytest.mark.asyncio
async def test_delete_all_user_sessions_noop_when_empty():
    settings = _make_settings()
    redis = AsyncMock()
    redis.smembers = AsyncMock(return_value=set())

    store = SessionStore(redis=redis, settings=settings)
    await store.delete_all_user_sessions("user-1")
    redis.pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_record_ratelimit_returns_count():
    settings = _make_settings()
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock()

    store = SessionStore(redis=redis, settings=settings)
    count = await store.record_ratelimit("1.2.3.4")
    assert count == 1
    redis.expire.assert_awaited_once()
