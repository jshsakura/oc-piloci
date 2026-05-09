"""REST API v1 — thin shims over existing MCP tool handlers.

All endpoints require Bearer JWT auth via ``_require_user``.  Project-scoped
endpoints (memory, recall, recommend, contradict) additionally require the JWT
to carry a ``project_id`` claim; otherwise they return 403.

Dependencies are pulled from ``request.app.state`` (``store``,
``instincts_store``) and from ``get_settings()`` for the embed function — the
same approach used by the existing REST routes in routes.py.
"""

from __future__ import annotations

import logging
from typing import Any

import orjson
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response

from piloci.config import get_settings
from piloci.curator.vault import invalidate_project_vault_cache

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Re-use helpers from routes.py (same module-boundary access)
# ---------------------------------------------------------------------------


def _json(data: Any, status: int = 200) -> Response:
    return Response(orjson.dumps(data), status_code=status, media_type="application/json")


def _require_user(request: Request) -> dict[str, Any] | None:
    return getattr(request.state, "user", None)


def _uid(user: dict[str, Any]) -> str:
    return user.get("sub") or user.get("user_id") or ""


def _require_project_id(user: dict[str, Any]) -> str | None:
    """Return project_id from JWT or None.  Returns None when claim is absent."""
    return user.get("project_id") or None


# ---------------------------------------------------------------------------
# Shared embed helper (mirrors mcp/server.py _embed closure)
# ---------------------------------------------------------------------------


async def _embed_fn(text: str) -> list[float]:
    from piloci.storage import embed as _embed_mod

    settings = get_settings()
    return await _embed_mod.embed_one(
        text,
        model=settings.embed_model,
        cache_dir=settings.embed_cache_dir,
        lru_size=settings.embed_lru_size,
        executor_workers=settings.embed_executor_workers,
        max_concurrency=settings.embed_max_concurrency,
    )


# ---------------------------------------------------------------------------
# Shared projects_fn / create_project_fn (stateless, built on each call)
# ---------------------------------------------------------------------------


async def _build_projects_fn():
    """Return a projects_fn compatible with handle_list_projects / handle_init."""
    from sqlalchemy import select

    from piloci.db.models import Project
    from piloci.db.session import async_session

    async def projects_fn(user_id: str, refresh: bool) -> list[dict[str, Any]]:
        async with async_session() as db:
            rows = (
                (await db.execute(select(Project).where(Project.user_id == user_id)))
                .scalars()
                .all()
            )
        return [
            {
                "id": p.id,
                "slug": p.slug,
                "name": p.name,
                "memory_count": p.memory_count,
                "cwd": p.cwd,
            }
            for p in rows
        ]

    return projects_fn


async def _build_create_project_fn():
    """Return a create_project_fn compatible with handle_init."""
    import hashlib
    import uuid
    from datetime import datetime, timezone

    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from piloci.db.models import Project
    from piloci.db.session import async_session

    async def create_project_fn(
        user_id: str, name: str, slug: str, cwd: str | None = None
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)

        async def _try_insert(target_slug: str, target_cwd: str | None) -> Project | None:
            project = Project(
                id=str(uuid.uuid4()),
                user_id=user_id,
                slug=target_slug,
                name=name,
                cwd=target_cwd,
                created_at=now,
                updated_at=now,
            )
            async with async_session() as db:
                db.add(project)
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    return None
            return project

        created = await _try_insert(slug, cwd)
        if created is not None:
            return {
                "id": created.id,
                "slug": created.slug,
                "name": created.name,
                "cwd": created.cwd,
            }

        # Slug taken — load existing row
        async with async_session() as db:
            row = (
                await db.execute(
                    select(Project).where(Project.user_id == user_id, Project.slug == slug)
                )
            ).scalar_one_or_none()

        if row is not None:
            same_cwd = (row.cwd or None) == (cwd or None)
            legacy_no_cwd = row.cwd is None and cwd is not None
            if same_cwd or legacy_no_cwd:
                return {"id": row.id, "slug": row.slug, "name": row.name, "cwd": cwd or row.cwd}

            if cwd:
                suffix = hashlib.sha1(cwd.encode()).hexdigest()[:6]
                disambig = f"{slug}-{suffix}"[:50]
                created = await _try_insert(disambig, cwd)
                if created is not None:
                    return {
                        "id": created.id,
                        "slug": created.slug,
                        "name": created.name,
                        "cwd": created.cwd,
                    }

        raise RuntimeError(f"create_project_fn: could not create project for slug={slug}")

    return create_project_fn


async def _build_profile_fn():
    from piloci.curator.profile import get_profile as _get_profile

    async def profile_fn(user_id: str, project_id: str) -> dict[str, Any] | None:
        return await _get_profile(user_id, project_id)

    return profile_fn


# ---------------------------------------------------------------------------
# POST /api/v1/memory
# ---------------------------------------------------------------------------


async def route_v1_memory(request: Request) -> Response:
    user = _require_user(request)
    if user is None:
        return _json({"error": "Unauthorized"}, 401)

    project_id = _require_project_id(user)
    if not project_id:
        return _json({"error": "project-scoped token required"}, 403)

    user_id = _uid(user)

    try:
        raw = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)

    from piloci.tools.memory_tools import MemoryInput, handle_memory

    try:
        args = MemoryInput.model_validate(raw)
    except ValidationError as exc:
        return _json({"error": "validation error", "details": exc.errors()}, 422)

    store = request.app.state.store
    result = await handle_memory(args, user_id, project_id, store, _embed_fn)

    if result.get("success"):
        settings = get_settings()
        await invalidate_project_vault_cache(
            settings.vault_dir,
            user_id,
            project_id,
            user.get("project_slug"),
        )

    return _json(result)


# ---------------------------------------------------------------------------
# POST /api/v1/recall
# ---------------------------------------------------------------------------


async def route_v1_recall(request: Request) -> Response:
    user = _require_user(request)
    if user is None:
        return _json({"error": "Unauthorized"}, 401)

    project_id = _require_project_id(user)
    if not project_id:
        return _json({"error": "project-scoped token required"}, 403)

    user_id = _uid(user)

    try:
        raw = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)

    from piloci.tools.memory_tools import RecallInput, handle_recall

    try:
        args = RecallInput.model_validate(raw)
    except ValidationError as exc:
        return _json({"error": "validation error", "details": exc.errors()}, 422)

    store = request.app.state.store
    settings = get_settings()
    profile_fn = await _build_profile_fn()

    result = await handle_recall(
        args,
        user_id,
        project_id,
        store,
        _embed_fn,
        profile_fn=profile_fn,
        export_dir=settings.export_dir,
    )
    return _json(result)


# ---------------------------------------------------------------------------
# GET /api/v1/projects
# ---------------------------------------------------------------------------


async def route_v1_projects(request: Request) -> Response:
    user = _require_user(request)
    if user is None:
        return _json({"error": "Unauthorized"}, 401)

    user_id = _uid(user)

    from piloci.tools.memory_tools import ListProjectsInput, handle_list_projects

    refresh_param = request.query_params.get("refresh", "").strip().lower()
    refresh = refresh_param in {"1", "true", "yes", "on"}

    args = ListProjectsInput(refresh=refresh)
    projects_fn = await _build_projects_fn()
    result = await handle_list_projects(args, user_id, projects_fn)
    return _json(result)


# ---------------------------------------------------------------------------
# GET /api/v1/whoami
# ---------------------------------------------------------------------------


async def route_v1_whoami(request: Request) -> Response:
    user = _require_user(request)
    if user is None:
        return _json({"error": "Unauthorized"}, 401)

    user_id = _uid(user)
    project_id = user.get("project_id")
    session_id = user.get("jti")

    from piloci.tools.memory_tools import WhoAmIInput, handle_whoami

    result = await handle_whoami(
        WhoAmIInput(),
        user_id,
        project_id,
        auth_payload=user,
        session_id=session_id,
        client_info=None,
    )
    return _json(result)


# ---------------------------------------------------------------------------
# POST /api/v1/init
# ---------------------------------------------------------------------------


async def route_v1_init(request: Request) -> Response:
    user = _require_user(request)
    if user is None:
        return _json({"error": "Unauthorized"}, 401)

    user_id = _uid(user)
    project_id = user.get("project_id")

    try:
        raw = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)

    from piloci.tools.memory_tools import InitInput, handle_init

    try:
        args = InitInput.model_validate(raw)
    except ValidationError as exc:
        return _json({"error": "validation error", "details": exc.errors()}, 422)

    projects_fn = await _build_projects_fn()
    create_project_fn = await _build_create_project_fn()

    result = await handle_init(
        args,
        user_id,
        project_id,
        projects_fn=projects_fn,
        create_project_fn=create_project_fn,
    )
    return _json(result)


# ---------------------------------------------------------------------------
# POST /api/v1/recommend
# ---------------------------------------------------------------------------


async def route_v1_recommend(request: Request) -> Response:
    user = _require_user(request)
    if user is None:
        return _json({"error": "Unauthorized"}, 401)

    project_id = _require_project_id(user)
    if not project_id:
        return _json({"error": "project-scoped token required"}, 403)

    user_id = _uid(user)

    try:
        raw = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)

    from piloci.tools.instinct_tools import RecommendInput, handle_recommend

    try:
        args = RecommendInput.model_validate(raw)
    except ValidationError as exc:
        return _json({"error": "validation error", "details": exc.errors()}, 422)

    instincts_store = getattr(request.app.state, "instincts_store", None)
    if instincts_store is None:
        return _json({"instincts": [], "total": 0, "error": "instincts not enabled"})

    result = await handle_recommend(args, user_id, project_id, instincts_store)
    return _json(result)


# ---------------------------------------------------------------------------
# POST /api/v1/contradict
# ---------------------------------------------------------------------------


async def route_v1_contradict(request: Request) -> Response:
    user = _require_user(request)
    if user is None:
        return _json({"error": "Unauthorized"}, 401)

    project_id = _require_project_id(user)
    if not project_id:
        return _json({"error": "project-scoped token required"}, 403)

    user_id = _uid(user)

    try:
        raw = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)

    from piloci.tools.instinct_tools import ContradictInput, handle_contradict

    try:
        args = ContradictInput.model_validate(raw)
    except ValidationError as exc:
        return _json({"error": "validation error", "details": exc.errors()}, 422)

    instincts_store = getattr(request.app.state, "instincts_store", None)
    if instincts_store is None:
        return _json({"success": False, "error": "instincts not enabled"})

    result = await handle_contradict(args, user_id, project_id, instincts_store)
    return _json(result)
