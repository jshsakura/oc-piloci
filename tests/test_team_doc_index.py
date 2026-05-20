"""Tests for the team-document indexing pipeline.

Exercises the chunk planner (count + approximate line ranges), the store
methods (deterministic ids, reindex-replaces, remove, cross-team isolation),
and the high-level ``index_team_document`` / ``remove_team_document`` helpers.

The real ``lancedb_store`` fixture (tmp_path-backed) runs the SQL filter,
LIKE delete, and merge_insert paths for real; ``embed_one`` is monkeypatched
to a fixed vector so no fastembed model is loaded.
"""

from __future__ import annotations

import pytest

from piloci.curator.team_doc_index import (
    CHUNK_CHARS,
    MAX_CHUNKS,
    _plan_chunks,
    index_team_document,
    index_team_file_stub,
    remove_team_document,
)
from piloci.storage.lancedb_store import VECTOR_SIZE

_TEAM_A = "team-aaaa"
_TEAM_B = "team-bbbb"
_VEC = [0.1] * VECTOR_SIZE


@pytest.fixture
def fixed_embed(monkeypatch):
    async def _embed(_text, **_kwargs):
        return list(_VEC)

    monkeypatch.setattr("piloci.curator.team_doc_index.embed_one", _embed)
    return _embed


@pytest.fixture
def settings_obj(tmp_path):
    from piloci.config import Settings

    return Settings(
        lancedb_path=tmp_path / "lancedb",
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
    )


# ---------------------------------------------------------------------------
# chunk planner
# ---------------------------------------------------------------------------


def test_plan_chunks_short_doc_is_single_chunk():
    planned = _plan_chunks("line one\nline two\nline three")
    assert len(planned) == 1
    assert planned[0]["line_start"] == 1
    assert planned[0]["line_end"] == 3


def test_plan_chunks_empty_returns_nothing():
    assert _plan_chunks("") == []
    # The planner itself treats whitespace as content; index_team_document is
    # what skips whitespace-only docs (see test_index_team_document_skips_empty).
    assert _plan_chunks("   ") != []


def test_plan_chunks_long_doc_produces_multiple_bounded_chunks():
    content = "\n".join(f"line {i}" for i in range(2000))  # well over CHUNK_CHARS
    planned = _plan_chunks(content)
    assert 1 < len(planned) <= MAX_CHUNKS
    # First chunk starts at line 1; ranges are increasing and within bounds.
    assert planned[0]["line_start"] == 1
    total_lines = content.count("\n") + 1
    for p in planned:
        assert 1 <= p["line_start"] <= p["line_end"] <= total_lines


def test_plan_chunks_caps_at_max():
    content = "a" * (CHUNK_CHARS * (MAX_CHUNKS + 50))
    planned = _plan_chunks(content)
    assert len(planned) <= MAX_CHUNKS


# ---------------------------------------------------------------------------
# store methods (direct)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_doc_chunks_uses_deterministic_ids(lancedb_store):
    chunks = [
        {"content": "alpha", "vector": _VEC, "metadata": {"path": "a.md"}},
        {"content": "beta", "vector": _VEC, "metadata": {"path": "a.md"}},
    ]
    ids = await lancedb_store.team_index_doc_chunks(_TEAM_A, "docX", chunks)
    assert ids == ["doc::docX::0", "doc::docX::1"]

    # Chunk ids contain '::' which _safe_id rejects, so they're reached via
    # team_list/search (the product path), never team_get-by-id.
    rows = await lancedb_store.team_list(_TEAM_A, limit=10)
    by_id = {r["id"]: r for r in rows}
    assert "doc::docX::0" in by_id
    row = by_id["doc::docX::0"]
    assert row["scope"] == "team"
    assert row["metadata"]["kind"] == "doc_chunk"
    assert row["metadata"]["doc_id"] == "docX"


@pytest.mark.asyncio
async def test_reindex_replaces_old_chunks_no_dupes(lancedb_store):
    first = [{"content": f"v1-{i}", "vector": _VEC, "metadata": {}} for i in range(4)]
    await lancedb_store.team_index_doc_chunks(_TEAM_A, "docR", first)
    assert await lancedb_store.team_count(_TEAM_A) == 4

    # Reindex with fewer chunks → old extras must be gone, not lingering.
    second = [{"content": f"v2-{i}", "vector": _VEC, "metadata": {}} for i in range(2)]
    await lancedb_store.team_index_doc_chunks(_TEAM_A, "docR", second)
    assert await lancedb_store.team_count(_TEAM_A) == 2

    rows = await lancedb_store.team_list(_TEAM_A, limit=10)
    by_id = {r["id"]: r["content"] for r in rows}
    assert by_id["doc::docR::0"] == "v2-0"
    # The old 3rd/4th chunk ids are gone.
    assert "doc::docR::2" not in by_id


@pytest.mark.asyncio
async def test_remove_doc_chunks_deletes_all(lancedb_store):
    chunks = [{"content": f"c{i}", "vector": _VEC, "metadata": {}} for i in range(3)]
    await lancedb_store.team_index_doc_chunks(_TEAM_A, "docD", chunks)
    assert await lancedb_store.team_count(_TEAM_A) == 3

    deleted = await lancedb_store.team_remove_doc_chunks(_TEAM_A, "docD")
    assert deleted == 3
    assert await lancedb_store.team_count(_TEAM_A) == 0


@pytest.mark.asyncio
async def test_doc_chunks_are_cross_team_isolated(lancedb_store):
    await lancedb_store.team_index_doc_chunks(
        _TEAM_A, "secret", [{"content": "team A only secret", "vector": _VEC, "metadata": {}}]
    )
    # Team B search must never see team A's chunk.
    b_results = await lancedb_store.team_hybrid_search(
        _TEAM_B, query_text="secret", query_vector=_VEC, top_k=10
    )
    assert all("team A only" not in r["content"] for r in b_results)
    assert await lancedb_store.team_count(_TEAM_B) == 0
    # Team A still sees it.
    assert await lancedb_store.team_count(_TEAM_A) == 1


# ---------------------------------------------------------------------------
# high-level helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_team_document_then_search_finds_chunk(
    lancedb_store, fixed_embed, settings_obj
):
    content = "The team deployment runbook. Roll out via docker compose on the Pi."
    n = await index_team_document(
        lancedb_store,
        _TEAM_A,
        "doc1",
        "ops/deploy.md",
        content,
        settings=settings_obj,
    )
    assert n >= 1

    results = await lancedb_store.team_hybrid_search(
        _TEAM_A, query_text="deployment runbook", query_vector=_VEC, top_k=5
    )
    assert results
    hit = results[0]
    assert hit["metadata"]["kind"] == "doc_chunk"
    assert hit["metadata"]["path"] == "ops/deploy.md"
    assert "line_start" in hit["metadata"]


@pytest.mark.asyncio
async def test_index_team_document_skips_empty(lancedb_store, fixed_embed, settings_obj):
    n = await index_team_document(
        lancedb_store, _TEAM_A, "empty", "e.md", "   ", settings=settings_obj
    )
    assert n == 0
    assert await lancedb_store.team_count(_TEAM_A) == 0


@pytest.mark.asyncio
async def test_remove_team_document_helper(lancedb_store, fixed_embed, settings_obj):
    await index_team_document(
        lancedb_store, _TEAM_A, "doc2", "x.md", "some content here", settings=settings_obj
    )
    assert await lancedb_store.team_count(_TEAM_A) >= 1
    await remove_team_document(lancedb_store, _TEAM_A, "doc2")
    assert await lancedb_store.team_count(_TEAM_A) == 0


# ---------------------------------------------------------------------------
# binary file stub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_team_file_stub_makes_file_discoverable(
    lancedb_store, fixed_embed, settings_obj
):
    """A binary upload is searchable by filename via its descriptor stub,
    stored as a single doc_file chunk at ``doc::<doc_id>::0`` — no bytes."""
    n = await index_team_file_stub(
        lancedb_store,
        _TEAM_A,
        "fileX",
        "assets/quarterly-report.pdf",
        "application/pdf",
        12345,
        settings=settings_obj,
    )
    assert n == 1
    assert await lancedb_store.team_count(_TEAM_A) == 1

    rows = await lancedb_store.team_list(_TEAM_A, limit=10)
    by_id = {r["id"]: r for r in rows}
    assert "doc::fileX::0" in by_id
    meta = by_id["doc::fileX::0"]["metadata"]
    assert meta["kind"] == "doc_file"
    assert meta["path"] == "assets/quarterly-report.pdf"
    assert meta["mime"] == "application/pdf"
    assert meta["size"] == 12345

    # Recall by filename surfaces the stub.
    results = await lancedb_store.team_hybrid_search(
        _TEAM_A, query_text="quarterly-report.pdf", query_vector=_VEC, top_k=5
    )
    assert any(r["metadata"].get("kind") == "doc_file" for r in results)


@pytest.mark.asyncio
async def test_file_stub_removed_by_remove_team_document(lancedb_store, fixed_embed, settings_obj):
    """The standard doc-remove (LIKE ``doc::<doc_id>::%``) clears the file
    stub too, so a deleted binary stops surfacing in recall."""
    await index_team_file_stub(
        lancedb_store,
        _TEAM_A,
        "fileD",
        "a.bin",
        "application/octet-stream",
        9,
        settings=settings_obj,
    )
    assert await lancedb_store.team_count(_TEAM_A) == 1
    deleted = await remove_team_document(lancedb_store, _TEAM_A, "fileD")
    assert deleted == 1
    assert await lancedb_store.team_count(_TEAM_A) == 0


@pytest.mark.asyncio
async def test_index_team_file_stub_never_raises(settings_obj):
    """Fire-and-forget safety: a broken store is swallowed, returns 0."""

    class _BrokenStore:
        async def team_index_doc_chunks(self, *a, **k):
            raise RuntimeError("boom")

    async def _embed(_t, **_k):
        return list(_VEC)

    import piloci.curator.team_doc_index as mod

    orig = mod.embed_one
    mod.embed_one = _embed
    try:
        n = await index_team_file_stub(
            _BrokenStore(), _TEAM_A, "f", "p.bin", "x/y", 1, settings=settings_obj
        )
        assert n == 0
    finally:
        mod.embed_one = orig


@pytest.mark.asyncio
async def test_index_team_document_never_raises(settings_obj):
    """Fire-and-forget safety: a broken store is swallowed, returns 0."""

    class _BrokenStore:
        async def team_index_doc_chunks(self, *a, **k):
            raise RuntimeError("boom")

        async def team_remove_doc_chunks(self, *a, **k):
            raise RuntimeError("boom")

    async def _embed(_t, **_k):
        return list(_VEC)

    import piloci.curator.team_doc_index as mod

    orig = mod.embed_one
    mod.embed_one = _embed
    try:
        n = await index_team_document(
            _BrokenStore(), _TEAM_A, "d", "p.md", "content", settings=settings_obj
        )
        assert n == 0
        deleted = await remove_team_document(_BrokenStore(), _TEAM_A, "d")
        assert deleted == 0
    finally:
        mod.embed_one = orig
