from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from piloci.curator import profile as profile_module


def _session_cm(session: MagicMock) -> AsyncMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.fixture(autouse=True)
def _clear_last_refresh():
    profile_module._last_refresh.clear()
    yield
    profile_module._last_refresh.clear()


@pytest.mark.asyncio
async def test_refresh_profile_debounce_returns_existing_profile(monkeypatch, settings, mock_store):
    user_id = "u1"
    project_id = "p1"
    profile_module._last_refresh[(user_id, project_id)] = 123.0

    existing = SimpleNamespace(profile_json='{"static":["pref"],"dynamic":["recent"]}')
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: existing))

    summarize = AsyncMock()
    monkeypatch.setattr(profile_module, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(profile_module, "_summarize", summarize)
    monkeypatch.setattr(profile_module.time, "time", lambda: 123.5)
    settings.profile_refresh_min_interval_sec = 10

    result = await profile_module.refresh_profile(user_id, project_id, settings, mock_store)

    assert result == {"static": ["pref"], "dynamic": ["recent"]}
    mock_store.list.assert_not_awaited()
    summarize.assert_not_awaited()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_profile_force_bypasses_debounce(monkeypatch, settings, mock_store):
    user_id = "u1"
    project_id = "p1"
    profile_module._last_refresh[(user_id, project_id)] = 100.0

    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    summarize = AsyncMock(return_value={"static": ["forced"], "dynamic": ["fresh"]})

    mock_store.list.return_value = [{"content": "new", "updated_at": 1}]
    monkeypatch.setattr(profile_module, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(profile_module, "_summarize", summarize)
    monkeypatch.setattr(profile_module.time, "time", lambda: 101.0)
    settings.profile_refresh_min_interval_sec = 60

    result = await profile_module.refresh_profile(
        user_id, project_id, settings, mock_store, force=True
    )

    assert result == {"static": ["forced"], "dynamic": ["fresh"]}
    mock_store.list.assert_awaited_once_with(
        user_id=user_id, project_id=project_id, limit=200, offset=0
    )
    summarize.assert_awaited_once()
    db.commit.assert_awaited_once()
    assert profile_module._last_refresh[(user_id, project_id)] == 101.0


@pytest.mark.asyncio
async def test_refresh_profile_success_sorts_memories_and_stores_profile(
    monkeypatch, settings, mock_store
):
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    summarize = AsyncMock(return_value={"static": ["stable"], "dynamic": ["recent"]})
    mock_store.list.return_value = [
        {"content": "older", "updated_at": 1},
        {"content": "newer", "updated_at": 5},
        {"content": "middle", "updated_at": 3},
    ]

    monkeypatch.setattr(profile_module, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(profile_module, "_summarize", summarize)
    monkeypatch.setattr(profile_module.time, "time", lambda: 77.0)
    settings.profile_refresh_min_interval_sec = 0

    result = await profile_module.refresh_profile("u1", "p1", settings, mock_store)

    assert result == {"static": ["stable"], "dynamic": ["recent"]}
    summarize.assert_awaited_once()
    await_args = summarize.await_args
    assert await_args is not None
    memories = await_args.args[0]
    assert [memory["content"] for memory in memories] == ["newer", "middle", "older"]
    db.execute.assert_awaited_once()
    db.commit.assert_awaited_once()
    assert profile_module._last_refresh[("u1", "p1")] == 77.0


@pytest.mark.asyncio
async def test_refresh_profile_summarize_error_returns_empty_profile(
    monkeypatch, settings, mock_store
):
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    mock_store.list.return_value = [{"content": "memory", "updated_at": 1}]
    monkeypatch.setattr(profile_module, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(profile_module, "_summarize", AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(profile_module.time, "time", lambda: 55.0)
    settings.profile_refresh_min_interval_sec = 0

    result = await profile_module.refresh_profile("u1", "p1", settings, mock_store)

    assert result == {"static": [], "dynamic": []}
    db.execute.assert_awaited_once()
    db.commit.assert_awaited_once()
    assert profile_module._last_refresh[("u1", "p1")] == 55.0


@pytest.mark.asyncio
async def test_get_profile_returns_normalized_payload(monkeypatch):
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(
            scalar_one_or_none=lambda: SimpleNamespace(
                profile_json='{"static":[1],"dynamic":[true]}'
            )
        )
    )

    monkeypatch.setattr(profile_module, "async_session", MagicMock(return_value=_session_cm(db)))

    result = await profile_module.get_profile("u1", "p1")

    assert result == {"static": ["1"], "dynamic": ["True"]}


@pytest.mark.asyncio
async def test_get_profile_returns_none_for_invalid_json(monkeypatch):
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(
            scalar_one_or_none=lambda: SimpleNamespace(profile_json="not-json")
        )
    )

    monkeypatch.setattr(profile_module, "async_session", MagicMock(return_value=_session_cm(db)))

    result = await profile_module.get_profile("u1", "p1")

    assert result is None


@pytest.mark.asyncio
async def test_run_profile_refresh_cycle_processes_multiple_projects_despite_refresh_error(
    monkeypatch, settings
):
    rows = [("u1", "p1"), ("u2", "p2"), ("u3", "p3")]
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
    refresh = AsyncMock(side_effect=[None, RuntimeError("bad"), None])
    sleep = AsyncMock()

    monkeypatch.setattr(profile_module, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(profile_module, "refresh_profile", refresh)
    monkeypatch.setattr(profile_module.asyncio, "sleep", sleep)

    settings.curator_profile_project_limit = 3
    settings.curator_profile_pause_ms = 20
    processed = await profile_module._run_profile_refresh_cycle(
        settings, MagicMock(), asyncio.Event()
    )

    assert processed == 3
    assert refresh.await_count == 3
    assert sleep.await_count == 3


@pytest.mark.asyncio
async def test_run_profile_refresh_cycle_stops_when_event_is_set(monkeypatch, settings):
    rows = [("u1", "p1"), ("u2", "p2"), ("u3", "p3")]
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
    stop_event = asyncio.Event()

    async def refresh_once(*args, **kwargs):
        stop_event.set()

    refresh = AsyncMock(side_effect=refresh_once)
    sleep = AsyncMock()

    monkeypatch.setattr(profile_module, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(profile_module, "refresh_profile", refresh)
    monkeypatch.setattr(profile_module.asyncio, "sleep", sleep)

    settings.curator_profile_project_limit = 3
    settings.curator_profile_pause_ms = 25
    processed = await profile_module._run_profile_refresh_cycle(settings, MagicMock(), stop_event)

    assert processed == 1
    refresh.assert_awaited_once()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_profile_worker_runs_cycle_until_stop(monkeypatch, settings):
    stop_event = asyncio.Event()
    cycle = AsyncMock(side_effect=[1, 0])

    async def fake_sleep(seconds: float):
        stop_event.set()

    monkeypatch.setattr(profile_module, "_run_profile_refresh_cycle", cycle)
    monkeypatch.setattr(profile_module.asyncio, "sleep", fake_sleep)

    settings.profile_refresh_min_interval_sec = 5
    await profile_module.run_profile_worker(settings, MagicMock(), stop_event)

    assert cycle.await_count == 1
