"""Tests for the install code pairing store."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import orjson
import pytest

from piloci.auth import install_pairing as ip


def _redis_with_getdel(initial: dict[str, bytes] | None = None) -> AsyncMock:
    """Return a mock Redis exposing set/getdel against an in-memory dict."""
    store: dict[str, bytes] = dict(initial or {})

    redis = AsyncMock()

    async def _set(key, value, ex=None):
        store[key] = value
        return True

    async def _getdel(key):
        return store.pop(key, None)

    redis.set = AsyncMock(side_effect=_set)
    redis.getdel = AsyncMock(side_effect=_getdel)
    return redis


def _redis_pipeline_only(initial: dict[str, bytes] | None = None) -> AsyncMock:
    """Return a mock Redis without ``getdel`` so the pipeline fallback fires."""
    store: dict[str, bytes] = dict(initial or {})

    redis = AsyncMock()

    async def _set(key, value, ex=None):
        store[key] = value
        return True

    redis.set = AsyncMock(side_effect=_set)

    # getdel raises so the store falls back to the pipeline branch.
    async def _getdel_missing(_key):
        raise AttributeError("not supported")

    redis.getdel = AsyncMock(side_effect=_getdel_missing)

    pipe = AsyncMock()

    captured = {"key": None}

    def _get(key):
        captured["key"] = key

    def _delete(key):
        # delete returns nothing; we drop after execute returns
        pass

    pipe.get = MagicMock(side_effect=_get)
    pipe.delete = MagicMock(side_effect=_delete)

    async def _execute():
        key = captured["key"]
        value = store.pop(key, None) if key is not None else None
        return [value, 1 if value is not None else 0]

    pipe.execute = AsyncMock(side_effect=_execute)

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=pipe)
    cm.__aexit__ = AsyncMock(return_value=False)
    redis.pipeline = MagicMock(return_value=cm)
    return redis


def test_generate_code_is_url_safe_and_unbounded_uniqueness() -> None:
    seen = {ip._generate_code() for _ in range(500)}
    assert len(seen) == 500
    for c in seen:
        assert c
        assert "/" not in c and "+" not in c and "=" not in c


@pytest.mark.asyncio
async def test_create_stores_payload_with_ttl() -> None:
    redis = _redis_with_getdel()
    store = ip.InstallPairingStore(redis=redis)

    code = await store.create(token="jwt-fake", base_url="https://piloci.example/")

    assert code
    redis.set.assert_awaited_once()
    call_kwargs = redis.set.await_args.kwargs
    assert call_kwargs["ex"] == ip.INSTALL_CODE_TTL_SEC


@pytest.mark.asyncio
async def test_consume_returns_payload_then_none() -> None:
    redis = _redis_with_getdel()
    store = ip.InstallPairingStore(redis=redis)
    code = await store.create(token="abc.def.ghi", base_url="https://x")

    first = await store.consume(code)
    assert first == {"token": "abc.def.ghi", "base_url": "https://x"}

    second = await store.consume(code)
    assert second is None


@pytest.mark.asyncio
async def test_consume_handles_unknown_or_blank_code() -> None:
    redis = _redis_with_getdel()
    store = ip.InstallPairingStore(redis=redis)

    assert await store.consume("") is None
    assert await store.consume("does-not-exist") is None


@pytest.mark.asyncio
async def test_consume_falls_back_to_pipeline_when_getdel_unavailable() -> None:
    payload = orjson.dumps({"token": "tok", "base_url": "https://y"})
    redis = _redis_pipeline_only(initial={"install:CODE-1": payload})
    store = ip.InstallPairingStore(redis=redis)

    result = await store.consume("CODE-1")
    assert result == {"token": "tok", "base_url": "https://y"}

    # second consume returns None — pipeline already deleted it
    assert await store.consume("CODE-1") is None


@pytest.mark.asyncio
async def test_consume_returns_none_for_corrupt_payload() -> None:
    redis = _redis_with_getdel(initial={"install:bad": b"not-json"})
    store = ip.InstallPairingStore(redis=redis)

    assert await store.consume("bad") is None
