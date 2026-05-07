from __future__ import annotations

"""Background worker: drain analyze queue → Gemma instinct extraction → save.

Mirrors curator.worker but for instincts. Each row in raw_analyses lives until
processed; on worker restart, ``process_unfinished_analyses`` re-queues any
pending rows so transcripts are never lost. Errors are stamped into the row's
``error`` column so they're visible without scraping logs.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from piloci.config import Settings
from piloci.curator.analyze_queue import AnalyzeJob, get_analyze_queue, try_enqueue_analyze
from piloci.curator.session_analyzer import extract_instincts
from piloci.db.models import RawAnalysis
from piloci.db.session import async_session
from piloci.storage import embed as _embed_mod
from piloci.storage.instincts_store import InstinctsStore

logger = logging.getLogger(__name__)


async def _process_analyze_job(
    job: AnalyzeJob,
    settings: Settings,
    instincts_store: InstinctsStore,
) -> None:
    async with async_session() as db:
        row = (
            await db.execute(select(RawAnalysis).where(RawAnalysis.analyze_id == job.analyze_id))
        ).scalar_one_or_none()
    if row is None:
        logger.warning("analyze_worker: row %s vanished — skipping", job.analyze_id)
        return
    if row.processed_at is not None:
        return  # already processed

    transcript = row.transcript

    try:
        raw_instincts = await extract_instincts(
            transcript=transcript,
            endpoint=settings.gemma_endpoint,
            model=settings.gemma_model,
        )
    except Exception as e:
        logger.exception("analyze_worker: extraction failed for %s", job.analyze_id)
        async with async_session() as db:
            await db.execute(
                update(RawAnalysis)
                .where(RawAnalysis.analyze_id == job.analyze_id)
                .values(error=str(e)[:500], processed_at=datetime.now(timezone.utc))
            )
            await db.commit()
        return

    saved = 0
    for inst in raw_instincts:
        try:
            combined = f"{inst['trigger']} {inst['action']}"
            vector = await _embed_mod.embed_one(
                text=combined,
                model=settings.embed_model,
                cache_dir=settings.embed_cache_dir,
                lru_size=settings.embed_lru_size,
                executor_workers=settings.embed_executor_workers,
                max_concurrency=settings.embed_max_concurrency,
            )
            await instincts_store.observe(
                user_id=job.user_id,
                project_id=job.project_id,
                trigger=inst["trigger"],
                action=inst["action"],
                domain=inst.get("domain", "other"),
                evidence_note=inst.get("evidence", ""),
                vector=vector,
            )
            saved += 1
        except Exception:
            logger.exception("analyze_worker: failed to store instinct for %s", job.analyze_id)

    async with async_session() as db:
        await db.execute(
            update(RawAnalysis)
            .where(RawAnalysis.analyze_id == job.analyze_id)
            .values(
                processed_at=datetime.now(timezone.utc),
                instincts_extracted=saved,
            )
        )
        await db.commit()

    logger.info(
        "Processed analyze %s: extracted %d instincts (%d candidates)",
        job.analyze_id,
        saved,
        len(raw_instincts),
    )


async def run_analyze_worker(
    settings: Settings,
    instincts_store: InstinctsStore,
    stop_event: asyncio.Event,
) -> None:
    """Long-running worker: drain the analyze queue until stop_event is set."""
    queue = get_analyze_queue(settings.analyze_queue_maxsize)
    logger.info("Analyze worker started")

    while not stop_event.is_set():
        try:
            job = await asyncio.wait_for(
                queue.get(), timeout=settings.curator_queue_poll_timeout_sec
            )
        except asyncio.TimeoutError:
            continue
        try:
            await _process_analyze_job(job, settings, instincts_store)
        except Exception:
            logger.exception("Unhandled error processing analyze job %s", job.analyze_id)
        finally:
            queue.task_done()

    logger.info("Analyze worker stopped")


async def process_unfinished_analyses(settings: Settings) -> int:
    """On startup, re-queue any raw_analyses that were never processed."""
    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(RawAnalysis).where(
                        RawAnalysis.processed_at.is_(None),
                        RawAnalysis.error.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )

    requeued = 0
    for row in rows:
        job = AnalyzeJob(
            analyze_id=row.analyze_id,
            user_id=row.user_id,
            project_id=row.project_id,
        )
        if not try_enqueue_analyze(job, maxsize=settings.analyze_queue_maxsize):
            logger.warning(
                "Analyze queue full during startup requeue; leaving %s pending",
                row.analyze_id,
            )
            continue
        requeued += 1
    return requeued
