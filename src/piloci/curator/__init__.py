from __future__ import annotations

"""Gemma-based curator: raw transcripts → wiki-grade memories.

Key components:
- queue.py: asyncio.Queue shared between /api/ingest and the worker
- gemma.py: HTTP client for local Gemma (OpenAI-compatible)
- worker.py: Background task that drains the queue
- profile.py: Periodic user-profile summarizer
"""

from piloci.curator.queue import get_ingest_queue

__all__ = ["get_ingest_queue"]
