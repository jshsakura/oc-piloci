"""Tests for Gemma curator worker with mocked Gemma responses."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from piloci.curator.queue import IngestJob, get_ingest_queue, reset_ingest_queue, try_enqueue_job


@pytest.fixture(autouse=True)
def _reset_queue():
    reset_ingest_queue()
    yield
    reset_ingest_queue()


# ---------------------------------------------------------------------------
# queue plumbing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_singleton_roundtrip():
    q1 = get_ingest_queue(maxsize=2)
    q2 = get_ingest_queue()
    assert q1 is q2

    await q1.put(IngestJob(ingest_id="i1", user_id="u", project_id="p"))
    job = await q2.get()
    assert job.ingest_id == "i1"


def test_queue_maxsize_applied_on_first_init():
    queue = get_ingest_queue(maxsize=2)
    assert queue.maxsize == 2


def test_try_enqueue_job_returns_false_when_full():
    queue = get_ingest_queue(maxsize=1)
    assert try_enqueue_job(IngestJob(ingest_id="i1", user_id="u", project_id="p"), maxsize=1) is True
    assert queue.qsize() == 1
    assert try_enqueue_job(IngestJob(ingest_id="i2", user_id="u", project_id="p"), maxsize=1) is False


# ---------------------------------------------------------------------------
# extraction prompt shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_memories_parses_gemma_output():
    from piloci.curator import worker as w

    gemma_payload = {
        "memories": [
            {"content": "user prefers dark mode", "tags": ["ui"], "category": "preference"},
            {"content": "", "tags": []},  # should be filtered (empty content)
        ]
    }

    with patch.object(w, "chat_json", AsyncMock(return_value=gemma_payload)):
        settings = type("S", (), {
            "gemma_endpoint": "x",
            "gemma_model": "x",
        })()
        transcript = [{"role": "user", "content": "I like dark mode"}]
        result = await w._extract_memories(transcript, settings)

    assert len(result) == 2  # extractor returns raw list; caller filters empties
    assert result[0]["content"] == "user prefers dark mode"


def test_shorten_transcript_truncates_large_input():
    from piloci.curator.worker import _shorten_transcript

    long_msg = "x" * 20_000
    transcript = [{"role": "user", "content": long_msg}]
    result = _shorten_transcript(transcript, max_chars=1000)
    assert "truncated" in result
    assert len(result) <= 1100  # allow small overhead


def test_shorten_transcript_handles_list_content():
    from piloci.curator.worker import _shorten_transcript

    transcript = [
        {"role": "assistant", "content": [{"type": "text", "text": "hello"}, {"text": "world"}]}
    ]
    result = _shorten_transcript(transcript)
    assert "hello" in result
    assert "world" in result


# ---------------------------------------------------------------------------
# dedup check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_duplicate_returns_true_when_similar():
    from piloci.curator.worker import _is_duplicate

    store = AsyncMock()
    store.search.return_value = [{"score": 0.97}]
    assert await _is_duplicate(store, "u", "p", [0.1] * 384) is True


@pytest.mark.asyncio
async def test_is_duplicate_returns_false_when_below_threshold():
    from piloci.curator.worker import _is_duplicate

    store = AsyncMock()
    store.search.return_value = [{"score": 0.5}]
    assert await _is_duplicate(store, "u", "p", [0.1] * 384) is False


@pytest.mark.asyncio
async def test_is_duplicate_returns_false_when_empty():
    from piloci.curator.worker import _is_duplicate

    store = AsyncMock()
    store.search.return_value = []
    assert await _is_duplicate(store, "u", "p", [0.1] * 384) is False
