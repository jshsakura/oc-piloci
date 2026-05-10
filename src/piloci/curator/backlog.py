from __future__ import annotations

"""Backlog ceiling enforcement for the lazy distillation pipeline.

The asyncio.Queue used by the legacy workers was a runtime-only notification
mechanism — once piLoci restarted, ``process_unfinished`` re-queued every
unprocessed RawSession ever recorded. With heavy use that meant an unbounded
backlog. This module replaces that by treating the database itself as the
queue and enforcing a hard ceiling: when ``pending`` count exceeds the
configured cap, the oldest rows are archived (state='archived', raw kept) so
the device never falls into an unrecoverable distillation debt spiral.

Archive policy is intentionally drop-oldest: a fresh long session is more
likely to capture the user's current behavior than a week-old one. If the
user wants those archived sessions back they can manually re-mark via API.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from piloci.db.models import RawSession

PENDING_STATE = "pending"
ARCHIVED_STATE = "archived"


async def count_pending(db: AsyncSession, user_id: str | None = None) -> int:
    """Count rows currently waiting for distillation.

    ``user_id`` scopes the count to a single user when provided — useful for
    per-user ceilings later. Without it, returns the global pending count.
    """
    stmt = (
        select(func.count())
        .select_from(RawSession)
        .where(RawSession.distillation_state == PENDING_STATE)
    )
    if user_id is not None:
        stmt = stmt.where(RawSession.user_id == user_id)
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def archive_overflow(
    db: AsyncSession,
    *,
    max_pending: int,
    user_id: str | None = None,
) -> int:
    """Archive the oldest pending rows until pending count <= max_pending.

    Returns the number archived. Idempotent: if pending is already within
    the cap, this is a no-op. Caller is responsible for committing the
    transaction — we keep the write inside the caller's session so the
    archive happens atomically with whatever write triggered the overflow
    check (typically a fresh ingest).
    """
    pending_now = await count_pending(db, user_id=user_id)
    if pending_now <= max_pending:
        return 0

    excess = pending_now - max_pending

    # Pick the N oldest pending rows to archive. Priority is honored — high
    # priority rows survive even when older. Without ORDER BY priority,
    # user-flagged 'process now' work could get archived ahead of trivia.
    candidates_stmt = (
        select(RawSession.ingest_id)
        .where(RawSession.distillation_state == PENDING_STATE)
        .order_by(RawSession.priority.asc(), RawSession.created_at.asc())
        .limit(excess)
    )
    if user_id is not None:
        candidates_stmt = candidates_stmt.where(RawSession.user_id == user_id)

    rows = (await db.execute(candidates_stmt)).scalars().all()
    if not rows:
        return 0

    now = datetime.now(timezone.utc)
    await db.execute(
        update(RawSession)
        .where(RawSession.ingest_id.in_(rows))
        .values(
            distillation_state=ARCHIVED_STATE,
            archived_at=now,
            filter_reason="backlog_overflow",
        )
    )
    return len(rows)


async def enforce_ceiling_after_ingest(
    db: AsyncSession,
    *,
    max_pending: int,
    user_id: str | None = None,
) -> int:
    """Convenience wrapper: call right after inserting a fresh pending row.

    Encapsulates the typical ingest-time pattern so callers don't have to
    juggle the count→archive sequence themselves.
    """
    return await archive_overflow(db, max_pending=max_pending, user_id=user_id)
