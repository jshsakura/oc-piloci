from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from piloci.curator.profile import (
    _PROFILE_MAX_LINES,
    _PROFILE_PROMPT_CHAR_BUDGET,
    _last_refresh,
    _normalize_profile_payload,
    _render_memory_lines,
    _summarize,
    get_profile,
    refresh_profile,
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


# ---------------------------------------------------------------------------
# _render_memory_lines — graceful truncation under Gemma's ctx ceiling
# ---------------------------------------------------------------------------


def test_render_memory_lines_respects_line_cap():
    """200 short memories: hard cap at _PROFILE_MAX_LINES."""
    memories = [{"content": f"m{i}", "tags": []} for i in range(200)]
    out = _render_memory_lines(memories)
    assert out.count("\n") + 1 == _PROFILE_MAX_LINES


def test_render_memory_lines_respects_char_budget():
    """Each memory is large — char budget should trip before the line cap.

    With 400-char inline clip × N lines we approach the 8000-char budget
    well before 80 lines, so the returned body stays under budget.
    """
    memories = [{"content": "x" * 800, "tags": []} for _ in range(80)]
    out = _render_memory_lines(memories)
    assert len(out) <= _PROFILE_PROMPT_CHAR_BUDGET
    # Each rendered line is "- " + 400 chars (clipped) → 402 chars. 8000/402
    # ≈ 19. Must produce some lines but well below the 80-line cap.
    assert 0 < out.count("\n") + 1 < _PROFILE_MAX_LINES


def test_render_memory_lines_clips_overlong_single_memory():
    """One giant memory: clipped inline so a single blob can't blow the budget."""
    memories = [{"content": "x" * 2000, "tags": []}]
    out = _render_memory_lines(memories)
    assert "..." in out
    # 400-char clip + "- " prefix → ~402 chars total.
    assert len(out) < 500


def test_render_memory_lines_keeps_at_least_one_line_even_if_over_budget():
    """Edge case: first line itself exceeds budget — keep it (clipped) anyway
    rather than returning an empty prompt that produces a useless summary."""
    memories = [{"content": "x" * 50_000, "tags": []}]
    out = _render_memory_lines(memories)
    assert out  # non-empty
    # Inline 400-char clip keeps the budget enforced even on a 50K memory.
    assert len(out) < 500


def test_render_memory_lines_empty_input():
    assert _render_memory_lines([]) == ""


def test_render_memory_lines_includes_tags():
    out = _render_memory_lines([{"content": "uses argon2", "tags": ["security", "auth"]}])
    assert "- uses argon2 [security,auth]" in out


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


# ---------------------------------------------------------------------------
# refresh_profile — change-gate keeps Gemma idle on quiet projects
# ---------------------------------------------------------------------------


def _patch_session(monkeypatch, existing_row):
    """Patch async_session so every `async with` yields a db whose select
    returns ``existing_row``. The same db is reused for the insert path."""
    from unittest.mock import AsyncMock, MagicMock

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_row
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("piloci.curator.profile.async_session", MagicMock(return_value=cm))
    return db


def _existing_row(profile, updated_at):
    import orjson

    row = MagicMock()
    row.profile_json = orjson.dumps(profile).decode()
    row.updated_at = updated_at  # naive datetime (UTC)
    return row


@pytest.mark.asyncio
async def test_refresh_profile_skips_llm_when_no_new_memory(monkeypatch):
    """A project whose newest memory predates its stored profile must NOT
    trigger an LLM call — this is the gate that stops the 24/7 regen loop."""
    from datetime import datetime, timezone

    _last_refresh.clear()
    stored = {"static": ["likes argon2"], "dynamic": ["working on wiki"]}
    profile_dt = datetime(2026, 6, 6, 0, 0, 0)  # naive UTC
    profile_epoch = profile_dt.replace(tzinfo=timezone.utc).timestamp()
    _patch_session(monkeypatch, _existing_row(stored, profile_dt))

    mock_chat = AsyncMock()
    monkeypatch.setattr("piloci.curator.profile.chat_json", mock_chat)

    store = AsyncMock()
    store.list = AsyncMock(
        return_value=[{"content": "old", "tags": [], "updated_at": int(profile_epoch - 1000)}]
    )
    settings = MagicMock(profile_refresh_min_interval_sec=1800)

    result = await refresh_profile("u1", "p1", settings, store, force=False)

    assert result == stored
    mock_chat.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_profile_regenerates_when_memory_is_newer(monkeypatch):
    """A memory newer than the stored profile must pass the gate and regen."""
    from datetime import datetime, timezone

    _last_refresh.clear()
    profile_dt = datetime(2026, 6, 6, 0, 0, 0)
    profile_epoch = profile_dt.replace(tzinfo=timezone.utc).timestamp()
    _patch_session(monkeypatch, _existing_row({"static": [], "dynamic": []}, profile_dt))

    mock_chat = AsyncMock(return_value={"static": ["fresh"], "dynamic": []})
    monkeypatch.setattr("piloci.curator.profile.chat_json", mock_chat)

    store = AsyncMock()
    store.list = AsyncMock(
        return_value=[{"content": "new", "tags": [], "updated_at": int(profile_epoch + 1000)}]
    )
    settings = MagicMock(profile_refresh_min_interval_sec=1800, gemma_endpoint="x", gemma_model="g")

    result = await refresh_profile("u1", "p1", settings, store, force=False)

    assert result == {"static": ["fresh"], "dynamic": []}
    mock_chat.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_profile_force_bypasses_gate(monkeypatch):
    """force=True regenerates even when nothing is newer than the profile."""
    from datetime import datetime, timezone

    _last_refresh.clear()
    profile_dt = datetime(2026, 6, 6, 0, 0, 0)
    profile_epoch = profile_dt.replace(tzinfo=timezone.utc).timestamp()
    _patch_session(monkeypatch, _existing_row({"static": ["old"], "dynamic": []}, profile_dt))

    mock_chat = AsyncMock(return_value={"static": ["forced"], "dynamic": []})
    monkeypatch.setattr("piloci.curator.profile.chat_json", mock_chat)

    store = AsyncMock()
    store.list = AsyncMock(
        return_value=[{"content": "old", "tags": [], "updated_at": int(profile_epoch - 1000)}]
    )
    settings = MagicMock(profile_refresh_min_interval_sec=1800, gemma_endpoint="x", gemma_model="g")

    result = await refresh_profile("u1", "p1", settings, store, force=True)

    assert result == {"static": ["forced"], "dynamic": []}
    mock_chat.assert_called_once()


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
