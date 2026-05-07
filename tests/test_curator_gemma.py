from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from piloci.curator.gemma import _get_semaphore, chat_json


def test_get_semaphore_returns_semaphore():
    sem = _get_semaphore()
    assert isinstance(sem, asyncio.Semaphore)


def test_get_semaphore_returns_same_instance():
    s1 = _get_semaphore()
    s2 = _get_semaphore()
    assert s1 is s2


@pytest.mark.asyncio
async def test_chat_json_success(monkeypatch):
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": '{"result": true}'}}]}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=fake_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("piloci.curator.gemma.httpx.AsyncClient", lambda timeout: mock_client)

    result = await chat_json([{"role": "user", "content": "hi"}])
    assert result == {"result": True}


@pytest.mark.asyncio
async def test_chat_json_strips_json_fences(monkeypatch):
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "choices": [{"message": {"content": '```json\n{"key": "val"}\n```'}}]
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=fake_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("piloci.curator.gemma.httpx.AsyncClient", lambda timeout: mock_client)

    result = await chat_json([{"role": "user", "content": "hi"}])
    assert result == {"key": "val"}


@pytest.mark.asyncio
async def test_chat_json_retries_on_failure(monkeypatch):
    import httpx

    call_count = 0

    async def fake_post(url, json, headers=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.HTTPError("timeout")

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": '{"ok": true}'}}]}
        return resp

    mock_client = AsyncMock()
    mock_client.post = fake_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("piloci.curator.gemma.httpx.AsyncClient", lambda timeout: mock_client)
    monkeypatch.setattr("piloci.curator.gemma.asyncio.sleep", AsyncMock())

    result = await chat_json([{"role": "user", "content": "hi"}], retries=3)
    assert result == {"ok": True}
    assert call_count == 2


@pytest.mark.asyncio
async def test_chat_json_raises_after_all_retries(monkeypatch):
    import httpx

    async def always_fail(url, json, headers=None):
        raise httpx.HTTPError("down")

    mock_client = AsyncMock()
    mock_client.post = always_fail
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("piloci.curator.gemma.httpx.AsyncClient", lambda timeout: mock_client)
    monkeypatch.setattr("piloci.curator.gemma.asyncio.sleep", AsyncMock())

    with pytest.raises(ValueError, match="failed after 3 retries"):
        await chat_json([{"role": "user", "content": "hi"}], retries=3)
