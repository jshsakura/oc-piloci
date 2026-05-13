from __future__ import annotations

"""Lazy distillation worker — single replacement for curator.worker +
analyze_worker.

Polls the scheduler at runtime to decide whether the device should currently
process anything, drains a small batch of pending RawSession rows, runs the
unified Gemma extraction once per row, and dispatches the resulting memories
and instincts into their respective stores. State transitions on RawSession
mirror what the user sees in the observability dashboard:

    pending  → (extract_session) → distilled
    pending  → (max_attempts)    → failed
    pending  → (backlog overflow at ingest) → archived

External LLM calls are recorded against the user's monthly budget.
"""

import asyncio
import logging
from datetime import datetime, timezone

import orjson
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from piloci.config import Settings
from piloci.curator.backlog import count_pending
from piloci.curator.budget import is_budget_exhausted, record_usage
from piloci.curator.extraction import (
    DistilledInstinct,
    DistilledMemory,
    DistilledSession,
    extract_session,
)
from piloci.curator.llm_providers import load_user_fallbacks
from piloci.curator.scheduler import (
    IdleWindow,
    SchedulerConfig,
    SchedulerDecision,
    parse_idle_window,
    poll,
)
from piloci.curator.vault import invalidate_project_vault_cache
from piloci.db.models import Project, RawSession, UserPreferences
from piloci.db.session import async_session
from piloci.storage import embed as _embed_mod
from piloci.storage.instincts_store import InstinctsStore
from piloci.storage.lancedb_store import MemoryStore, MemoryWrite

logger = logging.getLogger(__name__)


# Batch size: how many pending rows the worker handles per scheduler poll. Kept
# small so a temperature spike during a batch can still abort cleanly at the
# next poll boundary. Larger batches just delay that responsiveness.
DEFAULT_BATCH_SIZE = 4

# Memory dedup threshold inherited from the legacy curator. Two memories with
# cosine similarity ≥ this against an existing record are considered duplicates
# and skipped. Conservative because false-positive dedup loses information.
DEDUP_THRESHOLD = 0.95


# Module-level wake event so the /api/distillation/run-now endpoint can
# short-circuit the worker's sleep and trigger an immediate scheduler poll.
# Lazily constructed because the loop must own it (created inside
# run_distillation_worker on first call).
_wake_event: asyncio.Event | None = None


def _get_wake_event() -> asyncio.Event:
    global _wake_event
    if _wake_event is None:
        _wake_event = asyncio.Event()
    return _wake_event


def request_wake() -> bool:
    """Signal the worker to skip its remaining sleep and re-poll now.

    Returns True when the event was set (worker is alive and listening),
    False when no worker has registered yet (e.g., distillation disabled).
    The endpoint surfaces this so the user knows whether the wake actually
    landed.
    """
    if _wake_event is None:
        return False
    _wake_event.set()
    return True


async def _sleep_until(
    stop_event: asyncio.Event, wake_event: asyncio.Event, seconds: float
) -> None:
    """Sleep up to ``seconds`` but return early on stop or wake.

    Wake events are auto-cleared so the next sleep blocks again. Stop events
    aren't cleared — they're terminal.
    """
    if seconds <= 0:
        return
    try:
        await asyncio.wait_for(
            asyncio.wait(
                [
                    asyncio.create_task(stop_event.wait()),
                    asyncio.create_task(wake_event.wait()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            ),
            timeout=seconds,
        )
    except asyncio.TimeoutError:
        pass
    if wake_event.is_set():
        wake_event.clear()


def _build_scheduler_config(
    settings: Settings, user_prefs: UserPreferences | None
) -> SchedulerConfig:
    """Merge per-user preferences over server-wide settings.

    A NULL field on UserPreferences inherits the server default. This keeps
    the common case (user never touched their settings) fast — no row,
    everything from Settings.
    """
    idle_spec = settings.distillation_idle_window
    temp_ceiling = settings.distillation_temp_ceiling_c
    load_ceiling = settings.distillation_load_ceiling_1m
    overflow = settings.distillation_overflow_threshold

    if user_prefs is not None:
        if user_prefs.distillation_idle_window is not None:
            idle_spec = user_prefs.distillation_idle_window
        if user_prefs.distillation_temp_ceiling_c is not None:
            temp_ceiling = user_prefs.distillation_temp_ceiling_c
        if user_prefs.distillation_load_ceiling_1m is not None:
            load_ceiling = user_prefs.distillation_load_ceiling_1m
        if user_prefs.distillation_overflow_threshold is not None:
            overflow = user_prefs.distillation_overflow_threshold

    idle_window: IdleWindow | None = parse_idle_window(idle_spec) if idle_spec else None

    return SchedulerConfig(
        idle_window=idle_window,
        temp_ceiling_celsius=temp_ceiling,
        load_ceiling_1m=load_ceiling,
        overflow_threshold=overflow,
        poll_interval_normal=settings.distillation_poll_interval_normal_sec,
        poll_interval_idle=settings.distillation_poll_interval_idle_sec,
        poll_interval_held=settings.distillation_poll_interval_held_sec,
    )


async def _fetch_pending_batch(
    db: AsyncSession, *, limit: int, max_attempts: int
) -> list[RawSession]:
    """Pull up to ``limit`` rows ready for distillation.

    Ordering: highest priority first, then oldest. ``attempt_count`` capped so
    we don't grind on a poison row forever — once a row hits ``max_attempts``
    it transitions to 'failed' and stops being picked up.
    """
    stmt = (
        select(RawSession)
        .where(RawSession.distillation_state == "pending")
        .where(RawSession.attempt_count < max_attempts)
        .order_by(RawSession.priority.desc(), RawSession.created_at.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / ((na**0.5) * (nb**0.5))


async def _save_memories(
    settings: Settings,
    memory_store: MemoryStore,
    user_id: str,
    project_id: str,
    memories: list[DistilledMemory],
) -> int:
    """Embed, dedupe, save. Returns count actually written."""
    if not memories:
        return 0

    contents = [m.content for m in memories]
    vectors = await _embed_mod.embed_texts(
        contents,
        model=settings.embed_model,
        cache_dir=settings.embed_cache_dir,
        lru_size=settings.embed_lru_size,
        executor_workers=settings.embed_executor_workers,
        max_concurrency=settings.embed_max_concurrency,
    )

    pending: list[MemoryWrite] = []
    accepted_vectors: list[list[float]] = []
    for mem, vec in zip(memories, vectors, strict=True):
        if any(_cosine(vec, av) >= DEDUP_THRESHOLD for av in accepted_vectors):
            continue
        try:
            existing = await memory_store.search(
                user_id=user_id,
                project_id=project_id,
                query_vector=vec,
                top_k=1,
            )
        except Exception:
            logger.exception("dedup search failed; saving without check")
            existing = []
        if existing and existing[0].get("score", 0.0) >= DEDUP_THRESHOLD:
            continue
        pending.append(
            {
                "content": mem.content,
                "vector": vec,
                "tags": mem.tags[:5],
                "metadata": {"source": "distilled"},
            }
        )
        accepted_vectors.append(vec)

    if not pending:
        return 0
    saved = await memory_store.save_many(
        user_id=user_id,
        project_id=project_id,
        memories=pending,
    )
    return len(saved)


async def _save_instincts(
    settings: Settings,
    instincts_store: InstinctsStore,
    user_id: str,
    project_id: str,
    instincts: list[DistilledInstinct],
) -> int:
    """Embed and observe each instinct. Store handles its own merge logic."""
    saved = 0
    for inst in instincts:
        combined = f"{inst.trigger} {inst.action}"
        try:
            vector = await _embed_mod.embed_one(
                text=combined,
                model=settings.embed_model,
                cache_dir=settings.embed_cache_dir,
                lru_size=settings.embed_lru_size,
                executor_workers=settings.embed_executor_workers,
                max_concurrency=settings.embed_max_concurrency,
            )
            await instincts_store.observe(
                user_id=user_id,
                project_id=project_id,
                trigger=inst.trigger,
                action=inst.action,
                domain=inst.domain,
                evidence_note=inst.evidence,
                vector=vector,
            )
            saved += 1
        except Exception:
            logger.exception("failed to store instinct (%s → %s)", inst.trigger, inst.action)
    return saved


async def _process_one(
    row: RawSession,
    settings: Settings,
    memory_store: MemoryStore,
    instincts_store: InstinctsStore,
    use_external: bool,
) -> None:
    """Run extraction on a single RawSession row, persist results, advance state."""
    started = datetime.now(timezone.utc)
    transcript = orjson.loads(row.transcript_json)

    # Record the attempt before the LLM call so a worker crash mid-extraction
    # doesn't leave attempt_count understated.
    async with async_session() as db:
        await db.execute(
            update(RawSession)
            .where(RawSession.ingest_id == row.ingest_id)
            .values(
                attempt_count=RawSession.attempt_count + 1,
                last_attempted_at=started,
            )
        )

    fallbacks = await load_user_fallbacks(row.user_id)
    distilled: DistilledSession = await extract_session(
        transcript,
        endpoint=settings.gemma_endpoint,
        model=settings.gemma_model,
        fallbacks=fallbacks,
        prefer_external=use_external,
    )

    # An empty result with no error usually means the LLM returned junk JSON
    # (validation rejected everything). Treat as a soft-failure attempt — the
    # row stays pending until attempt_count maxes out.
    if not distilled.memories and not distilled.instincts:
        async with async_session() as db:
            current = await db.get(RawSession, row.ingest_id)
            if current is None:
                return
            attempts_now = current.attempt_count
            new_state = (
                "failed" if attempts_now >= settings.distillation_max_attempts else "pending"
            )
            await db.execute(
                update(RawSession)
                .where(RawSession.ingest_id == row.ingest_id)
                .values(
                    distillation_state=new_state,
                    error="empty_extraction",
                    processing_path=distilled.processing_path,
                    processed_at=datetime.now(timezone.utc) if new_state == "failed" else None,
                )
            )
        logger.info(
            "distillation: row %s yielded nothing (attempt %d/%d)",
            row.ingest_id,
            row.attempt_count + 1,
            settings.distillation_max_attempts,
        )
        return

    project_id = row.project_id or ""
    memories_saved = 0
    instincts_saved = 0
    if project_id:
        memories_saved = await _save_memories(
            settings, memory_store, row.user_id, project_id, distilled.memories
        )
        instincts_saved = await _save_instincts(
            settings, instincts_store, row.user_id, project_id, distilled.instincts
        )

    # External path: book the call against the budget. Token counts unknown
    # at this layer (chat_json doesn't return usage); use a flat default cost.
    if distilled.processing_path == "external":
        async with async_session() as db:
            await record_usage(
                db,
                user_id=row.user_id,
                provider_label="external-fallback",
                model=settings.gemma_model,
                tokens_in=0,
                tokens_out=0,
            )

    async with async_session() as db:
        await db.execute(
            update(RawSession)
            .where(RawSession.ingest_id == row.ingest_id)
            .values(
                distillation_state="distilled",
                processed_at=datetime.now(timezone.utc),
                memories_extracted=memories_saved,
                instincts_extracted=instincts_saved,
                processing_path=distilled.processing_path,
                error=None,
            )
        )
        if project_id and memories_saved > 0:
            await db.execute(
                update(Project)
                .where(Project.id == project_id)
                .values(memory_count=Project.memory_count + memories_saved)
            )
        if project_id and instincts_saved > 0:
            await db.execute(
                update(Project)
                .where(Project.id == project_id)
                .values(instinct_count=Project.instinct_count + instincts_saved)
            )

    if project_id and memories_saved > 0:
        await invalidate_project_vault_cache(settings.vault_dir, row.user_id, project_id)

    logger.info(
        "distillation: row %s done — %d memories, %d instincts via %s",
        row.ingest_id,
        memories_saved,
        instincts_saved,
        distilled.processing_path,
    )


async def _decide(settings: Settings) -> SchedulerDecision:
    """Single-shot scheduler poll across the whole pending pool.

    For now the scheduler runs against the global pending count and uses
    server-wide config — per-user gating would need a per-user pool but
    one shared Pi serves only a handful of users in practice and the
    extra complexity isn't worth it yet.
    """
    async with async_session() as db:
        pending = await count_pending(db)

    config = _build_scheduler_config(settings, None)

    # Probe whether *any* user has external provider keys + budget headroom.
    # Per-row use_external is decided when we know the row's user_id; this
    # global check just unlocks the path so the scheduler can flag overflow.
    has_external = bool(
        settings.external_llm_endpoint
        and settings.external_llm_model
        and settings.external_llm_api_key
    )

    return await poll(
        config,
        pending,
        has_external_provider=has_external,
        budget_exhausted=False,
    )


async def run_distillation_worker(
    settings: Settings,
    memory_store: MemoryStore,
    instincts_store: InstinctsStore,
    stop_event: asyncio.Event,
) -> None:
    """Long-running lazy distillation loop. Replaces run_worker + run_analyze_worker."""
    if not settings.distillation_enabled:
        logger.info("distillation: disabled via settings.distillation_enabled=False")
        return

    wake = _get_wake_event()
    logger.info("distillation: lazy worker started")
    while not stop_event.is_set():
        try:
            decision = await _decide(settings)
        except Exception:
            logger.exception("distillation: scheduler poll failed")
            await asyncio.sleep(settings.distillation_poll_interval_held_sec)
            continue

        if not decision.should_run:
            logger.debug(
                "distillation: holding (%s) — pending=%d temp=%s load=%s",
                decision.reason,
                decision.pending_count,
                decision.cpu_temp_c,
                decision.load_avg_1m,
            )
            await _sleep_until(stop_event, wake, decision.next_poll_seconds)
            continue

        # Pull a small batch and process sequentially. The scheduler is asked
        # again at the top of the loop so a temp spike during the batch
        # naturally gets respected on the next iteration.
        async with async_session() as db:
            batch = await _fetch_pending_batch(
                db,
                limit=DEFAULT_BATCH_SIZE,
                max_attempts=settings.distillation_max_attempts,
            )

        if not batch:
            # Pending count > 0 but every row exceeded max attempts. Sleep
            # normally so we don't busy-loop on poison rows.
            await asyncio.sleep(decision.next_poll_seconds)
            continue

        logger.info(
            "distillation: processing batch of %d (path=%s, reason=%s)",
            len(batch),
            "external" if decision.use_external else "local",
            decision.reason,
        )
        for row in batch:
            if stop_event.is_set():
                break
            # Per-row budget check: skip overflow path if this user is capped out.
            row_use_external = decision.use_external
            if row_use_external:
                async with async_session() as db:
                    if await is_budget_exhausted(db, row.user_id):
                        row_use_external = False
            try:
                await _process_one(
                    row,
                    settings,
                    memory_store,
                    instincts_store,
                    use_external=row_use_external,
                )
            except Exception:
                logger.exception("distillation: row %s processing crashed", row.ingest_id)
                async with async_session() as db:
                    current = await db.get(RawSession, row.ingest_id)
                    if current is not None:
                        new_state = (
                            "failed"
                            if current.attempt_count >= settings.distillation_max_attempts
                            else "pending"
                        )
                        await db.execute(
                            update(RawSession)
                            .where(RawSession.ingest_id == row.ingest_id)
                            .values(
                                distillation_state=new_state,
                                error="worker_exception",
                                processed_at=(
                                    datetime.now(timezone.utc) if new_state == "failed" else None
                                ),
                            )
                        )

    logger.info("distillation: lazy worker stopped")
