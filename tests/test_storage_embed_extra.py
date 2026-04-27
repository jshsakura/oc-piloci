from unittest.mock import MagicMock, patch

import pytest

from piloci.storage import embed


@pytest.fixture(autouse=True)
def _reset_globals():
    embed._embedder = None
    embed._cache = None
    embed._embed_executor = None
    embed._embed_executor_workers = None
    embed._embed_semaphore = None
    embed._embed_semaphore_limit = None
    yield
    embed.reset_embed_runtime()


class TestGetCache:
    def test_creates_cache(self):
        cache = embed.get_cache(500)
        assert cache is not None

    def test_returns_same_instance(self):
        c1 = embed.get_cache(500)
        c2 = embed.get_cache(500)
        assert c1 is c2


class TestGetEmbedExecutor:
    def test_creates_executor(self):
        executor = embed._get_embed_executor(2)
        assert executor is not None
        assert executor._max_workers == 2

    def test_raises_on_zero_workers(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            embed._get_embed_executor(0)

    def test_recreates_on_different_workers(self):
        e1 = embed._get_embed_executor(1)
        e2 = embed._get_embed_executor(4)
        assert e1 is not e2


class TestGetEmbedSemaphore:
    def test_creates_semaphore(self):
        sem = embed._get_embed_semaphore(3)
        assert sem is not None

    def test_raises_on_zero_limit(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            embed._get_embed_semaphore(0)


class TestResetEmbedRuntime:
    def test_resets_all_globals(self):
        embed._cache = MagicMock()
        embed._embed_executor = MagicMock()
        embed._embed_semaphore = MagicMock()
        embed.reset_embed_runtime()
        assert embed._cache is None
        assert embed._embed_executor is None
        assert embed._embed_semaphore is None


class TestEmbedSync:
    def test_calls_embedder(self):
        mock_vec = MagicMock()
        mock_vec.tolist.return_value = [0.1, 0.2]
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [mock_vec]
        embed._embedder = mock_embedder

        result = embed._embed_sync(["hello"], "model", None)
        assert result == [[0.1, 0.2]]


class TestEmbedTexts:
    @pytest.mark.asyncio
    async def test_all_cached(self):
        mock_cache = MagicMock()
        mock_cache.get.side_effect = lambda t: [0.1] * 10
        embed._cache = mock_cache
        with patch("piloci.storage.embed.get_settings", return_value=MagicMock()):
            result = await embed.embed_texts(["a", "b"], lru_size=10)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_cache_miss_triggers_embed(self):
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()
        embed._cache = mock_cache

        mock_vec = MagicMock()
        mock_vec.tolist.return_value = [0.5] * 10
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [mock_vec]
        embed._embedder = mock_embedder

        with patch(
            "piloci.storage.embed.get_settings",
            return_value=MagicMock(embed_executor_workers=1, embed_max_concurrency=1),
        ):
            result = await embed.embed_texts(["hello"], lru_size=10)
        assert len(result) == 1
        assert result[0] == [0.5] * 10


class TestEmbedOne:
    @pytest.mark.asyncio
    async def test_returns_single_vector(self):
        mock_cache = MagicMock()
        mock_cache.get.return_value = [0.3] * 10
        embed._cache = mock_cache

        with patch("piloci.storage.embed.get_settings", return_value=MagicMock()):
            result = await embed.embed_one("hello", lru_size=10)
        assert result == [0.3] * 10
