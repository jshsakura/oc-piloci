from __future__ import annotations

"""HTTP surface for the lazy distillation pipeline.

Four endpoints, each scoped to the authenticated user:

  GET  /api/distillation/status            — overall pipeline state
  GET  /api/projects/{id}/freshness        — per-project freshness/lag
  POST /api/distillation/run-now           — request an immediate worker tick
  GET  /api/budget/usage                   — external LLM monthly spend

The status endpoints surface the four observability dimensions the user
needs to trust the lazy model (count, lag, classification, freshness)
plus the local/external split when overflow has been routed.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from piloci.config import get_settings
from piloci.curator import distillation_worker as _worker_mod
from piloci.curator.budget import month_total_usd, remaining_budget_usd
from piloci.curator.scheduler import (
    parse_idle_window,
    read_cpu_temp_celsius,
    read_load_average_1min,
)
from piloci.db.models import ExternalLLMUsage, RawSession
from piloci.db.session import async_session


def _json(payload: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status)


def _require_user(request: Request) -> dict[str, Any] | None:
    user = getattr(request.state, "user", None)
    if user is None:
        return None
    return user


def _uid(user: dict[str, Any]) -> str:
    raw = user.get("user_id") or user.get("id")
    return str(raw) if raw else ""


def _next_idle_window(now: datetime, spec: str | None) -> datetime | None:
    """Return the next datetime the idle window will start, or None when unset.

    Used by the status endpoint so the UI can show "next aggressive run at HH:MM".
    Naive about timezones — uses local clock for parsing, matches scheduler.
    """
    if not spec:
        return None
    window = parse_idle_window(spec)
    if window is None:
        return None
    today = now.date()
    candidate = datetime.combine(today, window.start)
    if candidate <= now.replace(tzinfo=None):
        candidate = datetime.combine(today.replace(day=today.day), window.start)
        # If today's start time has already passed, push to tomorrow.
        from datetime import timedelta

        candidate = candidate + timedelta(days=1)
    return candidate


# ---------------------------------------------------------------------------
# GET /api/distillation/status
# ---------------------------------------------------------------------------


async def route_distillation_status(request: Request) -> Response:
    """Aggregate distillation pipeline state for the authenticated user.

    Returns counts in each state, current backlog lag (oldest pending age),
    last successful distillation timestamp, processing-path split for the
    last 30 days, and the next idle-window activation. The frontend renders
    this on the dashboard so the user can answer "is my data being processed?"
    without grepping logs.
    """
    user = _require_user(request)
    if user is None:
        return _json({"error": "unauthorized"}, 401)
    user_id = _uid(user)

    settings = get_settings()
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        # State counts in one round-trip.
        rows = (
            await db.execute(
                select(
                    RawSession.distillation_state,
                    func.count().label("n"),
                )
                .where(RawSession.user_id == user_id)
                .group_by(RawSession.distillation_state)
            )
        ).all()
        by_state = {r.distillation_state: int(r.n) for r in rows}

        # Oldest pending — how far behind we are.
        oldest_pending = (
            await db.execute(
                select(func.min(RawSession.created_at))
                .where(RawSession.user_id == user_id)
                .where(RawSession.distillation_state == "pending")
            )
        ).scalar()

        last_distilled = (
            await db.execute(
                select(func.max(RawSession.processed_at))
                .where(RawSession.user_id == user_id)
                .where(RawSession.distillation_state == "distilled")
            )
        ).scalar()

        # Processing path split (last 30 days) — local vs external.
        from datetime import timedelta

        cutoff = now - timedelta(days=30)
        path_rows = (
            await db.execute(
                select(
                    RawSession.processing_path,
                    func.count().label("n"),
                )
                .where(RawSession.user_id == user_id)
                .where(RawSession.distillation_state == "distilled")
                .where(RawSession.processed_at >= cutoff)
                .group_by(RawSession.processing_path)
            )
        ).all()
        path_split = {(r.processing_path or "unknown"): int(r.n) for r in path_rows}

    pending = by_state.get("pending", 0)
    lag_seconds: float | None = None
    if oldest_pending is not None:
        # Naive datetime in DB → assume UTC for arithmetic.
        oldest_aware = (
            oldest_pending if oldest_pending.tzinfo else oldest_pending.replace(tzinfo=timezone.utc)
        )
        lag_seconds = (now - oldest_aware).total_seconds()

    next_idle_at = _next_idle_window(now.replace(tzinfo=None), settings.distillation_idle_window)

    return _json(
        {
            "counts": {
                "pending": pending,
                "distilled": by_state.get("distilled", 0),
                "filtered": by_state.get("filtered", 0),
                "failed": by_state.get("failed", 0),
                "archived": by_state.get("archived", 0),
            },
            "lag": {
                "oldest_pending_at": oldest_pending.isoformat() if oldest_pending else None,
                "seconds_behind": lag_seconds,
            },
            "last_distilled_at": last_distilled.isoformat() if last_distilled else None,
            "processing_path_30d": path_split,
            "thresholds": {
                "max_pending_backlog": settings.distillation_max_pending_backlog,
                "overflow_threshold": settings.distillation_overflow_threshold,
                "temp_ceiling_c": settings.distillation_temp_ceiling_c,
                "load_ceiling_1m": settings.distillation_load_ceiling_1m,
            },
            "current": {
                "cpu_temp_c": read_cpu_temp_celsius(),
                "load_avg_1m": read_load_average_1min(),
            },
            "schedule": {
                "idle_window": settings.distillation_idle_window,
                "next_idle_at": next_idle_at.isoformat() if next_idle_at else None,
            },
            "enabled": settings.distillation_enabled,
        }
    )


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/freshness
# ---------------------------------------------------------------------------


async def route_project_freshness(request: Request) -> Response:
    """Per-project distillation freshness. Drives the project-card badge.

    Cheap: three small COUNT/MAX queries on indexed columns. Project ownership
    isn't double-checked here — the (user_id, project_id) filter prevents
    cross-tenant reads even if the path parameter is forged.
    """
    user = _require_user(request)
    if user is None:
        return _json({"error": "unauthorized"}, 401)
    user_id = _uid(user)
    project_id = request.path_params.get("id")
    if not project_id:
        return _json({"error": "project id required"}, 400)

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        pending_count = (
            await db.execute(
                select(func.count())
                .select_from(RawSession)
                .where(RawSession.user_id == user_id)
                .where(RawSession.project_id == project_id)
                .where(RawSession.distillation_state == "pending")
            )
        ).scalar() or 0

        last_distilled = (
            await db.execute(
                select(func.max(RawSession.processed_at))
                .where(RawSession.user_id == user_id)
                .where(RawSession.project_id == project_id)
                .where(RawSession.distillation_state == "distilled")
            )
        ).scalar()

        oldest_pending = (
            await db.execute(
                select(func.min(RawSession.created_at))
                .where(RawSession.user_id == user_id)
                .where(RawSession.project_id == project_id)
                .where(RawSession.distillation_state == "pending")
            )
        ).scalar()

    oldest_age_sec: float | None = None
    if oldest_pending is not None:
        oldest_aware = (
            oldest_pending if oldest_pending.tzinfo else oldest_pending.replace(tzinfo=timezone.utc)
        )
        oldest_age_sec = (now - oldest_aware).total_seconds()

    return _json(
        {
            "project_id": project_id,
            "pending_count": int(pending_count),
            "last_distilled_at": last_distilled.isoformat() if last_distilled else None,
            "oldest_pending_age_seconds": oldest_age_sec,
        }
    )


# ---------------------------------------------------------------------------
# POST /api/distillation/run-now
# ---------------------------------------------------------------------------


async def route_run_now(request: Request) -> Response:
    """Wake the worker for an immediate scheduler poll.

    Doesn't bypass temperature/load gates — those still apply. What it does
    is short-circuit the worker's sleep so the next decision happens within
    seconds instead of waiting out the configured poll interval. Useful when
    a user just configured an external provider and wants the backlog drained
    via the overflow path right away.
    """
    user = _require_user(request)
    if user is None:
        return _json({"error": "unauthorized"}, 401)

    woken = _worker_mod.request_wake()
    return _json(
        {
            "woken": woken,
            "note": (
                "Worker polled. Scheduler gates (temp/load/idle window) still apply — "
                "if held, the worker will hold."
            ),
        },
        202,
    )


# ---------------------------------------------------------------------------
# GET /api/budget/usage
# ---------------------------------------------------------------------------


async def route_budget_usage(request: Request) -> Response:
    """Monthly external LLM spend — total, remaining, per-provider breakdown."""
    user = _require_user(request)
    if user is None:
        return _json({"error": "unauthorized"}, 401)
    user_id = _uid(user)
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async with async_session() as db:
        spent = await month_total_usd(db, user_id, now=now)
        remaining = await remaining_budget_usd(db, user_id, now=now)

        per_provider = (
            await db.execute(
                select(
                    ExternalLLMUsage.provider_label,
                    func.count().label("calls"),
                    func.coalesce(func.sum(ExternalLLMUsage.tokens_in), 0).label("tokens_in"),
                    func.coalesce(func.sum(ExternalLLMUsage.tokens_out), 0).label("tokens_out"),
                    func.coalesce(func.sum(ExternalLLMUsage.estimated_cost_usd), 0.0).label(
                        "cost_usd"
                    ),
                )
                .where(ExternalLLMUsage.user_id == user_id)
                .where(ExternalLLMUsage.created_at >= month_start)
                .group_by(ExternalLLMUsage.provider_label)
            )
        ).all()

    settings = get_settings()
    return _json(
        {
            "month_start_utc": month_start.isoformat(),
            "spent_usd": spent,
            "remaining_usd": remaining,
            "cap_usd": settings.distillation_default_budget_monthly_usd,
            "by_provider": [
                {
                    "provider": r.provider_label,
                    "calls": int(r.calls),
                    "tokens_in": int(r.tokens_in),
                    "tokens_out": int(r.tokens_out),
                    "cost_usd": float(r.cost_usd),
                }
                for r in per_provider
            ],
        }
    )
