from __future__ import annotations

import asyncio
import sys
import types
from collections.abc import Awaitable, Callable, Coroutine
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from piloci.api.security import SecurityHeadersMiddleware
from piloci.auth.middleware import AuthMiddleware
from piloci.main import (
    _build_mcp,
    _ProjectsCache,
    _run_stdio,
    _shutdown,
    _startup,
    create_app,
    run_sse,
    run_stdio,
)
from piloci.utils.logging import RuntimeProfilingMiddleware


class _AsyncSessionContext:
    def __init__(self, db: object) -> None:
        self._db: object = db

    async def __aenter__(self) -> object:
        return self._db

    async def __aexit__(
        self, exc_type: object | None, exc: object | None, tb: object | None
    ) -> bool:
        return False


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self._value: int = value

    def scalar(self) -> int:
        return self._value


class _ProjectRowsResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows: list[object] = rows

    def scalars(self) -> "_ProjectRowsResult":
        return self

    def all(self) -> list[object]:
        return self._rows


def _settings(**overrides: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = {
        "jwt_secret": "test-secret-32-characters-minimum!",
        "session_secret": "test-secret-32-characters-minimum!",
        "cors_origins": ["http://localhost:3000"],
        "curator_enabled": True,
        "debug": False,
        "reload": False,
        "workers": 3,
        "host": "127.0.0.1",
        "port": 8314,
        "log_level": "INFO",
        "log_format": "text",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_projects_cache_set_and_get() -> None:
    cache = _ProjectsCache(ttl_sec=300)
    _ = cache.set("u1", [{"id": "p1", "name": "proj"}])

    result = cache.get("u1")

    assert result is not None
    assert len(result) == 1
    assert result[0]["id"] == "p1"


def test_projects_cache_miss() -> None:
    cache = _ProjectsCache()

    assert cache.get("unknown") is None


def test_projects_cache_expiry(monkeypatch) -> None:
    import time

    cache = _ProjectsCache(ttl_sec=10)
    _ = cache.set("u1", [{"id": "p1"}])

    current = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: current + 11)

    assert cache.get("u1") is None


def test_projects_cache_invalidate() -> None:
    cache = _ProjectsCache()
    _ = cache.set("u1", [{"id": "p1"}])

    cache.invalidate("u1")

    assert cache.get("u1") is None


def test_projects_cache_returns_copy() -> None:
    cache = _ProjectsCache()
    _ = cache.set("u1", [{"id": "p1"}])

    first = cache.get("u1")
    assert first is not None
    first[0]["id"] = "modified"

    second = cache.get("u1")
    assert second is not None
    assert second[0]["id"] == "p1"


@pytest.mark.asyncio
async def test_run_stdio_builds_stores_and_runs_server(monkeypatch) -> None:
    settings = _settings()
    store = AsyncMock()
    instincts_store = AsyncMock()
    mcp_server = MagicMock()
    mcp_server.run = AsyncMock()
    mcp_server.create_initialization_options.return_value = {"hello": "world"}

    class _StdioContext:
        async def __aenter__(self):
            return ("reader", "writer")

        async def __aexit__(
            self, exc_type: object | None, exc: object | None, tb: object | None
        ) -> bool:
            return False

    fake_stdio_module = types.ModuleType("mcp.server.stdio")
    fake_stdio_module.stdio_server = lambda: _StdioContext()

    monkeypatch.setattr("piloci.main.get_settings", lambda: settings)
    monkeypatch.setattr("piloci.main.MemoryStore", lambda received: store)
    monkeypatch.setattr("piloci.main.InstinctsStore", lambda received: instincts_store)
    monkeypatch.setattr(
        "piloci.main._build_mcp",
        lambda received_settings, received_store, received_instincts: mcp_server,
    )

    with pytest.MonkeyPatch.context() as patch_ctx:
        patch_ctx.setitem(sys.modules, "mcp.server.stdio", fake_stdio_module)
        await _run_stdio()

    store.ensure_collection.assert_awaited_once()
    instincts_store.ensure_collection.assert_awaited_once()
    mcp_server.run.assert_awaited_once_with("reader", "writer", {"hello": "world"})


def test_run_stdio_configures_logging_and_runs_asyncio(monkeypatch) -> None:
    configure_logging_mock = MagicMock()
    asyncio_run_mock = MagicMock()

    monkeypatch.setattr("piloci.main.configure_logging", configure_logging_mock)
    monkeypatch.setattr("piloci.main.asyncio.run", asyncio_run_mock)

    run_stdio()

    configure_logging_mock.assert_called_once_with()
    asyncio_run_mock.assert_called_once()

    coroutine = asyncio_run_mock.call_args.args[0]
    assert asyncio.iscoroutine(coroutine)
    coroutine.close()


@pytest.mark.asyncio
async def test_build_mcp_wires_resource_callbacks(monkeypatch) -> None:
    settings = _settings()
    store = AsyncMock()
    store.list.return_value = [
        {"id": "older", "updated_at": 10},
        {"id": "newer", "updated_at": 50},
    ]
    captured: dict[str, object] = {}
    db = AsyncMock()
    db.execute.return_value = _ProjectRowsResult(
        [
            SimpleNamespace(id="p1", slug="alpha", name="Alpha", memory_count=2),
            SimpleNamespace(id="p2", slug="beta", name="Beta", memory_count=5),
        ]
    )

    async def fake_get_profile(user_id: str, project_id: str) -> dict[str, str]:
        return {"user_id": user_id, "project_id": project_id}

    def fake_create_mcp_server(received_settings, received_store, **kwargs):
        captured.update(kwargs)
        assert received_settings is settings
        assert received_store is store
        return "server"

    monkeypatch.setattr("piloci.curator.profile.get_profile", fake_get_profile)
    monkeypatch.setattr("piloci.db.session.async_session", lambda: _AsyncSessionContext(db))
    monkeypatch.setattr("piloci.main.create_mcp_server", fake_create_mcp_server)

    server = _build_mcp(settings, store, instincts_store=MagicMock())

    assert server == "server"

    profile_fn = cast(
        Callable[[str, str], Awaitable[dict[str, str] | None]], captured["profile_fn"]
    )
    projects_fn = cast(
        Callable[[str, bool], Awaitable[list[dict[str, object]]]], captured["projects_fn"]
    )
    recent_fn = cast(
        Callable[[str, str, int], Awaitable[list[dict[str, object]]]], captured["recent_fn"]
    )

    profile = await profile_fn("user-1", "project-1")
    projects_first = await projects_fn("user-1", False)
    projects_cached = await projects_fn("user-1", False)
    projects_refresh = await projects_fn("user-1", True)
    recent = await recent_fn("user-1", "project-1", 2)

    assert profile == {"user_id": "user-1", "project_id": "project-1"}
    assert projects_first == [
        {"id": "p1", "slug": "alpha", "name": "Alpha", "memory_count": 2},
        {"id": "p2", "slug": "beta", "name": "Beta", "memory_count": 5},
    ]
    assert projects_cached == projects_first
    assert projects_refresh == projects_first
    assert db.execute.await_count == 2
    store.list.assert_awaited_once_with(user_id="user-1", project_id="project-1", limit=2, offset=0)
    assert [row["id"] for row in recent] == ["newer", "older"]


@pytest.mark.parametrize("with_static", [True, False])
def test_create_app_registers_routes_and_middleware(monkeypatch, with_static: bool) -> None:
    settings = _settings(curator_enabled=False)
    store = object()
    instincts_store = object()
    ratelimit_mock = MagicMock()

    async def healthz(request):
        return PlainTextResponse("ok")

    base_routes = [Route("/healthz", healthz)]
    static_app = Starlette() if with_static else None

    monkeypatch.setattr("piloci.main.get_settings", lambda: settings)
    monkeypatch.setattr("piloci.main.configure_logging", MagicMock())
    monkeypatch.setattr("piloci.main.MemoryStore", lambda received: store)
    monkeypatch.setattr("piloci.main.InstinctsStore", lambda received: instincts_store)
    monkeypatch.setattr("piloci.main._build_mcp", lambda *args: "mcp-server")
    monkeypatch.setattr("piloci.main.create_sse_app", lambda *args, **kwargs: Starlette())
    monkeypatch.setattr("piloci.main.get_routes", lambda: base_routes)
    monkeypatch.setattr("piloci.main.get_static_app", lambda: static_app)
    monkeypatch.setattr("piloci.main.setup_ratelimit", ratelimit_mock)

    app = create_app()

    route_paths = {getattr(route, "path", None) for route in app.routes}

    assert "/healthz" in route_paths
    assert "/mcp" in route_paths
    assert (("" in route_paths) or ("/" in route_paths)) is with_static
    assert app.user_middleware[0].cls is CORSMiddleware
    assert app.user_middleware[1].cls is RuntimeProfilingMiddleware
    assert app.user_middleware[2].cls is SecurityHeadersMiddleware
    assert app.user_middleware[3].cls is AuthMiddleware
    assert app.state.store is store
    assert app.state.instincts_store is instincts_store
    ratelimit_mock.assert_called_once_with(app)


@pytest.mark.asyncio
async def test_startup_initializes_db_and_background_workers(monkeypatch) -> None:
    settings = _settings(curator_enabled=True)
    init_db_mock = AsyncMock()
    store = AsyncMock()
    instincts_store = AsyncMock()
    process_unfinished_mock = AsyncMock(return_value=4)
    created_task_count = 0

    async def maintenance_worker(received_settings: object, stop_event: asyncio.Event):
        await stop_event.wait()

    async def curator_worker(
        received_settings: object, received_store: object, stop_event: asyncio.Event
    ):
        await stop_event.wait()

    async def profile_worker(
        received_settings: object, received_store: object, stop_event: asyncio.Event
    ):
        await stop_event.wait()

    def fake_create_task(coro: Coroutine[Any, Any, Any]) -> str:
        nonlocal created_task_count
        created_task_count += 1
        coro.close()
        return f"task-{created_task_count}"

    process_unfinished_analyses_mock = AsyncMock(return_value=2)

    async def analyze_worker(
        received_settings: object,
        received_store: object,
        stop_event: asyncio.Event,
    ):
        await stop_event.wait()

    maintenance_module = types.ModuleType("piloci.ops.maintenance")
    maintenance_module.run_maintenance_worker = maintenance_worker
    profile_module = types.ModuleType("piloci.curator.profile")
    profile_module.run_profile_worker = profile_worker
    worker_module = types.ModuleType("piloci.curator.worker")
    worker_module.process_unfinished = process_unfinished_mock
    worker_module.run_worker = curator_worker
    analyze_worker_module = types.ModuleType("piloci.curator.analyze_worker")
    analyze_worker_module.process_unfinished_analyses = process_unfinished_analyses_mock
    analyze_worker_module.run_analyze_worker = analyze_worker

    monkeypatch.setattr("piloci.main.get_settings", lambda: settings)
    monkeypatch.setattr("piloci.main.init_db", init_db_mock)
    monkeypatch.setattr("piloci.main.asyncio.create_task", fake_create_task)

    with pytest.MonkeyPatch.context() as patch_ctx:
        patch_ctx.setitem(sys.modules, "piloci.ops.maintenance", maintenance_module)
        patch_ctx.setitem(sys.modules, "piloci.curator.profile", profile_module)
        patch_ctx.setitem(sys.modules, "piloci.curator.worker", worker_module)
        patch_ctx.setitem(sys.modules, "piloci.curator.analyze_worker", analyze_worker_module)

        stop_event = asyncio.Event()
        bg_tasks: list[object] = []

        await _startup(Starlette(), store, stop_event, bg_tasks, instincts_store)

    init_db_mock.assert_awaited_once()
    store.ensure_collection.assert_awaited_once()
    instincts_store.ensure_collection.assert_awaited_once()
    process_unfinished_mock.assert_awaited_once_with(settings, store)
    process_unfinished_analyses_mock.assert_awaited_once_with(settings)
    assert created_task_count == 4
    assert bg_tasks == ["task-1", "task-2", "task-3", "task-4"]


@pytest.mark.asyncio
async def test_startup_skips_curator_when_disabled(monkeypatch) -> None:
    settings = _settings(curator_enabled=False)
    init_db_mock = AsyncMock()
    store = AsyncMock()
    created_task_count = 0

    async def maintenance_worker(received_settings: object, stop_event: asyncio.Event):
        await stop_event.wait()

    def fake_create_task(coro: Coroutine[Any, Any, Any]) -> str:
        nonlocal created_task_count
        created_task_count += 1
        coro.close()
        return "maintenance-task"

    maintenance_module = types.ModuleType("piloci.ops.maintenance")
    maintenance_module.run_maintenance_worker = maintenance_worker

    monkeypatch.setattr("piloci.main.get_settings", lambda: settings)
    monkeypatch.setattr("piloci.main.init_db", init_db_mock)
    monkeypatch.setattr("piloci.main.asyncio.create_task", fake_create_task)

    with pytest.MonkeyPatch.context() as patch_ctx:
        patch_ctx.setitem(sys.modules, "piloci.ops.maintenance", maintenance_module)

        stop_event = asyncio.Event()
        bg_tasks: list[object] = []

        await _startup(Starlette(), store, stop_event, bg_tasks, instincts_store=None)

    init_db_mock.assert_awaited_once()
    store.ensure_collection.assert_awaited_once()
    assert created_task_count == 1
    assert bg_tasks == ["maintenance-task"]


@pytest.mark.asyncio
async def test_shutdown_sets_stop_cancels_timeouts_and_closes_store(monkeypatch) -> None:
    stop_event = asyncio.Event()
    store = AsyncMock()
    timeout_task = MagicMock()
    error_task = MagicMock()
    ok_task = MagicMock()
    wait_for_mock = AsyncMock(side_effect=[asyncio.TimeoutError(), RuntimeError("boom"), None])

    monkeypatch.setattr("piloci.main.asyncio.wait_for", wait_for_mock)

    await _shutdown(store, stop_event, [timeout_task, error_task, ok_task])

    assert stop_event.is_set() is True
    timeout_task.cancel.assert_called_once_with()
    store.close.assert_awaited_once()
    assert wait_for_mock.await_count == 3


def test_run_sse_uses_factory_target_when_reload_enabled(monkeypatch) -> None:
    settings = _settings(reload=True, workers=5, log_level="WARNING")
    configure_logging_mock = MagicMock()
    uvicorn_run_mock = MagicMock()

    monkeypatch.setattr("piloci.main.get_settings", lambda: settings)
    monkeypatch.setattr("piloci.main.configure_logging", configure_logging_mock)
    monkeypatch.setattr("piloci.main.uvicorn.run", uvicorn_run_mock)

    run_sse()

    configure_logging_mock.assert_called_once_with(level="WARNING", fmt="text")
    uvicorn_run_mock.assert_called_once_with(
        "piloci.main:create_app",
        host="127.0.0.1",
        port=8314,
        reload=True,
        workers=1,
        log_level="warning",
        factory=True,
    )


def test_run_sse_builds_app_when_reload_disabled(monkeypatch) -> None:
    settings = _settings(reload=False, workers=4, log_level="DEBUG")
    app = Starlette()
    uvicorn_run_mock = MagicMock()

    monkeypatch.setattr("piloci.main.get_settings", lambda: settings)
    monkeypatch.setattr("piloci.main.configure_logging", MagicMock())
    monkeypatch.setattr("piloci.main.create_app", lambda: app)
    monkeypatch.setattr("piloci.main.uvicorn.run", uvicorn_run_mock)

    run_sse()

    uvicorn_run_mock.assert_called_once_with(
        app,
        host="127.0.0.1",
        port=8314,
        reload=False,
        workers=4,
        log_level="debug",
        factory=False,
    )
