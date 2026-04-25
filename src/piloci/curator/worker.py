from __future__ import annotations

"""Background worker: drain ingest queue → Gemma extraction → save memories."""

import asyncio
import logging
from datetime import datetime, timezone

import orjson
from sqlalchemy import select, update

from piloci.config import Settings
from piloci.curator.gemma import chat_json
from piloci.curator.queue import IngestJob, get_ingest_queue, try_enqueue_job
from piloci.curator.vault import invalidate_project_vault_cache
from piloci.db.models import RawSession
from piloci.db.session import async_session
from piloci.storage.embed import embed_texts
from piloci.storage.lancedb_store import MemoryStore

logger = logging.getLogger(__name__)

DEDUP_THRESHOLD = 0.95  # cosine similarity above this → skip as duplicate

_EXTRACT_SYSTEM = (
    "You extract durable memories from AI coding session transcripts. "
    "Output JSON only. Extract facts, decisions, preferences, code patterns, "
    "errors encountered, solutions found. Skip chitchat, tool traces, "
    "routine commands. Keep each memory to 1-2 self-contained sentences."
)

_EXTRACT_USER_TEMPLATE = """Transcript:
{transcript}

Extract memories. Output schema:
{{
  "memories": [
    {{
      "content": "single sentence, self-contained",
      "tags": ["tag1", "tag2"],
      "category": "fact|decision|preference|pattern|error|solution"
    }}
  ]
}}
Output ONLY the JSON object, no prose."""


def _shorten_transcript(transcript: list[dict[str, object]], max_chars: int = 8000) -> str:
    """Render transcript for Gemma, truncating long content if needed."""
    lines = []
    for msg in transcript:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") if isinstance(c, dict) else str(c) for c in content
            )
        lines.append(f"[{role}] {content}")
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text

    marker = "\n...[truncated]...\n"
    budget = max_chars - len(marker)
    # Favor recency: keep tail; if small enough, also keep head.
    head_budget = min(budget // 3, 500)
    tail_budget = budget - head_budget
    head = text[:head_budget]
    tail = text[-tail_budget:] if tail_budget > 0 else ""
    return head + marker + tail


async def _extract_memories(
    transcript: list[dict[str, object]], settings: Settings
) -> list[dict[str, object]]:
    max_chars = getattr(settings, "curator_transcript_max_chars", 8000)
    text = _shorten_transcript(transcript, max_chars=max_chars)
    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM},
        {"role": "user", "content": _EXTRACT_USER_TEMPLATE.format(transcript=text)},
    ]
    result = await chat_json(
        messages,
        endpoint=settings.gemma_endpoint,
        model=settings.gemma_model,
    )
    memories = result.get("memories", [])
    if not isinstance(memories, list):
        return []
    return memories


async def _is_duplicate(
    store: MemoryStore,
    user_id: str,
    project_id: str,
    vector: list[float],
) -> bool:
    """Check if a very similar memory already exists."""
    results = await store.search(
        user_id=user_id,
        project_id=project_id,
        query_vector=vector,
        top_k=1,
    )
    if not results:
        return False
    return results[0].get("score", 0.0) >= DEDUP_THRESHOLD


async def _process_job(job: IngestJob, settings: Settings, store: MemoryStore) -> None:
    async with async_session() as db:
        row = await db.get(RawSession, job.ingest_id)
        if row is None:
            logger.warning("RawSession %s not found", job.ingest_id)
            return
        transcript = orjson.loads(row.transcript_json)

    try:
        memories = await _extract_memories(transcript, settings)
    except Exception as e:
        logger.exception("Gemma extraction failed for %s: %s", job.ingest_id, e)
        async with async_session() as db:
            await db.execute(
                update(RawSession)
                .where(RawSession.ingest_id == job.ingest_id)
                .values(error=str(e)[:500])
            )
            await db.commit()
        return

    prepared: list[tuple[str, list[str]]] = []
    for mem in memories:
        raw_content = mem.get("content")
        content = raw_content.strip() if isinstance(raw_content, str) else ""
        if not content:
            continue
        raw_tags = mem.get("tags")
        tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else []
        category = mem.get("category")
        if category:
            tags = list(dict.fromkeys([*tags, str(category)]))
        prepared.append((content, tags[:5]))

    vectors = (
        await embed_texts(
            [content for content, _ in prepared],
            model=settings.embed_model,
            cache_dir=settings.embed_cache_dir,
            lru_size=settings.embed_lru_size,
            executor_workers=settings.embed_executor_workers,
            max_concurrency=settings.embed_max_concurrency,
        )
        if prepared
        else []
    )

    saved_count = 0
    for (content, tags), vector in zip(prepared, vectors, strict=True):
        try:
            if await _is_duplicate(store, job.user_id, job.project_id, vector):
                logger.debug("Skipping duplicate memory: %s", content[:60])
                continue
            await store.save(
                user_id=job.user_id,
                project_id=job.project_id,
                content=content,
                vector=vector,
                tags=tags[:5],
            )
            saved_count += 1
        except Exception as e:
            logger.warning("Failed to save extracted memory: %s", e)

    async with async_session() as db:
        await db.execute(
            update(RawSession)
            .where(RawSession.ingest_id == job.ingest_id)
            .values(
                processed_at=datetime.now(timezone.utc),
                memories_extracted=saved_count,
            )
        )
        await db.commit()

    if saved_count > 0:
        await invalidate_project_vault_cache(
            settings.vault_dir,
            job.user_id,
            job.project_id,
        )

    logger.info(
        "Processed ingest %s: extracted %d memories from %d transcript lines",
        job.ingest_id,
        saved_count,
        len(transcript),
    )


async def run_worker(settings: Settings, store: MemoryStore, stop_event: asyncio.Event) -> None:
    """Long-running worker: drain the queue until stop_event is set."""
    queue = get_ingest_queue(settings.ingest_queue_maxsize)
    logger.info("Curator worker started")

    while not stop_event.is_set():
        try:
            job = await asyncio.wait_for(
                queue.get(), timeout=settings.curator_queue_poll_timeout_sec
            )
        except asyncio.TimeoutError:
            continue
        try:
            await _process_job(job, settings, store)
        except Exception as e:
            logger.exception("Unhandled error processing job %s: %s", job.ingest_id, e)
        finally:
            queue.task_done()

    logger.info("Curator worker stopped")


async def process_unfinished(settings: Settings, store: MemoryStore) -> int:
    """On startup, re-queue any raw_sessions that were never processed."""
    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(RawSession).where(
                        RawSession.processed_at.is_(None),
                        RawSession.error.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )

    requeued = 0
    for row in rows:
        if row.project_id is None:
            continue
        job = IngestJob(
            ingest_id=row.ingest_id,
            user_id=row.user_id,
            project_id=row.project_id,
        )
        if not try_enqueue_job(job, maxsize=settings.ingest_queue_maxsize):
            logger.warning(
                "Ingest queue full during startup requeue; leaving %s pending",
                row.ingest_id,
            )
            continue
        requeued += 1
    return requeued
