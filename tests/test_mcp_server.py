from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from piloci.config import Settings
from piloci.mcp.server import (
    TOOL_DEFINITIONS,
    _build_context_text,
    _make_tool,
    _resource_list,
    _resource_uri,
    create_mcp_server,
)


def test_make_tool_returns_valid_tool():
    from piloci.tools.memory_tools import MemoryInput

    tool = _make_tool("test", "test desc", MemoryInput)
    assert tool.name == "test"
    assert tool.description == "test desc"
    assert "properties" in tool.inputSchema


def test_tool_definitions_count():
    assert len(TOOL_DEFINITIONS) == 7


def test_tool_definitions_names():
    names = {t.name for t in TOOL_DEFINITIONS}
    assert names == {
        "memory",
        "recall",
        "listProjects",
        "whoAmI",
        "init",
        "recommend",
        "contradict",
    }


def test_resource_list_returns_three():
    resources = _resource_list()
    assert len(resources) == 3
    uris = {str(r.uri) for r in resources}
    assert "piloci://profile" in uris
    assert "piloci://projects" in uris
    assert "piloci://recent" in uris


def test_resource_uri_returns_anyurl():
    uri = _resource_uri("piloci://profile")
    assert str(uri) == "piloci://profile"


def test_build_context_text_with_profile():
    text = _build_context_text({"static": ["pref1"], "dynamic": ["recent1"]})
    assert "User Context" in text
    assert "pref1" in text
    assert "recent1" in text


def test_build_context_text_no_profile():
    text = _build_context_text(None)
    assert "No user profile yet" in text


def test_build_context_text_static_only():
    text = _build_context_text({"static": ["a"], "dynamic": []})
    assert "a" in text


def test_build_context_text_exclude_recent():
    text = _build_context_text({"static": ["a"], "dynamic": ["secret"]}, include_recent=False)
    assert "a" in text
    assert "secret" not in text


def test_create_mcp_server_returns_server():
    settings = MagicMock(spec=Settings)
    store = AsyncMock()
    server = create_mcp_server(settings, store)
    assert server is not None
    assert server.name == "piloci"
