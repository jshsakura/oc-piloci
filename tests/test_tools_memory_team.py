"""Unit tests for the team-id branches of ``memory_tools``.

These cover ``_handle_team_memory`` (save/forget), ``_handle_team_recall``
(fetch/search/file modes), and ``handle_doc`` with team_id + path. All
external collaborators are AsyncMocked — the goal is exercising branch
logic, not the real LanceDB store or SQL session.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from piloci.tools.memory_tools import (
    DocInput,
    MemoryInput,
    RecallInput,
    handle_doc,
    handle_memory,
    handle_recall,
)


@pytest.fixture
def fake_store():
    """AsyncMock with the team_* methods the handlers use."""
    store = AsyncMock()
    store.team_save.return_value = "mem-1"
    store.team_delete.return_value = True
    store.team_get.return_value = {
        "id": "mem-1",
        "content": "team content",
        "metadata": {"author_id": "alice"},
        "tags": [],
        "created_at": 1,
        "updated_at": 2,
    }
    store.team_hybrid_search.return_value = [
        {
            "id": "mem-1",
            "memory_id": "mem-1",
            "content": "match",
            "tags": [],
            "score": 0.9,
        }
    ]
    return store


@pytest.fixture
def fake_embed():
    async def _embed(_text: str) -> list[float]:
        return [0.1, 0.2]

    return _embed


@pytest.mark.asyncio
async def test_handle_memory_team_save_returns_team_scope(fake_store, fake_embed, monkeypatch):
    """team_id=X + action=save → routes to team_save and stamps scope=team."""
    monkeypatch.setattr(
        "piloci.tools.memory_tools._ensure_team_member", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "piloci.tools.memory_tools._invalidate_team_vault_silently",
        AsyncMock(return_value=None),
    )

    result = await handle_memory(
        MemoryInput(content="안녕 팀", team_id="team-1", action="save"),
        user_id="alice",
        project_id=None,
        store=fake_store,
        embed_fn=fake_embed,
    )
    assert result["success"] is True
    assert result["team_id"] == "team-1"
    assert result["scope"] == "team"
    fake_store.team_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_memory_team_rejects_non_member(fake_store, fake_embed, monkeypatch):
    """Non-member → _ensure_team_member returns deny dict → handler returns it
    without touching the store."""
    monkeypatch.setattr(
        "piloci.tools.memory_tools._ensure_team_member",
        AsyncMock(return_value={"success": False, "error": "Not a member of this team"}),
    )

    result = await handle_memory(
        MemoryInput(content="x", team_id="team-1"),
        user_id="stranger",
        project_id=None,
        store=fake_store,
        embed_fn=fake_embed,
    )
    assert result["success"] is False
    assert "member" in result["error"].lower()
    fake_store.team_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_memory_team_forget_requires_memory_id(fake_store, fake_embed, monkeypatch):
    monkeypatch.setattr(
        "piloci.tools.memory_tools._ensure_team_member", AsyncMock(return_value=None)
    )
    result = await handle_memory(
        MemoryInput(content="x", team_id="team-1", action="forget"),
        user_id="alice",
        project_id=None,
        store=fake_store,
        embed_fn=fake_embed,
    )
    assert result["success"] is False
    assert "memory_id" in result["error"]


@pytest.mark.asyncio
async def test_handle_memory_team_forget_delegates_to_store(fake_store, fake_embed, monkeypatch):
    """forget+memory_id → owner-check SQL is swallowed (we patch async_session
    to a no-op) → store.team_delete called with allow_owner false."""
    monkeypatch.setattr(
        "piloci.tools.memory_tools._ensure_team_member", AsyncMock(return_value=None)
    )

    # The handler does ``from piloci.db.session import async_session`` inline
    # for the owner lookup. Forcing it to raise short-circuits is_owner=False.
    class _DummySession:
        async def __aenter__(self):
            raise RuntimeError("no db in this test")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("piloci.db.session.async_session", lambda: _DummySession())

    result = await handle_memory(
        MemoryInput(content="x", team_id="team-1", action="forget", memory_id="mem-1"),
        user_id="alice",
        project_id=None,
        store=fake_store,
        embed_fn=fake_embed,
    )
    assert result["success"] is True
    fake_store.team_delete.assert_awaited_once()
    assert fake_store.team_delete.await_args.kwargs["allow_owner"] is False


@pytest.mark.asyncio
async def test_handle_memory_personal_without_project_fails(fake_store, fake_embed):
    """team_id absent + project_id absent → soft error, never hits store."""
    result = await handle_memory(
        MemoryInput(content="x"),
        user_id="alice",
        project_id=None,
        store=fake_store,
        embed_fn=fake_embed,
    )
    assert result["success"] is False
    assert "project" in result["error"].lower()


# ---------------------------------------------------------------------------
# handle_recall — team branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_recall_team_preview_uses_hybrid_search(fake_store, fake_embed, monkeypatch):
    monkeypatch.setattr(
        "piloci.tools.memory_tools._ensure_team_member", AsyncMock(return_value=None)
    )
    result = await handle_recall(
        RecallInput(query="hello", team_id="team-1"),
        user_id="alice",
        project_id=None,
        store=fake_store,
        embed_fn=fake_embed,
    )
    assert result["mode"] == "preview"
    assert result["team_id"] == "team-1"
    fake_store.team_hybrid_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_recall_team_fetch_ids_hits_team_get(fake_store, fake_embed, monkeypatch):
    monkeypatch.setattr(
        "piloci.tools.memory_tools._ensure_team_member", AsyncMock(return_value=None)
    )
    result = await handle_recall(
        RecallInput(team_id="team-1", fetch_ids=["mem-1"]),
        user_id="alice",
        project_id=None,
        store=fake_store,
        embed_fn=fake_embed,
    )
    assert result["mode"] == "full"
    assert result["fetched"] == 1
    fake_store.team_get.assert_awaited_with("team-1", "mem-1")


@pytest.mark.asyncio
async def test_handle_recall_team_missing_query_returns_hint(fake_store, fake_embed, monkeypatch):
    monkeypatch.setattr(
        "piloci.tools.memory_tools._ensure_team_member", AsyncMock(return_value=None)
    )
    result = await handle_recall(
        RecallInput(team_id="team-1"),
        user_id="alice",
        project_id=None,
        store=fake_store,
        embed_fn=fake_embed,
    )
    assert result["mode"] == "preview"
    assert result["total"] == 0
    assert "query" in result["error"].lower()


# ---------------------------------------------------------------------------
# handle_doc — three branches (team+path, team only, personal)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_doc_team_with_path_writes_team_document(fake_embed, monkeypatch):
    """team_id + path → team_documents SQL upsert via _save_team_document."""
    monkeypatch.setattr(
        "piloci.tools.memory_tools._ensure_team_member", AsyncMock(return_value=None)
    )
    fake_doc = AsyncMock(
        return_value={
            "success": True,
            "doc_id": "d1",
            "team_id": "team-1",
            "path": "notes/a.md",
            "version": 1,
            "content_hash": "abc",
            "bytes": 5,
            "download_url": "/api/teams/team-1/documents/d1/raw",
            "scope": "team-doc",
        }
    )
    monkeypatch.setattr("piloci.tools.memory_tools._save_team_document", fake_doc)

    result = await handle_doc(
        DocInput(title="Note", content="hello", team_id="team-1", path="notes/a.md"),
        user_id="alice",
        project_id=None,
        store=AsyncMock(),
        embed_fn=fake_embed,
    )
    assert result["scope"] == "team-doc"
    assert result["download_url"].endswith("/raw")
    fake_doc.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_doc_team_without_path_writes_team_memory(fake_store, fake_embed, monkeypatch):
    monkeypatch.setattr(
        "piloci.tools.memory_tools._ensure_team_member", AsyncMock(return_value=None)
    )
    result = await handle_doc(
        DocInput(title="Note", content="content", team_id="team-1"),
        user_id="alice",
        project_id=None,
        store=fake_store,
        embed_fn=fake_embed,
    )
    assert result["scope"] == "team"
    assert result["team_id"] == "team-1"
    fake_store.team_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_doc_personal_requires_project(fake_store, fake_embed):
    result = await handle_doc(
        DocInput(title="Note", content="x"),
        user_id="alice",
        project_id=None,
        store=fake_store,
        embed_fn=fake_embed,
    )
    assert result["success"] is False
    assert "project" in result["error"].lower()


@pytest.mark.asyncio
async def test_handle_doc_personal_with_project_writes_via_store(fake_store, fake_embed, tmp_path):
    fake_store.save.return_value = "doc-1"
    result = await handle_doc(
        DocInput(title="My note", content="hi"),
        user_id="alice",
        project_id="proj-1",
        store=fake_store,
        embed_fn=fake_embed,
        export_dir=tmp_path,
    )
    assert result["success"] is True
    assert result["memory_id"] == "doc-1"
    fake_store.save.assert_awaited_once()


# ---------------------------------------------------------------------------
# _ensure_team_member (smoke — exercises the SQL bridge path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_team_member_returns_none_for_actual_member():
    """Patches async_session to return a fake member row — _ensure_team_member
    should return None (i.e. "allowed")."""
    from piloci.tools import memory_tools

    fake_member = MagicMock()

    class _Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    with patch("piloci.api.team_routes._get_team_member", AsyncMock(return_value=fake_member)):
        with patch("piloci.db.session.async_session", lambda: _Sess()):
            deny = await memory_tools._ensure_team_member("team-1", "alice")
    assert deny is None


@pytest.mark.asyncio
async def test_ensure_team_member_returns_error_for_stranger():
    from piloci.tools import memory_tools

    class _Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    with patch("piloci.api.team_routes._get_team_member", AsyncMock(return_value=None)):
        with patch("piloci.db.session.async_session", lambda: _Sess()):
            deny = await memory_tools._ensure_team_member("team-1", "stranger")
    assert deny is not None
    assert "member" in deny["error"].lower()


# ---------------------------------------------------------------------------
# recall preview — doc chunks + token cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_preview_surfaces_doc_chunk_path_and_lines(
    fake_store, fake_embed, monkeypatch
):
    """A doc_chunk result is shaped as kind='doc' with path + line range,
    while a memory result keeps kind='memory'."""
    monkeypatch.setattr(
        "piloci.tools.memory_tools._ensure_team_member", AsyncMock(return_value=None)
    )
    fake_store.team_hybrid_search.return_value = [
        {
            "id": "doc::d1::0",
            "memory_id": "doc::d1::0",
            "content": "the deploy runbook lives in ops/deploy.md and explains rollout",
            "tags": [],
            "score": 0.91,
            "metadata": {
                "kind": "doc_chunk",
                "doc_id": "d1",
                "path": "ops/deploy.md",
                "chunk_index": 0,
                "line_start": 12,
                "line_end": 30,
            },
        },
        {
            "id": "mem-1",
            "memory_id": "mem-1",
            "content": "a plain team memory",
            "tags": ["note"],
            "score": 0.5,
            "metadata": {},
        },
    ]

    result = await handle_recall(
        RecallInput(query="deploy", team_id="team-1"),
        user_id="alice",
        project_id=None,
        store=fake_store,
        embed_fn=fake_embed,
    )

    items = result["memories"]
    assert items[0]["kind"] == "doc"
    assert items[0]["path"] == "ops/deploy.md"
    assert items[0]["line_start"] == 12
    assert items[0]["line_end"] == 30
    assert "excerpt" in items[0]
    assert items[1]["kind"] == "memory"
    assert result["truncated"] is False
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_recall_preview_surfaces_binary_file_stub(fake_store, fake_embed, monkeypatch):
    """A ``doc_file`` stub becomes a kind='file' preview with path/mime/size
    and a pull hint instead of an excerpt."""
    monkeypatch.setattr(
        "piloci.tools.memory_tools._ensure_team_member", AsyncMock(return_value=None)
    )
    fake_store.team_hybrid_search.return_value = [
        {
            "id": "doc::f1::0",
            "memory_id": "doc::f1::0",
            "content": "[파일] assets/report.pdf (application/pdf, 2048 bytes)",
            "tags": [],
            "score": 0.88,
            "metadata": {
                "kind": "doc_file",
                "doc_id": "f1",
                "path": "assets/report.pdf",
                "mime": "application/pdf",
                "size": 2048,
            },
        }
    ]

    result = await handle_recall(
        RecallInput(query="report", team_id="team-1"),
        user_id="alice",
        project_id=None,
        store=fake_store,
        embed_fn=fake_embed,
    )

    item = result["memories"][0]
    assert item["kind"] == "file"
    assert item["path"] == "assets/report.pdf"
    assert item["mime"] == "application/pdf"
    assert item["size"] == 2048
    assert "piloci pull --path assets/report.pdf" in item["hint"]
    assert "excerpt" not in item


@pytest.mark.asyncio
async def test_recall_preview_truncates_and_flags_when_over_cap(
    fake_store, fake_embed, monkeypatch
):
    """Many large doc chunks → excerpt budget exhausted → fewer previews
    returned, truncated flag set, but total reflects the full match count."""
    from piloci.tools.memory_tools import _RECALL_CHAR_CAP

    monkeypatch.setattr(
        "piloci.tools.memory_tools._ensure_team_member", AsyncMock(return_value=None)
    )
    big = "x" * 5000
    fake_store.team_hybrid_search.return_value = [
        {
            "id": f"doc::d::{i}",
            "memory_id": f"doc::d::{i}",
            "content": big,
            "tags": [],
            "score": 0.9 - i * 0.01,
            "metadata": {
                "kind": "doc_chunk",
                "path": "big.md",
                "line_start": i,
                "line_end": i + 1,
            },
        }
        for i in range(60)
    ]

    result = await handle_recall(
        RecallInput(query="x", team_id="team-1", limit=50),
        user_id="alice",
        project_id=None,
        store=fake_store,
        embed_fn=fake_embed,
    )

    assert result["truncated"] is True
    assert result["total"] == 60
    assert len(result["memories"]) < 60
    total_excerpt = sum(len(m.get("excerpt", "")) for m in result["memories"])
    assert total_excerpt <= _RECALL_CHAR_CAP
