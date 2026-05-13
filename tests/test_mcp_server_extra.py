from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import mcp.types as types
import orjson
import pytest

from piloci.config import Settings
from piloci.mcp.server import (
    CONTEXT_PROMPT_NAME,
    RESOURCE_PROFILE,
    RESOURCE_PROJECTS,
    RESOURCE_RECENT,
    TOOL_DEFINITIONS,
    _build_context_text,
    _make_tool,
    _resource_list,
    create_mcp_server,
)
from piloci.mcp.session_state import McpSessionTracker, mcp_auth_ctx, mcp_session_ctx
from piloci.tools._schema import compact_schema
from piloci.tools.instinct_tools import ContradictInput, RecommendInput
from piloci.tools.memory_tools import MemoryInput


def _server_settings(tmp_path: Path) -> Settings:
    return cast(
        Settings,
        cast(
            object,
            SimpleNamespace(
                embed_model="test-embed-model",
                embed_cache_dir=tmp_path / "embed-cache",
                embed_lru_size=8,
                embed_executor_workers=2,
                embed_max_concurrency=3,
            ),
        ),
    )


async def _list_tools(server: Any) -> Any:
    return await server.request_handlers[types.ListToolsRequest](types.ListToolsRequest())


async def _call_tool(server: Any, name: str, arguments: dict[str, Any] | None = None) -> Any:
    return await server.request_handlers[types.CallToolRequest](
        types.CallToolRequest.model_validate(
            {"params": {"name": name, "arguments": arguments or {}}}
        )
    )


async def _list_resources(server: Any) -> Any:
    return await server.request_handlers[types.ListResourcesRequest](types.ListResourcesRequest())


async def _read_resource(server: Any, uri: str) -> Any:
    return await server.request_handlers[types.ReadResourceRequest](
        types.ReadResourceRequest.model_validate({"params": {"uri": uri}})
    )


async def _list_prompts(server: Any) -> Any:
    return await server.request_handlers[types.ListPromptsRequest](types.ListPromptsRequest())


async def _get_prompt(server: Any, name: str, arguments: dict[str, Any] | None = None) -> Any:
    return await server.request_handlers[types.GetPromptRequest](
        types.GetPromptRequest.model_validate({"params": {"name": name, "arguments": arguments}})
    )


def _content_text(result: Any) -> str:
    return result.root.content[0].text


def _content_json(result: Any) -> dict[str, Any]:
    return orjson.loads(_content_text(result))


def _resource_text(result: Any) -> str:
    return result.root.contents[0].text


def test_make_tool_compacts_schema_like_runtime_definition():
    tool = _make_tool("memory", "desc", MemoryInput)

    assert tool.name == "memory"
    assert tool.description == "desc"
    assert tool.inputSchema == compact_schema(MemoryInput.model_json_schema(), _top=True)


def test_resource_list_exposes_expected_metadata():
    resources = _resource_list()

    assert [(item.name, str(item.uri), item.mimeType) for item in resources] == [
        ("User Profile", RESOURCE_PROFILE, "application/json"),
        ("Projects", RESOURCE_PROJECTS, "application/json"),
        ("Recent Memories", RESOURCE_RECENT, "application/json"),
    ]


def test_build_context_text_dynamic_is_omitted_when_recent_disabled():
    text = _build_context_text({"static": [], "dynamic": ["recent fact"]}, include_recent=False)

    assert "recent fact" not in text
    assert "## User Context" not in text
    assert "No user profile yet" not in text


@pytest.mark.asyncio
async def test_server_lists_registered_tools_resources_and_prompts(tmp_path: Path):
    server = create_mcp_server(_server_settings(tmp_path), AsyncMock())

    tools_result = await _list_tools(server)
    resources_result = await _list_resources(server)
    prompts_result = await _list_prompts(server)

    assert [tool.name for tool in tools_result.root.tools] == [
        tool.name for tool in TOOL_DEFINITIONS
    ]
    assert [str(resource.uri) for resource in resources_result.root.resources] == [
        RESOURCE_PROFILE,
        RESOURCE_PROJECTS,
        RESOURCE_RECENT,
    ]
    assert len(prompts_result.root.prompts) == 1
    assert prompts_result.root.prompts[0].name == CONTEXT_PROMPT_NAME
    assert prompts_result.root.prompts[0].arguments[0].name == "include_recent"


@pytest.mark.asyncio
async def test_call_tool_requires_authentication(tmp_path: Path):
    server = create_mcp_server(_server_settings(tmp_path), AsyncMock())

    result = await _call_tool(server, "whoAmI")

    assert result.root.isError is True
    assert _content_text(result) == "MCP authentication required"


@pytest.mark.asyncio
async def test_memory_tool_saves_and_invalidates_vault_cache(tmp_path: Path):
    store = AsyncMock()
    store.save.return_value = "mem-123"
    store.search.return_value = []  # no duplicates
    server = create_mcp_server(_server_settings(tmp_path), store)
    tracker = McpSessionTracker()
    auth_token = mcp_auth_ctx.set(
        {
            "sub": "user-1",
            "project_id": "project-1",
            "project_slug": "alpha",
            "jti": "session-1",
        }
    )
    session_token = mcp_session_ctx.set(tracker)
    invalidate = AsyncMock()

    try:
        with (
            patch("piloci.mcp.server.embed_one", AsyncMock(return_value=[0.2, 0.4])),
            patch(
                "piloci.mcp.server.get_settings",
                return_value=SimpleNamespace(
                    vault_dir=tmp_path / "vaults", export_dir=tmp_path / "exports"
                ),
            ),
            patch("piloci.curator.vault.invalidate_project_vault_cache", invalidate),
        ):
            result = await _call_tool(
                server,
                "memory",
                {"content": "Remember this", "tags": ["decision", "python"]},
            )
    finally:
        mcp_session_ctx.reset(session_token)
        mcp_auth_ctx.reset(auth_token)

    payload = _content_json(result)
    assert payload == {
        "success": True,
        "action": "save",
        "memory_id": "mem-123",
        "project_id": "project-1",
    }
    store.save.assert_awaited_once_with(
        user_id="user-1",
        project_id="project-1",
        content="Remember this",
        vector=[0.2, 0.4],
        tags=["decision", "python"],
        metadata={"source": "manual"},
    )
    invalidate.assert_awaited_once_with(tmp_path / "vaults", "user-1", "project-1", "alpha")
    assert tracker.tool_calls == 1
    assert tracker.memory_saves == 1
    assert tracker.tags == {"decision", "python"}


@pytest.mark.asyncio
async def test_project_scoped_tool_requires_project_id(tmp_path: Path):
    server = create_mcp_server(_server_settings(tmp_path), AsyncMock())
    auth_token = mcp_auth_ctx.set({"sub": "user-1", "project_id": None, "jti": "session-1"})
    session_token = mcp_session_ctx.set(McpSessionTracker())

    try:
        result = await _call_tool(server, "memory", {"content": "Need a project"})
    finally:
        mcp_session_ctx.reset(session_token)
        mcp_auth_ctx.reset(auth_token)

    assert result.root.isError is True
    assert _content_text(result) == "This MCP action requires a project-scoped token"


@pytest.mark.asyncio
async def test_recall_tool_searches_with_embed_and_profile(tmp_path: Path):
    store = AsyncMock()
    _recall_row = {
        "memory_id": "mem-1",
        "content": "Stored memory text for previews",
        "tags": ["ops"],
        "score": 0.88,
        "created_at": 1714176000,
    }
    store.hybrid_search.return_value = [_recall_row]
    profile_fn = AsyncMock(return_value={"static": ["prefers uv"], "dynamic": ["recent test work"]})
    server = create_mcp_server(_server_settings(tmp_path), store, profile_fn=profile_fn)
    tracker = McpSessionTracker()
    auth_token = mcp_auth_ctx.set({"sub": "user-1", "project_id": "project-1", "jti": "session-1"})
    session_token = mcp_session_ctx.set(tracker)

    try:
        with (
            patch("piloci.mcp.server.embed_one", AsyncMock(return_value=[0.9])),
            patch(
                "piloci.mcp.server.get_settings",
                return_value=SimpleNamespace(
                    vault_dir=tmp_path / "vaults", export_dir=tmp_path / "exports"
                ),
            ),
        ):
            result = await _call_tool(
                server,
                "recall",
                {"query": "preview search", "tags": ["ops"], "limit": 3},
            )
    finally:
        mcp_session_ctx.reset(session_token)
        mcp_auth_ctx.reset(auth_token)

    payload = _content_json(result)
    assert payload["mode"] == "preview"
    assert payload["total"] == 1
    assert payload["profile"] == {"static": ["prefers uv"], "dynamic": ["recent test work"]}
    assert payload["memories"][0]["id"] == "mem-1"
    assert payload["memories"][0]["excerpt"].startswith("Stored memory text")
    store.hybrid_search.assert_awaited_once_with(
        user_id="user-1",
        project_id="project-1",
        query_text="preview search",
        query_vector=[0.9],
        top_k=3,
        tags=["ops"],
    )
    profile_fn.assert_awaited_once_with("user-1", "project-1")
    assert tracker.tool_calls == 1
    assert tracker.recall_calls == 1
    assert tracker.tags == {"ops"}


@pytest.mark.asyncio
async def test_list_projects_tool_uses_callback_when_available(tmp_path: Path):
    projects_fn = AsyncMock(return_value=[{"id": "project-1", "slug": "alpha"}])
    server = create_mcp_server(_server_settings(tmp_path), AsyncMock(), projects_fn=projects_fn)
    tracker = McpSessionTracker()
    auth_token = mcp_auth_ctx.set({"sub": "user-1", "project_id": None, "jti": "session-1"})
    session_token = mcp_session_ctx.set(tracker)

    try:
        result = await _call_tool(server, "listProjects", {"refresh": True})
    finally:
        mcp_session_ctx.reset(session_token)
        mcp_auth_ctx.reset(auth_token)

    assert _content_json(result) == {"projects": [{"id": "project-1", "slug": "alpha"}]}
    projects_fn.assert_awaited_once_with("user-1", True)
    assert tracker.tool_calls == 1
    assert tracker.list_projects_calls == 1


@pytest.mark.asyncio
async def test_list_projects_tool_returns_empty_when_callback_missing(tmp_path: Path):
    server = create_mcp_server(_server_settings(tmp_path), AsyncMock())
    auth_token = mcp_auth_ctx.set({"sub": "user-1", "project_id": None, "jti": "session-1"})
    session_token = mcp_session_ctx.set(McpSessionTracker())

    try:
        result = await _call_tool(server, "listProjects", {"refresh": False})
    finally:
        mcp_session_ctx.reset(session_token)
        mcp_auth_ctx.reset(auth_token)

    assert _content_json(result) == {"projects": []}


@pytest.mark.asyncio
async def test_whoami_tool_returns_identity_payload(tmp_path: Path):
    server = create_mcp_server(_server_settings(tmp_path), AsyncMock())
    tracker = McpSessionTracker()
    auth_token = mcp_auth_ctx.set(
        {
            "sub": "user-1",
            "project_id": "project-1",
            "email": "user@example.com",
            "scope": "mcp",
            "jti": "session-1",
        }
    )
    session_token = mcp_session_ctx.set(tracker)

    try:
        result = await _call_tool(server, "whoAmI")
    finally:
        mcp_session_ctx.reset(session_token)
        mcp_auth_ctx.reset(auth_token)

    assert _content_json(result) == {
        "userId": "user-1",
        "projectId": "project-1",
        "email": "user@example.com",
        "scope": "mcp",
        "sessionId": "session-1",
        "client": None,
    }
    assert tracker.tool_calls == 1
    assert tracker.whoami_calls == 1


@pytest.mark.asyncio
async def test_recommend_and_contradict_tools_use_instinct_store(tmp_path: Path):
    instincts_store = AsyncMock()
    instincts_store.list_instincts.return_value = [
        {"instinct_id": "inst-1", "domain": "testing", "confidence": 0.7}
    ]
    instincts_store.contradict.return_value = True
    server = create_mcp_server(
        _server_settings(tmp_path),
        AsyncMock(),
        instincts_store=instincts_store,
    )
    auth_token = mcp_auth_ctx.set({"sub": "user-1", "project_id": "project-1", "jti": "session-1"})
    session_token = mcp_session_ctx.set(McpSessionTracker())

    try:
        recommend_result = await _call_tool(
            server,
            "recommend",
            RecommendInput(domain="testing", min_confidence=0.5, limit=5).model_dump(),
        )
        contradict_result = await _call_tool(
            server,
            "contradict",
            ContradictInput(instinct_id="inst-1").model_dump(),
        )
    finally:
        mcp_session_ctx.reset(session_token)
        mcp_auth_ctx.reset(auth_token)

    recommend_payload = _content_json(recommend_result)
    contradict_payload = _content_json(contradict_result)
    assert recommend_payload["total"] == 1
    assert recommend_payload["instincts"][0]["instinct_id"] == "inst-1"
    assert "suggested_skills" in recommend_payload["instincts"][0]
    assert contradict_payload == {
        "success": True,
        "action": "confidence_decayed",
        "instinct_id": "inst-1",
    }
    instincts_store.list_instincts.assert_awaited_once_with(
        user_id="user-1",
        project_id="project-1",
        domain="testing",
        min_confidence=0.5,
        limit=5,
    )
    instincts_store.contradict.assert_awaited_once_with(
        user_id="user-1",
        project_id="project-1",
        instinct_id="inst-1",
    )


@pytest.mark.asyncio
async def test_recommend_and_contradict_return_disabled_errors_without_store(tmp_path: Path):
    server = create_mcp_server(_server_settings(tmp_path), AsyncMock())
    auth_token = mcp_auth_ctx.set({"sub": "user-1", "project_id": "project-1", "jti": "session-1"})
    session_token = mcp_session_ctx.set(McpSessionTracker())

    try:
        recommend_result = await _call_tool(server, "recommend", {"limit": 2})
        contradict_result = await _call_tool(server, "contradict", {"instinct_id": "inst-1"})
    finally:
        mcp_session_ctx.reset(session_token)
        mcp_auth_ctx.reset(auth_token)

    assert _content_json(recommend_result) == {
        "instincts": [],
        "total": 0,
        "error": "instincts not enabled",
    }
    assert _content_json(contradict_result) == {
        "success": False,
        "error": "instincts not enabled",
    }


@pytest.mark.asyncio
async def test_unknown_tool_raises_value_error(tmp_path: Path):
    server = create_mcp_server(_server_settings(tmp_path), AsyncMock())
    auth_token = mcp_auth_ctx.set({"sub": "user-1", "project_id": "project-1", "jti": "session-1"})
    session_token = mcp_session_ctx.set(McpSessionTracker())

    try:
        result = await _call_tool(server, "missing")
    finally:
        mcp_session_ctx.reset(session_token)
        mcp_auth_ctx.reset(auth_token)

    assert result.root.isError is True
    assert _content_text(result) == "Unknown tool: missing"


@pytest.mark.asyncio
async def test_read_resource_returns_profile_projects_and_recent(tmp_path: Path):
    profile_fn = AsyncMock(return_value={"static": ["pref"], "dynamic": ["recent"]})
    projects_fn = AsyncMock(return_value=[{"id": "project-1"}])
    recent_fn = AsyncMock(return_value=[{"memory_id": "mem-1"}])
    server = create_mcp_server(
        _server_settings(tmp_path),
        AsyncMock(),
        profile_fn=profile_fn,
        projects_fn=projects_fn,
        recent_fn=recent_fn,
    )
    auth_token = mcp_auth_ctx.set({"sub": "user-1", "project_id": "project-1", "jti": "session-1"})

    try:
        profile_result = await _read_resource(server, RESOURCE_PROFILE)
        projects_result = await _read_resource(server, RESOURCE_PROJECTS)
        recent_result = await _read_resource(server, RESOURCE_RECENT)
    finally:
        mcp_auth_ctx.reset(auth_token)

    assert orjson.loads(_resource_text(profile_result)) == {
        "static": ["pref"],
        "dynamic": ["recent"],
    }
    assert orjson.loads(_resource_text(projects_result)) == {"projects": [{"id": "project-1"}]}
    assert orjson.loads(_resource_text(recent_result)) == {"memories": [{"memory_id": "mem-1"}]}
    profile_fn.assert_awaited_once_with("user-1", "project-1")
    projects_fn.assert_awaited_once_with("user-1", False)
    recent_fn.assert_awaited_once_with("user-1", "project-1", 20)


@pytest.mark.asyncio
async def test_read_resource_unknown_uri_raises_value_error(tmp_path: Path):
    server = create_mcp_server(_server_settings(tmp_path), AsyncMock())
    auth_token = mcp_auth_ctx.set({"sub": "user-1", "project_id": "project-1", "jti": "session-1"})

    try:
        with pytest.raises(ValueError, match="Unknown resource"):
            await _read_resource(server, "piloci://missing")
    finally:
        mcp_auth_ctx.reset(auth_token)


@pytest.mark.asyncio
async def test_get_prompt_builds_context_and_parses_include_recent_string(tmp_path: Path):
    profile_fn = AsyncMock(return_value={"static": ["prefers uv"], "dynamic": ["recent deploy"]})
    server = create_mcp_server(_server_settings(tmp_path), AsyncMock(), profile_fn=profile_fn)
    auth_token = mcp_auth_ctx.set({"sub": "user-1", "project_id": "project-1", "jti": "session-1"})

    try:
        result = await _get_prompt(server, CONTEXT_PROMPT_NAME, {"include_recent": "false"})
    finally:
        mcp_auth_ctx.reset(auth_token)

    prompt_text = result.root.messages[0].content.text
    assert result.root.description == "piloci user context"
    assert "prefers uv" in prompt_text
    assert "recent deploy" not in prompt_text
    profile_fn.assert_awaited_once_with("user-1", "project-1")


@pytest.mark.asyncio
async def test_get_prompt_rejects_unknown_prompt_name(tmp_path: Path):
    server = create_mcp_server(_server_settings(tmp_path), AsyncMock())
    auth_token = mcp_auth_ctx.set({"sub": "user-1", "project_id": "project-1", "jti": "session-1"})

    try:
        with pytest.raises(ValueError, match="Unknown prompt: missing"):
            await _get_prompt(server, "missing")
    finally:
        mcp_auth_ctx.reset(auth_token)
