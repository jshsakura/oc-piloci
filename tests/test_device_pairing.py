"""Tests for the device-flow pairing store."""

from __future__ import annotations

from unittest.mock import AsyncMock

import orjson
import pytest

from piloci.auth import device_pairing as dp


def _fake_redis() -> AsyncMock:
    """In-memory mock that supports the subset of redis-py we touch."""
    store: dict[str, bytes] = {}

    redis = AsyncMock()

    async def _set(key, value, ex=None, nx=False):
        if nx and key in store:
            return None
        store[key] = value
        return True

    async def _get(key):
        return store.get(key)

    async def _delete(key):
        store.pop(key, None)
        return 1

    redis.set = AsyncMock(side_effect=_set)
    redis.get = AsyncMock(side_effect=_get)
    redis.delete = AsyncMock(side_effect=_delete)
    return redis


def test_user_code_format() -> None:
    code = dp._gen_user_code()
    assert len(code) == 9
    assert code[4] == "-"
    # No ambiguous characters in the alphabet.
    for c in code.replace("-", ""):
        assert c in dp._USER_CODE_ALPHABET


@pytest.mark.asyncio
async def test_create_returns_distinct_codes_and_writes_both_keys() -> None:
    redis = _fake_redis()
    store = dp.DevicePairingStore(redis=redis)

    device, user = await store.create()
    # Both keys present, both with TTL.
    assert any("device:" in k for k in (await _all_keys(redis)))
    assert any("device_user:" in k for k in (await _all_keys(redis)))
    # Round-trip: user_code resolves to device record.
    record = await store.lookup_user_code(user)
    assert record is not None
    assert record["device_code"] == device
    assert record["status"] == "pending"


@pytest.mark.asyncio
async def test_approve_then_poll_returns_token_then_record_is_gone() -> None:
    redis = _fake_redis()
    store = dp.DevicePairingStore(redis=redis)
    device, user = await store.create()

    assert await store.approve(device, token="JWT.fake.123") is True

    record = await store.poll(device)
    assert record is not None
    assert record["status"] == "approved"
    assert record["token"] == "JWT.fake.123"

    # poll() consumes terminal state — second call sees the empty Redis.
    assert await store.poll(device) is None
    assert await store.lookup_user_code(user) is None


@pytest.mark.asyncio
async def test_deny_propagates_through_poll() -> None:
    redis = _fake_redis()
    store = dp.DevicePairingStore(redis=redis)
    device, _ = await store.create()

    assert await store.deny(device) is True
    record = await store.poll(device)
    assert record is not None
    assert record["status"] == "denied"
    assert "token" not in record


@pytest.mark.asyncio
async def test_approve_after_terminal_state_is_noop() -> None:
    redis = _fake_redis()
    store = dp.DevicePairingStore(redis=redis)
    device, _ = await store.create()

    await store.approve(device, token="t1")
    # Second approval attempt should fail because status is no longer 'pending'.
    assert await store.approve(device, token="t2") is False


@pytest.mark.asyncio
async def test_lookup_user_code_returns_none_for_unknown_or_blank() -> None:
    redis = _fake_redis()
    store = dp.DevicePairingStore(redis=redis)
    assert await store.lookup_user_code("") is None
    assert await store.lookup_user_code("UNKN-OWN0") is None


async def _all_keys(redis: AsyncMock) -> list[str]:
    """Best-effort key listing for the fake redis."""
    # Our fake redis stashes things via .set side_effect; pull from the closure.
    # `.set.call_args_list` lets us list every key written.
    return [c.args[0] for c in redis.set.call_args_list if c.args]


def test_create_handles_user_code_collision(monkeypatch: pytest.MonkeyPatch) -> None:
    """If user_code collides, the loop retries until a free slot is found."""
    redis = _fake_redis()
    # Pre-occupy the first user_code we'll generate.
    sequence = ["AAAA-1111", "AAAA-1111", "BBBB-2222"]

    def _next_code() -> str:
        return sequence.pop(0) if sequence else "ZZZZ-9999"

    monkeypatch.setattr(dp, "_gen_user_code", _next_code)

    async def _run() -> None:
        # Pre-fill the conflicting key so the first attempt's nx=True fails.
        await redis.set(f"{dp.USER_CODE_PREFIX}AAAA-1111", b"existing")
        store = dp.DevicePairingStore(redis=redis)
        device, user = await store.create()
        assert user == "BBBB-2222"
        assert isinstance(device, str)

    import asyncio

    asyncio.run(_run())


@pytest.mark.asyncio
async def test_create_corrupt_payload_returns_none() -> None:
    redis = _fake_redis()
    # Hand-stuff a corrupt record so _read returns None.
    await redis.set(f"{dp.DEVICE_PREFIX}garbage", b"{not-json")
    store = dp.DevicePairingStore(redis=redis)
    assert await store._read("garbage") is None
    # Sanity: a clean record still parses.
    await redis.set(f"{dp.DEVICE_PREFIX}clean", orjson.dumps({"status": "pending"}))
    assert (await store._read("clean")) == {"status": "pending"}


@pytest.mark.asyncio
async def test_approve_with_targets_persists_selection_for_poll() -> None:
    redis = _fake_redis()
    store = dp.DevicePairingStore(redis=redis)
    device, _ = await store.create()

    assert await store.approve(device, token="JWT.fake", targets=["claude", "cursor"]) is True
    record = await store.poll(device)
    assert record is not None
    assert record["status"] == "approved"
    assert record["targets"] == ["claude", "cursor"]


@pytest.mark.asyncio
async def test_approve_without_targets_omits_field() -> None:
    redis = _fake_redis()
    store = dp.DevicePairingStore(redis=redis)
    device, _ = await store.create()

    assert await store.approve(device, token="JWT.fake") is True
    record = await store.poll(device)
    assert record is not None
    # Older clients that don't pass targets must not see a stray empty list —
    # the CLI keys on its absence to fall back to local auto-detection.
    assert "targets" not in record
