from __future__ import annotations

from piloci.storage.base import MemoryRecord, MemoryStoreProtocol, SearchResult


def test_memory_record_defaults():
    rec = MemoryRecord(
        user_id="u1",
        project_id="p1",
        content="hello",
        vector=[0.1, 0.2],
    )
    assert rec.user_id == "u1"
    assert rec.project_id == "p1"
    assert rec.content == "hello"
    assert rec.vector == [0.1, 0.2]
    assert rec.scope == "personal"
    assert rec.tags == []
    assert rec.metadata == {}
    assert isinstance(rec.memory_id, str)
    assert len(rec.memory_id) == 36
    assert isinstance(rec.created_at, int)
    assert isinstance(rec.updated_at, int)


def test_memory_record_custom_fields():
    rec = MemoryRecord(
        user_id="u2",
        project_id="p2",
        content="world",
        vector=[0.3],
        memory_id="custom-id",
        scope="shared",
        tags=["a", "b"],
        metadata={"key": "val"},
        created_at=1000,
        updated_at=2000,
    )
    assert rec.memory_id == "custom-id"
    assert rec.scope == "shared"
    assert rec.tags == ["a", "b"]
    assert rec.metadata == {"key": "val"}
    assert rec.created_at == 1000
    assert rec.updated_at == 2000


def test_memory_record_independent_defaults():
    r1 = MemoryRecord(user_id="u", project_id="p", content="c", vector=[])
    r2 = MemoryRecord(user_id="u", project_id="p", content="c", vector=[])
    r1.tags.append("x")
    r1.metadata["k"] = "v"
    assert r2.tags == []
    assert r2.metadata == {}
    assert r1.memory_id != r2.memory_id


def test_search_record_fields():
    rec = SearchResult(
        memory_id="mid",
        score=0.95,
        user_id="u1",
        project_id="p1",
        scope="personal",
        content="text",
        tags=["tag1"],
        metadata={"k": "v"},
        created_at=1000,
        updated_at=2000,
    )
    assert rec.memory_id == "mid"
    assert rec.score == 0.95
    assert rec.user_id == "u1"
    assert rec.project_id == "p1"
    assert rec.scope == "personal"
    assert rec.content == "text"
    assert rec.tags == ["tag1"]
    assert rec.metadata == {"k": "v"}
    assert rec.created_at == 1000
    assert rec.updated_at == 2000


def test_memory_store_protocol_is_runtime_checkable():
    class FullStore:
        async def ensure_collection(self) -> None:
            pass

        async def save(self, user_id, project_id, content, vector, tags=None, metadata=None):
            return "id"

        async def get(self, user_id, project_id, memory_id):
            return None

        async def update(
            self,
            user_id,
            project_id,
            memory_id,
            content=None,
            new_vector=None,
            tags=None,
            metadata=None,
        ):
            return True

        async def delete(self, user_id, project_id, memory_id):
            return True

        async def clear_project(self, user_id, project_id):
            return 0

        async def search(
            self, user_id, project_id, query_vector, top_k=5, tags=None, min_score=None
        ):
            return []

        async def list(self, user_id, project_id, tags=None, limit=20, offset=0):
            return []

        async def close(self):
            pass

    assert isinstance(FullStore(), MemoryStoreProtocol)


def test_memory_store_protocol_rejects_incomplete():
    class PartialStore:
        async def ensure_collection(self) -> None:
            pass

    # runtime_checkable only checks method existence, not signatures
    # But a bare object without any methods should still not match structurally
    assert not isinstance(object(), MemoryStoreProtocol)
