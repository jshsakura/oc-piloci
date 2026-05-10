from __future__ import annotations

"""Distillation scheduler: decides *when* and *how* the worker runs.

The lazy worker doesn't pull from a queue on its own — it asks the scheduler
"should I work right now, and if so, against which provider?" The scheduler
answers based on four signals:

  1. Backlog size       → empty queue means nothing to do; oversized backlog
                          unlocks the overflow path.
  2. Idle window        → user-configured hours (e.g. 02:00–07:00) where the
                          device should aggressively drain the backlog
                          regardless of temperature.
  3. CPU temperature    → outside the idle window we back off when the SoC is
                          already hot, since each Gemma call adds 200%+ CPU
                          for tens of seconds.
  4. CPU load average   → similar guard for non-temperature contention (other
                          containers spiking).

Only the idle-window path ignores temperature. Outside it, when a backlog
threshold is crossed and the user has external LLM keys configured, the
scheduler flips ``use_external=True`` so the worker can drain through a
hosted provider while leaving the Pi cool.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

logger = logging.getLogger(__name__)


THERMAL_ZONE_PATH = Path("/sys/class/thermal/thermal_zone0/temp")
LOADAVG_PATH = Path("/proc/loadavg")


@dataclass(frozen=True)
class IdleWindow:
    """Time-of-day range during which distillation runs unconditionally.

    ``start`` and ``end`` are local-clock times. Wraparound across midnight
    (e.g. 22:00–06:00) is supported and detected when ``end <= start``.
    """

    start: time
    end: time

    def contains(self, now: time) -> bool:
        if self.start <= self.end:
            return self.start <= now < self.end
        # Crosses midnight: window is [start, 24:00) ∪ [00:00, end).
        return now >= self.start or now < self.end


def parse_idle_window(spec: str | None) -> IdleWindow | None:
    """Parse "HH:MM-HH:MM" → IdleWindow. Returns None for missing/invalid input.

    Invalid input degrades gracefully — the scheduler treats absence of an
    idle window as 'always normal hours', so a misconfigured setting can't
    break distillation, only delay it.
    """
    if not spec or not isinstance(spec, str):
        return None
    try:
        start_s, end_s = spec.split("-", 1)
        start_h, start_m = (int(x) for x in start_s.strip().split(":", 1))
        end_h, end_m = (int(x) for x in end_s.strip().split(":", 1))
        return IdleWindow(start=time(start_h, start_m), end=time(end_h, end_m))
    except (ValueError, TypeError):
        logger.warning("invalid idle_window spec: %r — treating as unset", spec)
        return None


def read_cpu_temp_celsius() -> float | None:
    """Read the SoC temperature in °C, or None if /sys/class/thermal is absent.

    Pi 5 exposes thermal_zone0 with millidegree integer (e.g. 64523 → 64.523°C).
    Returning None lets the caller treat the gate as 'open' on platforms where
    the file isn't readable (e.g. inside a sandbox that lacks /sys mount).
    """
    try:
        raw = THERMAL_ZONE_PATH.read_text().strip()
        return int(raw) / 1000.0
    except (OSError, ValueError):
        return None


def read_load_average_1min() -> float | None:
    """Read the 1-minute load average, or None if /proc isn't available."""
    try:
        first_token = LOADAVG_PATH.read_text().split()[0]
        return float(first_token)
    except (OSError, ValueError, IndexError):
        return None


@dataclass
class SchedulerDecision:
    """Outcome of one scheduler poll.

    ``should_run`` is the gate. When False, the worker sleeps until the next
    poll. ``use_external`` matters only when ``should_run`` is True and tells
    the worker to call ``extract_session(..., prefer_external=True)``.

    ``reason`` is logged and surfaced to observability so the user can see
    why the scheduler is currently passing or holding (e.g., "idle window",
    "soc 72°C > ceiling 70°C", "overflow→external").

    ``next_poll_seconds`` is a hint to the worker on how long to sleep before
    asking again — short when actively running, longer when held off.
    """

    should_run: bool
    use_external: bool = False
    reason: str = ""
    pending_count: int = 0
    cpu_temp_c: float | None = None
    load_avg_1m: float | None = None
    next_poll_seconds: float = 60.0


@dataclass
class SchedulerConfig:
    """Subset of Settings the scheduler actually reads.

    Pulled out as a value object so the scheduler is unit-testable without
    a full Settings instance — tests can construct one directly and feed
    fake temp/load readings via the read_* hooks.
    """

    idle_window: IdleWindow | None
    temp_ceiling_celsius: float = 70.0
    load_ceiling_1m: float = 3.0
    overflow_threshold: int = 50
    poll_interval_normal: float = 60.0
    poll_interval_idle: float = 5.0
    poll_interval_held: float = 120.0


def _now_local_time() -> time:
    """Current wall-clock time in the host's local timezone.

    Idle windows are configured in user-local hours, not UTC — most users
    think "do this at 3am" not "do this at 1800Z". Using local time aligns
    with that expectation; daylight savings transitions are accepted as a
    minor wart (one missed/duplicated hour twice a year).
    """
    return datetime.now().time()


def decide(
    config: SchedulerConfig,
    pending_count: int,
    *,
    has_external_provider: bool = False,
    budget_exhausted: bool = False,
    now_time: time | None = None,
    cpu_temp: float | None = None,
    load_1m: float | None = None,
) -> SchedulerDecision:
    """Pure decision function — no I/O, no global state.

    All inputs are explicit so the scheduler is trivially testable. Use
    ``poll()`` for the real-world wrapper that reads /sys and queries the DB.
    """
    if pending_count <= 0:
        return SchedulerDecision(
            should_run=False,
            reason="queue empty",
            pending_count=0,
            cpu_temp_c=cpu_temp,
            load_avg_1m=load_1m,
            next_poll_seconds=config.poll_interval_normal,
        )

    now = now_time if now_time is not None else _now_local_time()

    # Idle window: ignore temperature, drain the backlog locally.
    if config.idle_window is not None and config.idle_window.contains(now):
        return SchedulerDecision(
            should_run=True,
            use_external=False,
            reason="idle window — full local throughput",
            pending_count=pending_count,
            cpu_temp_c=cpu_temp,
            load_avg_1m=load_1m,
            next_poll_seconds=config.poll_interval_idle,
        )

    # Normal hours, overflow path: backlog past threshold + external available
    # + budget left → drain through the hosted provider.
    if (
        pending_count >= config.overflow_threshold
        and has_external_provider
        and not budget_exhausted
    ):
        return SchedulerDecision(
            should_run=True,
            use_external=True,
            reason=(
                f"overflow — backlog {pending_count} ≥ "
                f"{config.overflow_threshold}, routing to external"
            ),
            pending_count=pending_count,
            cpu_temp_c=cpu_temp,
            load_avg_1m=load_1m,
            next_poll_seconds=config.poll_interval_idle,
        )

    # Normal hours, local path: gate on temperature and load.
    if cpu_temp is not None and cpu_temp >= config.temp_ceiling_celsius:
        return SchedulerDecision(
            should_run=False,
            reason=f"soc {cpu_temp:.1f}°C ≥ ceiling {config.temp_ceiling_celsius:.1f}°C",
            pending_count=pending_count,
            cpu_temp_c=cpu_temp,
            load_avg_1m=load_1m,
            next_poll_seconds=config.poll_interval_held,
        )

    if load_1m is not None and load_1m >= config.load_ceiling_1m:
        return SchedulerDecision(
            should_run=False,
            reason=f"load {load_1m:.2f} ≥ ceiling {config.load_ceiling_1m:.2f}",
            pending_count=pending_count,
            cpu_temp_c=cpu_temp,
            load_avg_1m=load_1m,
            next_poll_seconds=config.poll_interval_held,
        )

    return SchedulerDecision(
        should_run=True,
        use_external=False,
        reason="normal hours — local within thresholds",
        pending_count=pending_count,
        cpu_temp_c=cpu_temp,
        load_avg_1m=load_1m,
        next_poll_seconds=config.poll_interval_normal,
    )


async def poll(
    config: SchedulerConfig,
    pending_count: int,
    *,
    has_external_provider: bool = False,
    budget_exhausted: bool = False,
) -> SchedulerDecision:
    """I/O-touching wrapper: reads /sys/class/thermal and /proc/loadavg, then
    delegates to :func:`decide`.

    Kept thin so the worker can call it once per loop iteration without
    pulling in a full scheduler object. The pure ``decide`` is exposed
    separately so unit tests don't need to monkeypatch Path.read_text.
    """
    cpu_temp = read_cpu_temp_celsius()
    load_1m = read_load_average_1min()
    return decide(
        config,
        pending_count,
        has_external_provider=has_external_provider,
        budget_exhausted=budget_exhausted,
        cpu_temp=cpu_temp,
        load_1m=load_1m,
    )
