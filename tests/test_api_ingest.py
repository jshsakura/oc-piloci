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
    return session


@pytest.mark.asyncio
async def test_route_ingest_returns_429_when_queue_is_full(monkeypatch):
    from piloci.api import routes

    request = _make_request(
        {
            "client": "claude-code",
            "project_id": "project-1",
            "transcript": [{"role": "user", "content": "hello"}],
        },
        user={"sub": "user-1"},
    )

    settings = SimpleNamespace(ingest_queue_maxsize=1, ingest_retry_after_sec=9)
    write_session = _db_session()
    cleanup_session = _db_session()

    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(
        routes,
        "async_session",
        MagicMock(side_effect=[_session_cm(write_session), _session_cm(cleanup_session)]),
    )
    monkeypatch.setattr(routes, "get_ingest_queue", lambda maxsize=None: SimpleNamespace(qsize=lambda: 1, maxsize=1))
    monkeypatch.setattr(routes, "try_enqueue_job", lambda job, maxsize=None: False)

    response = await routes.route_ingest(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 429
    assert payload["error"] == "ingest queue is full"
    assert payload["queue_depth"] == 1
    assert payload["queue_capacity"] == 1
    assert payload["retry_after_sec"] == 9
    assert response.headers["Retry-After"] == "9"
    write_session.add.assert_called_once()
    write_session.commit.assert_awaited_once()
    cleanup_session.execute.assert_awaited_once()
    cleanup_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_ingest_returns_202_when_enqueued(monkeypatch):
    from piloci.api import routes

    request = _make_request(
        {
            "client": "claude-code",
            "project_id": "project-1",
            "transcript": [{"role": "user", "content": "hello"}],
        },
        user={"sub": "user-1"},
    )

    settings = SimpleNamespace(ingest_queue_maxsize=4, ingest_retry_after_sec=5)
    write_session = _db_session()

    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(write_session)))
    monkeypatch.setattr(routes, "get_ingest_queue", lambda maxsize=None: SimpleNamespace(qsize=lambda: 1, maxsize=4))
    monkeypatch.setattr(routes, "try_enqueue_job", lambda job, maxsize=None: True)

    response = await routes.route_ingest(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 202
    assert payload["queued"] is True
    assert payload["queue_depth"] == 1
    assert payload["queue_capacity"] == 4
    write_session.add.assert_called_once()
    write_session.commit.assert_awaited_once()
