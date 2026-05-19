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

from piloci.api.security import CSRFMiddleware, SecurityHeadersMiddleware
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
        "distillation_enabled": True,
        "health_monitor_enabled": False,
        "debug": False,
        "reload": False,
        "workers": 3,
        "host": "127.0.0.1",
        "port": 8314,
        "log_level": "INFO",
        "log_format": "text",
        "telegram_bot_token": None,
        "telegram_chat_id": None,
        "telegram_bot_enabled": False,
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
            SimpleNamespace(id="p1", slug="alpha", name="Alpha", memory_count=2, cwd=None),
            SimpleNamespace(id="p2", slug="beta", name="Beta", memory_count=5, cwd=None),
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
        {"id": "p1", "slug": "alpha", "name": "Alpha", "memory_count": 2, "cwd": None},
        {"id": "p2", "slug": "beta", "name": "Beta", "memory_count": 5, "cwd": None},
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
    assert app.user_middleware[3].cls is CSRFMiddleware
    assert app.user_middleware[4].cls is AuthMiddleware
    assert app.state.store is store
    assert app.state.instincts_store is instincts_store
    ratelimit_mock.assert_called_once_with(app)


@pytest.mark.asyncio
async def test_startup_initializes_db_and_background_workers(monkeypatch) -> None:
    """Startup wires maintenance + lazy distillation + profile workers.

    The eager curator and analyze workers were retired in favor of a single
    lazy distillation_worker that drains pending RawSession rows. Health
    monitor stays opt-in (defaults to False) so a fresh test settings
    instance only spins up three tasks.
    """
    settings = _settings(curator_enabled=True, distillation_enabled=True)
    init_db_mock = AsyncMock()
    store = AsyncMock()
    instincts_store = AsyncMock()
    created_task_count = 0

    async def maintenance_worker(received_settings: object, stop_event: asyncio.Event):
        await stop_event.wait()

    async def distillation_worker(
        received_settings: object,
        received_store: object,
        received_instincts: object,
        stop_event: asyncio.Event,
    ):
        await stop_event.wait()

    async def profile_worker(
        received_settings: object, received_store: object, stop_event: asyncio.Event
    ):
        await stop_event.wait()

    async def weekly_digest_worker(
        received_settings: object,
        received_store: object,
        received_instincts: object,
        stop_event: asyncio.Event,
    ):
        await stop_event.wait()

    async def team_wiki_worker(
        received_settings: object,
        received_store: object,
        stop_event: asyncio.Event,
    ):
        await stop_event.wait()

    def fake_create_task(coro: Coroutine[Any, Any, Any]) -> str:
        nonlocal created_task_count
        created_task_count += 1
        coro.close()
        return f"task-{created_task_count}"

    maintenance_module = types.ModuleType("piloci.ops.maintenance")
    maintenance_module.run_maintenance_worker = maintenance_worker
    profile_module = types.ModuleType("piloci.curator.profile")
    profile_module.run_profile_worker = profile_worker
    distillation_module = types.ModuleType("piloci.curator.distillation_worker")
    distillation_module.run_distillation_worker = distillation_worker
    weekly_module = types.ModuleType("piloci.curator.weekly_digest_worker")
    weekly_module.run_weekly_digest_worker = weekly_digest_worker
    team_wiki_module = types.ModuleType("piloci.curator.team_wiki_worker")
    team_wiki_module.run_team_wiki_worker = team_wiki_worker

    monkeypatch.setattr("piloci.main.get_settings", lambda: settings)
    monkeypatch.setattr("piloci.main.init_db", init_db_mock)
    monkeypatch.setattr("piloci.main.asyncio.create_task", fake_create_task)

    with pytest.MonkeyPatch.context() as patch_ctx:
        patch_ctx.setitem(sys.modules, "piloci.ops.maintenance", maintenance_module)
        patch_ctx.setitem(sys.modules, "piloci.curator.profile", profile_module)
        patch_ctx.setitem(sys.modules, "piloci.curator.distillation_worker", distillation_module)
        patch_ctx.setitem(sys.modules, "piloci.curator.weekly_digest_worker", weekly_module)
        patch_ctx.setitem(sys.modules, "piloci.curator.team_wiki_worker", team_wiki_module)

        stop_event = asyncio.Event()
        bg_tasks: list[object] = []

        await _startup(Starlette(), store, stop_event, bg_tasks, instincts_store)

    init_db_mock.assert_awaited_once()
    store.ensure_collection.assert_awaited_once()
    instincts_store.ensure_collection.assert_awaited_once()
    # maintenance + distillation + profile + weekly_digest + team_wiki = 5 tasks
    # (health monitor off by default)
    assert created_task_count == 5
    assert bg_tasks == ["task-1", "task-2", "task-3", "task-4", "task-5"]


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


class _ScalarOneOrNoneResult:
    def __init__(self, value: object) -> None:
        self._value: object = value

    def scalar_one_or_none(self) -> object:
        return self._value

    def scalar_one(self) -> object:
        if self._value is None:
            raise RuntimeError("no row")
        return self._value

    def execution_options(self, *args: Any, **kwargs: Any) -> "_ScalarOneOrNoneResult":
        return self


class _DBSessionStub:
    """Per-test fake AsyncSession that records add/commit calls.

    Each instance is a fresh context manager so successive ``async with
    async_session() as db`` blocks see independent commit outcomes. ``execute``
    answers from a queue of pre-built result objects, and ``commit`` either
    succeeds, raises ``IntegrityError`` once, or raises a custom exception."""

    def __init__(
        self,
        execute_results: list[object] | None = None,
        commit_side_effects: list[object] | None = None,
    ) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self._execute_queue: list[object] = list(execute_results or [])
        self._commit_queue: list[object] = list(commit_side_effects or [])

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def execute(self, *args: Any, **kwargs: Any) -> object:
        if not self._execute_queue:
            return _ScalarOneOrNoneResult(None)
        return self._execute_queue.pop(0)

    async def commit(self) -> None:
        self.commits += 1
        if not self._commit_queue:
            return
        outcome = self._commit_queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome

    async def rollback(self) -> None:
        self.rollbacks += 1


class _SessionFactory:
    """Hands out a pre-built ``_DBSessionStub`` per ``async_session()`` call."""

    def __init__(self, sessions: list[_DBSessionStub]) -> None:
        self._sessions: list[_DBSessionStub] = list(sessions)
        self.handed_out: list[_DBSessionStub] = []

    def __call__(self) -> _AsyncSessionContext:
        if not self._sessions:
            raise AssertionError("async_session called more times than expected")
        db = self._sessions.pop(0)
        self.handed_out.append(db)
        return _AsyncSessionContext(db)


def _capture_create_project_fn(monkeypatch, factory: _SessionFactory) -> Callable[..., Any]:
    """Build the MCP with mocked async_session and return ``create_project_fn``."""
    from piloci import main as main_mod

    settings = _settings()
    store = AsyncMock()
    captured: dict[str, Any] = {}

    def fake_create_mcp_server(received_settings, received_store, **kwargs):
        captured.update(kwargs)
        return "server"

    monkeypatch.setattr("piloci.db.session.async_session", factory)
    monkeypatch.setattr(main_mod, "create_mcp_server", fake_create_mcp_server)

    main_mod._build_mcp(settings, store, instincts_store=MagicMock())
    return cast(Callable[..., Any], captured["create_project_fn"])


@pytest.mark.asyncio
async def test_create_project_fn_fresh_insert_returns_new_row(monkeypatch) -> None:
    db_ok = _DBSessionStub()
    factory = _SessionFactory([db_ok])
    create_project_fn = _capture_create_project_fn(monkeypatch, factory)

    result = await create_project_fn("user-1", "Alpha", "alpha", cwd="/tmp/alpha")

    assert result["slug"] == "alpha"
    assert result["name"] == "Alpha"
    assert result["cwd"] == "/tmp/alpha"
    assert db_ok.commits == 1
    assert db_ok.rollbacks == 0
    assert len(db_ok.added) == 1


@pytest.mark.asyncio
async def test_create_project_fn_idempotent_same_cwd(monkeypatch) -> None:
    """Slug collides with a row that has the same cwd → claim and return."""
    from sqlalchemy.exc import IntegrityError

    existing = SimpleNamespace(id="p-existing", slug="alpha", name="Alpha", cwd="/tmp/alpha")
    insert_db = _DBSessionStub(
        commit_side_effects=[IntegrityError("INSERT", {}, Exception("uniq"))]
    )
    lookup_db = _DBSessionStub(execute_results=[_ScalarOneOrNoneResult(existing)])
    factory = _SessionFactory([insert_db, lookup_db])

    create_project_fn = _capture_create_project_fn(monkeypatch, factory)

    result = await create_project_fn("user-1", "Alpha", "alpha", cwd="/tmp/alpha")

    assert result == {"id": "p-existing", "slug": "alpha", "name": "Alpha", "cwd": "/tmp/alpha"}
    assert insert_db.rollbacks == 1
    # No claim write needed when cwd matches.
    assert lookup_db.commits == 0


@pytest.mark.asyncio
async def test_create_project_fn_claims_legacy_row_without_cwd(monkeypatch) -> None:
    """Slug collides with a legacy row whose cwd is NULL → stamp the new cwd."""
    from sqlalchemy.exc import IntegrityError

    legacy = SimpleNamespace(id="p-legacy", slug="alpha", name="Alpha", cwd=None)
    live = SimpleNamespace(id="p-legacy", slug="alpha", name="Alpha", cwd=None)
    insert_db = _DBSessionStub(
        commit_side_effects=[IntegrityError("INSERT", {}, Exception("uniq"))]
    )
    lookup_db = _DBSessionStub(execute_results=[_ScalarOneOrNoneResult(legacy)])
    claim_db = _DBSessionStub(
        execute_results=[_ScalarOneOrNoneResult(live), _ScalarOneOrNoneResult(live)],
    )
    factory = _SessionFactory([insert_db, lookup_db, claim_db])

    create_project_fn = _capture_create_project_fn(monkeypatch, factory)

    result = await create_project_fn("user-1", "Alpha", "alpha", cwd="/tmp/new-cwd")

    assert result["id"] == "p-legacy"
    assert result["cwd"] == "/tmp/new-cwd"
    # Claim path stamps the cwd onto the live row and commits.
    assert live.cwd == "/tmp/new-cwd"
    assert claim_db.commits == 1


@pytest.mark.asyncio
async def test_create_project_fn_disambiguates_on_different_cwd(monkeypatch) -> None:
    """Slug collides with a row using a *different* cwd → suffix-disambiguated insert."""
    from sqlalchemy.exc import IntegrityError

    existing = SimpleNamespace(id="p-other", slug="alpha", name="Alpha", cwd="/tmp/other")
    insert_db = _DBSessionStub(
        commit_side_effects=[IntegrityError("INSERT", {}, Exception("uniq"))]
    )
    lookup_db = _DBSessionStub(execute_results=[_ScalarOneOrNoneResult(existing)])
    disambig_db = _DBSessionStub()
    factory = _SessionFactory([insert_db, lookup_db, disambig_db])

    create_project_fn = _capture_create_project_fn(monkeypatch, factory)

    result = await create_project_fn("user-1", "Alpha", "alpha", cwd="/tmp/mine")

    assert result["slug"].startswith("alpha-")
    assert len(result["slug"]) <= 50
    assert result["cwd"] == "/tmp/mine"
    assert disambig_db.commits == 1
    # The disambiguation row was the project added to the third session.
    inserted = disambig_db.added[0]
    assert inserted.cwd == "/tmp/mine"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_create_project_fn_no_existing_row_falls_through_and_raises(monkeypatch) -> None:
    """Slug collides but lookup finds nothing → fallthrough re-insert raises RuntimeError.

    Both inserts are forced to succeed via empty commit queues so the function
    reaches the final ``raise RuntimeError`` guard.
    """
    from sqlalchemy.exc import IntegrityError

    insert_db = _DBSessionStub(
        commit_side_effects=[IntegrityError("INSERT", {}, Exception("uniq"))]
    )
    lookup_db = _DBSessionStub(execute_results=[_ScalarOneOrNoneResult(None)])
    fallthrough_db = _DBSessionStub()
    factory = _SessionFactory([insert_db, lookup_db, fallthrough_db])

    create_project_fn = _capture_create_project_fn(monkeypatch, factory)

    with pytest.raises(RuntimeError, match="unreachable"):
        await create_project_fn("user-1", "Alpha", "alpha", cwd=None)

    # The fallthrough block re-added a row before raising.
    assert len(fallthrough_db.added) == 1


@pytest.mark.asyncio
async def test_create_app_lifespan_invokes_startup_and_shutdown(monkeypatch) -> None:
    """Drive ``create_app``'s lifespan ctx so the inline startup/shutdown body runs."""
    settings = _settings(curator_enabled=False)
    store = object()
    instincts_store = object()
    startup_mock = AsyncMock()
    shutdown_mock = AsyncMock()

    monkeypatch.setattr("piloci.main.get_settings", lambda: settings)
    monkeypatch.setattr("piloci.main.configure_logging", MagicMock())
    monkeypatch.setattr("piloci.main.MemoryStore", lambda received: store)
    monkeypatch.setattr("piloci.main.InstinctsStore", lambda received: instincts_store)
    monkeypatch.setattr("piloci.main._build_mcp", lambda *args: "mcp-server")
    monkeypatch.setattr("piloci.main.create_sse_app", lambda *args, **kwargs: Starlette())
    monkeypatch.setattr(
        "piloci.main.create_streamable_http_app", lambda *args, **kwargs: Starlette()
    )
    monkeypatch.setattr("piloci.main.get_routes", lambda: [])
    monkeypatch.setattr("piloci.main.get_static_app", lambda: None)
    monkeypatch.setattr("piloci.main.setup_ratelimit", MagicMock())
    monkeypatch.setattr("piloci.main._startup", startup_mock)
    monkeypatch.setattr("piloci.main._shutdown", shutdown_mock)

    app = create_app()
    lifespan_ctx = app.router.lifespan_context(app)

    await lifespan_ctx.__aenter__()
    await lifespan_ctx.__aexit__(None, None, None)

    startup_mock.assert_awaited_once()
    shutdown_mock.assert_awaited_once()
    # Stop event + bg task list are shared across startup/shutdown.
    startup_args = startup_mock.await_args.args
    shutdown_args = shutdown_mock.await_args.args
    assert startup_args[2] is shutdown_args[1]  # stop_event
    assert startup_args[3] is shutdown_args[2]  # bg_tasks list


@pytest.mark.asyncio
async def test_startup_runs_health_monitor_when_enabled(monkeypatch) -> None:
    """``health_monitor_enabled=True`` adds the health monitor task to bg_tasks."""
    settings = _settings(curator_enabled=False, health_monitor_enabled=True)
    init_db_mock = AsyncMock()
    store = AsyncMock()
    health_invocations: list[tuple[object, object]] = []
    created_tasks = 0

    async def maintenance_worker(received_settings: object, stop_event: asyncio.Event):
        await stop_event.wait()

    async def health_monitor(received_settings: object, stop_event: asyncio.Event):
        health_invocations.append((received_settings, stop_event))
        await stop_event.wait()

    def fake_create_task(coro: Coroutine[Any, Any, Any]) -> str:
        nonlocal created_tasks
        created_tasks += 1
        # Drive the coroutine just enough to enter its body so we can prove
        # which worker was wrapped, then close it so no real task lingers.
        try:
            coro.send(None)
        except StopIteration:
            pass
        coro.close()
        return f"task-{created_tasks}"

    maintenance_module = types.ModuleType("piloci.ops.maintenance")
    maintenance_module.run_maintenance_worker = maintenance_worker
    health_module = types.ModuleType("piloci.notify.health")
    health_module.run_health_monitor = health_monitor

    monkeypatch.setattr("piloci.main.get_settings", lambda: settings)
    monkeypatch.setattr("piloci.main.init_db", init_db_mock)
    monkeypatch.setattr("piloci.main.asyncio.create_task", fake_create_task)

    with pytest.MonkeyPatch.context() as patch_ctx:
        patch_ctx.setitem(sys.modules, "piloci.ops.maintenance", maintenance_module)
        patch_ctx.setitem(sys.modules, "piloci.notify.health", health_module)

        stop_event = asyncio.Event()
        bg_tasks: list[object] = []

        await _startup(Starlette(), store, stop_event, bg_tasks, instincts_store=None)

    assert created_tasks == 2
    assert len(bg_tasks) == 2
    assert len(health_invocations) == 1
    assert health_invocations[0][0] is settings
    assert health_invocations[0][1] is stop_event


@pytest.mark.asyncio
async def test_startup_runs_telegram_bot_when_token_and_chat_id_present(monkeypatch) -> None:
    """Telegram bot section requires bot_enabled + token + chat_id all set."""
    settings = _settings(
        curator_enabled=False,
        telegram_bot_enabled=True,
        telegram_bot_token="bot-token",
        telegram_chat_id="chat-123",
    )
    init_db_mock = AsyncMock()
    store = AsyncMock()
    telegram_invocations: list[tuple[object, object]] = []
    created_tasks = 0

    async def maintenance_worker(received_settings: object, stop_event: asyncio.Event):
        await stop_event.wait()

    async def telegram_bot(received_settings: object, stop_event: asyncio.Event):
        telegram_invocations.append((received_settings, stop_event))
        await stop_event.wait()

    def fake_create_task(coro: Coroutine[Any, Any, Any]) -> str:
        nonlocal created_tasks
        created_tasks += 1
        try:
            coro.send(None)
        except StopIteration:
            pass
        coro.close()
        return f"task-{created_tasks}"

    maintenance_module = types.ModuleType("piloci.ops.maintenance")
    maintenance_module.run_maintenance_worker = maintenance_worker
    telegram_module = types.ModuleType("piloci.notify.telegram_bot")
    telegram_module.run_telegram_bot = telegram_bot

    monkeypatch.setattr("piloci.main.get_settings", lambda: settings)
    monkeypatch.setattr("piloci.main.init_db", init_db_mock)
    monkeypatch.setattr("piloci.main.asyncio.create_task", fake_create_task)

    with pytest.MonkeyPatch.context() as patch_ctx:
        patch_ctx.setitem(sys.modules, "piloci.ops.maintenance", maintenance_module)
        patch_ctx.setitem(sys.modules, "piloci.notify.telegram_bot", telegram_module)

        stop_event = asyncio.Event()
        bg_tasks: list[object] = []

        await _startup(Starlette(), store, stop_event, bg_tasks, instincts_store=None)

    assert created_tasks == 2
    assert len(bg_tasks) == 2
    assert len(telegram_invocations) == 1
    assert telegram_invocations[0][0] is settings
    assert telegram_invocations[0][1] is stop_event


@pytest.mark.asyncio
async def test_startup_skips_telegram_when_token_missing(monkeypatch) -> None:
    """Telegram block is gated on bot_enabled AND token AND chat_id."""
    settings = _settings(
        curator_enabled=False,
        telegram_bot_enabled=True,
        telegram_bot_token=None,
        telegram_chat_id="chat-123",
    )
    init_db_mock = AsyncMock()
    store = AsyncMock()
    task_count = 0

    async def maintenance_worker(received_settings: object, stop_event: asyncio.Event):
        await stop_event.wait()

    def fake_create_task(coro: Coroutine[Any, Any, Any]) -> str:
        nonlocal task_count
        task_count += 1
        coro.close()
        return f"task-{task_count}"

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

    # Only the maintenance worker — telegram path is gated off.
    assert task_count == 1
