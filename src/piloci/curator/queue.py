from __future__ import annotations
"""Shared asyncio queue between /api/ingest and the curator worker."""

import asyncio
from dataclasses import dataclass


@dataclass
class IngestJob:
    ingest_id: str
    user_id: str
    project_id: str


_queue: asyncio.Queue[IngestJob] | None = None


def get_ingest_queue(maxsize: int | None = None) -> asyncio.Queue[IngestJob]:
    global _queue
    if _queue is None:
        queue_size = maxsize if maxsize is not None else 0
        if queue_size < 0:
            raise ValueError("Queue maxsize must be >= 0")
        _queue = asyncio.Queue(maxsize=queue_size)
    return _queue


def try_enqueue_job(job: IngestJob, *, maxsize: int | None = None) -> bool:
    queue = get_ingest_queue(maxsize=maxsize)
    try:
        queue.put_nowait(job)
    except asyncio.QueueFull:
        return False
    return True


def reset_ingest_queue() -> None:
    """Test helper — drop the global queue so tests get a fresh one."""
    global _queue
    _queue = None
