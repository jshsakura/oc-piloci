"""Tests for Gemma curator worker with mocked Gemma responses."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from piloci.curator.queue import IngestJob, get_ingest_queue, reset_ingest_queue, try_enqueue_job


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.get = AsyncMock()
        self.execute = AsyncMock()
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


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
    assert (
        try_enqueue_job(IngestJob(ingest_id="i1", user_id="u", project_id="p"), maxsize=1) is True
    )
    assert queue.qsize() == 1
    assert (
        try_enqueue_job(IngestJob(ingest_id="i2", user_id="u", project_id="p"), maxsize=1) is False
    )


# ---------------------------------------------------------------------------
# extraction prompt shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_memories_parses_gemma_output(settings):
    from piloci.curator import worker as w

    gemma_payload = {
        "memories": [
            {"content": "user prefers dark mode", "tags": ["ui"], "category": "preference"},
            {"content": "", "tags": []},  # should be filtered (empty content)
        ]
    }

    with patch.object(w, "chat_json", AsyncMock(return_value=gemma_payload)):
        transcript: list[dict[str, Any]] = [{"role": "user", "content": "I like dark mode"}]
        result = await w._extract_memories(transcript, settings)

    assert len(result) == 2  # extractor returns raw list; caller filters empties
    assert result[0]["content"] == "user prefers dark mode"


def test_shorten_transcript_truncates_large_input():
    from piloci.curator.worker import _shorten_transcript

    long_msg = "x" * 20_000
    transcript: list[dict[str, Any]] = [{"role": "user", "content": long_msg}]
    result = _shorten_transcript(transcript, max_chars=1000)
    assert "truncated" in result
    assert len(result) <= 1100  # allow small overhead


def test_shorten_transcript_handles_list_content():
    from piloci.curator.worker import _shorten_transcript

    transcript: list[dict[str, Any]] = [
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


@pytest.mark.asyncio
async def test_process_job_batches_embedding_and_saves(settings, mock_store):
    from piloci.curator import worker as w

    job = IngestJob(ingest_id="i1", user_id="u1", project_id="p1")
    fake_db = _FakeAsyncSession()
    fake_db.get.return_value = SimpleNamespace(
        transcript_json='[{"role": "user", "content": "hello"}]'
    )
    first_vector = [1.0, *([0.0] * 383)]
    second_vector = [0.0, 1.0, *([0.0] * 382)]

    with (
        patch.object(
            w,
            "_extract_memories",
            AsyncMock(
                return_value=[
                    {"content": " first memory ", "tags": ["a"], "category": "fact"},
                    {"content": "second memory", "tags": ["b"], "category": "decision"},
                    {"content": "   ", "tags": [], "category": "fact"},
                ]
            ),
        ),
        patch.object(
            w, "embed_texts", AsyncMock(return_value=[first_vector, second_vector])
        ) as embed_mock,
        patch.object(w, "_is_duplicate", AsyncMock(side_effect=[False, False])),
        patch.object(w, "async_session", return_value=fake_db),
        patch.object(w, "invalidate_project_vault_cache", AsyncMock()) as invalidate_mock,
    ):
        mock_store.save_many.return_value = ["m1", "m2"]
        await w._process_job(job, settings, mock_store)

    embed_mock.assert_awaited_once()
    await_args = embed_mock.await_args
    assert await_args is not None
    assert await_args.args[0] == ["first memory", "second memory"]
    mock_store.save.assert_not_awaited()
    mock_store.save_many.assert_awaited_once()
    save_call = mock_store.save_many.await_args.kwargs
    assert save_call["user_id"] == "u1"
    assert save_call["project_id"] == "p1"
    assert save_call["memories"] == [
        {"content": "first memory", "vector": first_vector, "tags": ["a", "fact"]},
        {"content": "second memory", "vector": second_vector, "tags": ["b", "decision"]},
    ]
    invalidate_mock.assert_awaited_once_with(settings.vault_dir, "u1", "p1")


@pytest.mark.asyncio
async def test_process_job_skips_duplicate_but_invalidates_after_save(settings, mock_store):
    from piloci.curator import worker as w

    job = IngestJob(ingest_id="i2", user_id="u1", project_id="p1")
    fake_db = _FakeAsyncSession()
    fake_db.get.return_value = SimpleNamespace(
        transcript_json='[{"role": "user", "content": "hello"}]'
    )

    with (
        patch.object(
            w,
            "_extract_memories",
            AsyncMock(
                return_value=[
                    {"content": "keep me", "tags": [], "category": "fact"},
                    {"content": "drop me", "tags": [], "category": "fact"},
                ]
            ),
        ),
        patch.object(w, "embed_texts", AsyncMock(return_value=[[0.1] * 384, [0.2] * 384])),
        patch.object(w, "_is_duplicate", AsyncMock(side_effect=[False, True])),
        patch.object(w, "async_session", return_value=fake_db),
        patch.object(w, "invalidate_project_vault_cache", AsyncMock()) as invalidate_mock,
    ):
        mock_store.save_many.return_value = ["m1"]
        await w._process_job(job, settings, mock_store)

    mock_store.save.assert_not_awaited()
    mock_store.save_many.assert_awaited_once()
    assert mock_store.save_many.await_args.kwargs["memories"] == [
        {"content": "keep me", "vector": [0.1] * 384, "tags": ["fact"]}
    ]
    invalidate_mock.assert_awaited_once_with(settings.vault_dir, "u1", "p1")


@pytest.mark.asyncio
async def test_process_job_skips_in_batch_vector_duplicate_before_store_search(
    settings, mock_store
):
    from piloci.curator import worker as w

    job = IngestJob(ingest_id="i3", user_id="u1", project_id="p1")
    fake_db = _FakeAsyncSession()
    fake_db.get.return_value = SimpleNamespace(
        transcript_json='[{"role": "user", "content": "hello"}]'
    )
    duplicate_check = AsyncMock(return_value=False)

    with (
        patch.object(
            w,
            "_extract_memories",
            AsyncMock(
                return_value=[
                    {"content": "memory one", "tags": [], "category": "fact"},
                    {"content": "memory one paraphrased", "tags": [], "category": "fact"},
                ]
            ),
        ),
        patch.object(w, "embed_texts", AsyncMock(return_value=[[0.1] * 384, [0.1] * 384])),
        patch.object(w, "_is_duplicate", duplicate_check),
        patch.object(w, "async_session", return_value=fake_db),
        patch.object(w, "invalidate_project_vault_cache", AsyncMock()) as invalidate_mock,
    ):
        mock_store.save_many.return_value = ["m1"]
        await w._process_job(job, settings, mock_store)

    assert duplicate_check.await_count == 1
    mock_store.save_many.assert_awaited_once()
    assert mock_store.save_many.await_args.kwargs["memories"] == [
        {"content": "memory one", "vector": [0.1] * 384, "tags": ["fact"]}
    ]
    invalidate_mock.assert_awaited_once_with(settings.vault_dir, "u1", "p1")
