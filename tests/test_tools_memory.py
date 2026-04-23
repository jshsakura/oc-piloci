"""Tests for v0.3 MCP tools: memory, recall, listProjects, whoAmI."""
import pytest

from piloci.tools.memory_tools import (
    ListProjectsInput,
    MemoryInput,
    RecallInput,
    WhoAmIInput,
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
# recall
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_without_profile(mock_store):
    mock_store.search.return_value = [{"id": "m1", "content": "hi"}]
    args = RecallInput(query="hello", include_profile=False)
    result = await handle_recall(args, USER, PROJECT, mock_store, embed)
    assert result["memories"][0]["id"] == "m1"
    assert "profile" not in result


@pytest.mark.asyncio
async def test_recall_includes_profile(mock_store):
    mock_store.search.return_value = []

    async def profile_fn(uid, pid):
        return {"static": ["prefers TypeScript"], "dynamic": []}

    args = RecallInput(query="hi", include_profile=True)
    result = await handle_recall(args, USER, PROJECT, mock_store, embed, profile_fn=profile_fn)
    assert result["profile"]["static"] == ["prefers TypeScript"]


@pytest.mark.asyncio
async def test_recall_handles_profile_error(mock_store):
    mock_store.search.return_value = []

    async def bad_profile(uid, pid):
        raise RuntimeError("boom")

    args = RecallInput(query="hi", include_profile=True)
    result = await handle_recall(args, USER, PROJECT, mock_store, embed, profile_fn=bad_profile)
    assert "profile" not in result  # silently dropped
    assert result["memories"] == []


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
# whoAmI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whoami():
    auth = {"email": "a@b.com", "scope": "project"}
    result = await handle_whoami(
        WhoAmIInput(), USER, PROJECT, auth_payload=auth,
        session_id="sess-1", client_info={"name": "claude-code"},
    )
    assert result["userId"] == USER
    assert result["email"] == "a@b.com"
    assert result["sessionId"] == "sess-1"
    assert result["client"]["name"] == "claude-code"
