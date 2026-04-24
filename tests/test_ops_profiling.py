from __future__ import annotations

from types import SimpleNamespace

import orjson
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_profiler():
    from piloci.utils.logging import reset_runtime_profiler

    reset_runtime_profiler()
    yield
    reset_runtime_profiler()


def _make_request(path: str = "/profilez") -> Request:
    app = SimpleNamespace(state=SimpleNamespace(store=object()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "app": app,
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def test_runtime_profiler_snapshot_summarizes_samples():
    from piloci.utils.logging import get_runtime_profiler

    profiler = get_runtime_profiler()
    profiler.observe("embed_texts", 10)
    profiler.observe("embed_texts", 30)
    profiler.observe("embed_texts", 20)

    snapshot = profiler.snapshot()

    assert snapshot["rss_mb"] >= 0
    assert snapshot["metrics"]["embed_texts"]["count"] == 3
    assert snapshot["metrics"]["embed_texts"]["avg_ms"] == 20.0
    assert snapshot["metrics"]["embed_texts"]["last_ms"] == 30
    assert snapshot["metrics"]["embed_texts"]["max_ms"] == 30
    assert snapshot["metrics"]["embed_texts"]["p50_ms"] == 20
    assert snapshot["metrics"]["embed_texts"]["p95_ms"] == 30
    assert snapshot["window_size"] == 200
    assert snapshot["updated_at"] is not None


def test_runtime_profiler_snapshot_updated_at_none_when_empty():
    from piloci.utils.logging import get_runtime_profiler

    snapshot = get_runtime_profiler().snapshot()
    assert snapshot["updated_at"] is None


def test_runtime_profiler_reset_clears_metrics():
    from piloci.utils.logging import get_runtime_profiler, reset_runtime_profiler

    profiler = get_runtime_profiler()
    profiler.observe("embed_texts", 10)
    assert profiler.snapshot()["metrics"]["embed_texts"]["count"] == 1

    reset_runtime_profiler()
    snapshot = profiler.snapshot()

    assert snapshot["metrics"] == {}
    assert snapshot["updated_at"] is None


@pytest.mark.asyncio
async def test_runtime_profiling_middleware_skips_operational_paths():
    from piloci.utils.logging import RuntimeProfilingMiddleware, get_runtime_profiler

    async def app(scope, receive, send) -> None:
        return None

    middleware = RuntimeProfilingMiddleware(app=app)

    async def call_next(_: Request) -> Response:
        return Response("ok", status_code=200)

    for path in ("/healthz", "/readyz", "/profilez"):
        request = _make_request(path)
        await middleware.dispatch(request, call_next)

    snapshot = get_runtime_profiler().snapshot()
    assert snapshot["metrics"] == {}


@pytest.mark.asyncio
async def test_runtime_profiling_middleware_records_http_path():
    from piloci.utils.logging import RuntimeProfilingMiddleware, get_runtime_profiler

    async def app(scope, receive, send) -> None:
        return None

    middleware = RuntimeProfilingMiddleware(app=app)
    request = _make_request("/api/memories")

    async def call_next(_: Request) -> Response:
        return Response("ok", status_code=200)

    response = await middleware.dispatch(request, call_next)
    snapshot = get_runtime_profiler().snapshot()

    assert response.status_code == 200
    assert snapshot["metrics"]["http GET /api/memories"]["count"] == 1


@pytest.mark.asyncio
async def test_runtime_profiling_middleware_records_non_200_response():
    from piloci.utils.logging import RuntimeProfilingMiddleware, get_runtime_profiler

    async def app(scope, receive, send) -> None:
        return None

    middleware = RuntimeProfilingMiddleware(app=app)
    request = _make_request("/broken")

    async def call_next(_: Request) -> Response:
        return Response("nope", status_code=503)

    response = await middleware.dispatch(request, call_next)
    snapshot = get_runtime_profiler().snapshot()

    assert response.status_code == 503
    assert snapshot["metrics"]["http GET /broken"]["count"] == 1


@pytest.mark.asyncio
async def test_route_profilez_returns_snapshot(monkeypatch):
    from piloci.api import routes
    from piloci.utils.logging import get_runtime_profiler

    get_runtime_profiler().observe("lancedb.search", 12)
    request = _make_request()
    response = await routes.route_profilez(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["profiling"]["metrics"]["lancedb.search"]["count"] == 1
    assert payload["profiling"]["rss_mb"] >= 0
    assert payload["profiling"]["window_size"] == 200


def test_profilez_is_public_through_auth_and_profiling_middleware():
    from piloci.api.routes import route_profilez
    from piloci.auth.middleware import AuthMiddleware
    from piloci.config import Settings
    from piloci.utils.logging import RuntimeProfilingMiddleware, get_runtime_profiler

    settings = Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
    )
    app = Starlette(
        routes=[Route("/profilez", route_profilez)],
        middleware=[
            Middleware(RuntimeProfilingMiddleware),
            Middleware(AuthMiddleware, settings=settings),
        ],
    )
    app.state.store = object()

    with TestClient(app) as client:
        response = client.get("/profilez")

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert "http GET /profilez" not in payload["profiling"]["metrics"]
    assert "http GET /profilez" not in get_runtime_profiler().snapshot()["metrics"]
