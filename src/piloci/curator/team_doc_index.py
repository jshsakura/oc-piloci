"""Index team documents into the team LanceDB table as searchable chunks.

This is the "remote team-document search as if local" pipeline: a team
document (SQL ``team_documents`` row) is split into a bounded set of
overlapping windows, each window is embedded locally (fastembed, executor
backed — NO LLM call), and the resulting chunks are written to the same
team table that ``recall`` queries. The agent then gets token-bounded
snippets back without ever downloading the file.

Both entrypoints are designed to run as fire-and-forget background tasks
(``asyncio.create_task``): they catch and log every exception so a failed
index never crashes the request that triggered it.
"""

from __future__ import annotations

import logging
from math import ceil
from typing import TYPE_CHECKING

from piloci.curator.extraction import _split_into_chunks
from piloci.storage.embed import embed_one

if TYPE_CHECKING:
    from piloci.config import Settings
    from piloci.storage.lancedb_store import MemoryStore

logger = logging.getLogger(__name__)

# Target chunk size and overlap (chars). Tuned for bge-small context + Pi 5
# embedding cost. MAX_CHUNKS bounds the per-document embedding work so a huge
# upload can't monopolise the single embed executor.
CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200
MAX_CHUNKS = 40


def _line_range(content: str, start: int, end: int) -> tuple[int, int]:
    """Approximate 1-based line range a [start, end) char window spans."""
    line_start = content.count("\n", 0, start) + 1
    # end is exclusive; clamp into the content so trailing windows are sane.
    end = min(end, len(content))
    line_end = content.count("\n", 0, end) + 1
    return line_start, line_end


def _plan_chunks(content: str) -> list[dict]:
    """Split content into bounded overlapping windows with line ranges.

    Returns a list of {content, char_start, line_start, line_end}. Coverage is
    contiguous-ish: ``_split_into_chunks`` spreads window starts evenly across
    the document, and we size the count to step by ``CHUNK_CHARS - OVERLAP``.
    """
    if not content:
        return []

    if len(content) <= CHUNK_CHARS:
        n_chunks = 1
    else:
        stride = max(1, CHUNK_CHARS - CHUNK_OVERLAP)
        n_chunks = min(MAX_CHUNKS, ceil(len(content) / stride))

    windows = _split_into_chunks(content, n_chunks, CHUNK_CHARS, CHUNK_OVERLAP)

    planned: list[dict] = []
    search_from = 0
    for window in windows:
        if not window:
            continue
        # Recover each window's char offset. Windows are taken in order from
        # increasing start positions, so a forward-only find is correct and
        # avoids matching an earlier identical span.
        idx = content.find(window, search_from)
        if idx < 0:
            idx = content.find(window)
        char_start = idx if idx >= 0 else search_from
        char_end = char_start + len(window)
        search_from = char_start + 1
        line_start, line_end = _line_range(content, char_start, char_end)
        planned.append(
            {
                "content": window,
                "char_start": char_start,
                "line_start": line_start,
                "line_end": line_end,
            }
        )
    return planned


async def index_team_document(
    store: "MemoryStore",
    team_id: str,
    doc_id: str,
    path: str,
    content: str,
    *,
    settings: "Settings",
) -> int:
    """Chunk, embed, and index one team document. Returns chunk count.

    Safe as a fire-and-forget task: any failure is logged, never raised.
    """
    try:
        planned = _plan_chunks(content or "") if (content or "").strip() else []
        if not planned:
            # Empty/whitespace doc — still clear any prior chunks so a doc that
            # was emptied stops surfacing in recall.
            await store.team_remove_doc_chunks(team_id, doc_id)
            return 0

        chunks = []
        for idx, p in enumerate(planned):
            vector = await embed_one(
                p["content"],
                model=settings.embed_model,
                cache_dir=settings.embed_cache_dir,
                lru_size=settings.embed_lru_size,
                executor_workers=settings.embed_executor_workers,
                max_concurrency=settings.embed_max_concurrency,
            )
            chunks.append(
                {
                    "content": p["content"],
                    "vector": vector,
                    "metadata": {
                        "kind": "doc_chunk",
                        "doc_id": doc_id,
                        "path": path,
                        "chunk_index": idx,
                        "line_start": p["line_start"],
                        "line_end": p["line_end"],
                    },
                }
            )

        await store.team_index_doc_chunks(team_id, doc_id, chunks)
        logger.info("indexed team document team=%s doc=%s chunks=%d", team_id, doc_id, len(chunks))
        return len(chunks)
    except Exception:
        logger.exception("index_team_document failed team=%s doc=%s", team_id, doc_id)
        return 0


async def remove_team_document(store: "MemoryStore", team_id: str, doc_id: str) -> int:
    """Remove all indexed chunks for a team document. Returns rows deleted.

    Safe as a fire-and-forget task: any failure is logged, never raised.
    """
    try:
        return await store.team_remove_doc_chunks(team_id, doc_id)
    except Exception:
        logger.exception("remove_team_document failed team=%s doc=%s", team_id, doc_id)
        return 0
