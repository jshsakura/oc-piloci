from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import orjson
import pytest
from starlette.requests import Request

from piloci.curator.vault import (
    build_and_cache_project_vault,
    build_project_vault_preview,
    ensure_project_vault,
    export_project_vault_zip,
    invalidate_project_vault_cache,
    load_cached_project_vault,
)


def _project() -> dict[str, str]:
    return {"id": "p1", "slug": "alpha-lab", "name": "Alpha Lab"}


def _memories() -> list[dict[str, object]]:
    return [
        {
            "memory_id": "mem-12345678",
            "content": "Use [[Vector Search]] for semantic recall.",
            "tags": ["search", "rag"],
            "metadata": {"title": "Semantic Recall"},
            "created_at": 1710000000,
            "updated_at": 1710000100,
        }
    ]


def _many_memories(count: int = 6) -> list[dict[str, object]]:
    memories: list[dict[str, object]] = []
    for index in range(count):
        memories.append(
            {
                "memory_id": f"mem-{index:08d}",
                "content": f"Post-it memory {index} with detailed markdown content.",
                "tags": ["postit", f"tag-{index}"],
                "metadata": {"title": f"Post-it {index}"},
                "created_at": 1710000000 + index,
                "updated_at": 1710000100 + index,
            }
        )
    return memories


def _make_request(path: str, query_string: bytes = b"") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": query_string,
        "client": ("127.0.0.1", 12345),
        "state": {"user": {"sub": "user-1"}},
        "path_params": {"slug": "alpha-lab"},
        "app": SimpleNamespace(state=SimpleNamespace(store=AsyncMock())),
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def test_build_and_load_cached_project_vault(tmp_path) -> None:
    workspace = build_and_cache_project_vault(_project(), _memories(), tmp_path)
    cached = load_cached_project_vault(tmp_path, "alpha-lab")
    assert cached is not None
    assert cached["root"] == workspace["root"]
    assert cached["notes"][0]["title"] == "Semantic Recall"


def test_ensure_project_vault_prefers_cached_copy(tmp_path) -> None:
    first = ensure_project_vault(_project(), _memories(), tmp_path)
    second = ensure_project_vault(_project(), [], tmp_path)
    assert second["generated_at"] == first["generated_at"]
    assert len(second["notes"]) == 1


def test_export_project_vault_zip_contains_vault_json_and_notes(tmp_path) -> None:
    workspace = build_and_cache_project_vault(_project(), _memories(), tmp_path)
    payload = export_project_vault_zip(_project(), workspace)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert "vaults/alpha-lab/vault.json" in names
        assert any(name.endswith("semantic-recall-mem-1234.md") for name in names)


def test_build_project_vault_preview_limits_notes_and_drops_markdown(tmp_path) -> None:
    workspace = build_and_cache_project_vault(_project(), _many_memories(), tmp_path)

    preview = build_project_vault_preview(workspace, note_limit=5)

    assert preview["preview"] is True
    assert preview["note_limit"] == 5
    assert preview["stats"] == workspace["stats"]
    assert preview["graph"] == workspace["graph"]
    assert len(preview["notes"]) == 5
    assert all("markdown" not in note for note in preview["notes"])
    assert preview["notes"][0]["excerpt"]


@pytest.mark.asyncio
async def test_invalidate_project_vault_cache_removes_slug_dir(tmp_path) -> None:
    build_and_cache_project_vault(_project(), _memories(), tmp_path)
    await invalidate_project_vault_cache(tmp_path, "user-1", "p1", "alpha-lab")
    assert load_cached_project_vault(tmp_path, "alpha-lab") is None


@pytest.mark.asyncio
async def test_route_project_workspace_uses_cached_vault_without_store_list(monkeypatch, tmp_path):
    from piloci.api import routes

    request = _make_request("/api/projects/slug/alpha-lab/workspace")
    request.app.state.store.list.side_effect = AssertionError("store.list should not be called")

    workspace = build_and_cache_project_vault(_project(), _memories(), tmp_path)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(vault_dir=tmp_path))
    monkeypatch.setattr(routes, "_get_user_project_by_slug", AsyncMock(return_value=_project()))

    response = await routes.route_project_workspace(request)
    payload = orjson.loads(response.body)
    assert payload["workspace"]["root"] == workspace["root"]


@pytest.mark.asyncio
async def test_route_project_workspace_preview_uses_cached_vault_without_markdown(
    monkeypatch, tmp_path
):
    from piloci.api import routes

    request = _make_request("/api/projects/slug/alpha-lab/workspace/preview")
    request.app.state.store.list.side_effect = AssertionError("store.list should not be called")

    build_and_cache_project_vault(_project(), _many_memories(), tmp_path)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(vault_dir=tmp_path))
    monkeypatch.setattr(routes, "_get_user_project_by_slug", AsyncMock(return_value=_project()))

    response = await routes.route_project_workspace_preview(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 200
    assert payload["workspace"]["preview"] is True
    assert len(payload["workspace"]["notes"]) == 5
    assert all("markdown" not in note for note in payload["workspace"]["notes"])


@pytest.mark.asyncio
async def test_route_vault_export_returns_zip(monkeypatch, tmp_path):
    from piloci.api import routes

    request = _make_request("/api/vault/alpha-lab/export")
    request.app.state.store.list = AsyncMock(return_value=_memories())

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(vault_dir=tmp_path))
    monkeypatch.setattr(routes, "_get_user_project_by_slug", AsyncMock(return_value=_project()))

    response = await routes.route_vault_export(request)
    assert response.media_type == "application/zip"
    assert "alpha-lab-vault.zip" in response.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        assert "vaults/alpha-lab/vault.json" in archive.namelist()
