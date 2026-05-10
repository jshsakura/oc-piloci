from __future__ import annotations

"""Device health monitor → Telegram alerts.

Periodically checks the four signals that matter on a Pi 5 running piLoci:

  * sustained CPU temperature
  * sustained host load average
  * distillation backlog stuck (pending > 0 but nothing distilled in a while)
  * swap pressure (zram + nvme)

Each check is wrapped in an :class:`AlertTracker` so we don't spam the user
on transient spikes — a high reading must persist across several consecutive
polls before firing, and a fired alert won't re-fire until either it
recovers (NORMAL → ALERTED → NORMAL transition) or the cooldown window
elapses. Recovery messages are sent on the back edge so the user sees
both "system in trouble" and "system back to normal" without ambiguity.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from piloci.config import Settings
from piloci.curator.scheduler import read_cpu_temp_celsius, read_load_average_1min
from piloci.db.models import RawSession
from piloci.db.session import async_session
from piloci.notify.telegram import send_admin_notification

logger = logging.getLogger(__name__)


_MEMINFO_PATH = Path("/proc/meminfo")


# ---------------------------------------------------------------------------
# Alert state tracking
# ---------------------------------------------------------------------------


@dataclass
class AlertTracker:
    """Per-alert-kind state: dedupe + debounce + cooldown."""

    state: str = "normal"  # 'normal' | 'alerted'
    consecutive_breaches: int = 0
    last_fired_at: datetime | None = None
    last_value: str | None = None


_trackers: dict[str, AlertTracker] = {}


def _tracker(kind: str) -> AlertTracker:
    if kind not in _trackers:
        _trackers[kind] = AlertTracker()
    return _trackers[kind]


def reset_trackers() -> None:
    """Test hook — drop all in-memory alert state."""
    _trackers.clear()


# ---------------------------------------------------------------------------
# Probe helpers (pure I/O reads, no networking)
# ---------------------------------------------------------------------------


def _read_swap_used_ratio() -> float | None:
    """Return SwapUsed / SwapTotal in [0, 1], or None if /proc/meminfo absent.

    Returns 0.0 when no swap is configured (SwapTotal = 0) — that's "not
    under swap pressure" rather than an error condition.
    """
    try:
        text = _MEMINFO_PATH.read_text()
    except OSError:
        return None
    total = used = -1
    for line in text.splitlines():
        if line.startswith("SwapTotal:"):
            total = int(line.split()[1])
        elif line.startswith("SwapFree:"):
            free = int(line.split()[1])
            if total >= 0:
                used = total - free
    if total <= 0:
        return 0.0
    if used < 0:
        return None
    return used / total


# ---------------------------------------------------------------------------
# Per-check evaluators
# ---------------------------------------------------------------------------


@dataclass
class FiredAlert:
    kind: str
    severity: str  # 'warning' | 'info'
    message: str


def _eval_breach(
    tracker: AlertTracker,
    *,
    breached: bool,
    consecutive_required: int,
    cooldown_min: int,
    now: datetime,
    fire_message: str,
    recover_message: str,
    kind: str,
    new_value: str,
) -> list[FiredAlert]:
    """Common breach state machine. Returns 0 or 1 firing decisions.

    On every NORMAL→ALERTED transition we emit a 'warning'. On every
    ALERTED→NORMAL transition we emit an 'info' recovery. Cooldown only
    affects re-firing within the same ALERTED state, which currently can't
    happen with this state machine but the field stays for future
    extensions like rate-limited periodic reminders.
    """
    out: list[FiredAlert] = []
    if breached:
        tracker.consecutive_breaches += 1
        if tracker.state == "normal" and tracker.consecutive_breaches >= consecutive_required:
            cooldown_ok = tracker.last_fired_at is None or (
                now - tracker.last_fired_at
            ) >= timedelta(minutes=cooldown_min)
            if cooldown_ok:
                tracker.state = "alerted"
                tracker.last_fired_at = now
                tracker.last_value = new_value
                out.append(FiredAlert(kind=kind, severity="warning", message=fire_message))
    else:
        tracker.consecutive_breaches = 0
        if tracker.state == "alerted":
            tracker.state = "normal"
            tracker.last_value = new_value
            out.append(
                FiredAlert(kind=f"{kind}_recovered", severity="info", message=recover_message)
            )
    return out


async def _eval_temp(settings: Settings, now: datetime) -> list[FiredAlert]:
    temp = read_cpu_temp_celsius()
    if temp is None:
        return []
    threshold = settings.health_temp_alert_c
    return _eval_breach(
        _tracker("temp"),
        breached=temp >= threshold,
        consecutive_required=settings.health_alert_consecutive,
        cooldown_min=settings.health_alert_cooldown_min,
        now=now,
        fire_message=(
            f"🌡 SoC {temp:.1f}°C — 임계 {threshold:.0f}°C "
            f"{settings.health_alert_consecutive}회 연속 초과"
        ),
        recover_message=f"✅ SoC {temp:.1f}°C 정상 복귀",
        kind="temp",
        new_value=f"{temp:.1f}°C",
    )


async def _eval_load(settings: Settings, now: datetime) -> list[FiredAlert]:
    load = read_load_average_1min()
    if load is None:
        return []
    threshold = settings.health_load_alert_1m
    return _eval_breach(
        _tracker("load"),
        breached=load >= threshold,
        consecutive_required=settings.health_alert_consecutive,
        cooldown_min=settings.health_alert_cooldown_min,
        now=now,
        fire_message=f"⚙️ load1 {load:.2f} — 임계 {threshold:.1f} 지속 초과",
        recover_message=f"✅ load1 {load:.2f} 정상 복귀",
        kind="load",
        new_value=f"{load:.2f}",
    )


async def _eval_swap(settings: Settings, now: datetime) -> list[FiredAlert]:
    ratio = _read_swap_used_ratio()
    if ratio is None:
        return []
    threshold = settings.health_swap_alert_pct
    return _eval_breach(
        _tracker("swap"),
        breached=ratio >= threshold,
        consecutive_required=settings.health_alert_consecutive,
        cooldown_min=settings.health_alert_cooldown_min,
        now=now,
        fire_message=f"💾 swap {ratio*100:.0f}% 사용 — 임계 {threshold*100:.0f}% 지속 초과",
        recover_message=f"✅ swap {ratio*100:.0f}% 회복",
        kind="swap",
        new_value=f"{ratio*100:.0f}%",
    )


async def _eval_backlog_stuck(settings: Settings, now: datetime) -> list[FiredAlert]:
    """Fire when pending rows exist AND no distillation has happened in a while.

    Uses MAX(processed_at) over distilled rows as the freshness anchor. If
    nothing has ever been distilled but pending rows exist, the oldest
    pending creation time stands in — covers fresh installs that haven't
    yet drained anything.
    """
    threshold_min = settings.health_backlog_stuck_min
    async with async_session() as db:
        pending = (
            await db.execute(
                select(func.count())
                .select_from(RawSession)
                .where(RawSession.distillation_state == "pending")
            )
        ).scalar() or 0
        if pending <= 0:
            return _eval_breach(
                _tracker("backlog"),
                breached=False,
                consecutive_required=settings.health_alert_consecutive,
                cooldown_min=settings.health_alert_cooldown_min,
                now=now,
                fire_message="",
                recover_message=f"✅ 백로그 비움 ({pending} pending)",
                kind="backlog",
                new_value=f"pending={pending}",
            )

        last_processed = (
            await db.execute(
                select(func.max(RawSession.processed_at)).where(
                    RawSession.distillation_state == "distilled"
                )
            )
        ).scalar()
        oldest_pending = (
            await db.execute(
                select(func.min(RawSession.created_at)).where(
                    RawSession.distillation_state == "pending"
                )
            )
        ).scalar()

    anchor = last_processed or oldest_pending
    if anchor is None:
        return []
    anchor_aware = anchor if anchor.tzinfo else anchor.replace(tzinfo=timezone.utc)
    age = now - anchor_aware
    breached = age >= timedelta(minutes=threshold_min)
    return _eval_breach(
        _tracker("backlog"),
        breached=breached,
        consecutive_required=settings.health_alert_consecutive,
        cooldown_min=settings.health_alert_cooldown_min,
        now=now,
        fire_message=(
            f"📦 백로그 정체 — pending {pending}개, "
            f"마지막 진행 {age.total_seconds() // 60:.0f}분 전"
        ),
        recover_message=f"✅ 백로그 진행 재개 (pending {pending})",
        kind="backlog",
        new_value=f"pending={pending}, age={age.total_seconds():.0f}s",
    )


# ---------------------------------------------------------------------------
# Periodic heartbeat — orthogonal to threshold alerts
# ---------------------------------------------------------------------------


@dataclass
class _HeartbeatState:
    """Module-level memory for the periodic-report cadence.

    ``last_sent_at`` gates the next send; ``last_distilled_count`` lets us
    report a delta ("+5 since last report") rather than a noisy total.
    """

    last_sent_at: datetime | None = None
    last_distilled_count: int | None = None


_heartbeat = _HeartbeatState()


def reset_heartbeat() -> None:
    """Test hook — clears heartbeat memory so the next call sends immediately."""
    _heartbeat.last_sent_at = None
    _heartbeat.last_distilled_count = None


async def _build_heartbeat_message(settings: Settings, now: datetime) -> str:
    """Compose a one-shot status snapshot.

    Pulls counts from the DB and live readings from /proc, /sys. Format is
    intentionally short (≤ ~6 lines) so a Telegram thread doesn't drown in
    pretty-printed JSON. Delta from the previous heartbeat is the headline
    number — that's what tells the user "the device is making progress".
    """
    cpu_temp = read_cpu_temp_celsius()
    load_1m = read_load_average_1min()
    swap_ratio = _read_swap_used_ratio()

    async with async_session() as db:
        rows = (
            await db.execute(
                select(RawSession.distillation_state, func.count().label("n")).group_by(
                    RawSession.distillation_state
                )
            )
        ).all()
        last_processed_at = (
            await db.execute(
                select(func.max(RawSession.processed_at)).where(
                    RawSession.distillation_state == "distilled"
                )
            )
        ).scalar()

    counts = {row.distillation_state: int(row.n) for row in rows}
    distilled = counts.get("distilled", 0)
    pending = counts.get("pending", 0)
    failed = counts.get("failed", 0)

    if _heartbeat.last_distilled_count is None:
        delta_str = f"+{distilled} (since startup)"
    else:
        delta = distilled - _heartbeat.last_distilled_count
        delta_str = f"+{delta}" if delta >= 0 else str(delta)
    _heartbeat.last_distilled_count = distilled

    if last_processed_at is not None:
        anchor = (
            last_processed_at
            if last_processed_at.tzinfo
            else last_processed_at.replace(tzinfo=timezone.utc)
        )
        age_min = (now - anchor).total_seconds() / 60.0
        last_str = f"{age_min:.0f}분 전"
    else:
        last_str = "없음"

    temp_str = f"{cpu_temp:.1f}°C" if cpu_temp is not None else "—"
    load_str = f"{load_1m:.2f}" if load_1m is not None else "—"
    swap_str = f"{swap_ratio*100:.0f}%" if swap_ratio is not None else "—"

    return (
        f"📊 piLoci 상태 ({settings.health_periodic_report_interval_min}분 주기)\n"
        f"🌡 SoC {temp_str}  ⚙️ load {load_str}  💾 swap {swap_str}\n"
        f"📦 증류: {delta_str} (총 {distilled})\n"
        f"⏳ 대기 {pending}건"
        + (f"  ⚠️ 실패 {failed}" if failed > 0 else "")
        + f"\n🕒 마지막 처리: {last_str}"
    )


async def _maybe_send_heartbeat(settings: Settings, now: datetime) -> None:
    """Send a periodic report if the configured interval has elapsed.

    First call after startup always sends — that's the "I'm alive" ping
    the user expects on container restart.
    """
    if not settings.health_periodic_report_enabled:
        return
    interval_min = settings.health_periodic_report_interval_min
    if interval_min <= 0:
        return
    if _heartbeat.last_sent_at is not None:
        if (now - _heartbeat.last_sent_at) < timedelta(minutes=interval_min):
            return

    try:
        text = await _build_heartbeat_message(settings, now)
        sent = await send_admin_notification(text, settings)
        if sent:
            _heartbeat.last_sent_at = now
    except Exception:
        logger.exception("heartbeat: build/send failed")


# ---------------------------------------------------------------------------
# Worker entry point
# ---------------------------------------------------------------------------


async def run_health_monitor(settings: Settings, stop_event: object) -> None:
    """Long-running task: poll every ``health_check_interval_sec``, send alerts.

    No-ops when the user hasn't enabled the feature or hasn't configured
    Telegram. The worker still runs cheaply (one syscall + small SQL) so
    it can be flipped on at runtime without a restart.
    """
    import asyncio

    if not isinstance(stop_event, asyncio.Event):
        raise TypeError("run_health_monitor expects an asyncio.Event")

    logger.info("health monitor started (enabled=%s)", settings.health_monitor_enabled)
    while not stop_event.is_set():
        if settings.health_monitor_enabled and settings.telegram_bot_token:
            try:
                now = datetime.now(timezone.utc)
                fired: list[FiredAlert] = []
                for evaluator in (_eval_temp, _eval_load, _eval_swap, _eval_backlog_stuck):
                    try:
                        fired.extend(await evaluator(settings, now))
                    except Exception:
                        logger.exception("health monitor: %s failed", evaluator.__name__)
                for alert in fired:
                    icon = "⚠️" if alert.severity == "warning" else "ℹ️"
                    text = f"{icon} piLoci\n{alert.message}"
                    try:
                        await send_admin_notification(text, settings)
                    except Exception:
                        logger.exception("health monitor: telegram send failed (%s)", alert.kind)
                # Heartbeat is independent of breach detection — fires on its
                # own cadence so the user gets steady progress reports during
                # the stabilization window even when nothing is wrong.
                await _maybe_send_heartbeat(settings, now)
            except Exception:
                logger.exception("health monitor: poll iteration failed")

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.health_check_interval_sec,
            )
        except asyncio.TimeoutError:
            pass

    logger.info("health monitor stopped")
