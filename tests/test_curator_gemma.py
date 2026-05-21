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


@pytest.mark.asyncio
async def test_chat_json_expands_budget_on_truncation(monkeypatch):
    # First response is length-capped (finish_reason == "length") → chat_json
    # should retry the same target with a doubled budget, then succeed.
    truncated = MagicMock()
    truncated.raise_for_status = MagicMock()
    truncated.json.return_value = {
        "choices": [{"finish_reason": "length", "message": {"content": '{"partial": '}}]
    }
    complete = MagicMock()
    complete.raise_for_status = MagicMock()
    complete.json.return_value = {
        "choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}]
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[truncated, complete])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("piloci.curator.gemma.httpx.AsyncClient", lambda timeout: mock_client)

    result = await chat_json(
        [{"role": "user", "content": "hi"}], max_tokens=1000, expand_on_truncation=2
    )
    assert result == {"ok": True}
    assert mock_client.post.call_count == 2
    first = mock_client.post.call_args_list[0].kwargs["json"]["max_tokens"]
    second = mock_client.post.call_args_list[1].kwargs["json"]["max_tokens"]
    assert second > first


@pytest.mark.asyncio
async def test_chat_json_ignores_truncation_when_not_opted_in(monkeypatch):
    # finish_reason == "length" but parseable + expand_on_truncation=0 (default):
    # legacy behavior, the result is returned as-is with no retry.
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"finish_reason": "length", "message": {"content": '{"ok": 1}'}}]
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("piloci.curator.gemma.httpx.AsyncClient", lambda timeout: mock_client)

    result = await chat_json([{"role": "user", "content": "hi"}])
    assert result == {"ok": 1}
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_chat_text_continues_on_length_truncation(monkeypatch):
    # First chunk stops at the cap (finish_reason="length") → chat_text must
    # ask the model to continue and stitch the parts into a complete body.
    part1 = MagicMock()
    part1.raise_for_status = MagicMock()
    part1.json.return_value = {
        "choices": [{"finish_reason": "length", "message": {"content": "AAA"}}]
    }
    part2 = MagicMock()
    part2.raise_for_status = MagicMock()
    part2.json.return_value = {
        "choices": [{"finish_reason": "stop", "message": {"content": "BBB"}}]
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[part1, part2])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("piloci.curator.gemma.httpx.AsyncClient", lambda timeout: mock_client)

    from piloci.curator.gemma import ProviderTarget, chat_text

    targets = [ProviderTarget(endpoint="https://x", model="glm", api_key="k", label="ext")]
    out = await chat_text([{"role": "user", "content": "write"}], targets=targets, max_tokens=10)
    assert out == "AAABBB"
    assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_chat_text_returns_single_shot_when_not_truncated(monkeypatch):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"finish_reason": "stop", "message": {"content": "DONE"}}]
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("piloci.curator.gemma.httpx.AsyncClient", lambda timeout: mock_client)

    from piloci.curator.gemma import ProviderTarget, chat_text

    targets = [ProviderTarget(endpoint="https://x", model="glm", api_key="k", label="ext")]
    out = await chat_text([{"role": "user", "content": "hi"}], targets=targets)
    assert out == "DONE"
    assert mock_client.post.call_count == 1
