from __future__ import annotations

"""Async queue for /api/sessions/analyze → background instinct extraction.

Separate from the ingest queue so memory extraction (SessionStart catch-up)
and instinct extraction (per-turn Stop hook) don't starve each other for
Gemma slots, and so a single misbehaving worker doesn't take down the other.
"""

import asyncio
from dataclasses import dataclass


@dataclass
class AnalyzeJob:
    analyze_id: str
    user_id: str
    project_id: str


_queue: asyncio.Queue[AnalyzeJob] | None = None


def get_analyze_queue(maxsize: int | None = None) -> asyncio.Queue[AnalyzeJob]:
    global _queue
    if _queue is None:
        queue_size = maxsize if maxsize is not None else 0
        if queue_size < 0:
            raise ValueError("Queue maxsize must be >= 0")
        _queue = asyncio.Queue(maxsize=queue_size)
    return _queue


def try_enqueue_analyze(job: AnalyzeJob, *, maxsize: int | None = None) -> bool:
    queue = get_analyze_queue(maxsize=maxsize)
    try:
        queue.put_nowait(job)
    except asyncio.QueueFull:
        return False
    return True


def reset_analyze_queue() -> None:
    """Test helper — drop the global queue so tests get a fresh one."""
    global _queue
    _queue = None
