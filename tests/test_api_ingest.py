from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import orjson
import pytest
from starlette.requests import Request


def _make_request(body: dict[str, object], user: dict[str, str] | None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/ingest",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "state": {"user": user},
    }

    payload = orjson.dumps(body)

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(scope, receive)


def _make_memory_request(
    body: dict[str, object],
    user: dict[str, str] | None,
    store: object,
) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/memories",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "state": {"user": user},
        "app": SimpleNamespace(state=SimpleNamespace(store=store)),
    }

    payload = orjson.dumps(body)

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(scope, receive)


def _session_cm(session: MagicMock) -> AsyncMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _db_session() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_route_ingest_filters_trivial_transcript(monkeypatch):
    from piloci.api import routes

    # Single short user message — prefilter rejects (too_short, no_assistant_content).
    request = _make_request(
        {
            "client": "claude-code",
            "project_id": "project-1",
            "transcript": [{"role": "user", "content": "hello"}],
        },
        user={"sub": "user-1"},
    )

    settings = SimpleNamespace(
        ingest_max_body_bytes=10 * 1024 * 1024,
        distillation_max_pending_backlog=200,
    )
    write_session = _db_session()
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(write_session)))

    response = await routes.route_ingest(request)
    payload = orjson.loads(response.body)

    # Trivial transcripts persist with state='filtered' — still 202, but not queued.
    assert response.status_code == 202
    assert payload["queued"] is False
    assert payload["state"] == "filtered"
    assert payload["filter_reason"] is not None
    write_session.add.assert_called_once()
    write_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_ingest_returns_202_when_substantive(monkeypatch):
    from piloci.api import routes

    transcript = [
        {"role": "user", "content": "I want to refactor the auth middleware to argon2id."},
        {
            "role": "assistant",
            "content": (
                "Sure — the bcrypt path needs migration handling so existing users stay "
                "working during the rollover. Let's introduce a hash version column and "
                "a verifier dispatcher function that branches on the hash prefix."
            ),
        },
        {"role": "user", "content": "Show me the dispatcher first."},
        {
            "role": "assistant",
            "content": (
                "Here is one approach using a strategy table keyed on hash prefix. "
                "Argon2 hashes start with $argon2 while bcrypt uses $2 — branch on that "
                "and dispatch to the right verify call."
            ),
        },
    ]
    request = _make_request(
        {
            "client": "claude-code",
            "project_id": "project-1",
            "transcript": transcript,
        },
        user={"sub": "user-1"},
    )

    settings = SimpleNamespace(
        ingest_max_body_bytes=10 * 1024 * 1024,
        distillation_max_pending_backlog=200,
    )
    write_session = _db_session()

    async def _no_archive(*args, **kwargs):
        return 0

    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(write_session)))
    monkeypatch.setattr("piloci.curator.backlog.enforce_ceiling_after_ingest", _no_archive)

    response = await routes.route_ingest(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 202
    assert payload["queued"] is True
    assert payload["state"] == "pending"
    assert payload["filter_reason"] is None
    assert payload["archived_overflow"] == 0
    write_session.add.assert_called_once()
    write_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_create_memory_saves_project_scoped_memory(monkeypatch, mock_store, settings):
    from piloci.api import routes
    from piloci.storage import embed

    vector = [0.2] * 384
    mock_store.save.return_value = "memory-1"
    request = _make_memory_request(
        {"content": "remember this", "tags": ["alpha", "beta"], "metadata": {"source": "ui"}},
        user={"sub": "user-1", "project_id": "project-1"},
        store=mock_store,
    )

    invalidated: list[tuple[object, str, str]] = []

    async def fake_embed_one(**kwargs):
        assert kwargs["text"] == "remember this"
        return vector

    async def fake_invalidate(vault_dir, user_id: str, project_id: str) -> None:
        invalidated.append((vault_dir, user_id, project_id))

    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(embed, "embed_one", fake_embed_one)
    monkeypatch.setattr(routes, "invalidate_project_vault_cache", fake_invalidate)

    response = await routes.route_create_memory(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 201
    assert payload == {"success": True, "memory_id": "memory-1", "project_id": "project-1"}
    mock_store.save.assert_awaited_once_with(
        user_id="user-1",
        project_id="project-1",
        content="remember this",
        vector=vector,
        tags=["alpha", "beta"],
        metadata={"source": "ui"},
    )
    assert invalidated == [(settings.vault_dir, "user-1", "project-1")]


@pytest.mark.asyncio
async def test_route_create_memory_requires_project_scope(mock_store):
    from piloci.api import routes

    request = _make_memory_request(
        {"content": "remember this"},
        user={"sub": "user-1"},
        store=mock_store,
    )

    response = await routes.route_create_memory(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 400
    assert payload["error"] == "project scope required"
    mock_store.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_create_memory_rejects_blank_content(mock_store):
    from piloci.api import routes

    request = _make_memory_request(
        {"content": "   "},
        user={"sub": "user-1", "project_id": "project-1"},
        store=mock_store,
    )

    response = await routes.route_create_memory(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 400
    assert payload["error"] == "content required"
    mock_store.save.assert_not_awaited()
