from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from piloci.config import Settings
from piloci.db.models import Project, RawSession, User
from piloci.db.session import init_db
from piloci.notify import health as health_mod
from piloci.notify.health import (
    AlertTracker,
    FiredAlert,
    _eval_breach,
    _format_consolidated,
    _is_in_active_window,
    _read_swap_used_ratio,
    _tracker,
    prime_heartbeat_baseline,
    reset_heartbeat,
    reset_pending_queue,
    reset_trackers,
    run_health_monitor,
)


def setup_function() -> None:
    reset_trackers()
    reset_pending_queue()
    reset_heartbeat()


def _settings(**overrides) -> Settings:
    base = dict(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
        health_monitor_enabled=True,
        health_alert_consecutive=1,
        health_alert_cooldown_min=0,
        health_temp_alert_c=75.0,
        health_load_alert_1m=4.0,
        health_swap_alert_pct=0.85,
        health_backlog_stuck_min=60,
        health_periodic_report_enabled=False,
        health_periodic_report_interval_min=60,
        health_periodic_report_active_window=None,
        telegram_bot_token="bot-token",
        telegram_chat_id="chat-id",
        health_check_interval_sec=1,
    )
    base.update(overrides)
    return Settings(**base)


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


# ---------------------------------------------------------------------------
# DB fixture — small in-memory sqlite for tests that touch
# _eval_backlog_stuck / _build_heartbeat_message.
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_engine(monkeypatch, tmp_path) -> AsyncGenerator[AsyncEngine, None]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'health.db'}"
    settings = _settings(database_url=database_url)
    monkeypatch.setattr("piloci.db.session.get_settings", lambda: settings)
    monkeypatch.setattr("piloci.db.session._engine", None)
    monkeypatch.setattr("piloci.db.session._session_factory", None)

    eng = create_async_engine(database_url, echo=False, connect_args={"check_same_thread": False})
    await init_db(engine=eng)

    factory = async_sessionmaker(
        bind=eng,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    @asynccontextmanager
    async def _test_async_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    monkeypatch.setattr(health_mod, "async_session", _test_async_session)
    yield eng
    await eng.dispose()


async def _seed_user_project(engine: AsyncEngine) -> tuple[str, str]:
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        user = User(id="u1", email="u1@example.com", created_at=_now())
        project = Project(
            id="p1",
            user_id="u1",
            slug="proj",
            name="proj",
            created_at=_now(),
            updated_at=_now(),
        )
        sess.add_all([user, project])
        await sess.commit()
    return "u1", "p1"


async def _insert_raw(
    engine: AsyncEngine,
    *,
    state: str,
    created_at: datetime,
    processed_at: datetime | None = None,
    ingest_id: str | None = None,
) -> None:
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        sess.add(
            RawSession(
                ingest_id=ingest_id or f"r-{state}-{created_at.timestamp()}",
                user_id="u1",
                project_id="p1",
                client="test",
                transcript_json="{}",
                created_at=created_at,
                processed_at=processed_at,
                distillation_state=state,
            )
        )
        await sess.commit()


# ---------------------------------------------------------------------------
# _tracker / reset_trackers / reset_pending_queue / reset_heartbeat
# ---------------------------------------------------------------------------


def test_tracker_creates_and_reuses() -> None:
    a = _tracker("foo")
    b = _tracker("foo")
    assert a is b
    a.consecutive_breaches = 7
    assert _tracker("foo").consecutive_breaches == 7


def test_reset_trackers_clears_state() -> None:
    t = _tracker("bar")
    t.consecutive_breaches = 5
    reset_trackers()
    assert _tracker("bar").consecutive_breaches == 0


def test_reset_pending_queue_clears() -> None:
    health_mod._pending_queue.append(FiredAlert(kind="x", severity="warning", message="m"))
    reset_pending_queue()
    assert health_mod._pending_queue == []


def test_reset_heartbeat_clears_state() -> None:
    health_mod._heartbeat.last_sent_at = _now()
    health_mod._heartbeat.last_distilled_count = 42
    reset_heartbeat()
    assert health_mod._heartbeat.last_sent_at is None
    assert health_mod._heartbeat.last_distilled_count is None


# ---------------------------------------------------------------------------
# _is_in_active_window
# ---------------------------------------------------------------------------


def test_is_in_active_window_unset_means_always_on() -> None:
    s = _settings(health_periodic_report_active_window=None)
    assert _is_in_active_window(s) is True


def test_is_in_active_window_invalid_spec_means_always_on() -> None:
    s = _settings(health_periodic_report_active_window="not-a-window")
    assert _is_in_active_window(s) is True


def test_is_in_active_window_inside(monkeypatch) -> None:
    class _Dt(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return datetime(2026, 5, 20, 12, 0, 0)

    monkeypatch.setattr(health_mod, "datetime", _Dt)
    s = _settings(health_periodic_report_active_window="09:00-17:00")
    assert _is_in_active_window(s) is True


def test_is_in_active_window_outside(monkeypatch) -> None:
    class _Dt(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return datetime(2026, 5, 20, 23, 30, 0)

    monkeypatch.setattr(health_mod, "datetime", _Dt)
    s = _settings(health_periodic_report_active_window="09:00-17:00")
    assert _is_in_active_window(s) is False


# ---------------------------------------------------------------------------
# _format_consolidated
# ---------------------------------------------------------------------------


def test_format_consolidated_single_alert() -> None:
    queue = [FiredAlert(kind="temp", severity="warning", message="hot!")]
    out = _format_consolidated(queue)
    assert "야간 누적 알림 1건" in out
    assert "• hot!" in out
    assert "×" not in out


def test_format_consolidated_collapses_repeats() -> None:
    queue = [
        FiredAlert(kind="temp", severity="warning", message="hot-1"),
        FiredAlert(kind="temp", severity="warning", message="hot-2"),
        FiredAlert(kind="load", severity="warning", message="loady"),
        FiredAlert(kind="temp", severity="warning", message="hot-3"),
    ]
    out = _format_consolidated(queue)
    assert "야간 누적 알림 4건" in out
    assert "[temp ×3] hot-3" in out
    assert "• loady" in out


def test_format_consolidated_preserves_order() -> None:
    queue = [
        FiredAlert(kind="b", severity="warning", message="bbb"),
        FiredAlert(kind="a", severity="warning", message="aaa"),
    ]
    lines = _format_consolidated(queue).splitlines()
    assert lines[0].startswith("🌙")
    assert "bbb" in lines[1]
    assert "aaa" in lines[2]


# ---------------------------------------------------------------------------
# _read_swap_used_ratio
# ---------------------------------------------------------------------------


def test_swap_ratio_missing_meminfo(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(health_mod, "_MEMINFO_PATH", tmp_path / "nope")
    assert _read_swap_used_ratio() is None


def test_swap_ratio_zero_swap(monkeypatch, tmp_path) -> None:
    p = tmp_path / "meminfo"
    p.write_text("MemTotal: 1000 kB\nSwapTotal:        0 kB\nSwapFree:        0 kB\n")
    monkeypatch.setattr(health_mod, "_MEMINFO_PATH", p)
    assert _read_swap_used_ratio() == 0.0


def test_swap_ratio_partial_use(monkeypatch, tmp_path) -> None:
    p = tmp_path / "meminfo"
    p.write_text("SwapTotal:     1000 kB\nSwapFree:       250 kB\n")
    monkeypatch.setattr(health_mod, "_MEMINFO_PATH", p)
    ratio = _read_swap_used_ratio()
    assert ratio is not None
    assert abs(ratio - 0.75) < 1e-6


def test_swap_ratio_missing_swapfree(monkeypatch, tmp_path) -> None:
    p = tmp_path / "meminfo"
    p.write_text("SwapTotal:     1000 kB\n")
    monkeypatch.setattr(health_mod, "_MEMINFO_PATH", p)
    assert _read_swap_used_ratio() is None


# ---------------------------------------------------------------------------
# _eval_temp / _eval_load / _eval_swap — guard branches
# ---------------------------------------------------------------------------


async def test_eval_temp_no_reading(monkeypatch) -> None:
    monkeypatch.setattr(health_mod, "read_cpu_temp_celsius", lambda: None)
    out = await health_mod._eval_temp(_settings(), _now())
    assert out == []


async def test_eval_temp_fires_when_over_threshold(monkeypatch) -> None:
    monkeypatch.setattr(health_mod, "read_cpu_temp_celsius", lambda: 88.5)
    out = await health_mod._eval_temp(
        _settings(health_temp_alert_c=75.0, health_alert_consecutive=1),
        _now(),
    )
    assert len(out) == 1
    assert out[0].kind == "temp"
    assert "88.5" in out[0].message
    assert "75" in out[0].message


async def test_eval_load_no_reading(monkeypatch) -> None:
    monkeypatch.setattr(health_mod, "read_load_average_1min", lambda: None)
    out = await health_mod._eval_load(_settings(), _now())
    assert out == []


async def test_eval_load_fires(monkeypatch) -> None:
    monkeypatch.setattr(health_mod, "read_load_average_1min", lambda: 6.5)
    out = await health_mod._eval_load(
        _settings(health_load_alert_1m=4.0, health_alert_consecutive=1),
        _now(),
    )
    assert len(out) == 1
    assert out[0].kind == "load"
    assert "6.50" in out[0].message


async def test_eval_swap_no_reading(monkeypatch) -> None:
    monkeypatch.setattr(health_mod, "_read_swap_used_ratio", lambda: None)
    out = await health_mod._eval_swap(_settings(), _now())
    assert out == []


async def test_eval_swap_fires(monkeypatch) -> None:
    monkeypatch.setattr(health_mod, "_read_swap_used_ratio", lambda: 0.92)
    out = await health_mod._eval_swap(
        _settings(health_swap_alert_pct=0.85, health_alert_consecutive=1),
        _now(),
    )
    assert len(out) == 1
    assert out[0].kind == "swap"
    assert "92%" in out[0].message


# ---------------------------------------------------------------------------
# _eval_backlog_stuck
# ---------------------------------------------------------------------------


async def test_backlog_no_pending_no_alert(db_engine: AsyncEngine) -> None:
    await _seed_user_project(db_engine)
    out = await health_mod._eval_backlog_stuck(_settings(), _now())
    assert out == []


async def test_backlog_recovers_after_alerted(db_engine: AsyncEngine) -> None:
    await _seed_user_project(db_engine)
    t = _tracker("backlog")
    t.state = "alerted"
    out = await health_mod._eval_backlog_stuck(_settings(), _now())
    assert len(out) == 1
    assert out[0].kind == "backlog_recovered"
    assert out[0].severity == "info"


async def test_backlog_stuck_fires_when_pending_and_old(db_engine: AsyncEngine) -> None:
    await _seed_user_project(db_engine)
    now = _now()
    await _insert_raw(
        db_engine,
        state="pending",
        created_at=now - timedelta(hours=2),
        ingest_id="r-old-pending",
    )
    out = await health_mod._eval_backlog_stuck(
        _settings(health_backlog_stuck_min=60, health_alert_consecutive=1),
        now,
    )
    assert len(out) == 1
    assert out[0].kind == "backlog"
    assert "백로그" in out[0].message


async def test_backlog_not_stuck_when_recently_processed(db_engine: AsyncEngine) -> None:
    await _seed_user_project(db_engine)
    now = _now()
    await _insert_raw(
        db_engine,
        state="pending",
        created_at=now - timedelta(hours=5),
        ingest_id="r-pending-1",
    )
    await _insert_raw(
        db_engine,
        state="distilled",
        created_at=now - timedelta(minutes=10),
        processed_at=now - timedelta(minutes=5),
        ingest_id="r-distilled-1",
    )
    out = await health_mod._eval_backlog_stuck(
        _settings(health_backlog_stuck_min=60, health_alert_consecutive=1),
        now,
    )
    assert out == []


# ---------------------------------------------------------------------------
# _build_heartbeat_message
# ---------------------------------------------------------------------------


async def test_build_heartbeat_message_first_call(db_engine: AsyncEngine, monkeypatch) -> None:
    await _seed_user_project(db_engine)
    now = _now()
    await _insert_raw(
        db_engine,
        state="pending",
        created_at=now - timedelta(minutes=3),
        ingest_id="hb-p",
    )
    await _insert_raw(
        db_engine,
        state="distilled",
        created_at=now - timedelta(minutes=10),
        processed_at=now - timedelta(minutes=4),
        ingest_id="hb-d",
    )
    await _insert_raw(
        db_engine,
        state="failed",
        created_at=now - timedelta(minutes=8),
        ingest_id="hb-f",
    )
    monkeypatch.setattr(health_mod, "read_cpu_temp_celsius", lambda: 64.0)
    monkeypatch.setattr(health_mod, "read_load_average_1min", lambda: 1.25)
    monkeypatch.setattr(health_mod, "_read_swap_used_ratio", lambda: 0.10)

    out = await health_mod._build_heartbeat_message(_settings(), now)
    assert "piLoci 상태" in out
    assert "64.0°C" in out
    assert "1.25" in out
    assert "10%" in out
    assert "since startup" in out
    assert "실패 1" in out


async def test_build_heartbeat_message_delta_and_missing_probes(
    db_engine: AsyncEngine, monkeypatch
) -> None:
    await _seed_user_project(db_engine)
    now = _now()
    health_mod._heartbeat.last_distilled_count = 2
    await _insert_raw(
        db_engine,
        state="distilled",
        created_at=now - timedelta(minutes=20),
        processed_at=now - timedelta(minutes=10),
        ingest_id="hb-d1",
    )
    await _insert_raw(
        db_engine,
        state="distilled",
        created_at=now - timedelta(minutes=15),
        processed_at=now - timedelta(minutes=7),
        ingest_id="hb-d2",
    )
    await _insert_raw(
        db_engine,
        state="distilled",
        created_at=now - timedelta(minutes=12),
        processed_at=now - timedelta(minutes=5),
        ingest_id="hb-d3",
    )
    monkeypatch.setattr(health_mod, "read_cpu_temp_celsius", lambda: None)
    monkeypatch.setattr(health_mod, "read_load_average_1min", lambda: None)
    monkeypatch.setattr(health_mod, "_read_swap_used_ratio", lambda: None)

    out = await health_mod._build_heartbeat_message(_settings(), now)
    assert "+1" in out
    assert "실패" not in out
    assert "—" in out


async def test_build_heartbeat_message_no_distilled_yet(
    db_engine: AsyncEngine, monkeypatch
) -> None:
    await _seed_user_project(db_engine)
    monkeypatch.setattr(health_mod, "read_cpu_temp_celsius", lambda: 60.0)
    monkeypatch.setattr(health_mod, "read_load_average_1min", lambda: 0.5)
    monkeypatch.setattr(health_mod, "_read_swap_used_ratio", lambda: 0.0)
    out = await health_mod._build_heartbeat_message(_settings(), _now())
    assert "없음" in out


# ---------------------------------------------------------------------------
# _maybe_send_heartbeat
# ---------------------------------------------------------------------------


async def test_heartbeat_disabled_short_circuit(monkeypatch) -> None:
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(health_mod, "send_admin_notification", sent)
    monkeypatch.setattr(health_mod, "_build_heartbeat_message", AsyncMock(return_value="x"))
    await health_mod._maybe_send_heartbeat(_settings(health_periodic_report_enabled=False), _now())
    sent.assert_not_called()


async def test_heartbeat_interval_zero_short_circuit(monkeypatch) -> None:
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(health_mod, "send_admin_notification", sent)
    monkeypatch.setattr(health_mod, "_build_heartbeat_message", AsyncMock(return_value="x"))
    await health_mod._maybe_send_heartbeat(
        _settings(
            health_periodic_report_enabled=True,
            health_periodic_report_interval_min=0,
        ),
        _now(),
    )
    sent.assert_not_called()


async def test_heartbeat_outside_window_suppressed(monkeypatch) -> None:
    class _Dt(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is not None:
                return datetime(2026, 5, 20, 23, 30, 0, tzinfo=tz)
            return datetime(2026, 5, 20, 23, 30, 0)

    monkeypatch.setattr(health_mod, "datetime", _Dt)
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(health_mod, "send_admin_notification", sent)
    monkeypatch.setattr(health_mod, "_build_heartbeat_message", AsyncMock(return_value="x"))
    await health_mod._maybe_send_heartbeat(
        _settings(
            health_periodic_report_enabled=True,
            health_periodic_report_active_window="09:00-17:00",
        ),
        _now(),
    )
    sent.assert_not_called()
    assert health_mod._heartbeat.last_sent_at is None


async def test_heartbeat_interval_not_elapsed(monkeypatch) -> None:
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(health_mod, "send_admin_notification", sent)
    monkeypatch.setattr(health_mod, "_build_heartbeat_message", AsyncMock(return_value="x"))
    now = _now()
    health_mod._heartbeat.last_sent_at = now - timedelta(minutes=5)
    await health_mod._maybe_send_heartbeat(
        _settings(
            health_periodic_report_enabled=True,
            health_periodic_report_interval_min=60,
        ),
        now,
    )
    sent.assert_not_called()


async def test_heartbeat_sends_and_updates_last_sent(monkeypatch) -> None:
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(health_mod, "send_admin_notification", sent)
    monkeypatch.setattr(health_mod, "_build_heartbeat_message", AsyncMock(return_value="hb-text"))
    now = _now()
    await health_mod._maybe_send_heartbeat(
        _settings(
            health_periodic_report_enabled=True,
            health_periodic_report_interval_min=60,
            health_periodic_report_active_window=None,
        ),
        now,
    )
    sent.assert_awaited_once()
    assert sent.await_args.args[0] == "hb-text"
    assert health_mod._heartbeat.last_sent_at == now


def test_prime_heartbeat_baseline_seeds_when_unset() -> None:
    assert health_mod._heartbeat.last_sent_at is None
    now = _now()
    prime_heartbeat_baseline(now)
    assert health_mod._heartbeat.last_sent_at == now


def test_prime_heartbeat_baseline_does_not_overwrite_warm_cadence() -> None:
    earlier = _now() - timedelta(hours=3)
    health_mod._heartbeat.last_sent_at = earlier
    prime_heartbeat_baseline(_now())
    assert health_mod._heartbeat.last_sent_at == earlier


async def test_heartbeat_suppressed_immediately_after_startup_prime(monkeypatch) -> None:
    """Regression: a (re)start must not emit a periodic report. Priming the
    baseline at startup makes the first poll wait a full interval, so a burst
    of restarts no longer produces one ping each."""
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(health_mod, "send_admin_notification", sent)
    monkeypatch.setattr(health_mod, "_build_heartbeat_message", AsyncMock(return_value="x"))
    now = _now()
    prime_heartbeat_baseline(now)
    await health_mod._maybe_send_heartbeat(
        _settings(
            health_periodic_report_enabled=True,
            health_periodic_report_interval_min=180,
            health_periodic_report_active_window=None,
        ),
        now,
    )
    sent.assert_not_called()


async def test_heartbeat_failure_is_swallowed(monkeypatch) -> None:
    monkeypatch.setattr(
        health_mod,
        "_build_heartbeat_message",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    monkeypatch.setattr(health_mod, "send_admin_notification", AsyncMock(return_value=True))
    await health_mod._maybe_send_heartbeat(
        _settings(
            health_periodic_report_enabled=True,
            health_periodic_report_interval_min=60,
            health_periodic_report_active_window=None,
        ),
        _now(),
    )
    assert health_mod._heartbeat.last_sent_at is None


# ---------------------------------------------------------------------------
# run_health_monitor
# ---------------------------------------------------------------------------


async def test_run_health_monitor_rejects_non_event() -> None:
    with pytest.raises(TypeError):
        await run_health_monitor(_settings(), object())


async def test_run_health_monitor_stops_immediately_when_disabled(monkeypatch) -> None:
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(health_mod, "send_admin_notification", sent)
    stop = asyncio.Event()
    stop.set()
    await run_health_monitor(_settings(health_monitor_enabled=False, telegram_bot_token=None), stop)
    sent.assert_not_called()


async def test_run_health_monitor_sends_alert_in_window(
    db_engine: AsyncEngine, monkeypatch
) -> None:
    await _seed_user_project(db_engine)
    monkeypatch.setattr(health_mod, "read_cpu_temp_celsius", lambda: 99.0)
    monkeypatch.setattr(health_mod, "read_load_average_1min", lambda: 0.1)
    monkeypatch.setattr(health_mod, "_read_swap_used_ratio", lambda: 0.0)
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(health_mod, "send_admin_notification", sent)

    stop = asyncio.Event()

    async def _run() -> None:
        await run_health_monitor(
            _settings(
                health_alert_consecutive=1,
                health_check_interval_sec=60,
                health_periodic_report_active_window=None,
                health_periodic_report_enabled=False,
            ),
            stop,
        )

    task = asyncio.create_task(_run())
    for _ in range(10):
        await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert sent.await_count >= 1
    sent_text = sent.await_args_list[0].args[0]
    assert "piLoci" in sent_text


async def test_run_health_monitor_queues_outside_window_then_flushes(
    db_engine: AsyncEngine, monkeypatch
) -> None:
    await _seed_user_project(db_engine)
    monkeypatch.setattr(health_mod, "read_cpu_temp_celsius", lambda: 99.0)
    monkeypatch.setattr(health_mod, "read_load_average_1min", lambda: 0.1)
    monkeypatch.setattr(health_mod, "_read_swap_used_ratio", lambda: 0.0)
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(health_mod, "send_admin_notification", sent)

    # Phase 1: window closed → alert is queued, no send.
    monkeypatch.setattr(health_mod, "_is_in_active_window", lambda s: False)
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_health_monitor(
            _settings(
                health_alert_consecutive=1,
                health_check_interval_sec=60,
                health_periodic_report_enabled=False,
            ),
            stop,
        )
    )
    for _ in range(10):
        await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert sent.await_count == 0
    assert len(health_mod._pending_queue) >= 1

    # Phase 2: window reopens → next iteration flushes the queue.
    monkeypatch.setattr(health_mod, "_is_in_active_window", lambda s: True)
    monkeypatch.setattr(health_mod, "read_cpu_temp_celsius", lambda: 30.0)
    sent.reset_mock()
    stop2 = asyncio.Event()
    task2 = asyncio.create_task(
        run_health_monitor(
            _settings(
                health_alert_consecutive=1,
                health_check_interval_sec=60,
                health_periodic_report_enabled=False,
            ),
            stop2,
        )
    )
    for _ in range(10):
        await asyncio.sleep(0)
    stop2.set()
    await asyncio.wait_for(task2, timeout=2.0)

    assert sent.await_count >= 1
    assert health_mod._pending_queue == []
    flush_text = sent.await_args_list[0].args[0]
    assert "야간 누적 알림" in flush_text


async def test_run_health_monitor_swallows_evaluator_exception(monkeypatch) -> None:
    async def _boom(settings, now):
        raise RuntimeError("eval failed")

    monkeypatch.setattr(health_mod, "_eval_temp", _boom)
    monkeypatch.setattr(health_mod, "_eval_load", AsyncMock(return_value=[]))
    monkeypatch.setattr(health_mod, "_eval_swap", AsyncMock(return_value=[]))
    monkeypatch.setattr(health_mod, "_eval_backlog_stuck", AsyncMock(return_value=[]))
    monkeypatch.setattr(health_mod, "_maybe_send_heartbeat", AsyncMock())
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(health_mod, "send_admin_notification", sent)

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_health_monitor(
            _settings(health_alert_consecutive=1, health_periodic_report_enabled=False),
            stop,
        )
    )
    for _ in range(10):
        await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    sent.assert_not_called()
