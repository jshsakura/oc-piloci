from __future__ import annotations

"""Periodic, staggered curator orchestrator.

Replaces the autonomous worker army (independent continuous loops for
distillation + profile + weekly-digest + team-wiki). The old distillation
scheduler granted "idle window → full local throughput" (a 5s poll), so the
Pi ground the local Gemma back-to-back whenever idle = furnace; four workers
also hammered the single local model slot concurrently.

This runs exactly ONE job per tick in round-robin, spread across the cycle so
jobs never overlap (one local LLM burst at a time), with a temp/load safety
gate that skips a tick when the SoC is hot. team-wiki is intentionally
excluded.

    cycle = settings.curator_cycle_sec          (default 6h)
    tick  = cycle / number_of_active_jobs        (3 jobs → one job every 2h)

The shared wake event (``/api/distillation/run-now`` → ``request_wake()``)
forces an immediate distillation pass, independent of the rotation.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from piloci.config import Settings
from piloci.curator.distillation_worker import _get_wake_event, run_distillation_pass
from piloci.curator.profile import _run_profile_refresh_cycle
from piloci.curator.scheduler import read_cpu_temp_celsius, read_load_average_1min
from piloci.curator.weekly_digest_worker import _run_cycle as _run_weekly_digest_cycle
from piloci.storage.instincts_store import InstinctsStore
from piloci.storage.lancedb_store import MemoryStore

logger = logging.getLogger(__name__)

_MIN_TICK_SEC = 60


def _hot_reason(settings: Settings) -> str | None:
    """Return a reason string if the SoC is too hot/busy to run a job now."""
    temp = read_cpu_temp_celsius()
    if temp is not None and temp >= settings.distillation_temp_ceiling_c:
        return f"soc {temp:.1f}°C ≥ {settings.distillation_temp_ceiling_c:.1f}°C"
    load = read_load_average_1min()
    if load is not None and load >= settings.distillation_load_ceiling_1m:
        return f"load {load:.2f} ≥ {settings.distillation_load_ceiling_1m:.2f}"
    return None


async def _sleep_or_signal(
    stop_event: asyncio.Event, wake_event: asyncio.Event, seconds: float
) -> str:
    """Sleep up to ``seconds``; return 'stop' | 'wake' | 'timeout'.

    Unlike distillation_worker._sleep_until this reports *why* it woke so the
    orchestrator can tell a forced run-now from a normal tick. Wake is cleared
    here so the next sleep blocks again.
    """
    if seconds <= 0:
        return "timeout"
    stop_task = asyncio.create_task(stop_event.wait())
    wake_task = asyncio.create_task(wake_event.wait())
    try:
        await asyncio.wait(
            {stop_task, wake_task},
            timeout=seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for t in (stop_task, wake_task):
            if not t.done():
                t.cancel()
    if stop_event.is_set():
        return "stop"
    if wake_event.is_set():
        wake_event.clear()
        return "wake"
    return "timeout"


async def run_periodic_curator(
    settings: Settings,
    store: MemoryStore,
    instincts_store: InstinctsStore | None,
    stop_event: asyncio.Event,
) -> None:
    """Single staggered orchestrator: one curation job per tick, round-robin.

    Distillation and weekly digest need the instincts store; when it's absent
    only the profile job runs. team-wiki is not included by design.
    """
    if not (settings.curator_enabled and settings.distillation_enabled):
        logger.info("periodic curator: disabled (curator/distillation gate off)")
        return

    async def _profile() -> int:
        return await _run_profile_refresh_cycle(settings, store, stop_event)

    jobs: list[tuple[str, Callable[[], Awaitable[int]]]] = []
    distill_fn: Callable[[], Awaitable[int]] | None = None
    if instincts_store is not None:
        instincts = instincts_store  # narrowed non-None for the closures below

        async def _distill() -> int:
            return await run_distillation_pass(settings, store, instincts, stop_event)

        async def _digest() -> int:
            return await _run_weekly_digest_cycle(settings, store, instincts)

        distill_fn = _distill
        jobs = [("distill", _distill), ("profile", _profile), ("digest", _digest)]
    else:
        jobs = [("profile", _profile)]

    tick = max(_MIN_TICK_SEC, settings.curator_cycle_sec // len(jobs))
    wake = _get_wake_event()
    logger.info(
        "periodic curator started: %d jobs [%s], cycle=%ds, tick=%ds",
        len(jobs),
        ", ".join(name for name, _ in jobs),
        settings.curator_cycle_sec,
        tick,
    )

    idx = 0
    while not stop_event.is_set():
        signal = await _sleep_or_signal(stop_event, wake, tick)
        if signal == "stop":
            break

        if signal == "wake":
            # Explicit /api/distillation/run-now → one distill pass now,
            # bypassing rotation and the temp gate (user asked for it).
            if distill_fn is None:
                continue
            try:
                n = await distill_fn()
                logger.info("periodic curator: run-now distill pass → %d rows", n)
            except Exception:
                logger.exception("periodic curator: run-now distill failed")
            continue

        # Normal tick: safety gate, then exactly one job in rotation.
        reason = _hot_reason(settings)
        if reason is not None:
            logger.info("periodic curator: tick skipped — %s", reason)
            continue  # do NOT advance idx — retry the same job next tick

        name, job = jobs[idx % len(jobs)]
        idx += 1
        try:
            result = await job()
            logger.info("periodic curator: ran '%s' → %s", name, result)
        except Exception:
            logger.exception("periodic curator: job '%s' failed", name)

    logger.info("periodic curator stopped")
