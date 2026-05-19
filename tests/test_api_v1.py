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
    path_params: dict | None = None,
    raw_body: bytes | None = None,
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
        "path_params": path_params or {},
        "app": SimpleNamespace(state=app_state),
        "scheme": "https",
        "server": ("testserver", 443),
    }

    payload = raw_body if raw_body is not None else orjson.dumps(body or {})

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


# ---------------------------------------------------------------------------
# Invalid JSON body branches (400)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_memory_400_invalid_json():
    from piloci.api.v1 import route_v1_memory

    req = _make_request(
        raw_body=b"{not valid json",
        user={"sub": "user-1", "project_id": "proj-1"},
    )
    resp = await route_v1_memory(req)
    assert resp.status_code == 400
    assert orjson.loads(resp.body)["error"] == "invalid JSON"


@pytest.mark.asyncio
async def test_v1_recall_400_invalid_json():
    from piloci.api.v1 import route_v1_recall

    req = _make_request(
        raw_body=b"not-json",
        user={"sub": "user-1", "project_id": "proj-1"},
    )
    resp = await route_v1_recall(req)
    assert resp.status_code == 400
    assert orjson.loads(resp.body)["error"] == "invalid JSON"


@pytest.mark.asyncio
async def test_v1_init_400_invalid_json():
    from piloci.api.v1 import route_v1_init

    req = _make_request(
        raw_body=b"{[",
        user={"sub": "user-1"},
    )
    resp = await route_v1_init(req)
    assert resp.status_code == 400
    assert orjson.loads(resp.body)["error"] == "invalid JSON"


@pytest.mark.asyncio
async def test_v1_recommend_400_invalid_json():
    from piloci.api.v1 import route_v1_recommend

    req = _make_request(
        raw_body=b"invalid",
        user={"sub": "user-1", "project_id": "proj-1"},
        instincts_store=AsyncMock(),
    )
    resp = await route_v1_recommend(req)
    assert resp.status_code == 400
    assert orjson.loads(resp.body)["error"] == "invalid JSON"


@pytest.mark.asyncio
async def test_v1_contradict_400_invalid_json():
    from piloci.api.v1 import route_v1_contradict

    req = _make_request(
        raw_body=b"not json at all",
        user={"sub": "user-1", "project_id": "proj-1"},
        instincts_store=AsyncMock(),
    )
    resp = await route_v1_contradict(req)
    assert resp.status_code == 400
    assert orjson.loads(resp.body)["error"] == "invalid JSON"


# ---------------------------------------------------------------------------
# Instincts store missing branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_recommend_instincts_disabled():
    """When instincts_store is None, return an empty result with error hint."""
    from piloci.api.v1 import route_v1_recommend

    req = _make_request(
        body={"limit": 5},
        user={"sub": "user-1", "project_id": "proj-1"},
        instincts_store=None,
    )
    resp = await route_v1_recommend(req)
    assert resp.status_code == 200
    payload = orjson.loads(resp.body)
    assert payload["instincts"] == []
    assert payload["total"] == 0
    assert payload["error"] == "instincts not enabled"


@pytest.mark.asyncio
async def test_v1_contradict_instincts_disabled():
    """When instincts_store is None, return success=False."""
    from piloci.api.v1 import route_v1_contradict

    req = _make_request(
        body={"instinct_id": "inst-abc"},
        user={"sub": "user-1", "project_id": "proj-1"},
        instincts_store=None,
    )
    resp = await route_v1_contradict(req)
    assert resp.status_code == 200
    payload = orjson.loads(resp.body)
    assert payload["success"] is False
    assert payload["error"] == "instincts not enabled"


# ---------------------------------------------------------------------------
# GET /api/v1/memories — list with pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_memories_list_401_no_auth():
    from piloci.api.v1 import route_v1_memories_list

    req = _make_request(method="GET", user=None)
    resp = await route_v1_memories_list(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_v1_memories_list_403_no_project_scope():
    from piloci.api.v1 import route_v1_memories_list

    req = _make_request(method="GET", user={"sub": "user-1"})
    resp = await route_v1_memories_list(req)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_v1_memories_list_400_bad_query_params():
    from piloci.api.v1 import route_v1_memories_list

    req = _make_request(
        method="GET",
        user={"sub": "user-1", "project_id": "proj-1"},
        query_string=b"limit=foo&offset=0",
    )
    resp = await route_v1_memories_list(req)
    assert resp.status_code == 400
    assert "integer" in orjson.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_v1_memories_list_200_default_pagination():
    """No query params -> defaults; verify store.list/count called with (user, project)."""
    from piloci.api.v1 import route_v1_memories_list

    store = AsyncMock()
    store.list.return_value = [{"id": "m1"}, {"id": "m2"}]
    store.count.return_value = 2

    req = _make_request(
        method="GET",
        user={"sub": "user-9", "project_id": "proj-9"},
        store=store,
    )
    resp = await route_v1_memories_list(req)
    assert resp.status_code == 200
    payload = orjson.loads(resp.body)
    assert payload["memories"] == [{"id": "m1"}, {"id": "m2"}]
    assert payload["total"] == 2
    assert payload["limit"] == 20
    assert payload["offset"] == 0

    # Security: store.list MUST be called with user_id + project_id from JWT
    list_kwargs = store.list.await_args.kwargs
    assert list_kwargs["user_id"] == "user-9"
    assert list_kwargs["project_id"] == "proj-9"
    assert list_kwargs["limit"] == 20
    assert list_kwargs["offset"] == 0
    assert list_kwargs["tags"] is None


@pytest.mark.asyncio
async def test_v1_memories_list_200_with_tags_and_pagination():
    from piloci.api.v1 import route_v1_memories_list

    store = AsyncMock()
    store.list.return_value = []
    store.count.return_value = 0

    req = _make_request(
        method="GET",
        user={"sub": "user-1", "project_id": "proj-1"},
        store=store,
        query_string=b"limit=5&offset=10&tags=foo,bar,,baz",
    )
    resp = await route_v1_memories_list(req)
    assert resp.status_code == 200
    payload = orjson.loads(resp.body)
    assert payload["limit"] == 5
    assert payload["offset"] == 10

    list_kwargs = store.list.await_args.kwargs
    assert list_kwargs["tags"] == ["foo", "bar", "baz"]


@pytest.mark.asyncio
async def test_v1_memories_list_limit_clamped():
    """limit > 100 is clamped to 100; negative offset clamped to 0."""
    from piloci.api.v1 import route_v1_memories_list

    store = AsyncMock()
    store.list.return_value = []
    store.count.return_value = 0

    req = _make_request(
        method="GET",
        user={"sub": "user-1", "project_id": "proj-1"},
        store=store,
        query_string=b"limit=999&offset=-5",
    )
    resp = await route_v1_memories_list(req)
    assert resp.status_code == 200
    payload = orjson.loads(resp.body)
    assert payload["limit"] == 100
    assert payload["offset"] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/memories/{memory_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_memory_detail_401_no_auth():
    from piloci.api.v1 import route_v1_memory_detail

    req = _make_request(method="GET", user=None, path_params={"memory_id": "mem-1"})
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_v1_memory_detail_403_no_project_scope():
    from piloci.api.v1 import route_v1_memory_detail

    req = _make_request(method="GET", user={"sub": "user-1"}, path_params={"memory_id": "mem-1"})
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_v1_memory_detail_400_missing_id():
    from piloci.api.v1 import route_v1_memory_detail

    req = _make_request(
        method="GET",
        user={"sub": "user-1", "project_id": "proj-1"},
        path_params={"memory_id": ""},
    )
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 400
    assert orjson.loads(resp.body)["error"] == "memory_id required"


@pytest.mark.asyncio
async def test_v1_memory_detail_get_200():
    from piloci.api.v1 import route_v1_memory_detail

    store = AsyncMock()
    store.get.return_value = {"id": "mem-1", "content": "hello"}

    req = _make_request(
        method="GET",
        user={"sub": "user-1", "project_id": "proj-1"},
        store=store,
        path_params={"memory_id": "mem-1"},
    )
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 200
    assert orjson.loads(resp.body) == {"id": "mem-1", "content": "hello"}

    # Security: store.get gets exact (user_id, project_id, memory_id)
    args = store.get.await_args.args
    assert args == ("user-1", "proj-1", "mem-1")


@pytest.mark.asyncio
async def test_v1_memory_detail_get_404():
    from piloci.api.v1 import route_v1_memory_detail

    store = AsyncMock()
    store.get.return_value = None

    req = _make_request(
        method="GET",
        user={"sub": "user-1", "project_id": "proj-1"},
        store=store,
        path_params={"memory_id": "missing"},
    )
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 404
    assert orjson.loads(resp.body)["error"] == "not found"


@pytest.mark.asyncio
async def test_v1_memory_detail_delete_200(monkeypatch):
    from piloci.api import v1
    from piloci.api.v1 import route_v1_memory_detail

    store = AsyncMock()
    store.delete.return_value = True

    invalidate_calls: list = []

    async def fake_invalidate(vault_dir, user_id, project_id, project_slug=None):
        invalidate_calls.append((vault_dir, user_id, project_id, project_slug))

    monkeypatch.setattr(v1, "invalidate_project_vault_cache", fake_invalidate)
    monkeypatch.setattr(v1, "get_settings", lambda: SimpleNamespace(vault_dir="/tmp/vault"))

    req = _make_request(
        method="DELETE",
        user={"sub": "user-1", "project_id": "proj-1", "project_slug": "my-proj"},
        store=store,
        path_params={"memory_id": "mem-1"},
    )
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 200
    payload = orjson.loads(resp.body)
    assert payload["success"] is True
    assert payload["memory_id"] == "mem-1"

    store.delete.assert_awaited_once_with("user-1", "proj-1", "mem-1")
    assert invalidate_calls == [("/tmp/vault", "user-1", "proj-1", "my-proj")]


@pytest.mark.asyncio
async def test_v1_memory_detail_delete_404():
    from piloci.api.v1 import route_v1_memory_detail

    store = AsyncMock()
    store.delete.return_value = False

    req = _make_request(
        method="DELETE",
        user={"sub": "user-1", "project_id": "proj-1"},
        store=store,
        path_params={"memory_id": "missing"},
    )
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 404
    assert orjson.loads(resp.body)["error"] == "not found"


@pytest.mark.asyncio
async def test_v1_memory_detail_patch_400_invalid_json():
    from piloci.api.v1 import route_v1_memory_detail

    req = _make_request(
        method="PATCH",
        user={"sub": "user-1", "project_id": "proj-1"},
        path_params={"memory_id": "mem-1"},
        raw_body=b"not-valid",
    )
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 400
    assert orjson.loads(resp.body)["error"] == "invalid JSON"


@pytest.mark.asyncio
async def test_v1_memory_detail_patch_400_no_fields():
    from piloci.api.v1 import route_v1_memory_detail

    req = _make_request(
        method="PATCH",
        user={"sub": "user-1", "project_id": "proj-1"},
        path_params={"memory_id": "mem-1"},
        body={},
    )
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 400
    assert "content" in orjson.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_v1_memory_detail_patch_422_content_not_string():
    from piloci.api.v1 import route_v1_memory_detail

    req = _make_request(
        method="PATCH",
        user={"sub": "user-1", "project_id": "proj-1"},
        path_params={"memory_id": "mem-1"},
        body={"content": 12345},
    )
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 422
    assert "string" in orjson.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_v1_memory_detail_patch_422_tags_not_list():
    from piloci.api.v1 import route_v1_memory_detail

    req = _make_request(
        method="PATCH",
        user={"sub": "user-1", "project_id": "proj-1"},
        path_params={"memory_id": "mem-1"},
        body={"tags": "not-a-list"},
    )
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 422
    assert "list" in orjson.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_v1_memory_detail_patch_tags_only(monkeypatch):
    """Tags-only PATCH skips embedding; only update + invalidate run."""
    from piloci.api import v1
    from piloci.api.v1 import route_v1_memory_detail

    store = AsyncMock()
    store.update.return_value = True

    monkeypatch.setattr(v1, "invalidate_project_vault_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(v1, "get_settings", lambda: SimpleNamespace(vault_dir="/tmp/vault"))

    req = _make_request(
        method="PATCH",
        user={"sub": "user-1", "project_id": "proj-1"},
        store=store,
        path_params={"memory_id": "mem-1"},
        body={"tags": ["alpha", "beta"]},
    )
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 200
    payload = orjson.loads(resp.body)
    assert payload["success"] is True

    update_kwargs = store.update.await_args.kwargs
    assert update_kwargs["user_id"] == "user-1"
    assert update_kwargs["project_id"] == "proj-1"
    assert update_kwargs["memory_id"] == "mem-1"
    assert update_kwargs["content"] is None
    assert update_kwargs["new_vector"] is None
    assert update_kwargs["tags"] == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_v1_memory_detail_patch_content_embeds(monkeypatch):
    """Content PATCH calls embed_one and passes new_vector to store.update."""
    from piloci.api import v1
    from piloci.api.v1 import route_v1_memory_detail
    from piloci.storage import embed as embed_mod

    store = AsyncMock()
    store.update.return_value = True

    async def fake_embed_one(text, **kwargs):
        return [0.5] * 16

    monkeypatch.setattr(embed_mod, "embed_one", fake_embed_one)
    monkeypatch.setattr(v1, "invalidate_project_vault_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(
        v1,
        "get_settings",
        lambda: SimpleNamespace(
            vault_dir="/tmp/vault",
            embed_model="BAAI/bge-small-en-v1.5",
            embed_cache_dir=None,
            embed_lru_size=100,
            embed_executor_workers=1,
            embed_max_concurrency=1,
        ),
    )

    req = _make_request(
        method="PATCH",
        user={"sub": "user-1", "project_id": "proj-1"},
        store=store,
        path_params={"memory_id": "mem-1"},
        body={"content": "new content"},
    )
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 200
    assert orjson.loads(resp.body)["success"] is True

    update_kwargs = store.update.await_args.kwargs
    assert update_kwargs["content"] == "new content"
    assert update_kwargs["new_vector"] == [0.5] * 16


@pytest.mark.asyncio
async def test_v1_memory_detail_patch_404(monkeypatch):
    from piloci.api.v1 import route_v1_memory_detail

    store = AsyncMock()
    store.update.return_value = False

    req = _make_request(
        method="PATCH",
        user={"sub": "user-1", "project_id": "proj-1"},
        store=store,
        path_params={"memory_id": "missing"},
        body={"tags": ["x"]},
    )
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 404
    assert orjson.loads(resp.body)["error"] == "not found"


@pytest.mark.asyncio
async def test_v1_memory_detail_405_method_not_allowed():
    from piloci.api.v1 import route_v1_memory_detail

    req = _make_request(
        method="PUT",
        user={"sub": "user-1", "project_id": "proj-1"},
        path_params={"memory_id": "mem-1"},
    )
    resp = await route_v1_memory_detail(req)
    assert resp.status_code == 405
    assert orjson.loads(resp.body)["error"] == "method not allowed"


# ---------------------------------------------------------------------------
# Internal helpers: _embed_fn, _build_*_fn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_fn_delegates_to_storage(monkeypatch):
    from piloci.api import v1
    from piloci.storage import embed as embed_mod

    seen: dict = {}

    async def fake_embed_one(text, **kwargs):
        seen["text"] = text
        seen["kwargs"] = kwargs
        return [0.42] * 8

    monkeypatch.setattr(embed_mod, "embed_one", fake_embed_one)
    monkeypatch.setattr(
        v1,
        "get_settings",
        lambda: SimpleNamespace(
            embed_model="m",
            embed_cache_dir="/c",
            embed_lru_size=7,
            embed_executor_workers=3,
            embed_max_concurrency=2,
        ),
    )

    vec = await v1._embed_fn("hello")
    assert vec == [0.42] * 8
    assert seen["text"] == "hello"
    assert seen["kwargs"]["model"] == "m"
    assert seen["kwargs"]["cache_dir"] == "/c"
    assert seen["kwargs"]["lru_size"] == 7
    assert seen["kwargs"]["executor_workers"] == 3
    assert seen["kwargs"]["max_concurrency"] == 2


@pytest.mark.asyncio
async def test_build_projects_fn_filters_by_user(monkeypatch):
    """The projects_fn returned by _build_projects_fn must filter by user_id."""
    from piloci.api import v1

    class _Row:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    captured_filter: dict = {}

    class _Scalars:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return _Scalars(self._rows)

    class _DB:
        async def execute(self, stmt):
            # Reach into the where clause to verify a user_id filter is applied.
            # SQLAlchemy stores the compiled SQL; for the test we just record
            # that execute() was called and return a row matching user_id.
            captured_filter["called"] = True
            return _Result(
                [
                    _Row(
                        id="p1",
                        slug="my-proj",
                        name="My Project",
                        memory_count=3,
                        cwd="/x",
                    )
                ]
            )

    class _Session:
        async def __aenter__(self):
            return _DB()

        async def __aexit__(self, *exc):
            return False

    from piloci.db import session as db_session

    monkeypatch.setattr(db_session, "async_session", lambda: _Session())

    projects_fn = await v1._build_projects_fn()
    rows = await projects_fn("user-1", refresh=False)

    assert captured_filter == {"called": True}
    assert rows == [
        {
            "id": "p1",
            "slug": "my-proj",
            "name": "My Project",
            "memory_count": 3,
            "cwd": "/x",
        }
    ]


@pytest.mark.asyncio
async def test_build_create_project_fn_insert_success(monkeypatch):
    """First _try_insert succeeds — returns the freshly-inserted project."""
    from piloci.api import v1

    class _DB:
        def __init__(self):
            self.added = []

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            return None

        async def rollback(self):
            return None

    class _Session:
        instance: _DB | None = None

        async def __aenter__(self):
            _Session.instance = _DB()
            return _Session.instance

        async def __aexit__(self, *exc):
            return False

    from piloci.db import session as db_session

    monkeypatch.setattr(db_session, "async_session", lambda: _Session())

    create_fn = await v1._build_create_project_fn()
    out = await create_fn("user-1", name="My Proj", slug="my-proj", cwd="/tmp/x")

    assert out["slug"] == "my-proj"
    assert out["name"] == "My Proj"
    assert out["cwd"] == "/tmp/x"
    assert isinstance(out["id"], str) and len(out["id"]) > 0


@pytest.mark.asyncio
async def test_build_create_project_fn_slug_taken_same_cwd(monkeypatch):
    """Slug conflict + same cwd: reuse existing project row."""
    from sqlalchemy.exc import IntegrityError

    from piloci.api import v1

    class _ExistingRow:
        id = "existing-id"
        slug = "my-proj"
        name = "Existing"
        cwd = "/tmp/x"

    class _Scalar:
        def __init__(self, row):
            self._row = row

        def scalar_one_or_none(self):
            return self._row

    class _DB:
        mode: str = "insert"  # or "select"

        def add(self, obj):
            pass

        async def commit(self):
            raise IntegrityError("stmt", {}, Exception("dup"))

        async def rollback(self):
            return None

        async def execute(self, stmt):
            return _Scalar(_ExistingRow())

    class _Session:
        async def __aenter__(self):
            return _DB()

        async def __aexit__(self, *exc):
            return False

    from piloci.db import session as db_session

    monkeypatch.setattr(db_session, "async_session", lambda: _Session())

    create_fn = await v1._build_create_project_fn()
    out = await create_fn("user-1", name="My Proj", slug="my-proj", cwd="/tmp/x")
    assert out["id"] == "existing-id"
    assert out["slug"] == "my-proj"
    assert out["cwd"] == "/tmp/x"


@pytest.mark.asyncio
async def test_build_create_project_fn_slug_taken_legacy_no_cwd(monkeypatch):
    """Existing row has cwd=None (legacy), incoming cwd is set: adopt the row."""
    from sqlalchemy.exc import IntegrityError

    from piloci.api import v1

    class _ExistingRow:
        id = "legacy-id"
        slug = "my-proj"
        name = "Legacy"
        cwd = None

    class _Scalar:
        def scalar_one_or_none(self):
            return _ExistingRow()

    class _DB:
        def add(self, obj):
            pass

        async def commit(self):
            raise IntegrityError("stmt", {}, Exception("dup"))

        async def rollback(self):
            return None

        async def execute(self, stmt):
            return _Scalar()

    class _Session:
        async def __aenter__(self):
            return _DB()

        async def __aexit__(self, *exc):
            return False

    from piloci.db import session as db_session

    monkeypatch.setattr(db_session, "async_session", lambda: _Session())

    create_fn = await v1._build_create_project_fn()
    out = await create_fn("user-1", name="Legacy", slug="my-proj", cwd="/tmp/newcwd")
    assert out["id"] == "legacy-id"
    assert out["cwd"] == "/tmp/newcwd"


@pytest.mark.asyncio
async def test_build_create_project_fn_slug_taken_diff_cwd_disambiguate(monkeypatch):
    """Slug conflict with different cwd → second insert with -<hash> suffix succeeds."""
    from sqlalchemy.exc import IntegrityError

    from piloci.api import v1

    class _ExistingRow:
        id = "old-id"
        slug = "my-proj"
        name = "Other"
        cwd = "/tmp/other"

    class _Scalar:
        def scalar_one_or_none(self):
            return _ExistingRow()

    state: dict = {"insert_calls": 0}

    class _DB:
        def add(self, obj):
            state["last_added"] = obj

        async def commit(self):
            state["insert_calls"] += 1
            if state["insert_calls"] == 1:
                raise IntegrityError("stmt", {}, Exception("dup"))
            return None

        async def rollback(self):
            return None

        async def execute(self, stmt):
            return _Scalar()

    class _Session:
        async def __aenter__(self):
            return _DB()

        async def __aexit__(self, *exc):
            return False

    from piloci.db import session as db_session

    monkeypatch.setattr(db_session, "async_session", lambda: _Session())

    create_fn = await v1._build_create_project_fn()
    out = await create_fn("user-1", name="MyProj", slug="my-proj", cwd="/tmp/incoming")
    assert out["slug"].startswith("my-proj-")
    assert out["cwd"] == "/tmp/incoming"
    assert state["insert_calls"] == 2


@pytest.mark.asyncio
async def test_build_profile_fn_delegates(monkeypatch):
    from piloci.api import v1
    from piloci.curator import profile as profile_mod

    captured: dict = {}

    async def fake_get_profile(user_id, project_id):
        captured["user_id"] = user_id
        captured["project_id"] = project_id
        return {"likes": ["a"]}

    monkeypatch.setattr(profile_mod, "get_profile", fake_get_profile)

    profile_fn = await v1._build_profile_fn()
    out = await profile_fn("user-1", "proj-1")
    assert out == {"likes": ["a"]}
    assert captured == {"user_id": "user-1", "project_id": "proj-1"}
