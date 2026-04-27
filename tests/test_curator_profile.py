from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from piloci.curator.profile import (
    _normalize_profile_payload,
    _summarize,
    get_profile,
    run_profile_worker,
)


def test_normalize_valid_payload():
    result = _normalize_profile_payload(
        {
            "static": ["pref1", "pref2"],
            "dynamic": ["recent1"],
        }
    )
    assert result == {"static": ["pref1", "pref2"], "dynamic": ["recent1"]}


def test_normalize_truncates_to_limits():
    result = _normalize_profile_payload(
        {
            "static": [f"s{i}" for i in range(30)],
            "dynamic": [f"d{i}" for i in range(20)],
        }
    )
    assert len(result["static"]) == 20
    assert len(result["dynamic"]) == 10


def test_normalize_non_dict_returns_empty():
    result = _normalize_profile_payload("not a dict")
    assert result == {"static": [], "dynamic": []}


def test_normalize_missing_keys():
    result = _normalize_profile_payload({})
    assert result == {"static": [], "dynamic": []}


def test_normalize_non_list_values():
    result = _normalize_profile_payload({"static": "not a list", "dynamic": 42})
    assert result == {"static": [], "dynamic": []}


def test_normalize_converts_items_to_strings():
    result = _normalize_profile_payload({"static": [123, None, True], "dynamic": []})
    assert result["static"] == ["123", "None", "True"]


@pytest.mark.asyncio
async def test_summarize_empty_memories():
    result = await _summarize([], MagicMock())
    assert result == {"static": [], "dynamic": []}


@pytest.mark.asyncio
async def test_summarize_calls_chat_json(monkeypatch):
    mock_chat = AsyncMock(return_value={"static": ["pref"], "dynamic": ["recent"]})
    monkeypatch.setattr("piloci.curator.profile.chat_json", mock_chat)
    settings = MagicMock(gemma_endpoint="http://localhost:9090", gemma_model="gemma")

    memories = [{"content": "user likes black", "tags": ["style"]}]
    result = await _summarize(memories, settings)

    assert result == {"static": ["pref"], "dynamic": ["recent"]}
    mock_chat.assert_called_once()


@pytest.mark.asyncio
async def test_get_profile_returns_none_when_no_row(monkeypatch):
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    @patch("piloci.curator.profile.async_session")
    async def run_test(mock_session_fn):
        mock_session_fn.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_fn.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await get_profile("u1", "p1")
        assert result is None

    await run_test()


@pytest.mark.asyncio
async def test_run_profile_worker_stops_on_event(monkeypatch):
    import asyncio

    settings = MagicMock()
    settings.curator_profile_project_limit = 5
    settings.curator_profile_pause_ms = 0
    settings.profile_refresh_min_interval_sec = 5

    stop_event = asyncio.Event()
    stop_event.set()

    mock_store = AsyncMock()
    await run_profile_worker(settings, mock_store, stop_event)
