"""Integration tests for the team-scoped LanceDB methods.

These exercise the actual table on a tmp_path-backed store (the shared
``lancedb_store`` fixture from ``conftest.py``) so the SQL filter, BTree
index, and merge_insert paths all run for real. Faster than spinning up
the full app — the store has no network I/O.
"""

from __future__ import annotations

import pytest

from piloci.storage.lancedb_store import VECTOR_SIZE

_TEAM = "team-aaaa-bbbb"
_AUTHOR = "user-1"
_VECTOR = [0.1] * VECTOR_SIZE


@pytest.mark.asyncio
async def test_team_save_assigns_uuid_and_records_author(lancedb_store):
    mid = await lancedb_store.team_save(_TEAM, _AUTHOR, "hello team", _VECTOR)
    assert len(mid) >= 8

    row = await lancedb_store.team_get(_TEAM, mid)
    assert row is not None
    assert row["scope"] == "team"
    assert row["team_id"] == _TEAM
    # team_save stamps author_id into metadata so team_delete can enforce
    # author-only deletion later.
    assert row["metadata"]["author_id"] == _AUTHOR


@pytest.mark.asyncio
async def test_team_save_with_tags_and_metadata(lancedb_store):
    mid = await lancedb_store.team_save(
        _TEAM,
        _AUTHOR,
        "tagged team mem",
        _VECTOR,
        tags=["ops", "doc"],
        metadata={"category": "knowledge"},
    )
    row = await lancedb_store.team_get(_TEAM, mid)
    assert row is not None
    assert "ops" in row["tags"]
    assert row["metadata"]["category"] == "knowledge"
    # author_id is still populated even when caller passes metadata.
    assert row["metadata"]["author_id"] == _AUTHOR


@pytest.mark.asyncio
async def test_team_save_many_returns_all_ids(lancedb_store):
    ids = await lancedb_store.team_save_many(
        _TEAM,
        _AUTHOR,
        [
            {"content": "first", "vector": _VECTOR, "tags": ["a"]},
            {"content": "second", "vector": [0.2] * VECTOR_SIZE},
        ],
    )
    assert len(ids) == 2
    assert ids[0] != ids[1]


@pytest.mark.asyncio
async def test_team_save_many_empty_input_is_a_no_op(lancedb_store):
    ids = await lancedb_store.team_save_many(_TEAM, _AUTHOR, [])
    assert ids == []


@pytest.mark.asyncio
async def test_team_list_and_count(lancedb_store):
    await lancedb_store.team_save(_TEAM, _AUTHOR, "one", _VECTOR, tags=["x"])
    await lancedb_store.team_save(_TEAM, _AUTHOR, "two", _VECTOR, tags=["y"])

    rows = await lancedb_store.team_list(_TEAM, limit=10)
    assert len(rows) == 2

    # Tag filter prunes the list.
    filtered = await lancedb_store.team_list(_TEAM, tags=["x"], limit=10)
    assert len(filtered) == 1
    assert filtered[0]["content"] == "one"

    assert await lancedb_store.team_count(_TEAM) == 2
    assert await lancedb_store.team_count(_TEAM, tags=["y"]) == 1


@pytest.mark.asyncio
async def test_team_search_returns_within_team_scope_only(lancedb_store):
    # Save into two different teams; search should only see one.
    await lancedb_store.team_save(_TEAM, _AUTHOR, "alpha", _VECTOR)
    other_team = "team-cccc-dddd"
    await lancedb_store.team_save(other_team, _AUTHOR, "beta", _VECTOR)

    results = await lancedb_store.team_search(_TEAM, _VECTOR, top_k=5)
    contents = {r["content"] for r in results}
    assert "alpha" in contents
    assert "beta" not in contents


@pytest.mark.asyncio
async def test_team_hybrid_search_returns_results(lancedb_store):
    await lancedb_store.team_save(_TEAM, _AUTHOR, "hybrid lookup target", _VECTOR)
    rows = await lancedb_store.team_hybrid_search(
        _TEAM, query_text="hybrid", query_vector=_VECTOR, top_k=3
    )
    assert any(r["content"] == "hybrid lookup target" for r in rows)


@pytest.mark.asyncio
async def test_team_delete_allows_only_author_by_default(lancedb_store):
    mid = await lancedb_store.team_save(_TEAM, _AUTHOR, "mine", _VECTOR)

    # Different requester is rejected.
    other = "user-2"
    rejected = await lancedb_store.team_delete(_TEAM, mid, requester_id=other)
    assert rejected is False
    assert await lancedb_store.team_get(_TEAM, mid) is not None

    # Author is accepted.
    deleted = await lancedb_store.team_delete(_TEAM, mid, requester_id=_AUTHOR)
    assert deleted is True
    assert await lancedb_store.team_get(_TEAM, mid) is None


@pytest.mark.asyncio
async def test_team_delete_with_allow_owner_overrides_author_check(lancedb_store):
    mid = await lancedb_store.team_save(_TEAM, _AUTHOR, "owner-removable", _VECTOR)
    other = "team-owner"
    deleted = await lancedb_store.team_delete(_TEAM, mid, requester_id=other, allow_owner=True)
    assert deleted is True


@pytest.mark.asyncio
async def test_team_delete_returns_false_for_missing_row(lancedb_store):
    assert (await lancedb_store.team_delete(_TEAM, "never-existed", requester_id=_AUTHOR)) is False


@pytest.mark.asyncio
async def test_personal_scope_is_isolated_from_team_writes(lancedb_store):
    """Personal recall must never surface team rows even when the same vector
    is used — the team_id sentinel filter is what enforces this."""

    await lancedb_store.team_save(_TEAM, _AUTHOR, "team-only content", _VECTOR)

    # A personal save under the same author_id and a synthetic project.
    project_id = "proj-1"
    pid = await lancedb_store.save(_AUTHOR, project_id, "personal content", _VECTOR)
    assert pid

    personal = await lancedb_store.search(_AUTHOR, project_id, _VECTOR, top_k=10)
    contents = {r["content"] for r in personal}
    assert "personal content" in contents
    assert "team-only content" not in contents
