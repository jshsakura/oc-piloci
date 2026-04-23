from __future__ import annotations
import asyncio
import logging
from functools import partial

from piloci.storage.cache import EmbeddingCache

logger = logging.getLogger(__name__)

_embedder = None
_cache: EmbeddingCache | None = None


def _get_embedder(model: str, cache_dir: str | None):
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        kwargs: dict = {"model_name": model}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        logger.info("Loading embedding model %s", model)
        _embedder = TextEmbedding(**kwargs)
        logger.info("Embedding model loaded")
    return _embedder


def get_cache(maxsize: int = 1000) -> EmbeddingCache:
    global _cache
    if _cache is None:
        _cache = EmbeddingCache(maxsize=maxsize)
    return _cache


def _embed_sync(texts: list[str], model: str, cache_dir: str | None) -> list[list[float]]:
    """Run in executor — blocking fastembed call."""
    embedder = _get_embedder(model, cache_dir)
    return [v.tolist() for v in embedder.embed(texts)]


async def embed_texts(
    texts: list[str],
    model: str = "BAAI/bge-small-en-v1.5",
    cache_dir: str | None = None,
    lru_size: int = 1000,
) -> list[list[float]]:
    """Embed a list of texts. Cached results skip the model call."""
    cache = get_cache(lru_size)
    results: list[list[float] | None] = [cache.get(t) for t in texts]
    missing_idx = [i for i, r in enumerate(results) if r is None]

    if missing_idx:
        missing_texts = [texts[i] for i in missing_idx]
        loop = asyncio.get_event_loop()
        new_vectors = await loop.run_in_executor(
            None, partial(_embed_sync, missing_texts, model, cache_dir)
        )
        for i, vec in zip(missing_idx, new_vectors):
            cache.set(texts[i], vec)
            results[i] = vec

    return results  # type: ignore[return-value]


async def embed_one(
    text: str,
    model: str = "BAAI/bge-small-en-v1.5",
    cache_dir: str | None = None,
    lru_size: int = 1000,
) -> list[float]:
    vectors = await embed_texts([text], model=model, cache_dir=cache_dir, lru_size=lru_size)
    return vectors[0]
