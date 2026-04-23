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


def get_ingest_queue() -> asyncio.Queue[IngestJob]:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


def reset_ingest_queue() -> None:
    """Test helper — drop the global queue so tests get a fresh one."""
    global _queue
    _queue = None
