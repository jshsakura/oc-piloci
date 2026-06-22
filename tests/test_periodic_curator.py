"""Tests for the periodic, staggered curator orchestrator (curator/periodic.py).

_sleep_or_signal and the three job passes are monkeypatched so ticks are
driven deterministically with no real sleeping or LLM/DB work.
"""

import asyncio

import pytest

from piloci.curator import periodic


class _Settings:
    curator_enabled = True
    distillation_enabled = True
    curator_cycle_sec = 21600
    distillation_temp_ceiling_c = 70.0
    distillation_load_ceiling_1m = 3.0


class _Store:
    pass


class _Instincts:
    pass


def _patch_jobs(monkeypatch, calls):
    async def fake_distill(*a, **k):
        calls.append("distill")
        return 1

    async def fake_profile(*a, **k):
        calls.append("profile")
        return 2

    async def fake_digest(*a, **k):
        calls.append("digest")
        return 3

    monkeypatch.setattr(periodic, "run_distillation_pass", fake_distill)
    monkeypatch.setattr(periodic, "_run_profile_refresh_cycle", fake_profile)
    monkeypatch.setattr(periodic, "_run_weekly_digest_cycle", fake_digest)


def _patch_cool(monkeypatch):
    monkeypatch.setattr(periodic, "read_cpu_temp_celsius", lambda: 40.0)
    monkeypatch.setattr(periodic, "read_load_average_1min", lambda: 0.5)


def _drive(monkeypatch, signals):
    """Replace _sleep_or_signal with a scripted sequence; stop when exhausted."""
    seq = list(signals)

    async def fake_sleep(stop_ev, wake_ev, seconds):
        if seq:
            return seq.pop(0)
        stop_ev.set()
        return "stop"

    monkeypatch.setattr(periodic, "_sleep_or_signal", fake_sleep)


@pytest.mark.asyncio
async def test_round_robin_one_job_per_tick(monkeypatch):
    calls = []
    _patch_jobs(monkeypatch, calls)
    _patch_cool(monkeypatch)
    _drive(monkeypatch, ["timeout"] * 4)

    await periodic.run_periodic_curator(_Settings(), _Store(), _Instincts(), asyncio.Event())

    # one job per tick, spread non-overlapping in rotation order
    assert calls == ["distill", "profile", "digest", "distill"]


@pytest.mark.asyncio
async def test_hot_tick_skipped_without_advancing(monkeypatch):
    calls = []
    _patch_jobs(monkeypatch, calls)
    temps = iter([90.0, 40.0])  # tick1 hot → skip, tick2 cool → run first job
    monkeypatch.setattr(periodic, "read_cpu_temp_celsius", lambda: next(temps))
    monkeypatch.setattr(periodic, "read_load_average_1min", lambda: 0.5)
    _drive(monkeypatch, ["timeout", "timeout"])

    await periodic.run_periodic_curator(_Settings(), _Store(), _Instincts(), asyncio.Event())

    # hot tick ran nothing and did not advance the rotation
    assert calls == ["distill"]


@pytest.mark.asyncio
async def test_run_now_wake_forces_distill(monkeypatch):
    calls = []
    _patch_jobs(monkeypatch, calls)
    _patch_cool(monkeypatch)
    _drive(monkeypatch, ["wake"])

    await periodic.run_periodic_curator(_Settings(), _Store(), _Instincts(), asyncio.Event())

    assert calls == ["distill"]


@pytest.mark.asyncio
async def test_stop_ends_loop_immediately(monkeypatch):
    calls = []
    _patch_jobs(monkeypatch, calls)
    _patch_cool(monkeypatch)
    _drive(monkeypatch, [])  # first sleep returns 'stop'

    await periodic.run_periodic_curator(_Settings(), _Store(), _Instincts(), asyncio.Event())

    assert calls == []


@pytest.mark.asyncio
async def test_no_instincts_runs_only_profile(monkeypatch):
    calls = []
    _patch_jobs(monkeypatch, calls)
    _patch_cool(monkeypatch)
    _drive(monkeypatch, ["timeout", "timeout"])

    await periodic.run_periodic_curator(_Settings(), _Store(), None, asyncio.Event())

    assert calls == ["profile", "profile"]


@pytest.mark.asyncio
async def test_wake_without_instincts_is_noop(monkeypatch):
    calls = []
    _patch_jobs(monkeypatch, calls)
    _patch_cool(monkeypatch)
    _drive(monkeypatch, ["wake"])

    await periodic.run_periodic_curator(_Settings(), _Store(), None, asyncio.Event())

    assert calls == []  # no distill capability without instincts store


@pytest.mark.asyncio
async def test_disabled_gate_returns_without_running(monkeypatch):
    calls = []
    _patch_jobs(monkeypatch, calls)

    class _Off(_Settings):
        curator_enabled = False

    await periodic.run_periodic_curator(_Off(), _Store(), _Instincts(), asyncio.Event())

    assert calls == []
