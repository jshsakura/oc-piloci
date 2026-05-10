from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import orjson
import pytest
from starlette.requests import Request


def _make_request(store: object) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(store=store))

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/readyz",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "app": app,
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def _session_cm(session: MagicMock) -> AsyncMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _db_session() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_route_readyz_reports_ok(monkeypatch):
    from piloci.api import routes
    from piloci.curator import backlog as backlog_mod

    store = MagicMock()
    store._get_table = AsyncMock()
    request = _make_request(store)
    db_session = _db_session()

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(distillation_max_pending_backlog=200),
    )
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db_session)))
    monkeypatch.setattr(
        routes,
        "get_session_store",
        lambda settings: SimpleNamespace(ping=AsyncMock(return_value=True)),
    )
    monkeypatch.setattr(backlog_mod, "count_pending", AsyncMock(return_value=12))

    response = await routes.route_readyz(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["causes"] == []
    assert payload["checks"]["redis"]["status"] == "ok"
    assert payload["checks"]["distillation_backlog"]["pressure"] == "normal"
    assert payload["checks"]["distillation_backlog"]["depth"] == 12
    assert payload["checks"]["distillation_backlog"]["capacity"] == 200


@pytest.mark.asyncio
async def test_route_readyz_reports_degraded_with_explicit_causes(monkeypatch):
    from piloci.api import routes
    from piloci.curator import backlog as backlog_mod

    store = MagicMock()
    store._get_table = AsyncMock(side_effect=RuntimeError("lancedb offline"))
    request = _make_request(store)
    db_session = _db_session()
    db_session.execute = AsyncMock(side_effect=RuntimeError("db offline"))

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(distillation_max_pending_backlog=4),
    )
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db_session)))
    monkeypatch.setattr(
        routes,
        "get_session_store",
        lambda settings: SimpleNamespace(ping=AsyncMock(side_effect=RuntimeError("redis offline"))),
    )
    # Backlog at capacity → 'full' pressure → cause appended.
    monkeypatch.setattr(backlog_mod, "count_pending", AsyncMock(return_value=4))

    response = await routes.route_readyz(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 503
    assert payload["status"] == "degraded"
    assert payload["checks"]["lancedb"]["status"] == "error"
    assert payload["checks"]["db"]["status"] == "error"
    assert payload["checks"]["redis"]["status"] == "error"
    assert payload["checks"]["distillation_backlog"]["status"] == "error"
    assert payload["checks"]["distillation_backlog"]["pressure"] == "full"
    assert "lancedb_unavailable" in payload["causes"]
    assert "database_unavailable" in payload["causes"]
    assert "redis_unavailable" in payload["causes"]
    assert "distillation_backlog_full" in payload["causes"]
