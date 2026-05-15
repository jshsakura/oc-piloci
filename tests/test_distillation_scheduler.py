from __future__ import annotations

from datetime import time

from piloci.curator.scheduler import IdleWindow, SchedulerConfig, decide, parse_idle_window


def _config(
    *,
    idle_window: IdleWindow | None = None,
    temp_ceiling: float = 70.0,
    load_ceiling: float = 3.0,
    overflow: int = 50,
    max_chunks: int = 4,
) -> SchedulerConfig:
    return SchedulerConfig(
        idle_window=idle_window,
        temp_ceiling_celsius=temp_ceiling,
        load_ceiling_1m=load_ceiling,
        overflow_threshold=overflow,
        max_chunks=max_chunks,
    )


def test_empty_queue_holds() -> None:
    decision = decide(_config(), pending_count=0)
    assert decision.should_run is False
    assert "empty" in decision.reason


def test_idle_window_runs_regardless_of_temp() -> None:
    window = IdleWindow(start=time(2, 0), end=time(7, 0))
    decision = decide(
        _config(idle_window=window),
        pending_count=10,
        cpu_temp=85.0,  # well above ceiling
        load_1m=4.0,
        now_time=time(3, 30),
    )
    assert decision.should_run is True
    assert decision.use_external is False
    assert "idle" in decision.reason


def test_idle_window_wraparound_midnight() -> None:
    window = IdleWindow(start=time(22, 0), end=time(6, 0))
    inside = decide(_config(idle_window=window), pending_count=1, now_time=time(23, 30))
    assert inside.should_run is True
    inside_after_midnight = decide(
        _config(idle_window=window), pending_count=1, now_time=time(3, 0)
    )
    assert inside_after_midnight.should_run is True
    outside = decide(_config(idle_window=window), pending_count=1, now_time=time(12, 0))
    # outside the window, falls through to temp/load checks (none provided → run)
    assert outside.should_run is True


def test_normal_hours_temp_gate_holds() -> None:
    decision = decide(
        _config(temp_ceiling=70.0),
        pending_count=5,
        cpu_temp=72.0,
        load_1m=1.0,
        now_time=time(14, 0),
    )
    assert decision.should_run is False
    assert "soc" in decision.reason
    assert "70" in decision.reason


def test_normal_hours_load_gate_holds() -> None:
    decision = decide(
        _config(load_ceiling=3.0),
        pending_count=5,
        cpu_temp=50.0,
        load_1m=4.0,
        now_time=time(14, 0),
    )
    assert decision.should_run is False
    assert "load" in decision.reason


def test_overflow_routes_external_when_provider_available() -> None:
    decision = decide(
        _config(overflow=10),
        pending_count=15,
        has_external_provider=True,
        cpu_temp=72.0,  # would normally hold, but overflow path bypasses
        load_1m=1.0,
        now_time=time(14, 0),
    )
    assert decision.should_run is True
    assert decision.use_external is True
    assert "overflow" in decision.reason


def test_overflow_does_not_route_when_budget_exhausted() -> None:
    decision = decide(
        _config(overflow=10),
        pending_count=15,
        has_external_provider=True,
        budget_exhausted=True,
        cpu_temp=72.0,
        load_1m=1.0,
        now_time=time(14, 0),
    )
    # Falls through to local path; temp gate still holds.
    assert decision.should_run is False


def test_overflow_does_not_route_without_provider() -> None:
    decision = decide(
        _config(overflow=10),
        pending_count=15,
        has_external_provider=False,
        cpu_temp=50.0,
        load_1m=1.0,
        now_time=time(14, 0),
    )
    # No external available — local path runs since temp/load are fine.
    assert decision.should_run is True
    assert decision.use_external is False


def test_normal_hours_local_runs_when_within_thresholds() -> None:
    decision = decide(
        _config(),
        pending_count=5,
        cpu_temp=50.0,
        load_1m=1.0,
        now_time=time(14, 0),
    )
    assert decision.should_run is True
    assert decision.use_external is False
    assert "normal" in decision.reason


def test_parse_idle_window_valid() -> None:
    w = parse_idle_window("02:00-07:00")
    assert w is not None
    assert w.start == time(2, 0)
    assert w.end == time(7, 0)


def test_parse_idle_window_invalid() -> None:
    assert parse_idle_window("garbage") is None
    assert parse_idle_window("") is None
    assert parse_idle_window(None) is None
    assert parse_idle_window("25:00-26:00") is None


def test_recommended_chunks_full_when_cool_and_idle_load() -> None:
    decision = decide(
        _config(max_chunks=4),
        pending_count=5,
        cpu_temp=45.0,
        load_1m=0.5,
        now_time=time(14, 0),
    )
    assert decision.should_run is True
    assert decision.recommended_max_chunks == 4


def test_recommended_chunks_halved_when_warm() -> None:
    # 56°C ≥ ceiling 70 - 15 = 55 → warm tier, chunks halved.
    decision = decide(
        _config(max_chunks=4),
        pending_count=5,
        cpu_temp=56.0,
        load_1m=0.5,
        now_time=time(14, 0),
    )
    assert decision.should_run is True
    assert decision.recommended_max_chunks == 2


def test_recommended_chunks_one_when_hot() -> None:
    # 66°C ≥ ceiling 70 - 5 = 65 → hot tier, chunks=1.
    decision = decide(
        _config(max_chunks=4),
        pending_count=5,
        cpu_temp=66.0,
        load_1m=0.5,
        now_time=time(14, 0),
    )
    # Still under the 70 hold ceiling so it runs, but with the smallest cap.
    assert decision.should_run is True
    assert decision.recommended_max_chunks == 1


def test_recommended_chunks_one_when_load_near_ceiling() -> None:
    # load 2.8 ≥ ceiling 3.0 * 0.9 = 2.7 → hot tier even though SoC is cool.
    decision = decide(
        _config(max_chunks=4, load_ceiling=3.0),
        pending_count=5,
        cpu_temp=45.0,
        load_1m=2.8,
        now_time=time(14, 0),
    )
    assert decision.should_run is True
    assert decision.recommended_max_chunks == 1


def test_recommended_chunks_full_for_external_overflow() -> None:
    # External provider doesn't pay the SoC cost — recommend full chunks even
    # if local sensors say "warm".
    decision = decide(
        _config(max_chunks=4, overflow=10),
        pending_count=15,
        has_external_provider=True,
        cpu_temp=66.0,
        load_1m=0.5,
        now_time=time(14, 0),
    )
    assert decision.should_run is True
    assert decision.use_external is True
    assert decision.recommended_max_chunks == 4


def test_recommended_chunks_idle_window_scales_with_temp() -> None:
    # Even inside the idle window, hot SoC scales chunks down so the next
    # poll doesn't run into the thermal hold ceiling.
    window = IdleWindow(start=time(2, 0), end=time(7, 0))
    decision = decide(
        _config(idle_window=window, max_chunks=4),
        pending_count=10,
        cpu_temp=66.0,
        load_1m=0.5,
        now_time=time(3, 0),
    )
    assert decision.should_run is True
    assert decision.recommended_max_chunks == 1
