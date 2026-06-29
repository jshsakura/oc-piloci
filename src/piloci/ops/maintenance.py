from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from piloci.config import Settings
from piloci.db.models import AuditLog, RawSession
from piloci.db.session import async_session

logger = logging.getLogger(__name__)


async def cleanup_retention(settings: Settings) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    raw_cutoff = now - timedelta(days=settings.raw_session_retention_days)
    audit_cutoff = now - timedelta(days=settings.audit_log_retention_days)

    async with async_session() as db:
        # A raw session is reclaimable once it reaches a terminal state and ages
        # out. Two terminal paths exist and only the first sets processed_at:
        #   - distilled / failed → processed_at is stamped
        #   - archived (backlog overflow, FIFO-dropped) → processed_at stays NULL,
        #     so keying retention on processed_at alone leaks these forever.
        # Archived rows are never going to be distilled, so age them out by
        # archived_at (falling back to created_at). Pending rows are still owed
        # distillation and are intentionally kept regardless of age.
        processed_filter = RawSession.processed_at.is_not(None) & (
            RawSession.processed_at < raw_cutoff
        )
        archived_filter = (RawSession.distillation_state == "archived") & (
            func.coalesce(RawSession.archived_at, RawSession.created_at) < raw_cutoff
        )
        raw_filter = processed_filter | archived_filter
        audit_filter = AuditLog.created_at < audit_cutoff

        deleted_raw = int(
            (
                await db.execute(select(func.count()).select_from(RawSession).where(raw_filter))
            ).scalar_one()
        )
        deleted_archived = int(
            (
                await db.execute(
                    select(func.count()).select_from(RawSession).where(archived_filter)
                )
            ).scalar_one()
        )
        deleted_audit = int(
            (
                await db.execute(select(func.count()).select_from(AuditLog).where(audit_filter))
            ).scalar_one()
        )

        if deleted_raw:
            await db.execute(delete(RawSession).where(raw_filter))
        if deleted_audit:
            await db.execute(delete(AuditLog).where(audit_filter))

        await db.commit()

    logger.info(
        "Retention cleanup finished (raw_sessions=%d [archived=%d], audit_logs=%d)",
        deleted_raw,
        deleted_archived,
        deleted_audit,
    )
    return {"raw_sessions": deleted_raw, "audit_logs": deleted_audit}


async def run_maintenance_worker(settings: Settings, stop_event: asyncio.Event) -> None:
    logger.info(
        "Maintenance worker started (interval=%ss, raw_retention_days=%d, audit_retention_days=%d)",
        settings.maintenance_interval_sec,
        settings.raw_session_retention_days,
        settings.audit_log_retention_days,
    )
    while not stop_event.is_set():
        try:
            await cleanup_retention(settings)
        except Exception:
            logger.exception("Maintenance cleanup failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.maintenance_interval_sec)
        except asyncio.TimeoutError:
            continue

    logger.info("Maintenance worker stopped")
