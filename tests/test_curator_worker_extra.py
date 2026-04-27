from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from piloci.curator import worker as worker_module
from piloci.curator.queue import IngestJob, reset_ingest_queue


def _session_cm(session: MagicMock) -> AsyncMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.fixture(autouse=True)
def _reset_queue():
    reset_ingest_queue()
    yield
    reset_ingest_queue()


def _session_factory(*sessions: MagicMock):
    iterator = iter(sessions)
    return MagicMock(side_effect=lambda: _session_cm(next(iterator)))


def test_cosine_similarity_handles_mismatch_and_zero_vectors():
    assert worker_module._cosine_similarity([1.0, 0.0], [1.0]) == 0.0
    assert worker_module._cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_is_duplicate_in_batch_uses_similarity_threshold():
    accepted = [[1.0, 0.0], [0.0, 1.0]]

    assert worker_module._is_duplicate_in_batch([1.0, 0.0], accepted) is True
    assert worker_module._is_duplicate_in_batch([0.7, 0.7], accepted) is False


@pytest.mark.asyncio
async def test_process_job_returns_when_raw_session_missing(monkeypatch, settings, mock_store):
    job = IngestJob(ingest_id="missing", user_id="u1", project_id="p1")
    db = MagicMock()
    db.get = AsyncMock(return_value=None)

    monkeypatch.setattr(worker_module, "async_session", MagicMock(return_value=_session_cm(db)))

    await worker_module._process_job(job, settings, mock_store)

    mock_store.save_many.assert_not_awaited()
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_process_job_extraction_failure_updates_raw_session_error(
    monkeypatch, settings, mock_store
):
    job = IngestJob(ingest_id="i-fail", user_id="u1", project_id="p1")
    read_db = MagicMock()
    read_db.get = AsyncMock(
        return_value=SimpleNamespace(transcript_json='[{"role": "user", "content": "hello"}]')
    )
    write_db = MagicMock()
    write_db.execute = AsyncMock()
    write_db.commit = AsyncMock()

    monkeypatch.setattr(
        worker_module,
        "async_session",
        _session_factory(read_db, write_db),
    )
    monkeypatch.setattr(
        worker_module,
        "_extract_memories",
        AsyncMock(side_effect=RuntimeError("x" * 600)),
    )

    await worker_module._process_job(job, settings, mock_store)

    mock_store.save_many.assert_not_awaited()
    write_db.execute.assert_awaited_once()
    write_db.commit.assert_awaited_once()
    stmt = write_db.execute.await_args.args[0]
    params = stmt.compile().params
    assert params["ingest_id_1"] == "i-fail"
    assert len(params["error"]) == 500


@pytest.mark.asyncio
async def test_process_job_updates_processed_status_even_when_save_fails(
    monkeypatch, settings, mock_store
):
    job = IngestJob(ingest_id="i-save", user_id="u1", project_id="p1")
    read_db = MagicMock()
    read_db.get = AsyncMock(
        return_value=SimpleNamespace(transcript_json='[{"role": "user", "content": "hello"}]')
    )
    write_db = MagicMock()
    write_db.execute = AsyncMock()
    write_db.commit = AsyncMock()

    monkeypatch.setattr(
        worker_module,
        "async_session",
        _session_factory(read_db, write_db),
    )
    monkeypatch.setattr(
        worker_module,
        "_extract_memories",
        AsyncMock(return_value=[{"content": "memory", "tags": ["a"], "category": "fact"}]),
    )
    monkeypatch.setattr(worker_module, "embed_texts", AsyncMock(return_value=[[1.0, 0.0]]))
    monkeypatch.setattr(worker_module, "_is_duplicate", AsyncMock(return_value=False))
    invalidate = AsyncMock()
    monkeypatch.setattr(worker_module, "invalidate_project_vault_cache", invalidate)
    mock_store.save_many.side_effect = RuntimeError("disk full")

    await worker_module._process_job(job, settings, mock_store)

    mock_store.save_many.assert_awaited_once()
    invalidate.assert_not_awaited()
    write_db.execute.assert_awaited_once()
    write_db.commit.assert_awaited_once()
    stmt = write_db.execute.await_args.args[0]
    params = stmt.compile().params
    assert params["ingest_id_1"] == "i-save"
    assert params["memories_extracted"] == 0
    assert params["processed_at"] is not None


@pytest.mark.asyncio
async def test_process_job_handles_dedup_check_exception_and_saves_remaining(
    monkeypatch, settings, mock_store
):
    job = IngestJob(ingest_id="i-dedup", user_id="u1", project_id="p1")
    read_db = MagicMock()
    read_db.get = AsyncMock(
        return_value=SimpleNamespace(transcript_json='[{"role": "user", "content": "hello"}]')
    )
    write_db = MagicMock()
    write_db.execute = AsyncMock()
    write_db.commit = AsyncMock()

    monkeypatch.setattr(
        worker_module,
        "async_session",
        _session_factory(read_db, write_db),
    )
    monkeypatch.setattr(
        worker_module,
        "_extract_memories",
        AsyncMock(
            return_value=[
                {"content": "keep one", "tags": [], "category": "fact"},
                {"content": "drop two", "tags": [], "category": "fact"},
            ]
        ),
    )
    monkeypatch.setattr(
        worker_module,
        "embed_texts",
        AsyncMock(return_value=[[1.0, 0.0], [0.0, 1.0]]),
    )
    monkeypatch.setattr(
        worker_module,
        "_is_duplicate",
        AsyncMock(side_effect=[False, RuntimeError("search failed")]),
    )
    invalidate = AsyncMock()
    monkeypatch.setattr(worker_module, "invalidate_project_vault_cache", invalidate)
    mock_store.save_many.return_value = ["m1"]

    await worker_module._process_job(job, settings, mock_store)

    mock_store.save_many.assert_awaited_once()
    assert mock_store.save_many.await_args.kwargs["memories"] == [
        {"content": "keep one", "vector": [1.0, 0.0], "tags": ["fact"]}
    ]
    invalidate.assert_awaited_once_with(settings.vault_dir, "u1", "p1")


@pytest.mark.asyncio
async def test_run_worker_processes_one_job_and_marks_task_done(monkeypatch, settings):
    queue: asyncio.Queue[IngestJob] = asyncio.Queue()
    job = IngestJob(ingest_id="i1", user_id="u1", project_id="p1")
    await queue.put(job)
    stop_event = asyncio.Event()

    async def process_once(received_job, received_settings, received_store):
        assert received_job == job
        stop_event.set()

    process = AsyncMock(side_effect=process_once)

    monkeypatch.setattr(worker_module, "get_ingest_queue", MagicMock(return_value=queue))
    monkeypatch.setattr(worker_module, "_process_job", process)
    settings.curator_queue_poll_timeout_sec = 0.01

    await worker_module.run_worker(settings, MagicMock(), stop_event)

    process.assert_awaited_once()
    assert queue.qsize() == 0


@pytest.mark.asyncio
async def test_run_worker_continues_after_empty_poll_until_stopped(monkeypatch, settings):
    stop_event = asyncio.Event()
    queue = MagicMock()
    process = AsyncMock()
    calls = {"count": 0}

    async def fake_wait_for(awaitable, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise asyncio.TimeoutError
        stop_event.set()
        return IngestJob(ingest_id="i2", user_id="u2", project_id="p2")

    monkeypatch.setattr(worker_module, "get_ingest_queue", MagicMock(return_value=queue))
    monkeypatch.setattr(worker_module, "_process_job", process)
    monkeypatch.setattr(worker_module.asyncio, "wait_for", fake_wait_for)
    settings.curator_queue_poll_timeout_sec = 0.01

    await worker_module.run_worker(settings, MagicMock(), stop_event)

    process.assert_awaited_once()
    queue.task_done.assert_called_once()


@pytest.mark.asyncio
async def test_run_worker_exits_immediately_when_stop_event_is_already_set(settings):
    stop_event = asyncio.Event()
    stop_event.set()

    await worker_module.run_worker(settings, MagicMock(), stop_event)


@pytest.mark.asyncio
async def test_process_unfinished_requeues_unprocessed_rows(monkeypatch, settings):
    rows = [
        SimpleNamespace(ingest_id="i1", user_id="u1", project_id="p1"),
        SimpleNamespace(ingest_id="i2", user_id="u2", project_id="p2"),
        SimpleNamespace(ingest_id="i3", user_id="u3", project_id=None),
    ]
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))
    )
    enqueue = MagicMock(side_effect=[True, True])

    monkeypatch.setattr(worker_module, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(worker_module, "try_enqueue_job", enqueue)

    requeued = await worker_module.process_unfinished(settings, MagicMock())

    assert requeued == 2
    assert enqueue.call_count == 2
    first_job = enqueue.call_args_list[0].args[0]
    second_job = enqueue.call_args_list[1].args[0]
    assert first_job == IngestJob(ingest_id="i1", user_id="u1", project_id="p1")
    assert second_job == IngestJob(ingest_id="i2", user_id="u2", project_id="p2")
