from __future__ import annotations

from datetime import datetime, timezone

from piloci.notify.health import AlertTracker, _eval_breach, reset_trackers


def setup_function() -> None:
    reset_trackers()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_no_fire_below_consecutive_required() -> None:
    tracker = AlertTracker()
    now = _now()
    for _ in range(2):
        fired = _eval_breach(
            tracker,
            breached=True,
            consecutive_required=3,
            cooldown_min=30,
            now=now,
            fire_message="hot",
            recover_message="ok",
            kind="temp",
            new_value="80",
        )
        assert fired == []
    assert tracker.state == "normal"


def test_fires_on_third_consecutive_breach() -> None:
    tracker = AlertTracker()
    now = _now()
    for i in range(3):
        fired = _eval_breach(
            tracker,
            breached=True,
            consecutive_required=3,
            cooldown_min=30,
            now=now,
            fire_message="hot",
            recover_message="ok",
            kind="temp",
            new_value="80",
        )
        if i < 2:
            assert fired == []
        else:
            assert len(fired) == 1
            assert fired[0].kind == "temp"
            assert fired[0].severity == "warning"
            assert "hot" in fired[0].message
    assert tracker.state == "alerted"


def test_recovery_fires_on_back_edge() -> None:
    tracker = AlertTracker(state="alerted", consecutive_breaches=3)
    now = _now()
    fired = _eval_breach(
        tracker,
        breached=False,
        consecutive_required=3,
        cooldown_min=30,
        now=now,
        fire_message="hot",
        recover_message="ok now",
        kind="temp",
        new_value="60",
    )
    assert len(fired) == 1
    assert fired[0].kind == "temp_recovered"
    assert fired[0].severity == "info"
    assert tracker.state == "normal"


def test_no_recovery_when_was_normal() -> None:
    tracker = AlertTracker()  # never alerted
    fired = _eval_breach(
        tracker,
        breached=False,
        consecutive_required=3,
        cooldown_min=30,
        now=_now(),
        fire_message="hot",
        recover_message="ok",
        kind="temp",
        new_value="50",
    )
    assert fired == []
    assert tracker.state == "normal"


def test_breach_counter_resets_on_recovery() -> None:
    tracker = AlertTracker()
    now = _now()
    # Two breaches accumulated
    for _ in range(2):
        _eval_breach(
            tracker,
            breached=True,
            consecutive_required=3,
            cooldown_min=30,
            now=now,
            fire_message="hot",
            recover_message="ok",
            kind="temp",
            new_value="80",
        )
    assert tracker.consecutive_breaches == 2
    # One non-breach resets the counter
    _eval_breach(
        tracker,
        breached=False,
        consecutive_required=3,
        cooldown_min=30,
        now=now,
        fire_message="hot",
        recover_message="ok",
        kind="temp",
        new_value="60",
    )
    assert tracker.consecutive_breaches == 0


def test_does_not_double_fire_within_alerted_state() -> None:
    tracker = AlertTracker()
    now = _now()
    # Cross threshold and fire once
    for _ in range(3):
        _eval_breach(
            tracker,
            breached=True,
            consecutive_required=3,
            cooldown_min=30,
            now=now,
            fire_message="hot",
            recover_message="ok",
            kind="temp",
            new_value="80",
        )
    assert tracker.state == "alerted"
    # Sustained breach should NOT re-fire
    fired = _eval_breach(
        tracker,
        breached=True,
        consecutive_required=3,
        cooldown_min=30,
        now=now,
        fire_message="hot",
        recover_message="ok",
        kind="temp",
        new_value="82",
    )
    assert fired == []
