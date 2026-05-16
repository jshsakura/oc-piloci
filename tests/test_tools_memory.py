"""Tests for v0.3 MCP tools: memory, recall, listProjects, whoAmI."""

from pathlib import Path

import pytest

from piloci.tools.memory_tools import (
    ListProjectsInput,
    MemoryInput,
    RecallInput,
    WhoAmIInput,
    cwd_to_slug,
    handle_list_projects,
    handle_memory,
    handle_recall,
    handle_whoami,
)

USER = "user-1"
PROJECT = "proj-1"


async def embed(text):
    return [0.1] * 384


# ---------------------------------------------------------------------------
# memory (save/forget)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_save(mock_store):
    args = MemoryInput(content="hello world", tags=["test"])
    result = await handle_memory(args, USER, PROJECT, mock_store, embed)
    assert result["success"] is True
    assert result["action"] == "save"
    assert result["memory_id"] == "test-memory-id"
    mock_store.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_forget_requires_id(mock_store):
    args = MemoryInput(content="ignored", action="forget")
    result = await handle_memory(args, USER, PROJECT, mock_store, embed)
    assert result["success"] is False
    assert "memory_id" in result["error"]
    mock_store.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_memory_forget_with_id(mock_store):
    mock_store.delete.return_value = True
    args = MemoryInput(content="ignored", action="forget", memory_id="abc")
    result = await handle_memory(args, USER, PROJECT, mock_store, embed)
    assert result["success"] is True
    assert result["memory_id"] == "abc"
    mock_store.delete.assert_awaited_once()


# ---------------------------------------------------------------------------
# recall — preview mode (default)
# ---------------------------------------------------------------------------


_RECALL_ROW_M1 = {
    "memory_id": "m1",
    "content": "hello world this is a fairly long content string",
    "score": 0.92,
    "tags": ["test"],
    "created_at": 1700000000,
}


@pytest.mark.asyncio
async def test_recall_preview_mode(mock_store):
    mock_store.hybrid_search.return_value = [_RECALL_ROW_M1]
    args = RecallInput(query="hello", include_profile=False)
    result = await handle_recall(args, USER, PROJECT, mock_store, embed)
    assert result["mode"] == "preview"
    assert result["total"] == 1
    mem = result["memories"][0]
    assert mem["id"] == "m1"
    assert mem["tags"] == ["test"]
    assert "excerpt" in mem
    assert mem["length"] == len("hello world this is a fairly long content string")
    assert "profile" not in result


@pytest.mark.asyncio
async def test_recall_preview_truncates_long_content(mock_store):
    mock_store.hybrid_search.return_value = [
        {"memory_id": "m2", "content": "x" * 200, "score": 0.8, "tags": [], "created_at": 0},
    ]
    args = RecallInput(query="test", include_profile=False)
    result = await handle_recall(args, USER, PROJECT, mock_store, embed)
    mem = result["memories"][0]
    assert len(mem["excerpt"]) <= 83  # 80 chars + "..."
    assert mem["length"] == 200


# ---------------------------------------------------------------------------
# recall — fetch_ids mode (full content)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_fetch_ids(mock_store):
    mock_store.get.return_value = {
        "memory_id": "abc",
        "content": "full content here",
        "tags": ["x"],
    }
    args = RecallInput(query=None, fetch_ids=["abc"])
    result = await handle_recall(args, USER, PROJECT, mock_store, embed)
    assert result["mode"] == "full"
    assert result["fetched"] == 1
    assert result["memories"][0]["content"] == "full content here"


@pytest.mark.asyncio
async def test_recall_fetch_ids_skips_missing(mock_store):
    mock_store.get.return_value = None
    args = RecallInput(query=None, fetch_ids=["nonexistent"])
    result = await handle_recall(args, USER, PROJECT, mock_store, embed)
    assert result["fetched"] == 0
    assert result["memories"] == []


# ---------------------------------------------------------------------------
# recall — feedback (private) memory filter
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402 — local alias for test data construction

_FEEDBACK_ROW = {
    "memory_id": "feedback-1",
    "content": "사용자가 multipass 결과에 굿잡이라며 만족",
    "score": 0.88,
    "tags": ["multipass"],
    "created_at": 1700000001,
    # category lands inside the metadata JSON blob (matches what
    # distillation_worker._save_memories writes since v0.3.36).
    "metadata": _json.dumps({"source": "distilled", "category": "feedback"}),
}

_CODING_ROW = {
    "memory_id": "coding-1",
    "content": "uses argon2id for password hashing",
    "score": 0.85,
    "tags": ["security"],
    "created_at": 1700000002,
    "metadata": _json.dumps({"source": "distilled", "category": "preference"}),
}


@pytest.mark.asyncio
async def test_recall_preview_drops_feedback_by_default(mock_store):
    """MCP recall defaults to LLM-facing — feedback memories must not leak."""
    mock_store.hybrid_search.return_value = [_FEEDBACK_ROW, _CODING_ROW]
    args = RecallInput(query="hello", include_profile=False)
    result = await handle_recall(args, USER, PROJECT, mock_store, embed)
    ids = [m["id"] for m in result["memories"]]
    assert "feedback-1" not in ids
    assert "coding-1" in ids


@pytest.mark.asyncio
async def test_recall_preview_keeps_feedback_when_opted_in(mock_store):
    """UI / weekly-digest callers pass include_feedback=True to see everything."""
    mock_store.hybrid_search.return_value = [_FEEDBACK_ROW, _CODING_ROW]
    args = RecallInput(query="hello", include_profile=False, include_feedback=True)
    result = await handle_recall(args, USER, PROJECT, mock_store, embed)
    ids = {m["id"] for m in result["memories"]}
    assert ids == {"feedback-1", "coding-1"}


@pytest.mark.asyncio
async def test_recall_fetch_ids_also_filters_feedback(mock_store):
    """fetch_ids path runs the same filter — direct ID lookup can't bypass it."""

    def _fake_get(user_id, project_id, memory_id):
        return _FEEDBACK_ROW if memory_id == "feedback-1" else _CODING_ROW

    mock_store.get.side_effect = _fake_get
    args = RecallInput(query=None, fetch_ids=["feedback-1", "coding-1"])
    result = await handle_recall(args, USER, PROJECT, mock_store, embed)
    ids = [m["memory_id"] for m in result["memories"]]
    assert ids == ["coding-1"]
    assert result["fetched"] == 1


@pytest.mark.asyncio
async def test_recall_filter_tolerates_bad_metadata(mock_store):
    """Malformed metadata JSON should never hide a coding memory."""
    row = {**_CODING_ROW, "metadata": "{not valid json"}
    mock_store.hybrid_search.return_value = [row]
    args = RecallInput(query="hello", include_profile=False)
    result = await handle_recall(args, USER, PROJECT, mock_store, embed)
    assert len(result["memories"]) == 1


# ---------------------------------------------------------------------------
# recall — to_file mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_to_file(mock_store, tmp_path):
    mock_store.hybrid_search.return_value = [
        {"memory_id": "m1", "content": "x" * 200, "score": 0.95, "tags": ["a"], "created_at": 0},
    ]
    args = RecallInput(query="test", to_file=True, include_profile=False)
    result = await handle_recall(args, USER, PROJECT, mock_store, embed, export_dir=tmp_path)
    assert result["mode"] == "file"
    assert "file" in result
    assert result["count"] == 1
    assert Path(result["file"]).exists()
    content = Path(result["file"]).read_text()
    assert "x" * 200 in content


# ---------------------------------------------------------------------------
# recall — profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_includes_profile(mock_store):
    mock_store.hybrid_search.return_value = []

    async def profile_fn(uid, pid):
        return {"static": ["prefers TypeScript"], "dynamic": []}

    args = RecallInput(query="hi", include_profile=True)
    result = await handle_recall(args, USER, PROJECT, mock_store, embed, profile_fn=profile_fn)
    assert result["profile"]["static"] == ["prefers TypeScript"]


@pytest.mark.asyncio
async def test_recall_handles_profile_error(mock_store):
    mock_store.hybrid_search.return_value = []

    async def bad_profile(uid, pid):
        raise RuntimeError("boom")

    args = RecallInput(query="hi", include_profile=True)
    result = await handle_recall(args, USER, PROJECT, mock_store, embed, profile_fn=bad_profile)
    assert "profile" not in result
    assert result["memories"] == []


@pytest.mark.asyncio
async def test_recall_no_query_no_fetch_ids_returns_error(mock_store):
    args = RecallInput(query=None, fetch_ids=None)
    result = await handle_recall(args, USER, PROJECT, mock_store, embed)
    assert "error" in result
    assert result["total"] == 0


# ---------------------------------------------------------------------------
# listProjects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_projects():
    captured = {}

    async def projects_fn(uid, refresh):
        captured["uid"] = uid
        captured["refresh"] = refresh
        return [{"id": "p1", "slug": "web"}]

    result = await handle_list_projects(ListProjectsInput(refresh=True), USER, projects_fn)
    assert result["projects"][0]["slug"] == "web"
    assert captured == {"uid": USER, "refresh": True}


# ---------------------------------------------------------------------------
# cwd_to_slug — single source of truth for hook + init project resolution
# ---------------------------------------------------------------------------


def test_cwd_to_slug_basic():
    assert cwd_to_slug("/home/pi/app/my-project") == "my-project"
    assert cwd_to_slug("/home/pi/app/My Project") == "my-project"
    assert cwd_to_slug("/home/pi/app/proj_v2") == "proj-v2"


def test_cwd_to_slug_trailing_slash_and_unicode():
    # Trailing slash must not break dir extraction
    assert cwd_to_slug("/home/pi/app/example/") == "example"
    # Non-ASCII (Korean) is stripped — hook + init must agree on this fallback
    assert cwd_to_slug("/home/pi/app/한글프로젝트") == "project"


def test_cwd_to_slug_windows_paths():
    assert cwd_to_slug("C:\\Users\\me\\Repo") == "repo"


# ---------------------------------------------------------------------------
# whoAmI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whoami():
    auth = {"email": "a@b.com", "scope": "project"}
    result = await handle_whoami(
        WhoAmIInput(),
        USER,
        PROJECT,
        auth_payload=auth,
        session_id="sess-1",
        client_info={"name": "claude-code"},
    )
    assert result["userId"] == USER
    assert result["email"] == "a@b.com"
    assert result["sessionId"] == "sess-1"
    assert result["client"]["name"] == "claude-code"
