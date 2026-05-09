"""Async AsyncPiloci client tests using respx."""

from __future__ import annotations

import httpx
import pytest
import respx

from piloci_client import (
    AsyncPiloci,
    PilociAuthError,
    PilociPermissionError,
    PilociServerError,
    PilociValidationError,
)

BASE = "https://piloci.test"


def make_client(**kwargs) -> AsyncPiloci:
    return AsyncPiloci(base_url=BASE, token="test-token", **kwargs)


# Reuse same fixtures as sync tests
MEMORY_SAVE_RESP = {
    "success": True,
    "action": "save",
    "memory_id": "mem-001",
    "project_id": "proj-abc",
}

MEMORY_FORGET_RESP = {
    "success": True,
    "action": "forget",
    "memory_id": "mem-001",
}

RECALL_RESP = {
    "mode": "preview",
    "total": 1,
    "memories": [
        {
            "id": "mem-001",
            "score": 0.92,
            "tags": ["security"],
            "excerpt": "we decided to use argon2id...",
            "length": 35,
            "created_at": "2026-05-09T12:00:00Z",
        }
    ],
}

PROJECTS_RESP = {
    "projects": [
        {
            "id": "proj-abc",
            "name": "My Project",
            "slug": "my-project",
            "cwd": "/home/user/my-project",
        }
    ]
}

WHOAMI_RESP = {
    "userId": "user-123",
    "projectId": "proj-abc",
    "email": "dev@example.com",
    "scope": "project",
    "sessionId": "sess-xyz",
    "client": None,
}

INIT_RESP = {
    "success": True,
    "project_id": "proj-abc",
    "project_name": "my-project",
    "anchor": "## piLoci Memory",
    "files": {"CLAUDE.md": "## piLoci Memory\n...", "AGENTS.md": "## piLoci Memory\n..."},
    "instructions": "For each file...",
}

RECOMMEND_RESP = {
    "instincts": [
        {
            "instinct_id": "inst-001",
            "domain": "testing",
            "pattern": "always write tests first",
            "confidence": 0.75,
            "count": 5,
            "promoted": True,
            "suggested_skills": ["pytest"],
        }
    ],
    "total": 1,
    "hint": "Use contradict to lower confidence on wrong patterns.",
}

CONTRADICT_RESP = {
    "success": True,
    "action": "confidence_decayed",
    "instinct_id": "inst-001",
}


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


@respx.mock
async def test_async_memory_save():
    respx.post(f"{BASE}/api/v1/memory").mock(
        return_value=httpx.Response(200, json=MEMORY_SAVE_RESP)
    )
    async with make_client() as client:
        result = await client.memory.save("we decided to use argon2id", tags=["security"])
    assert result.success is True
    assert result.memory_id == "mem-001"
    assert result.raw == MEMORY_SAVE_RESP


@respx.mock
async def test_async_memory_delete():
    respx.post(f"{BASE}/api/v1/memory").mock(
        return_value=httpx.Response(200, json=MEMORY_FORGET_RESP)
    )
    async with make_client() as client:
        result = await client.memory.delete("mem-001")
    assert result.success is True
    assert result.action == "forget"


@respx.mock
async def test_async_recall():
    respx.post(f"{BASE}/api/v1/recall").mock(return_value=httpx.Response(200, json=RECALL_RESP))
    async with make_client() as client:
        result = await client.recall(query="what auth did we pick?", limit=5)
    assert result.mode == "preview"
    assert len(result.previews) == 1
    assert result.previews[0].score == pytest.approx(0.92)


@respx.mock
async def test_async_projects_list():
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=httpx.Response(200, json=PROJECTS_RESP))
    async with make_client() as client:
        result = await client.projects.list()
    assert len(result.projects) == 1
    assert result.projects[0].slug == "my-project"


@respx.mock
async def test_async_whoami():
    respx.get(f"{BASE}/api/v1/whoami").mock(return_value=httpx.Response(200, json=WHOAMI_RESP))
    async with make_client() as client:
        result = await client.whoami()
    assert result.user_id == "user-123"
    assert result.email == "dev@example.com"


@respx.mock
async def test_async_projects_init():
    respx.post(f"{BASE}/api/v1/init").mock(return_value=httpx.Response(200, json=INIT_RESP))
    async with make_client() as client:
        result = await client.projects.init(cwd="/home/user/my-project")
    assert result.success is True
    assert "AGENTS.md" in result.files


@respx.mock
async def test_async_recommend():
    respx.post(f"{BASE}/api/v1/recommend").mock(
        return_value=httpx.Response(200, json=RECOMMEND_RESP)
    )
    async with make_client() as client:
        result = await client.recommend(min_confidence=0.5)
    assert result.total == 1
    assert result.instincts[0].domain == "testing"


@respx.mock
async def test_async_contradict():
    respx.post(f"{BASE}/api/v1/contradict").mock(
        return_value=httpx.Response(200, json=CONTRADICT_RESP)
    )
    async with make_client() as client:
        result = await client.contradict("inst-001")
    assert result.success is True
    assert result.action == "confidence_decayed"


# ---------------------------------------------------------------------------
# Error mapping tests (async parity with sync)
# ---------------------------------------------------------------------------


@respx.mock
async def test_async_401_raises_auth_error():
    respx.post(f"{BASE}/api/v1/recall").mock(
        return_value=httpx.Response(401, json={"detail": "Unauthorized"})
    )
    async with make_client() as client:
        with pytest.raises(PilociAuthError) as exc_info:
            await client.recall(query="test")
    assert exc_info.value.status_code == 401


@respx.mock
async def test_async_403_raises_permission_error():
    respx.post(f"{BASE}/api/v1/memory").mock(
        return_value=httpx.Response(403, json={"detail": "Forbidden"})
    )
    async with make_client() as client:
        with pytest.raises(PilociPermissionError) as exc_info:
            await client.memory.save("test")
    assert exc_info.value.status_code == 403
    assert "project_id" in str(exc_info.value)


@respx.mock
async def test_async_422_raises_validation_error():
    body = {"detail": [{"loc": ["body", "instinct_id"], "msg": "field required"}]}
    respx.post(f"{BASE}/api/v1/contradict").mock(return_value=httpx.Response(422, json=body))
    async with make_client() as client:
        with pytest.raises(PilociValidationError) as exc_info:
            await client.contradict("bad-id")
    assert exc_info.value.status_code == 422


@respx.mock
async def test_async_500_raises_server_error():
    respx.post(f"{BASE}/api/v1/recommend").mock(
        return_value=httpx.Response(500, json={"detail": "Internal Server Error"})
    )
    async with make_client() as client:
        with pytest.raises(PilociServerError) as exc_info:
            await client.recommend()
    assert exc_info.value.status_code == 500


@respx.mock
async def test_async_project_header_forwarded():
    route = respx.post(f"{BASE}/api/v1/recall").mock(
        return_value=httpx.Response(200, json=RECALL_RESP)
    )
    async with make_client() as client:
        await client.recall(query="test", project="my-project")
    assert route.calls[0].request.headers.get("x-piloci-project") == "my-project"


@respx.mock
async def test_async_user_agent_header():
    route = respx.get(f"{BASE}/api/v1/whoami").mock(
        return_value=httpx.Response(200, json=WHOAMI_RESP)
    )
    async with make_client() as client:
        await client.whoami()
    ua = route.calls[0].request.headers.get("user-agent", "")
    assert ua.startswith("piloci-client-python/")


def test_async_timeout_config():
    client = make_client(timeout=10.0)
    assert client._http.timeout.connect == pytest.approx(10.0)
