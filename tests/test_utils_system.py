from __future__ import annotations

import os

from piloci.utils.system import detect_active_cores


def test_detect_active_cores_respects_env_override(monkeypatch) -> None:
    monkeypatch.setenv("PILOCI_AVAILABLE_CORES", "2")
    assert detect_active_cores() == 2


def test_detect_active_cores_ignores_garbage_env(monkeypatch) -> None:
    monkeypatch.setenv("PILOCI_AVAILABLE_CORES", "not-an-int")
    # Falls through to sched_getaffinity / cpu_count, both of which return >=1.
    assert detect_active_cores() >= 1


def test_detect_active_cores_clamps_zero_or_negative(monkeypatch) -> None:
    monkeypatch.setenv("PILOCI_AVAILABLE_CORES", "0")
    # Zero is treated as "unset" — falls through to the kernel reading.
    assert detect_active_cores() >= 1


def test_detect_active_cores_no_env_returns_kernel_view(monkeypatch) -> None:
    monkeypatch.delenv("PILOCI_AVAILABLE_CORES", raising=False)
    n = detect_active_cores()
    assert n >= 1
    # Must agree with the affinity mask the test runner sees.
    try:
        assert n == len(os.sched_getaffinity(0))
    except AttributeError:
        # Platform without sched_getaffinity — just confirm the fallback held.
        assert n == (os.cpu_count() or 1)
