from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from piloci.main import _ProjectsCache, _shutdown, _startup


def test_projects_cache_set_and_get():
    cache = _ProjectsCache(ttl_sec=300)
    cache.set("u1", [{"id": "p1", "name": "proj"}])
    result = cache.get("u1")
    assert result is not None
    assert len(result) == 1
    assert result[0]["id"] == "p1"


def test_projects_cache_miss():
    cache = _ProjectsCache()
    assert cache.get("unknown") is None


def test_projects_cache_expiry(monkeypatch):
    import time

    cache = _ProjectsCache(ttl_sec=10)
    cache.set("u1", [{"id": "p1"}])

    current = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: current + 11)
    assert cache.get("u1") is None


def test_projects_cache_invalidate():
    cache = _ProjectsCache()
    cache.set("u1", [{"id": "p1"}])
    cache.invalidate("u1")
    assert cache.get("u1") is None


def test_projects_cache_returns_copy():
    cache = _ProjectsCache()
    cache.set("u1", [{"id": "p1"}])
    r1 = cache.get("u1")
    r1[0]["id"] = "modified"
    r2 = cache.get("u1")
    assert r2[0]["id"] == "p1"


@pytest.mark.asyncio
async def test_shutdown_sets_stop_and_closes_store():
    stop = asyncio.Event()
    store = AsyncMock()
    task = asyncio.create_task(asyncio.sleep(100))
    bg = [task]

    await _shutdown(store, stop, bg)
    assert stop.is_set()
    store.close.assert_called_once()


@pytest.mark.asyncio
async def test_startup_initializes_db_and_store(monkeypatch):
    mock_init_db = AsyncMock()
    mock_store = AsyncMock()
    mock_settings = MagicMock()
    mock_settings.curator_enabled = False

    monkeypatch.setattr("piloci.main.init_db", mock_init_db)
    monkeypatch.setattr("piloci.main.get_settings", lambda: mock_settings)

    stop = asyncio.Event()
    bg = []
    app = MagicMock()

    await _startup(app, mock_store, stop, bg)

    mock_init_db.assert_called_once()
    mock_store.ensure_collection.assert_called_once()
