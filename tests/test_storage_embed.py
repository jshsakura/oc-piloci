from __future__ import annotations

import asyncio
import threading
import time

import pytest


@pytest.fixture(autouse=True)
def _reset_embed_runtime():
    from piloci.storage.embed import reset_embed_runtime
    from piloci.utils.logging import reset_runtime_profiler

    reset_runtime_profiler()
    reset_embed_runtime()
    yield
    reset_embed_runtime()
    reset_runtime_profiler()


@pytest.mark.asyncio
async def test_embed_texts_uses_dedicated_executor(monkeypatch):
    from piloci.storage import embed as embed_module

    seen = []

    async def fake_run_in_executor(executor, func):
        seen.append(executor)
        return func()

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "run_in_executor", fake_run_in_executor)
    monkeypatch.setattr(embed_module, "_embed_sync", lambda texts, model, cache_dir: [[0.1] for _ in texts])

    vectors = await embed_module.embed_texts(
        ["hello"],
        executor_workers=1,
        max_concurrency=1,
        lru_size=10,
    )

    assert vectors == [[0.1]]
    assert len(seen) == 1
    assert seen[0] is not None


@pytest.mark.asyncio
async def test_embed_texts_respects_max_concurrency(monkeypatch):
    from piloci.storage import embed as embed_module

    active = 0
    max_seen = 0
    lock = threading.Lock()

    def fake_embed_sync(texts, model, cache_dir):
        nonlocal active, max_seen
        with lock:
            active += 1
            max_seen = max(max_seen, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return [[float(len(text))] for text in texts]

    monkeypatch.setattr(embed_module, "_embed_sync", fake_embed_sync)

    await asyncio.gather(
        embed_module.embed_texts(["one"], executor_workers=2, max_concurrency=1, lru_size=10),
        embed_module.embed_texts(["two"], executor_workers=2, max_concurrency=1, lru_size=10),
    )

    assert max_seen == 1


@pytest.mark.asyncio
async def test_embed_texts_cache_hit_skips_profiler_metric(monkeypatch):
    from piloci.storage import embed as embed_module
    from piloci.utils.logging import get_runtime_profiler

    monkeypatch.setattr(embed_module, "_embed_sync", lambda texts, model, cache_dir: [[0.1] for _ in texts])

    await embed_module.embed_texts(["hello"], executor_workers=1, max_concurrency=1, lru_size=10)
    assert get_runtime_profiler().snapshot()["metrics"]["embed_texts"]["count"] == 1

    await embed_module.embed_texts(["hello"], executor_workers=1, max_concurrency=1, lru_size=10)
    assert get_runtime_profiler().snapshot()["metrics"]["embed_texts"]["count"] == 1


@pytest.mark.asyncio
async def test_embed_texts_failure_still_records_profiler_metric(monkeypatch):
    from piloci.storage import embed as embed_module
    from piloci.utils.logging import get_runtime_profiler

    def boom(texts, model, cache_dir):
        raise RuntimeError("embed failed")

    monkeypatch.setattr(embed_module, "_embed_sync", boom)

    with pytest.raises(RuntimeError, match="embed failed"):
        await embed_module.embed_texts(["hello"], executor_workers=1, max_concurrency=1, lru_size=10)

    assert get_runtime_profiler().snapshot()["metrics"]["embed_texts"]["count"] == 1
