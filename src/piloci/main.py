from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount

from piloci.api.ratelimit import setup_ratelimit
from piloci.api.routes import get_routes
from piloci.api.security import SecurityHeadersMiddleware
from piloci.api.static import get_static_app
from piloci.auth.middleware import AuthMiddleware
from piloci.config import get_settings
from piloci.db.session import init_db
from piloci.mcp.server import create_mcp_server
from piloci.mcp.sse import create_sse_app
from piloci.mcp.streamable_http import create_streamable_http_app
from piloci.storage.instincts_store import InstinctsStore
from piloci.storage.lancedb_store import MemoryStore
from piloci.utils.logging import RuntimeProfilingMiddleware, configure_logging

logger = logging.getLogger(__name__)


@dataclass
class _ProjectsCacheEntry:
    fetched_at: float
    projects: list[dict[str, Any]]


class _ProjectsCache:
    def __init__(self, ttl_sec: float = 300.0) -> None:
        self.ttl_sec = ttl_sec
        self._entries: dict[str, _ProjectsCacheEntry] = {}

    def get(self, user_id: str) -> list[dict[str, Any]] | None:
        entry = self._entries.get(user_id)
        if entry is None:
            return None
        if time.monotonic() - entry.fetched_at >= self.ttl_sec:
            self._entries.pop(user_id, None)
            return None
        return [project.copy() for project in entry.projects]

    def set(self, user_id: str, projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cached = [project.copy() for project in projects]
        self._entries[user_id] = _ProjectsCacheEntry(
            fetched_at=time.monotonic(),
            projects=cached,
        )
        return [project.copy() for project in cached]

    def invalidate(self, user_id: str) -> None:
        self._entries.pop(user_id, None)


async def _run_stdio() -> None:
    from mcp.server.stdio import stdio_server

    settings = get_settings()
    store = MemoryStore(settings)
    instincts_store = InstinctsStore(settings)
    await store.ensure_collection()
    await instincts_store.ensure_collection()
    mcp_server = _build_mcp(settings, store, instincts_store)
    logger.info("piLoci stdio MCP server starting")
    async with stdio_server() as (read, write):
        await mcp_server.run(read, write, mcp_server.create_initialization_options())


def run_stdio() -> None:
    configure_logging()
    asyncio.run(_run_stdio())


def _build_mcp(settings, store: MemoryStore, instincts_store: InstinctsStore | None = None):
    """Build MCP server with v0.3 resources/prompts wired to DB + store."""
    from sqlalchemy import select

    from piloci.curator.profile import get_profile as _get_profile
    from piloci.db.models import Project
    from piloci.db.session import async_session

    projects_cache = _ProjectsCache(ttl_sec=300.0)

    async def profile_fn(user_id: str, project_id: str) -> dict[str, Any] | None:
        return await _get_profile(user_id, project_id)

    async def projects_fn(user_id: str, refresh: bool) -> list[dict[str, Any]]:
        if not refresh:
            cached = projects_cache.get(user_id)
            if cached is not None:
                return cached
        async with async_session() as db:
            rows = (
                (await db.execute(select(Project).where(Project.user_id == user_id)))
                .scalars()
                .all()
            )
        projects = [
            {"id": p.id, "slug": p.slug, "name": p.name, "memory_count": p.memory_count}
            for p in rows
        ]
        return projects_cache.set(user_id, projects)

    async def recent_fn(user_id: str, project_id: str, limit: int) -> list[dict[str, Any]]:
        rows = await store.list(user_id=user_id, project_id=project_id, limit=limit, offset=0)
        rows.sort(key=lambda m: m.get("updated_at", 0), reverse=True)
        return rows

    async def create_project_fn(user_id: str, name: str, slug: str) -> dict[str, Any]:
        import uuid
        from datetime import datetime, timezone

        from sqlalchemy.exc import IntegrityError

        from piloci.db.models import Project

        now = datetime.now(timezone.utc)
        project = Project(
            id=str(uuid.uuid4()),
            user_id=user_id,
            slug=slug,
            name=name,
            created_at=now,
            updated_at=now,
        )
        async with async_session() as db:
            db.add(project)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                row = (
                    await db.execute(
                        select(Project).where(Project.user_id == user_id, Project.slug == slug)
                    )
                ).scalar_one_or_none()
                if row:
                    return {"id": row.id, "slug": row.slug, "name": row.name}
                raise
        return {"id": project.id, "slug": project.slug, "name": project.name}

    return create_mcp_server(
        settings,
        store,
        profile_fn=profile_fn,
        projects_fn=projects_fn,
        recent_fn=recent_fn,
        instincts_store=instincts_store,
        create_project_fn=create_project_fn,
    )


def create_app():
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)

    store = MemoryStore(settings)
    instincts_store = InstinctsStore(settings)
    mcp_server = _build_mcp(settings, store, instincts_store)

    mcp_app = create_sse_app(mcp_server, debug=settings.debug, prefix="/mcp")
    http_app = create_streamable_http_app(mcp_server)

    from starlette.routing import Mount as SMount

    routes = [
        *get_routes(),
        SMount("/mcp/http", app=http_app),
        SMount("/mcp", app=mcp_app),
    ]

    static = get_static_app()
    if static:
        routes.append(Mount("/", app=static))

    # State held across lifespan
    stop_event = asyncio.Event()
    bg_tasks: list[asyncio.Task[Any]] = []

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app_inner):
        await _startup(app_inner, store, stop_event, bg_tasks, instincts_store)
        try:
            yield
        finally:
            await _shutdown(store, stop_event, bg_tasks)

    app = Starlette(
        debug=settings.debug,
        routes=routes,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=settings.cors_origins,
                allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                allow_headers=["Authorization", "Content-Type"],
                allow_credentials=True,
            ),
            Middleware(RuntimeProfilingMiddleware),
            Middleware(SecurityHeadersMiddleware),
            Middleware(AuthMiddleware, settings=settings),
        ],
        lifespan=lifespan,
    )
    app.state.store = store
    app.state.instincts_store = instincts_store
    setup_ratelimit(app)
    return app


async def _startup(app, store, stop_event, bg_tasks, instincts_store=None) -> None:
    settings = get_settings()
    await init_db()
    logger.info("Database initialized")
    await store.ensure_collection()
    if instincts_store is not None:
        await instincts_store.ensure_collection()
    logger.info("LanceDB collection ready")

    from piloci.ops.maintenance import run_maintenance_worker

    bg_tasks.append(asyncio.create_task(run_maintenance_worker(settings, stop_event)))
    logger.info("Maintenance worker started")

    if settings.curator_enabled:
        from piloci.curator.analyze_worker import process_unfinished_analyses, run_analyze_worker
        from piloci.curator.profile import run_profile_worker
        from piloci.curator.worker import process_unfinished, run_worker

        requeued = await process_unfinished(settings, store)
        logger.info("Re-queued %d unprocessed sessions", requeued)

        bg_tasks.append(asyncio.create_task(run_worker(settings, store, stop_event)))
        bg_tasks.append(asyncio.create_task(run_profile_worker(settings, store, stop_event)))
        logger.info("Curator + profile workers started")

        if instincts_store is not None:
            requeued_analyses = await process_unfinished_analyses(settings)
            logger.info("Re-queued %d unprocessed analyses", requeued_analyses)
            bg_tasks.append(
                asyncio.create_task(run_analyze_worker(settings, instincts_store, stop_event))
            )
            logger.info("Analyze worker started")


async def _shutdown(store, stop_event, bg_tasks) -> None:
    stop_event.set()
    for task in bg_tasks:
        try:
            await asyncio.wait_for(task, timeout=10.0)
        except asyncio.TimeoutError:
            task.cancel()
        except Exception as exc:
            logger.debug("Background task failed during shutdown: %s", exc)
    await store.close()
    logger.info("LanceDB connection closed")


def run_sse() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    app_target = "piloci.main:create_app" if settings.reload else create_app()
    uvicorn.run(
        app_target,
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=1 if settings.reload else settings.workers,
        log_level=settings.log_level.lower(),
        factory=settings.reload,
    )
