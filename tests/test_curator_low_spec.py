from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from piloci.config import Settings
from piloci.curator.queue import get_ingest_queue, reset_ingest_queue


def _settings(**overrides: Any) -> Settings:
    return Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
        **overrides,
    )


def _session_cm(session: MagicMock) -> AsyncMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.fixture(autouse=True)
def _reset_queue():
    reset_ingest_queue()
    yield
    reset_ingest_queue()


def test_low_spec_mode_applies_safer_runtime_defaults():
    settings = _settings(low_spec_mode=True)

    assert settings.workers == 1
    assert settings.embed_lru_size == 256
    assert settings.embed_executor_workers == 1
    assert settings.embed_max_concurrency == 1
    assert settings.ingest_queue_maxsize == 64
    assert settings.profile_refresh_min_interval_sec == 1800
    assert settings.curator_queue_poll_timeout_sec == 10.0
    assert settings.curator_profile_project_limit == 25
    assert settings.curator_profile_pause_ms == 250
    assert settings.curator_transcript_max_chars == 4000


@pytest.mark.asyncio
async def test_process_unfinished_respects_bounded_queue(monkeypatch):
    from piloci.curator import worker as worker_module

    rows = [
        SimpleNamespace(ingest_id="i1", user_id="u1", project_id="p1"),
        SimpleNamespace(ingest_id="i2", user_id="u2", project_id="p2"),
    ]
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))
    )

    monkeypatch.setattr(worker_module, "async_session", MagicMock(return_value=_session_cm(db)))

    settings = _settings(ingest_queue_maxsize=1)
    requeued = await worker_module.process_unfinished(settings, MagicMock())

    queue = get_ingest_queue(settings.ingest_queue_maxsize)
    assert requeued == 1
    assert queue.qsize() == 1


@pytest.mark.asyncio
async def test_profile_refresh_cycle_respects_limit_and_pause(monkeypatch):
    from piloci.curator import profile as profile_module

    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: [("u1", "p1"), ("u2", "p2")]))

    refresh = AsyncMock()
    sleep = AsyncMock()

    monkeypatch.setattr(profile_module, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(profile_module, "refresh_profile", refresh)
    monkeypatch.setattr(profile_module.asyncio, "sleep", sleep)

    settings = _settings(curator_profile_project_limit=2, curator_profile_pause_ms=25)
    processed = await profile_module._run_profile_refresh_cycle(
        settings, MagicMock(), asyncio.Event()
    )

    assert processed == 2
    assert refresh.await_count == 2
    assert sleep.await_count == 2
