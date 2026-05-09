"""Sync Piloci client tests using respx."""

from __future__ import annotations

import httpx
import pytest
import respx

from piloci_client import (
    Piloci,
    PilociAuthError,
    PilociPermissionError,
    PilociServerError,
    PilociValidationError,
)
from piloci_client._errors import PilociError

BASE = "https://piloci.test"


def make_client(**kwargs) -> Piloci:
    return Piloci(base_url=BASE, token="test-token", **kwargs)


# ---------------------------------------------------------------------------
# Fixtures: typical server responses
# ---------------------------------------------------------------------------

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
# Tests: happy paths
# ---------------------------------------------------------------------------


@respx.mock
def test_memory_save():
    respx.post(f"{BASE}/api/v1/memory").mock(
        return_value=httpx.Response(200, json=MEMORY_SAVE_RESP)
    )
    client = make_client()
    result = client.memory.save("we decided to use argon2id", tags=["security"])
    assert result.success is True
    assert result.action == "save"
    assert result.memory_id == "mem-001"
    assert result.raw == MEMORY_SAVE_RESP


@respx.mock
def test_memory_delete():
    respx.post(f"{BASE}/api/v1/memory").mock(
        return_value=httpx.Response(200, json=MEMORY_FORGET_RESP)
    )
    client = make_client()
    result = client.memory.delete("mem-001")
    assert result.success is True
    assert result.action == "forget"
    assert result.memory_id == "mem-001"


@respx.mock
def test_recall():
    respx.post(f"{BASE}/api/v1/recall").mock(return_value=httpx.Response(200, json=RECALL_RESP))
    client = make_client()
    result = client.recall(query="what auth did we pick?", limit=5)
    assert result.mode == "preview"
    assert result.total == 1
    assert len(result.previews) == 1
    assert result.previews[0].score == pytest.approx(0.92)
    assert result.previews[0].tags == ["security"]
    assert result.raw == RECALL_RESP


@respx.mock
def test_projects_list():
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=httpx.Response(200, json=PROJECTS_RESP))
    client = make_client()
    result = client.projects.list()
    assert len(result.projects) == 1
    assert result.projects[0].id == "proj-abc"
    assert result.projects[0].slug == "my-project"


@respx.mock
def test_projects_list_refresh():
    route = respx.get(f"{BASE}/api/v1/projects").mock(
        return_value=httpx.Response(200, json=PROJECTS_RESP)
    )
    client = make_client()
    client.projects.list(refresh=True)
    assert "refresh=true" in str(route.calls[0].request.url)


@respx.mock
def test_whoami():
    respx.get(f"{BASE}/api/v1/whoami").mock(return_value=httpx.Response(200, json=WHOAMI_RESP))
    client = make_client()
    result = client.whoami()
    assert result.user_id == "user-123"
    assert result.email == "dev@example.com"
    assert result.project_id == "proj-abc"


@respx.mock
def test_projects_init():
    respx.post(f"{BASE}/api/v1/init").mock(return_value=httpx.Response(200, json=INIT_RESP))
    client = make_client()
    result = client.projects.init(cwd="/home/user/my-project")
    assert result.success is True
    assert result.project_id == "proj-abc"
    assert "CLAUDE.md" in result.files


@respx.mock
def test_recommend():
    respx.post(f"{BASE}/api/v1/recommend").mock(
        return_value=httpx.Response(200, json=RECOMMEND_RESP)
    )
    client = make_client()
    result = client.recommend(domain="testing", min_confidence=0.5)
    assert result.total == 1
    assert result.instincts[0].instinct_id == "inst-001"
    assert result.instincts[0].confidence == pytest.approx(0.75)
    assert result.instincts[0].promoted is True


@respx.mock
def test_contradict():
    respx.post(f"{BASE}/api/v1/contradict").mock(
        return_value=httpx.Response(200, json=CONTRADICT_RESP)
    )
    client = make_client()
    result = client.contradict("inst-001")
    assert result.success is True
    assert result.action == "confidence_decayed"
    assert result.instinct_id == "inst-001"


# ---------------------------------------------------------------------------
# Tests: error mapping
# ---------------------------------------------------------------------------


@respx.mock
def test_401_raises_auth_error():
    respx.post(f"{BASE}/api/v1/recall").mock(
        return_value=httpx.Response(401, json={"detail": "Unauthorized"})
    )
    client = make_client()
    with pytest.raises(PilociAuthError) as exc_info:
        client.recall(query="test")
    assert exc_info.value.status_code == 401


@respx.mock
def test_403_raises_permission_error():
    respx.post(f"{BASE}/api/v1/recall").mock(
        return_value=httpx.Response(403, json={"detail": "Forbidden"})
    )
    client = make_client()
    with pytest.raises(PilociPermissionError) as exc_info:
        client.recall(query="test")
    assert exc_info.value.status_code == 403
    assert "project_id" in str(exc_info.value)


@respx.mock
def test_422_raises_validation_error():
    body = {"detail": [{"loc": ["body", "query"], "msg": "field required"}]}
    respx.post(f"{BASE}/api/v1/recall").mock(return_value=httpx.Response(422, json=body))
    client = make_client()
    with pytest.raises(PilociValidationError) as exc_info:
        client.recall(query="test")
    assert exc_info.value.status_code == 422
    assert exc_info.value.details is not None


@respx.mock
def test_500_raises_server_error():
    respx.post(f"{BASE}/api/v1/memory").mock(
        return_value=httpx.Response(500, json={"detail": "Internal Server Error"})
    )
    client = make_client()
    with pytest.raises(PilociServerError) as exc_info:
        client.memory.save("oops")
    assert exc_info.value.status_code == 500


@respx.mock
def test_unexpected_status_raises_piloci_error():
    respx.get(f"{BASE}/api/v1/whoami").mock(
        return_value=httpx.Response(429, json={"detail": "too many requests"})
    )
    client = make_client()
    with pytest.raises(PilociError) as exc_info:
        client.whoami()
    assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# Tests: request mechanics
# ---------------------------------------------------------------------------


@respx.mock
def test_auth_header_sent():
    route = respx.post(f"{BASE}/api/v1/recall").mock(
        return_value=httpx.Response(200, json=RECALL_RESP)
    )
    client = make_client()
    client.recall(query="test")
    auth = route.calls[0].request.headers.get("authorization", "")
    assert auth == "Bearer test-token"


@respx.mock
def test_user_agent_header():
    route = respx.get(f"{BASE}/api/v1/whoami").mock(
        return_value=httpx.Response(200, json=WHOAMI_RESP)
    )
    client = make_client()
    client.whoami()
    ua = route.calls[0].request.headers.get("user-agent", "")
    assert ua.startswith("piloci-client-python/")


@respx.mock
def test_project_header_forwarded():
    route = respx.post(f"{BASE}/api/v1/recall").mock(
        return_value=httpx.Response(200, json=RECALL_RESP)
    )
    client = make_client()
    client.recall(query="test", project="my-project")
    assert route.calls[0].request.headers.get("x-piloci-project") == "my-project"


def test_timeout_config():
    client = make_client(timeout=5.0)
    assert client._http.timeout.connect == pytest.approx(5.0)


@respx.mock
def test_context_manager():
    respx.get(f"{BASE}/api/v1/whoami").mock(return_value=httpx.Response(200, json=WHOAMI_RESP))
    with make_client() as client:
        result = client.whoami()
    assert result.user_id == "user-123"
