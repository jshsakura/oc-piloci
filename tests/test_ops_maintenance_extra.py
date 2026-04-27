from __future__ import annotations

import asyncio
import importlib
from unittest.mock import MagicMock

import pytest

maintenance = importlib.import_module("piloci.ops.maintenance")


@pytest.mark.asyncio
async def test_run_maintenance_worker_stops_immediately():
    settings = MagicMock()
    settings.maintenance_interval_sec = 60
    settings.raw_session_retention_days = 14
    settings.audit_log_retention_days = 90

    stop = asyncio.Event()
    stop.set()

    await maintenance.run_maintenance_worker(settings, stop)


@pytest.mark.asyncio
async def test_run_maintenance_worker_handles_cleanup_exception(monkeypatch):
    call_count = {"n": 0}

    async def failing_cleanup(s):
        call_count["n"] += 1
        raise RuntimeError("db error")

    monkeypatch.setattr(maintenance, "cleanup_retention", failing_cleanup)

    settings = MagicMock()
    settings.maintenance_interval_sec = 1
    settings.raw_session_retention_days = 14
    settings.audit_log_retention_days = 90

    stop = asyncio.Event()

    async def quick_stop():
        await asyncio.sleep(0.1)
        stop.set()

    await asyncio.gather(
        maintenance.run_maintenance_worker(settings, stop),
        quick_stop(),
    )
    assert call_count["n"] >= 1
