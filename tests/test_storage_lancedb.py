"""Integration tests for LanceDB MemoryStore using a real temporary database."""
from __future__ import annotations

import uuid

import pytest

from piloci.storage.lancedb_store import MemoryStore, VECTOR_SIZE
from piloci.utils.logging import get_runtime_profiler, reset_runtime_profiler

_USER = "aaaaaaaa-0000-0000-0000-000000000001"
_PROJECT = "bbbbbbbb-0000-0000-0000-000000000001"
_VECTOR = [0.1] * VECTOR_SIZE


@pytest.fixture(autouse=True)
def _reset_runtime_profiler_fixture():
    reset_runtime_profiler()
    yield
    reset_runtime_profiler()


# ---------------------------------------------------------------------------
# ensure_collection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensure_collection_idempotent(lancedb_store):
    # Calling twice should not raise
    await lancedb_store.ensure_collection()


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_returns_uuid(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "hello world", _VECTOR)
    uuid.UUID(mid)  # raises if invalid
    assert get_runtime_profiler().snapshot()["metrics"]["lancedb.save"]["count"] == 1


@pytest.mark.asyncio
async def test_save_with_tags(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "tagged", _VECTOR, tags=["ai", "notes"])
    record = await lancedb_store.get(_USER, _PROJECT, mid)
    assert record is not None
    assert "ai" in record["tags"]
    assert "notes" in record["tags"]


@pytest.mark.asyncio
async def test_save_with_metadata(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "meta", _VECTOR, metadata={"key": "val"})
    record = await lancedb_store.get(_USER, _PROJECT, mid)
    assert record is not None
    assert record["metadata"]["key"] == "val"


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_returns_none_when_missing(lancedb_store):
    fake_id = str(uuid.uuid4())
    result = await lancedb_store.get(_USER, _PROJECT, fake_id)
    assert result is None
    assert get_runtime_profiler().snapshot()["metrics"]["lancedb.get"]["count"] == 1


@pytest.mark.asyncio
async def test_get_enforces_project_isolation(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "secret", _VECTOR)
    other_project = "proj-cccccccc-0000-0000-0000-000000000002"
    reset_runtime_profiler()
    result = await lancedb_store.get(_USER, other_project, mid)
    assert result is None
    snapshot = get_runtime_profiler().snapshot()["metrics"]
    assert snapshot["lancedb.get"]["count"] == 1


@pytest.mark.asyncio
async def test_get_enforces_user_isolation(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "secret", _VECTOR)
    other_user = "user-dddddddd-0000-0000-0000-000000000002"
    reset_runtime_profiler()
    result = await lancedb_store.get(other_user, _PROJECT, mid)
    assert result is None
    snapshot = get_runtime_profiler().snapshot()["metrics"]
    assert snapshot["lancedb.get"]["count"] == 1


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_returns_only_project_memories(lancedb_store):
    await lancedb_store.save(_USER, _PROJECT, "mem1", _VECTOR)
    await lancedb_store.save(_USER, _PROJECT, "mem2", _VECTOR)
    other = "proj-eeeeeeee-0000-0000-0000-000000000003"
    await lancedb_store.save(_USER, other, "other", _VECTOR)

    results = await lancedb_store.list(_USER, _PROJECT)
    assert len(results) == 2
    assert all(r["project_id"] == _PROJECT for r in results)


@pytest.mark.asyncio
async def test_list_tag_filter(lancedb_store):
    await lancedb_store.save(_USER, _PROJECT, "tagged", _VECTOR, tags=["python"])
    await lancedb_store.save(_USER, _PROJECT, "untagged", _VECTOR)

    results = await lancedb_store.list(_USER, _PROJECT, tags=["python"])
    assert len(results) == 1
    assert results[0]["content"] == "tagged"
    assert get_runtime_profiler().snapshot()["metrics"]["lancedb.list"]["count"] == 1


@pytest.mark.asyncio
async def test_list_pagination(lancedb_store):
    for i in range(5):
        await lancedb_store.save(_USER, _PROJECT, f"mem{i}", _VECTOR)

    page1 = await lancedb_store.list(_USER, _PROJECT, limit=3, offset=0)
    page2 = await lancedb_store.list(_USER, _PROJECT, limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 2


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_returns_false_when_missing(lancedb_store):
    result = await lancedb_store.update(_USER, _PROJECT, str(uuid.uuid4()), content="new")
    assert result is False
    assert get_runtime_profiler().snapshot()["metrics"]["lancedb.update"]["count"] == 1


@pytest.mark.asyncio
async def test_update_content(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "original", _VECTOR)
    reset_runtime_profiler()
    result = await lancedb_store.update(_USER, _PROJECT, mid, content="updated")
    assert result is True
    snapshot = get_runtime_profiler().snapshot()["metrics"]
    assert snapshot["lancedb.update"]["count"] == 1
    assert "lancedb.get" not in snapshot
    record = await lancedb_store.get(_USER, _PROJECT, mid)
    assert record is not None
    assert record["content"] == "updated"


@pytest.mark.asyncio
async def test_update_tags(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "content", _VECTOR, tags=["old"])
    await lancedb_store.update(_USER, _PROJECT, mid, tags=["new"])
    record = await lancedb_store.get(_USER, _PROJECT, mid)
    assert record is not None
    assert record["tags"] == ["new"]


@pytest.mark.asyncio
async def test_update_with_new_vector(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "vec", _VECTOR)
    new_vec = [0.9] * VECTOR_SIZE
    result = await lancedb_store.update(_USER, _PROJECT, mid, content="updated vec", new_vector=new_vec)
    assert result is True
    record = await lancedb_store.get(_USER, _PROJECT, mid)
    assert record is not None
    assert record["content"] == "updated vec"


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_returns_false_when_missing(lancedb_store):
    result = await lancedb_store.delete(_USER, _PROJECT, str(uuid.uuid4()))
    assert result is False
    assert get_runtime_profiler().snapshot()["metrics"]["lancedb.delete"]["count"] == 1


@pytest.mark.asyncio
async def test_delete_removes_record(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "to delete", _VECTOR)
    reset_runtime_profiler()
    result = await lancedb_store.delete(_USER, _PROJECT, mid)
    assert result is True
    assert await lancedb_store.get(_USER, _PROJECT, mid) is None
    assert get_runtime_profiler().snapshot()["metrics"]["lancedb.delete"]["count"] == 1


@pytest.mark.asyncio
async def test_delete_existing_does_not_profile_get(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "to delete", _VECTOR)
    reset_runtime_profiler()

    result = await lancedb_store.delete(_USER, _PROJECT, mid)

    assert result is True
    snapshot = get_runtime_profiler().snapshot()["metrics"]
    assert snapshot["lancedb.delete"]["count"] == 1
    assert "lancedb.get" not in snapshot


@pytest.mark.asyncio
async def test_delete_enforces_isolation(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "protected", _VECTOR)
    other_project = "proj-ffffffff-0000-0000-0000-000000000004"
    result = await lancedb_store.delete(_USER, other_project, mid)
    assert result is False
    # Original still exists
    assert await lancedb_store.get(_USER, _PROJECT, mid) is not None


# ---------------------------------------------------------------------------
# clear_project
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clear_project_removes_all(lancedb_store):
    for _ in range(3):
        await lancedb_store.save(_USER, _PROJECT, "mem", _VECTOR)
    reset_runtime_profiler()
    count = await lancedb_store.clear_project(_USER, _PROJECT)
    assert count == 3
    remaining = await lancedb_store.list(_USER, _PROJECT)
    assert remaining == []
    assert get_runtime_profiler().snapshot()["metrics"]["lancedb.clear_project"]["count"] == 1


@pytest.mark.asyncio
async def test_clear_project_does_not_touch_other_projects(lancedb_store):
    other = "proj-11111111-0000-0000-0000-000000000005"
    await lancedb_store.save(_USER, _PROJECT, "mine", _VECTOR)
    await lancedb_store.save(_USER, other, "theirs", _VECTOR)

    reset_runtime_profiler()
    await lancedb_store.clear_project(_USER, _PROJECT)

    assert await lancedb_store.list(_USER, other) != []
    assert get_runtime_profiler().snapshot()["metrics"]["lancedb.clear_project"]["count"] == 1


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_returns_results(lancedb_store):
    await lancedb_store.save(_USER, _PROJECT, "searchable", _VECTOR)
    results = await lancedb_store.search(_USER, _PROJECT, _VECTOR, top_k=5)
    assert len(results) >= 1
    assert "score" in results[0]
    assert 0.0 <= results[0]["score"] <= 1.0
    assert get_runtime_profiler().snapshot()["metrics"]["lancedb.search"]["count"] == 1


@pytest.mark.asyncio
async def test_get_isolation_still_records_profiler_metric(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "secret", _VECTOR)
    reset_runtime_profiler()

    result = await lancedb_store.get("other-user", _PROJECT, mid)

    assert result is None
    assert get_runtime_profiler().snapshot()["metrics"]["lancedb.get"]["count"] == 1


@pytest.mark.asyncio
async def test_search_isolation(lancedb_store):
    other = "proj-22222222-0000-0000-0000-000000000006"
    await lancedb_store.save(_USER, other, "invisible", _VECTOR)
    results = await lancedb_store.search(_USER, _PROJECT, _VECTOR, top_k=5)
    ids = [r["id"] for r in results]
    other_mems = await lancedb_store.list(_USER, other)
    for m in other_mems:
        assert m["id"] not in ids
