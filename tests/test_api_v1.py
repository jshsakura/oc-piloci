from __future__ import annotations

"""Tests for the /api/v1/* REST shim layer.

Strategy: build minimal Starlette Request objects (same pattern as other
test_api_*.py files), monkeypatch store / embed / DB helpers, and verify that
the shim correctly:
  - enforces JWT auth (401)
  - enforces project-scope for project-gated endpoints (403)
  - validates request bodies with Pydantic (422)
  - delegates to the right handle_* function (200)
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import orjson
import pytest
from starlette.requests import Request

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    body: dict | None = None,
    user: dict | None = None,
    method: str = "POST",
    path: str = "/api/v1/test",
    query_string: bytes = b"",
    store: object | None = None,
    instincts_store: object | None = None,
) -> Request:
    app_state = SimpleNamespace(
        store=store or AsyncMock(),
        instincts_store=instincts_store,
    )
    state: dict = {}
    if user is not None:
        state["user"] = user

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query_string,
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "state": state,
        "path_params": {},
        "app": SimpleNamespace(state=app_state),
        "scheme": "https",
        "server": ("testserver", 443),
    }

    payload = orjson.dumps(body or {})

    async def receive() -> dict:
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(scope, receive)


# ---------------------------------------------------------------------------
# POST /api/v1/memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_memory_401_no_auth():
    from piloci.api.v1 import route_v1_memory

    req = _make_request(body={"content": "hello", "action": "save"}, user=None)
    resp = await route_v1_memory(req)
    assert resp.status_code == 401
    assert orjson.loads(resp.body)["error"] == "Unauthorized"


@pytest.mark.asyncio
async def test_v1_memory_403_no_project_scope():
    from piloci.api.v1 import route_v1_memory

    req = _make_request(
        body={"content": "hello", "action": "save"},
        user={"sub": "user-1"},  # no project_id
    )
    resp = await route_v1_memory(req)
    assert resp.status_code == 403
    assert orjson.loads(resp.body)["error"] == "project-scoped token required"


@pytest.mark.asyncio
async def test_v1_memory_422_validation_error():
    from piloci.api.v1 import route_v1_memory

    # action must be 'save' or 'forget', not 'delete'
    req = _make_request(
        body={"content": "hello", "action": "delete"},
        user={"sub": "user-1", "project_id": "proj-1"},
    )
    resp = await route_v1_memory(req)
    assert resp.status_code == 422
    payload = orjson.loads(resp.body)
    assert payload["error"] == "validation error"
    assert "details" in payload


@pytest.mark.asyncio
async def test_v1_memory_200_save(monkeypatch):
    from piloci.api import v1
    from piloci.tools import memory_tools

    saved_args: list = []

    async def fake_handle_memory(args, user_id, project_id, store, embed_fn):
        saved_args.append((args, user_id, project_id))
        return {"success": True, "action": "save", "memory_id": "mem-1", "project_id": project_id}

    async def fake_invalidate(vault_dir, user_id, project_id, project_slug=None):
        pass

    monkeypatch.setattr(memory_tools, "handle_memory", fake_handle_memory)
    monkeypatch.setattr(v1, "invalidate_project_vault_cache", fake_invalidate)

    # Patch get_settings so vault_dir is accessible
    monkeypatch.setattr(
        v1,
        "get_settings",
        lambda: SimpleNamespace(
            vault_dir="/tmp/vault",
            export_dir="/tmp/exports",
            embed_model="BAAI/bge-small-en-v1.5",
            embed_cache_dir=None,
            embed_lru_size=100,
            embed_executor_workers=1,
            embed_max_concurrency=1,
        ),
    )

    req = _make_request(
        body={"content": "important fact", "action": "save"},
        user={"sub": "user-1", "project_id": "proj-1"},
    )
    from piloci.api.v1 import route_v1_memory

    resp = await route_v1_memory(req)
    assert resp.status_code == 200
    payload = orjson.loads(resp.body)
    assert payload["success"] is True
    assert payload["memory_id"] == "mem-1"
    assert len(saved_args) == 1
    _, uid, pid = saved_args[0]
    assert uid == "user-1"
    assert pid == "proj-1"


# ---------------------------------------------------------------------------
# POST /api/v1/recall
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_recall_401_no_auth():
    from piloci.api.v1 import route_v1_recall

    req = _make_request(body={"query": "what did I do"}, user=None)
    resp = await route_v1_recall(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_v1_recall_403_no_project_scope():
    from piloci.api.v1 import route_v1_recall

    req = _make_request(
        body={"query": "what did I do"},
        user={"sub": "user-1"},
    )
    resp = await route_v1_recall(req)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_v1_recall_422_missing_query():
    from piloci.api.v1 import route_v1_recall

    # fetch_ids is None and query is None — passes validation (both optional)
    # but limit out-of-range triggers 422
    req = _make_request(
        body={"limit": 999},
        user={"sub": "user-1", "project_id": "proj-1"},
    )
    resp = await route_v1_recall(req)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_v1_recall_200_happy_path(monkeypatch):
    from piloci.api import v1
    from piloci.tools import memory_tools

    async def fake_handle_recall(args, user_id, project_id, store, embed_fn, **kw):
        return {"memories": [], "mode": "preview", "total": 0}

    async def fake_profile_fn(user_id, project_id):
        return None

    monkeypatch.setattr(memory_tools, "handle_recall", fake_handle_recall)
    monkeypatch.setattr(v1, "_build_profile_fn", AsyncMock(return_value=fake_profile_fn))
    monkeypatch.setattr(
        v1,
        "get_settings",
        lambda: SimpleNamespace(
            export_dir="/tmp/exports",
            embed_model="BAAI/bge-small-en-v1.5",
            embed_cache_dir=None,
            embed_lru_size=100,
            embed_executor_workers=1,
            embed_max_concurrency=1,
        ),
    )

    req = _make_request(
        body={"query": "show me memories"},
        user={"sub": "user-1", "project_id": "proj-1"},
    )
    from piloci.api.v1 import route_v1_recall

    resp = await route_v1_recall(req)
    assert resp.status_code == 200
    assert orjson.loads(resp.body)["total"] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_projects_401_no_auth():
    from piloci.api.v1 import route_v1_projects

    req = _make_request(method="GET", user=None)
    resp = await route_v1_projects(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_v1_projects_200_happy_path(monkeypatch):
    from piloci.api import v1
    from piloci.tools import memory_tools

    async def fake_handle_list_projects(args, user_id, projects_fn):
        return {"projects": [{"id": "p1", "slug": "my-project", "name": "My Project"}]}

    async def fake_projects_fn(user_id, refresh):
        return []

    monkeypatch.setattr(memory_tools, "handle_list_projects", fake_handle_list_projects)
    monkeypatch.setattr(v1, "_build_projects_fn", AsyncMock(return_value=fake_projects_fn))

    req = _make_request(method="GET", user={"sub": "user-1"})
    from piloci.api.v1 import route_v1_projects

    resp = await route_v1_projects(req)
    assert resp.status_code == 200
    payload = orjson.loads(resp.body)
    assert len(payload["projects"]) == 1


# ---------------------------------------------------------------------------
# GET /api/v1/whoami
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_whoami_401_no_auth():
    from piloci.api.v1 import route_v1_whoami

    req = _make_request(method="GET", user=None)
    resp = await route_v1_whoami(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_v1_whoami_200_happy_path():
    from piloci.api.v1 import route_v1_whoami

    user = {
        "sub": "user-42",
        "email": "test@example.com",
        "project_id": "proj-1",
        "jti": "sess-abc",
        "scope": "user",
    }
    req = _make_request(method="GET", user=user)
    resp = await route_v1_whoami(req)
    assert resp.status_code == 200
    payload = orjson.loads(resp.body)
    assert payload["userId"] == "user-42"
    assert payload["email"] == "test@example.com"
    assert payload["projectId"] == "proj-1"
    assert payload["sessionId"] == "sess-abc"


# ---------------------------------------------------------------------------
# POST /api/v1/init
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_init_401_no_auth():
    from piloci.api.v1 import route_v1_init

    req = _make_request(body={"cwd": "/home/user/myproject"}, user=None)
    resp = await route_v1_init(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_v1_init_422_validation(monkeypatch):
    from piloci.api.v1 import route_v1_init

    # cwd must be str or None; pass an int to trigger validation error
    req = _make_request(
        body={"cwd": 12345},
        user={"sub": "user-1"},
    )
    resp = await route_v1_init(req)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_v1_init_200_happy_path(monkeypatch):
    from piloci.api import v1
    from piloci.tools import memory_tools

    async def fake_handle_init(args, user_id, project_id, projects_fn, create_project_fn):
        return {
            "success": True,
            "project_id": "proj-new",
            "project_name": "myproject",
            "anchor": "## piLoci Memory",
            "files": {"CLAUDE.md": "...", "AGENTS.md": "..."},
            "instructions": "...",
        }

    async def fake_projects_fn(user_id, refresh):
        return []

    async def fake_create_project_fn(user_id, name, slug, cwd=None):
        return {"id": "proj-new", "slug": slug, "name": name, "cwd": cwd}

    monkeypatch.setattr(memory_tools, "handle_init", fake_handle_init)
    monkeypatch.setattr(v1, "_build_projects_fn", AsyncMock(return_value=fake_projects_fn))
    monkeypatch.setattr(
        v1, "_build_create_project_fn", AsyncMock(return_value=fake_create_project_fn)
    )

    req = _make_request(
        body={"cwd": "/home/user/myproject"},
        user={"sub": "user-1"},
    )
    from piloci.api.v1 import route_v1_init

    resp = await route_v1_init(req)
    assert resp.status_code == 200
    payload = orjson.loads(resp.body)
    assert payload["success"] is True
    assert payload["project_id"] == "proj-new"


# ---------------------------------------------------------------------------
# POST /api/v1/recommend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_recommend_401_no_auth():
    from piloci.api.v1 import route_v1_recommend

    req = _make_request(body={}, user=None)
    resp = await route_v1_recommend(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_v1_recommend_403_no_project_scope():
    from piloci.api.v1 import route_v1_recommend

    req = _make_request(body={}, user={"sub": "user-1"})
    resp = await route_v1_recommend(req)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_v1_recommend_422_validation_error():
    from piloci.api.v1 import route_v1_recommend

    # min_confidence out of range (> 0.9)
    req = _make_request(
        body={"min_confidence": 1.5},
        user={"sub": "user-1", "project_id": "proj-1"},
        instincts_store=AsyncMock(),
    )
    resp = await route_v1_recommend(req)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_v1_recommend_200_happy_path(monkeypatch):
    from piloci.tools import instinct_tools

    async def fake_handle_recommend(args, user_id, project_id, instincts_store):
        return {"instincts": [], "total": 0, "hint": "..."}

    monkeypatch.setattr(instinct_tools, "handle_recommend", fake_handle_recommend)

    mock_instincts = AsyncMock()
    req = _make_request(
        body={"limit": 5},
        user={"sub": "user-1", "project_id": "proj-1"},
        instincts_store=mock_instincts,
    )
    from piloci.api.v1 import route_v1_recommend

    resp = await route_v1_recommend(req)
    assert resp.status_code == 200
    assert orjson.loads(resp.body)["total"] == 0


# ---------------------------------------------------------------------------
# POST /api/v1/contradict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_contradict_401_no_auth():
    from piloci.api.v1 import route_v1_contradict

    req = _make_request(body={"instinct_id": "inst-1"}, user=None)
    resp = await route_v1_contradict(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_v1_contradict_403_no_project_scope():
    from piloci.api.v1 import route_v1_contradict

    req = _make_request(body={"instinct_id": "inst-1"}, user={"sub": "user-1"})
    resp = await route_v1_contradict(req)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_v1_contradict_422_missing_instinct_id():
    from piloci.api.v1 import route_v1_contradict

    req = _make_request(
        body={},  # instinct_id is required
        user={"sub": "user-1", "project_id": "proj-1"},
        instincts_store=AsyncMock(),
    )
    resp = await route_v1_contradict(req)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_v1_contradict_200_happy_path(monkeypatch):
    from piloci.tools import instinct_tools

    async def fake_handle_contradict(args, user_id, project_id, instincts_store):
        return {"success": True, "action": "confidence_decayed", "instinct_id": args.instinct_id}

    monkeypatch.setattr(instinct_tools, "handle_contradict", fake_handle_contradict)

    mock_instincts = AsyncMock()
    req = _make_request(
        body={"instinct_id": "inst-abc"},
        user={"sub": "user-1", "project_id": "proj-1"},
        instincts_store=mock_instincts,
    )
    from piloci.api.v1 import route_v1_contradict

    resp = await route_v1_contradict(req)
    assert resp.status_code == 200
    payload = orjson.loads(resp.body)
    assert payload["success"] is True
    assert payload["instinct_id"] == "inst-abc"
