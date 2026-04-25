from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from piloci.config import get_settings
from piloci.storage.cache import EmbeddingCache
from piloci.utils.logging import get_runtime_profiler

logger = logging.getLogger(__name__)

_embedder = None
_cache: EmbeddingCache | None = None
_embed_executor: ThreadPoolExecutor | None = None
_embed_executor_workers: int | None = None
_embed_semaphore: asyncio.Semaphore | None = None
_embed_semaphore_limit: int | None = None


def _get_embedder(model: str, cache_dir: str | None):
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        logger.info("Loading embedding model %s", model)
        if cache_dir:
            _embedder = TextEmbedding(model_name=model, cache_dir=cache_dir)
        else:
            _embedder = TextEmbedding(model_name=model)
        logger.info("Embedding model loaded")
    return _embedder


def get_cache(maxsize: int = 1000) -> EmbeddingCache:
    global _cache
    if _cache is None:
        _cache = EmbeddingCache(maxsize=maxsize)
    return _cache


def _get_embed_executor(max_workers: int) -> ThreadPoolExecutor:
    global _embed_executor, _embed_executor_workers
    if max_workers < 1:
        raise ValueError("embed executor workers must be >= 1")
    if _embed_executor is None or _embed_executor_workers != max_workers:
        if _embed_executor is not None:
            _embed_executor.shutdown(wait=False, cancel_futures=False)
        _embed_executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="piloci-embed",
        )
        _embed_executor_workers = max_workers
    return _embed_executor


def _get_embed_semaphore(limit: int) -> asyncio.Semaphore:
    global _embed_semaphore, _embed_semaphore_limit
    if limit < 1:
        raise ValueError("embed max concurrency must be >= 1")
    if _embed_semaphore is None or _embed_semaphore_limit != limit:
        _embed_semaphore = asyncio.Semaphore(limit)
        _embed_semaphore_limit = limit
    return _embed_semaphore


def reset_embed_runtime() -> None:
    global _cache, _embed_executor, _embed_executor_workers, _embed_semaphore, _embed_semaphore_limit
    _cache = None
    if _embed_executor is not None:
        _embed_executor.shutdown(wait=False, cancel_futures=False)
    _embed_executor = None
    _embed_executor_workers = None
    _embed_semaphore = None
    _embed_semaphore_limit = None


def _embed_sync(texts: list[str], model: str, cache_dir: str | None) -> list[list[float]]:
    """Run in executor — blocking fastembed call."""
    embedder = _get_embedder(model, cache_dir)
    return [v.tolist() for v in embedder.embed(texts)]


async def embed_texts(
    texts: list[str],
    model: str = "BAAI/bge-small-en-v1.5",
    cache_dir: str | None = None,
    lru_size: int = 1000,
    executor_workers: int | None = None,
    max_concurrency: int | None = None,
) -> list[list[float]]:
    """Embed a list of texts. Cached results skip the model call."""
    settings = get_settings()
    worker_count = executor_workers or getattr(settings, "embed_executor_workers", 1)
    concurrency_limit = max_concurrency or getattr(settings, "embed_max_concurrency", 1)

    cache = get_cache(lru_size)
    results: list[list[float] | None] = [cache.get(t) for t in texts]
    missing_idx = [i for i, r in enumerate(results) if r is None]

    if missing_idx:
        missing_texts = [texts[i] for i in missing_idx]
        loop = asyncio.get_event_loop()
        executor = _get_embed_executor(worker_count)
        semaphore = _get_embed_semaphore(concurrency_limit)
        async with semaphore:
            with get_runtime_profiler().track("embed_texts"):
                new_vectors = await loop.run_in_executor(
                    executor, partial(_embed_sync, missing_texts, model, cache_dir)
                )
        for i, vec in zip(missing_idx, new_vectors, strict=True):
            cache.set(texts[i], vec)
            results[i] = vec

    if any(vec is None for vec in results):
        raise RuntimeError("embedding results incomplete")
    return [vec for vec in results if vec is not None]


async def embed_one(
    text: str,
    model: str = "BAAI/bge-small-en-v1.5",
    cache_dir: str | None = None,
    lru_size: int = 1000,
    executor_workers: int | None = None,
    max_concurrency: int | None = None,
) -> list[float]:
    vectors = await embed_texts(
        [text],
        model=model,
        cache_dir=cache_dir,
        lru_size=lru_size,
        executor_workers=executor_workers,
        max_concurrency=max_concurrency,
    )
    return vectors[0]
