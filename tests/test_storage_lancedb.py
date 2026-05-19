"""Integration tests for LanceDB MemoryStore using a real temporary database."""

from __future__ import annotations

import uuid

import pytest

from piloci.config import Settings
from piloci.storage.lancedb_store import VECTOR_SIZE, MemoryStore, _row_to_dict
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


@pytest.mark.asyncio
async def test_save_many_inserts_batch_with_single_profile_sample(lancedb_store):
    ids = await lancedb_store.save_many(
        _USER,
        _PROJECT,
        [
            {"content": "first", "vector": _VECTOR, "tags": ["a"]},
            {"content": "second", "vector": [0.2] * VECTOR_SIZE, "metadata": {"source": "test"}},
        ],
    )

    assert len(ids) == 2
    assert ids[0] != ids[1]
    first = await lancedb_store.get(_USER, _PROJECT, ids[0])
    second = await lancedb_store.get(_USER, _PROJECT, ids[1])
    assert first is not None
    assert second is not None
    assert first["content"] == "first"
    assert first["tags"] == ["a"]
    assert second["content"] == "second"
    assert second["metadata"] == {"source": "test"}
    assert get_runtime_profiler().snapshot()["metrics"]["lancedb.save"]["count"] == 1


def test_row_to_dict_parses_metadata_bytes():
    record = _row_to_dict(
        {
            "memory_id": "mem-1",
            "user_id": _USER,
            "project_id": _PROJECT,
            "content": "meta bytes",
            "tags": ["meta"],
            "metadata": b'{"key":"val"}',
            "created_at": 1,
            "updated_at": 2,
        }
    )

    assert record["metadata"] == {"key": "val"}


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
async def test_list_rejects_unsafe_tag_filter(lancedb_store):
    await lancedb_store.save(_USER, _PROJECT, "tagged", _VECTOR, tags=["safe"])

    with pytest.raises(ValueError):
        await lancedb_store.list(_USER, _PROJECT, tags=["bad'tag"])


@pytest.mark.asyncio
async def test_save_many_rejects_unsafe_user_id(lancedb_store):
    with pytest.raises(ValueError):
        await lancedb_store.save_many(
            "bad'user",
            _PROJECT,
            [{"content": "bad", "vector": _VECTOR}],
        )


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
async def test_update_metadata_merges_existing_metadata(lancedb_store):
    mid = await lancedb_store.save(
        _USER,
        _PROJECT,
        "content",
        _VECTOR,
        metadata={"existing": "kept", "changed": "old"},
    )

    result = await lancedb_store.update(
        _USER,
        _PROJECT,
        mid,
        metadata={"changed": "new", "added": "value"},
    )

    assert result is True
    record = await lancedb_store.get(_USER, _PROJECT, mid)
    assert record is not None
    assert record["metadata"] == {
        "existing": "kept",
        "changed": "new",
        "added": "value",
    }


@pytest.mark.asyncio
async def test_update_with_new_vector(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "vec", _VECTOR)
    new_vec = [0.9] * VECTOR_SIZE
    result = await lancedb_store.update(
        _USER, _PROJECT, mid, content="updated vec", new_vector=new_vec
    )
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


# ---------------------------------------------------------------------------
# _row_to_dict edge cases
# ---------------------------------------------------------------------------


def test_row_to_dict_falls_back_when_metadata_invalid_json():
    record = _row_to_dict(
        {
            "memory_id": "mem-x",
            "user_id": _USER,
            "project_id": _PROJECT,
            "content": "bad meta",
            "tags": [],
            "metadata": "{not valid json",
            "created_at": 1,
            "updated_at": 2,
        }
    )
    assert record["metadata"] == {}


def test_row_to_dict_personal_sentinel_normalises_to_none():
    record = _row_to_dict(
        {
            "memory_id": "mem-y",
            "user_id": _USER,
            "project_id": _PROJECT,
            "team_id": "__personal__",
            "content": "x",
            "tags": [],
            "metadata": "{}",
            "created_at": 1,
            "updated_at": 2,
        }
    )
    assert record["team_id"] is None


# ---------------------------------------------------------------------------
# save_many empty input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_many_empty_input_returns_empty_list(lancedb_store):
    ids = await lancedb_store.save_many(_USER, _PROJECT, [])
    assert ids == []


# ---------------------------------------------------------------------------
# ensure_collection — vector index threshold path + idempotent migration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_collection_migrates_legacy_table_without_team_id(tmp_path):
    """Open a table created before the team_id column shipped and verify
    ensure_collection backfills the column with the personal sentinel."""
    import lancedb
    import pyarrow as pa

    from piloci.storage.lancedb_store import TABLE_NAME

    db_path = tmp_path / "lancedb-legacy"
    db_path.mkdir(parents=True, exist_ok=True)
    db = await lancedb.connect_async(str(db_path))
    legacy_schema = pa.schema(
        [
            pa.field("memory_id", pa.string(), nullable=False),
            pa.field("user_id", pa.string(), nullable=False),
            pa.field("project_id", pa.string(), nullable=False),
            pa.field("scope", pa.string(), nullable=False),
            pa.field("content", pa.string()),
            pa.field("tags", pa.list_(pa.string())),
            pa.field("metadata", pa.string()),
            pa.field("created_at", pa.int64()),
            pa.field("updated_at", pa.int64()),
            pa.field("vector", pa.list_(pa.float32(), VECTOR_SIZE)),
        ]
    )
    await db.create_table(TABLE_NAME, schema=legacy_schema)

    s = Settings(
        lancedb_path=db_path,
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
    )
    store = MemoryStore(s)
    await store.ensure_collection()
    # Re-opening the table should now report team_id in the schema.
    tbl = await store._get_table()
    schema = await tbl.schema()
    assert "team_id" in schema.names
    await store.close()


@pytest.mark.asyncio
async def test_ensure_collection_creates_vector_index_above_threshold(tmp_path):
    """When row count >= lancedb_index_threshold, ensure_collection attempts
    IVF_PQ index creation. The lancedb call may swallow / no-op on tiny
    fixtures, but the code path itself must execute without raising."""
    s = Settings(
        lancedb_path=tmp_path / "lancedb-idx",
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
        lancedb_index_threshold=1,
    )
    store = MemoryStore(s)
    await store.ensure_collection()
    # Seed a row so the next ensure_collection attempts the vector index.
    await store.save(_USER, _PROJECT, "indexed", _VECTOR)
    await store.ensure_collection()  # exercises the count >= threshold branch
    # And a third call to exercise the "index already exists" exception arm.
    await store.ensure_collection()
    await store.close()


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_returns_zero_when_empty(lancedb_store):
    assert await lancedb_store.count(_USER, _PROJECT) == 0


@pytest.mark.asyncio
async def test_count_reflects_saved_rows(lancedb_store):
    for i in range(3):
        await lancedb_store.save(_USER, _PROJECT, f"m{i}", _VECTOR)
    assert await lancedb_store.count(_USER, _PROJECT) == 3


@pytest.mark.asyncio
async def test_count_with_tag_filter(lancedb_store):
    await lancedb_store.save(_USER, _PROJECT, "tagged", _VECTOR, tags=["alpha"])
    await lancedb_store.save(_USER, _PROJECT, "untagged", _VECTOR)
    assert await lancedb_store.count(_USER, _PROJECT, tags=["alpha"]) == 1


@pytest.mark.asyncio
async def test_count_isolated_by_project(lancedb_store):
    await lancedb_store.save(_USER, _PROJECT, "mine", _VECTOR)
    other_project = "proj-99999999-0000-0000-0000-000000000099"
    await lancedb_store.save(_USER, other_project, "theirs", _VECTOR)
    assert await lancedb_store.count(_USER, _PROJECT) == 1


# ---------------------------------------------------------------------------
# search — min_score branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_filters_by_min_score(lancedb_store):
    """A min_score above the maximum possible (1.0) must drop every result."""
    await lancedb_store.save(_USER, _PROJECT, "alpha", _VECTOR)
    results = await lancedb_store.search(_USER, _PROJECT, _VECTOR, top_k=5, min_score=1.5)
    assert results == []


# ---------------------------------------------------------------------------
# hybrid_search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_search_returns_saved_memory(lancedb_store):
    await lancedb_store.save(_USER, _PROJECT, "hybrid lookup target", _VECTOR)
    rows = await lancedb_store.hybrid_search(
        _USER,
        _PROJECT,
        query_text="hybrid",
        query_vector=_VECTOR,
        top_k=3,
    )
    contents = {r["content"] for r in rows}
    assert "hybrid lookup target" in contents
    assert all(0.0 <= r["score"] <= 1.0 for r in rows)


@pytest.mark.asyncio
async def test_hybrid_search_respects_tag_filter(lancedb_store):
    await lancedb_store.save(_USER, _PROJECT, "tagged hybrid", _VECTOR, tags=["keep"])
    await lancedb_store.save(_USER, _PROJECT, "skip me", _VECTOR, tags=["drop"])
    rows = await lancedb_store.hybrid_search(
        _USER,
        _PROJECT,
        query_text="hybrid",
        query_vector=_VECTOR,
        top_k=5,
        tags=["keep"],
    )
    contents = {r["content"] for r in rows}
    assert "skip me" not in contents


@pytest.mark.asyncio
async def test_hybrid_search_isolation_by_project(lancedb_store):
    other = "proj-77777777-0000-0000-0000-000000000077"
    await lancedb_store.save(_USER, other, "other-project content", _VECTOR)
    rows = await lancedb_store.hybrid_search(
        _USER,
        _PROJECT,
        query_text="other",
        query_vector=_VECTOR,
        top_k=5,
    )
    assert all(r["content"] != "other-project content" for r in rows)


@pytest.mark.asyncio
async def test_hybrid_search_min_score_drops_everything(lancedb_store):
    await lancedb_store.save(_USER, _PROJECT, "anything", _VECTOR)
    rows = await lancedb_store.hybrid_search(
        _USER,
        _PROJECT,
        query_text="anything",
        query_vector=_VECTOR,
        top_k=5,
        min_score=1.5,
    )
    assert rows == []


@pytest.mark.asyncio
async def test_hybrid_search_empty_table_returns_empty(lancedb_store):
    rows = await lancedb_store.hybrid_search(
        _USER,
        _PROJECT,
        query_text="missing",
        query_vector=_VECTOR,
        top_k=5,
    )
    assert rows == []


# ---------------------------------------------------------------------------
# update — branch coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_with_no_fields_only_bumps_timestamp(lancedb_store):
    """No content/tags/metadata/vector: hits the `len(updates) == 1` branch."""
    mid = await lancedb_store.save(_USER, _PROJECT, "ts only", _VECTOR)
    result = await lancedb_store.update(_USER, _PROJECT, mid)
    assert result is True
    record = await lancedb_store.get(_USER, _PROJECT, mid)
    assert record is not None
    assert record["content"] == "ts only"


@pytest.mark.asyncio
async def test_update_content_and_tags_together(lancedb_store):
    mid = await lancedb_store.save(_USER, _PROJECT, "old", _VECTOR, tags=["old"])
    ok = await lancedb_store.update(_USER, _PROJECT, mid, content="new", tags=["new"])
    assert ok is True
    record = await lancedb_store.get(_USER, _PROJECT, mid)
    assert record is not None
    assert record["content"] == "new"
    assert record["tags"] == ["new"]


@pytest.mark.asyncio
async def test_update_metadata_only_branch(lancedb_store):
    """metadata is not None, new_vector is None → hits the metadata merge
    branch including the content/tag conditional skips."""
    mid = await lancedb_store.save(_USER, _PROJECT, "meta", _VECTOR, metadata={"a": 1})
    ok = await lancedb_store.update(_USER, _PROJECT, mid, metadata={"b": 2})
    assert ok is True
    record = await lancedb_store.get(_USER, _PROJECT, mid)
    assert record is not None
    assert record["metadata"] == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_update_metadata_path_also_updates_content_and_tags(lancedb_store):
    """Hits the content + tags conditionals inside the metadata-fetch branch."""
    mid = await lancedb_store.save(
        _USER, _PROJECT, "before", _VECTOR, tags=["t1"], metadata={"k": "v0"}
    )
    ok = await lancedb_store.update(
        _USER,
        _PROJECT,
        mid,
        content="after",
        tags=["t2"],
        metadata={"k": "v1"},
    )
    assert ok is True
    record = await lancedb_store.get(_USER, _PROJECT, mid)
    assert record is not None
    assert record["content"] == "after"
    assert record["tags"] == ["t2"]
    assert record["metadata"] == {"k": "v1"}


@pytest.mark.asyncio
async def test_update_with_new_vector_returns_false_when_missing(lancedb_store):
    """Hits the `if not rows: return False` branch of the fetch-then-merge path."""
    new_vec = [0.5] * VECTOR_SIZE
    result = await lancedb_store.update(
        _USER,
        _PROJECT,
        str(uuid.uuid4()),
        content="ghost",
        new_vector=new_vec,
    )
    assert result is False


# ---------------------------------------------------------------------------
# team_search / team_hybrid_search — min_score branches
# ---------------------------------------------------------------------------


_TEAM = "team-cov-aaaa"
_TEAM_AUTHOR = "user-cov-1"


@pytest.mark.asyncio
async def test_team_search_min_score_drops_results(lancedb_store):
    await lancedb_store.team_save(_TEAM, _TEAM_AUTHOR, "team hit", _VECTOR)
    results = await lancedb_store.team_search(_TEAM, _VECTOR, top_k=5, min_score=1.5)
    assert results == []


@pytest.mark.asyncio
async def test_team_hybrid_search_min_score_drops_results(lancedb_store):
    await lancedb_store.team_save(_TEAM, _TEAM_AUTHOR, "hybrid team hit", _VECTOR)
    results = await lancedb_store.team_hybrid_search(
        _TEAM,
        query_text="hybrid",
        query_vector=_VECTOR,
        top_k=5,
        min_score=1.5,
    )
    assert results == []


@pytest.mark.asyncio
async def test_team_hybrid_search_with_tag_filter(lancedb_store):
    await lancedb_store.team_save(_TEAM, _TEAM_AUTHOR, "with tag", _VECTOR, tags=["a"])
    await lancedb_store.team_save(_TEAM, _TEAM_AUTHOR, "no tag", _VECTOR)
    rows = await lancedb_store.team_hybrid_search(
        _TEAM,
        query_text="tag",
        query_vector=_VECTOR,
        top_k=5,
        tags=["a"],
    )
    assert all("a" in r["tags"] for r in rows)


# ---------------------------------------------------------------------------
# team_update — metadata-only path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_update_metadata_only_merges(lancedb_store):
    mid = await lancedb_store.team_save(_TEAM, _TEAM_AUTHOR, "tm", _VECTOR, metadata={"k1": "v1"})
    ok = await lancedb_store.team_update(
        _TEAM,
        mid,
        requester_id=_TEAM_AUTHOR,
        metadata={"k2": "v2"},
    )
    assert ok is True
    row = await lancedb_store.team_get(_TEAM, mid)
    assert row is not None
    assert row["metadata"]["k1"] == "v1"
    assert row["metadata"]["k2"] == "v2"
    # author_id stamp is preserved across the merge.
    assert row["metadata"]["author_id"] == _TEAM_AUTHOR
