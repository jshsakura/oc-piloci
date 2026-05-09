import os
from unittest.mock import AsyncMock

import pytest

from piloci.config import Settings
from piloci.storage.lancedb_store import MemoryStore

# Ensure every test session has valid secrets even when .env is absent (CI).
_VALID_SECRET = "test-secret-32-characters-minimum!"


@pytest.fixture(autouse=True, scope="session")
def _set_secret_env_vars():
    for key in ("JWT_SECRET", "SESSION_SECRET"):
        os.environ.setdefault(key, _VALID_SECRET)
    yield


@pytest.fixture
def settings(tmp_path):
    return Settings(
        lancedb_path=tmp_path / "lancedb",
        embed_model="BAAI/bge-small-en-v1.5",
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
    )


@pytest.fixture
def mock_store():
    store = AsyncMock(spec=MemoryStore)
    store.save.return_value = "test-memory-id"
    store.save_many.return_value = ["test-memory-id"]
    store.search.return_value = []
    store.hybrid_search.return_value = []
    store.count.return_value = 0
    store.get.return_value = None
    store.list.return_value = []
    store.update.return_value = True
    store.delete.return_value = True
    store.clear_project.return_value = 0
    return store


@pytest.fixture
async def mock_embed():
    async def _embed(text: str) -> list[float]:
        return [0.1] * 384

    return _embed


@pytest.fixture
async def lancedb_store(tmp_path):
    s = Settings(
        lancedb_path=tmp_path / "lancedb",
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
    )
    store = MemoryStore(s)
    await store.ensure_collection()
    yield store
    await store.close()
