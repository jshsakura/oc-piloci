from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import orjson
from cryptography.fernet import InvalidToken
from sqlalchemy import delete
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from piloci.api.ratelimit import RATE_DATA_IO, RATE_LOGIN, RATE_PASSWORD_RESET, RATE_SIGNUP, limiter
from piloci.auth.jwt_utils import create_token
from piloci.auth.local import (
    AccountLockedError,
    ApprovalPendingError,
    ApprovalRejectedError,
    EmailExistsError,
    InvalidCredentialsError,
    InvalidTOTPError,
    TokenExpiredError,
    TokenInvalidError,
    TokenUsedError,
    TOTPRequiredError,
    WeakPasswordError,
    create_reset_token,
    login,
    reset_password,
    signup,
)
from piloci.auth.session import get_session_store
from piloci.config import get_settings
from piloci.curator.queue import IngestJob, get_ingest_queue, try_enqueue_job


def _resolve_base_url(request: Request, settings: Any) -> str:
    """Determine the public base URL, respecting reverse-proxy headers.

    Priority:
      1. ``settings.base_url`` (BASE_URL / PILOCI_PUBLIC_URL env var)
      2. ``X-Forwarded-Proto`` + ``Host`` header  (Cloudflare Tunnel, nginx, etc.)
      3. ``request.base_url`` fallback
    """
    if settings.base_url:
        return settings.base_url

    proto = request.headers.get("x-forwarded-proto")
    host = request.headers.get("host") or request.headers.get("x-forwarded-host")
    if proto and host:
        return f"{proto}://{host}"

    return str(request.base_url).rstrip("/")


from sqlalchemy.ext.asyncio import AsyncSession

from piloci.api import v1
from piloci.curator.vault import (
    build_project_vault_preview,
    ensure_project_vault,
    export_project_vault_zip,
    invalidate_project_vault_cache,
    load_cached_project_vault,
)
from piloci.db.session import async_session
from piloci.utils.logging import get_runtime_profiler

logger = logging.getLogger(__name__)


def _generate_token_setup(token: str, base_url: str) -> dict[str, Any]:
    """Generate ready-to-paste config snippets for Claude Code integration."""
    from piloci.tools.memory_tools import (
        HOOK_SCRIPT,
        _build_session_start_hook,
        build_hook_config_json,
    )

    auth_header = {"Authorization": f"Bearer {token}"}
    mcp_config = {
        "mcpServers": {
            "piloci": {
                "type": "http",
                "url": f"{base_url}/mcp/http",
                "headers": auth_header,
            }
        }
    }
    hook_config = _build_session_start_hook()
    hook_config_json = build_hook_config_json(token, base_url)
    claude_md = (
        "## piLoci Memory\n\n"
        "Use piLoci MCP tools to maintain context across sessions:\n\n"
        "1. **Session start**: Call `recall` with a query about the current task "
        "to load relevant memories from past sessions\n"
        "2. **Save actively**: Use `memory` throughout the conversation to save facts, "
        "decisions, preferences, code patterns, and insights. When in doubt, SAVE.\n"
        "3. **Tags**: Add 1-3 tags when saving "
        '(e.g. `["architecture", "bugfix", "preference"]`)\n'
    )
    return {
        "mcp_config": mcp_config,
        "hook_config": hook_config,
        "hook_config_json": hook_config_json,
        "hook_script": HOOK_SCRIPT,
        "claude_md": claude_md,
    }


def _json(data: Any, status: int = 200) -> Response:
    return Response(orjson.dumps(data), status_code=status, media_type="application/json")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _queue_pressure(depth: int, capacity: int) -> str:
    if capacity <= 0:
        return "unbounded"
    utilization = depth / capacity
    if utilization >= 1.0:
        return "full"
    if utilization >= 0.8:
        return "high"
    return "normal"


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


async def route_signup(request: Request) -> Response:
    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    name = (body.get("name") or "").strip()

    if not email or not password:
        return _json({"error": "email and password are required"}, 400)

    settings = get_settings()
    try:
        async with async_session() as db:
            user = await signup(
                email=email, password=password, name=name, db_session=db, settings=settings
            )
        return _json(
            {
                "user_id": user.id,
                "email": user.email,
                "approval_status": user.approval_status,
                "is_admin": user.is_admin,
            },
            201,
        )
    except EmailExistsError:
        return _json({"error": "Email already registered"}, 409)
    except WeakPasswordError as e:
        return _json({"error": str(e)}, 422)
    except Exception:
        return _json({"error": "Internal server error"}, 500)


async def route_login(request: Request) -> Response:
    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    totp_code: str | None = body.get("totp_code") or None

    if not email or not password:
        return _json({"error": "email and password are required"}, 400)

    settings = get_settings()
    redis_session = get_session_store(settings)
    ip = _ip(request)
    ua = request.headers.get("user-agent", "")

    try:
        async with async_session() as db:
            user, session_id = await login(
                email=email,
                password=password,
                ip=ip,
                user_agent=ua,
                db_session=db,
                redis_session=redis_session,
                settings=settings,
                totp_code=totp_code,
            )
        response = _json({"user_id": user.id, "email": user.email, "is_admin": user.is_admin})
        response.set_cookie(
            "piloci_session",
            session_id,
            httponly=True,
            samesite="lax",
            secure=_resolve_base_url(request, settings).startswith("https"),
            max_age=settings.session_expire_days * 86400,
            path="/",
        )
        return response
    except AccountLockedError as e:
        return _json({"error": str(e)}, 429)
    except TOTPRequiredError:
        return _json({"error": "2FA code required", "totp_required": True}, 401)
    except InvalidTOTPError:
        return _json({"error": "Invalid 2FA code"}, 401)
    except InvalidCredentialsError:
        return _json({"error": "Invalid email or password"}, 401)
    except ApprovalPendingError:
        return _json({"error": "Account pending admin approval"}, 403)
    except ApprovalRejectedError:
        return _json({"error": "Account has been rejected by an admin"}, 403)
    except Exception:
        return _json({"error": "Internal server error"}, 500)


async def route_logout(request: Request) -> Response:
    session_id = request.cookies.get("piloci_session")
    if session_id:
        settings = get_settings()
        store = get_session_store(settings)
        session = await store.get_session(session_id)
        if session:
            await store.delete_session(session_id, session["user_id"])
    response = _json({"status": "logged out"})
    response.delete_cookie("piloci_session", path="/")
    return response


async def route_forgot_password(request: Request) -> Response:
    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    email = (body.get("email") or "").strip().lower()
    if not email:
        return _json({"error": "email is required"}, 400)

    try:
        async with async_session() as db:
            token = await create_reset_token(email=email, db_session=db)
        if token is None:
            return _json({"message": "If that email exists, a reset token has been generated"}, 200)
        return _json({"token": token}, 200)
    except Exception:
        return _json({"message": "If that email exists, a reset token has been generated"}, 200)


async def route_reset_password(request: Request) -> Response:
    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    token = body.get("token") or ""
    new_password = body.get("new_password") or ""

    if not token or not new_password:
        return _json({"error": "token and new_password are required"}, 400)

    try:
        async with async_session() as db:
            await reset_password(token=token, new_password=new_password, db_session=db)
        return _json({"message": "Password has been reset successfully"}, 200)
    except TokenInvalidError:
        return _json({"error": "Invalid reset token"}, 400)
    except TokenUsedError:
        return _json({"error": "Reset token has already been used"}, 400)
    except TokenExpiredError:
        return _json({"error": "Reset token has expired"}, 400)
    except WeakPasswordError as e:
        return _json({"error": str(e)}, 422)
    except Exception:
        return _json({"error": "Internal server error"}, 500)


# ---------------------------------------------------------------------------
# Project API routes (require auth)
# ---------------------------------------------------------------------------


def _require_user(request: Request) -> dict[str, Any] | None:
    return getattr(request.state, "user", None)


def _uid(user: dict[str, Any]) -> str:
    """Extract user id from JWT payload (sub) or session dict (user_id)."""
    return user.get("sub") or user.get("user_id") or ""


def _require_admin(request: Request) -> dict[str, Any] | None:
    user = getattr(request.state, "user", None)
    if user is None or not user.get("is_admin"):
        return None
    return user


async def _get_user_project_by_slug(user_id: str, slug: str) -> dict[str, Any] | None:
    from sqlalchemy import select

    from piloci.db.models import Project

    async with async_session() as db:
        result = await db.execute(
            select(Project).where(Project.user_id == user_id, Project.slug == slug)
        )
        project = result.scalar_one_or_none()

    if project is None:
        return None

    return {
        "id": project.id,
        "slug": project.slug,
        "name": project.name,
        "description": project.description,
        "memory_count": project.memory_count,
        "created_at": project.created_at.isoformat(),
    }


async def route_dashboard_summary(request: Request) -> Response:
    """GET /api/dashboard/summary — cross-project activity feed for the dashboard.

    Returns recent memories, top instincts, recent sessions, daily session
    counts (last 30 days), and aggregated top tags — all in one round-trip so
    the dashboard can show living data without N project drilldowns.
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    user_id = _uid(user)

    from sqlalchemy import func, select

    from piloci.db.models import Project, RawSession

    async with async_session() as db:
        proj_rows = (
            (await db.execute(select(Project).where(Project.user_id == user_id))).scalars().all()
        )
    project_by_id = {p.id: {"slug": p.slug, "name": p.name} for p in proj_rows}

    store = request.app.state.store
    instincts_store = getattr(request.app.state, "instincts_store", None)

    recent_memories: list[dict[str, Any]] = []
    top_instincts: list[dict[str, Any]] = []
    tag_counts: dict[str, int] = {}

    for p in proj_rows:
        try:
            mems = await store.list(user_id=user_id, project_id=p.id, limit=25, offset=0)
        except Exception:
            mems = []
        for m in mems:
            tags = m.get("tags") or []
            for t in tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1
            recent_memories.append(
                {
                    "memory_id": m.get("memory_id"),
                    "content": (m.get("content") or "")[:300],
                    "tags": tags[:5],
                    "project_slug": p.slug,
                    "project_name": p.name,
                    "created_at": m.get("created_at"),
                    "updated_at": m.get("updated_at"),
                }
            )

        if instincts_store is not None:
            try:
                ins = await instincts_store.list_instincts(
                    user_id=user_id, project_id=p.id, limit=10
                )
            except Exception:
                ins = []
            for i in ins:
                top_instincts.append(
                    {
                        "instinct_id": i.get("instinct_id"),
                        "trigger": i.get("trigger") or "",
                        "action": i.get("action") or "",
                        "domain": i.get("domain") or "other",
                        "confidence": i.get("confidence", 0.0),
                        "instinct_count": i.get("instinct_count", 0),
                        "project_slug": p.slug,
                        "project_name": p.name,
                    }
                )

    recent_memories.sort(key=lambda r: r.get("updated_at") or 0, reverse=True)
    recent_memories = recent_memories[:10]

    top_instincts.sort(
        key=lambda r: r.get("confidence", 0.0) * (r.get("instinct_count") or 1),
        reverse=True,
    )
    top_instincts = top_instincts[:8]

    top_tags = sorted(
        ({"tag": k, "count": v} for k, v in tag_counts.items()),
        key=lambda r: r["count"],
        reverse=True,
    )[:15]

    # Recent ingested sessions + activity buckets — single SQL pass. Window
    # matches raw_session_retention_days so the chart doesn't show fake zeros
    # past the retention edge.
    from datetime import timedelta

    settings = get_settings()
    activity_window = getattr(settings, "raw_session_retention_days", 90)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=activity_window)
    async with async_session() as db:
        recent_sess_rows = (
            (
                await db.execute(
                    select(RawSession)
                    .where(RawSession.user_id == user_id)
                    .order_by(RawSession.created_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        bucket_rows = (
            await db.execute(
                select(
                    func.date(RawSession.created_at).label("day"),
                    func.count().label("count"),
                )
                .where(RawSession.user_id == user_id, RawSession.created_at >= cutoff)
                .group_by(func.date(RawSession.created_at))
            )
        ).all()

    recent_sessions = [
        {
            "ingest_id": s.ingest_id,
            "project_slug": project_by_id.get(s.project_id, {}).get("slug"),
            "project_name": project_by_id.get(s.project_id, {}).get("name"),
            "created_at": s.created_at.isoformat(),
            "processed_at": s.processed_at.isoformat() if s.processed_at else None,
            "memories_extracted": s.memories_extracted,
            "client": s.client,
        }
        for s in recent_sess_rows
    ]

    bucket_map = {str(row.day): int(row.count) for row in bucket_rows}
    activity = []
    for offset_days in range(activity_window - 1, -1, -1):
        d = (now - timedelta(days=offset_days)).date()
        activity.append({"date": d.isoformat(), "count": bucket_map.get(str(d), 0)})

    return _json(
        {
            "recent_memories": recent_memories,
            "top_instincts": top_instincts,
            "recent_sessions": recent_sessions,
            "activity": activity,
            "top_tags": top_tags,
        }
    )


async def route_list_projects(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    from sqlalchemy import func, select

    from piloci.db.models import Project, RawAnalysis, RawSession

    user_id = _uid(user)

    async with async_session() as db:
        result = await db.execute(
            select(Project).where(Project.user_id == user_id).order_by(Project.created_at)
        )
        projects = result.scalars().all()

        # Project counts stay small per user — issue one aggregate query per source
        # rather than joining through the dashboard hot path.
        sess_rows = (
            await db.execute(
                select(
                    RawSession.project_id,
                    func.count().label("count"),
                    func.max(RawSession.created_at).label("last_active"),
                )
                .where(RawSession.user_id == user_id)
                .group_by(RawSession.project_id)
            )
        ).all()
        analyze_rows = (
            await db.execute(
                select(
                    RawAnalysis.project_id,
                    func.max(RawAnalysis.processed_at).label("last_analyzed"),
                )
                .where(RawAnalysis.user_id == user_id)
                .group_by(RawAnalysis.project_id)
            )
        ).all()

    sess_by_pid = {row.project_id: (row.count, row.last_active) for row in sess_rows}
    last_analyzed_by_pid = {row.project_id: row.last_analyzed for row in analyze_rows}

    out: list[dict[str, Any]] = []
    for p in projects:
        sess_count, last_active = sess_by_pid.get(p.id, (0, None))
        last_analyzed = last_analyzed_by_pid.get(p.id)
        out.append(
            {
                "id": p.id,
                "slug": p.slug,
                "name": p.name,
                "description": p.description,
                "memory_count": p.memory_count,
                "instinct_count": p.instinct_count,
                "session_count": int(sess_count or 0),
                "last_active_at": last_active.isoformat() if last_active else None,
                "last_analyzed_at": last_analyzed.isoformat() if last_analyzed else None,
                "created_at": p.created_at.isoformat(),
            }
        )
    return _json(out)


async def _resolve_or_create_project(user_id: str, cwd: str) -> str | None:
    """Resolve a user's project for ``cwd``, auto-creating one on first sight.

    Returns the project_id string, or None if the cwd is a home/root dir
    (init refuses those — same guard applies here).
    """
    import hashlib
    import uuid as _uuid_mod
    from datetime import datetime, timezone

    from sqlalchemy import select as _sel
    from sqlalchemy.exc import IntegrityError

    from piloci.db.models import Project
    from piloci.tools.memory_tools import _dir_name, _is_home_or_root, cwd_to_slug

    if _is_home_or_root(cwd):
        return None

    slug = cwd_to_slug(cwd)

    async with async_session() as db:
        # Exact cwd match wins.
        row = (
            await db.execute(
                _sel(Project.id).where(Project.user_id == user_id, Project.cwd == cwd).limit(1)
            )
        ).scalar_one_or_none()
        if row is not None:
            return row
        # Legacy slug match (cwd not yet stamped) — claim by backfilling cwd.
        legacy = (
            await db.execute(
                _sel(Project)
                .where(
                    Project.user_id == user_id,
                    Project.slug == slug,
                    Project.cwd.is_(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if legacy is not None:
            legacy.cwd = cwd
            await db.commit()
            return legacy.id

    # Auto-create. On slug collision (different cwd already owns this slug),
    # disambiguate with a 6-char hash so the two folders don't merge.
    now = datetime.now(timezone.utc)
    candidate_slug = slug
    for attempt in range(2):
        new_proj = Project(
            id=str(_uuid_mod.uuid4()),
            user_id=user_id,
            slug=candidate_slug,
            name=_dir_name(cwd) or candidate_slug,
            cwd=cwd,
            created_at=now,
            updated_at=now,
        )
        try:
            async with async_session() as db:
                db.add(new_proj)
                await db.commit()
            return new_proj.id
        except IntegrityError:
            if attempt == 0:
                suffix = hashlib.sha1(cwd.encode("utf-8")).hexdigest()[:6]
                candidate_slug = f"{slug}-{suffix}"[:50]
                continue
            # Two collisions in a row shouldn't happen — bubble the next one.
            raise
    return None


async def route_create_project(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    slug = (body.get("slug") or "").strip().lower()
    name = (body.get("name") or "").strip()
    description = body.get("description")
    cwd = body.get("cwd")
    if isinstance(cwd, str):
        cwd = cwd.strip() or None
    else:
        cwd = None

    if not slug or not name:
        return _json({"error": "slug and name are required"}, 400)

    if not re.match(r"^[a-z0-9][a-z0-9-]{0,48}[a-z0-9]$", slug) and len(slug) > 1:
        if not re.match(r"^[a-z0-9]$", slug):
            return _json({"error": "slug must be lowercase alphanumeric with hyphens"}, 422)

    from sqlalchemy.exc import IntegrityError

    from piloci.db.models import Project

    now = datetime.now(timezone.utc)
    project = Project(
        id=str(uuid.uuid4()),
        user_id=_uid(user),
        slug=slug,
        name=name,
        description=description,
        cwd=cwd,
        created_at=now,
        updated_at=now,
    )

    try:
        async with async_session() as db:
            db.add(project)
            await db.flush()
        return _json({"id": project.id, "slug": project.slug, "name": project.name}, 201)
    except IntegrityError:
        return _json({"error": "Project slug already exists"}, 409)
    except Exception:
        return _json({"error": "Internal server error"}, 500)


async def route_update_project(request: Request) -> Response:
    """PATCH /api/projects/{id} — update editable fields (name, description).

    Slug stays immutable on purpose: it keys vault paths and project-scoped
    tokens; renaming would orphan existing memories.
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    project_id = request.path_params.get("id")
    if not isinstance(project_id, str) or not project_id:
        return _json({"error": "project id required"}, 400)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    updates: dict[str, Any] = {}
    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            return _json({"error": "name must not be empty"}, 422)
        if len(name) > 200:
            return _json({"error": "name must be <= 200 chars"}, 422)
        updates["name"] = name
    if "description" in body:
        desc = body.get("description")
        if desc is not None and not isinstance(desc, str):
            return _json({"error": "description must be a string or null"}, 422)
        if isinstance(desc, str) and len(desc) > 2000:
            return _json({"error": "description must be <= 2000 chars"}, 422)
        updates["description"] = desc.strip() if isinstance(desc, str) else None

    if not updates:
        return _json({"error": "no editable fields supplied (name, description)"}, 422)

    from sqlalchemy import select, update

    from piloci.db.models import Project

    updates["updated_at"] = datetime.now(timezone.utc)

    async with async_session() as db:
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == _uid(user))
        )
        project = result.scalar_one_or_none()
        if not project:
            return _json({"error": "Not found"}, 404)
        await db.execute(update(Project).where(Project.id == project_id).values(**updates))

    return _json(
        {
            "id": project_id,
            "name": updates.get("name", project.name),
            "description": updates.get("description", project.description),
            "slug": project.slug,
        }
    )


async def route_delete_project(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    project_id = request.path_params.get("id")
    if not isinstance(project_id, str) or not project_id:
        return _json({"error": "project id required"}, 400)
    try:
        body = orjson.loads(await request.body())
    except Exception:
        body = {}

    if not body.get("confirm"):
        return _json({"error": "confirm:true required"}, 422)

    from sqlalchemy import delete, select

    from piloci.db.models import Project

    async with async_session() as db:
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == _uid(user))
        )
        project = result.scalar_one_or_none()
        if not project:
            return _json({"error": "Not found"}, 404)
        await db.execute(delete(Project).where(Project.id == project_id))

    await invalidate_project_vault_cache(
        get_settings().vault_dir,
        _uid(user),
        project_id,
        project.slug,
    )

    return _json({"deleted": True})


async def route_project_workspace(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    slug = (request.path_params.get("slug") or "").strip().lower()
    if not slug:
        return _json({"error": "project slug required"}, 400)

    user_id = _uid(user)
    project = await _get_user_project_by_slug(user_id, slug)
    if project is None:
        return _json({"error": "Not found"}, 404)

    settings = get_settings()
    refresh = _truthy(request.query_params.get("refresh"))
    workspace = None if refresh else load_cached_project_vault(settings.vault_dir, project["slug"])
    if workspace is None:
        store = request.app.state.store
        memories = await store.list(user_id=user_id, project_id=project["id"], limit=200, offset=0)
        workspace = ensure_project_vault(project, memories, settings.vault_dir, force=True)
    return _json({"project": project, "workspace": workspace})


async def route_project_workspace_preview(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    slug = (request.path_params.get("slug") or "").strip().lower()
    if not slug:
        return _json({"error": "project slug required"}, 400)

    user_id = _uid(user)
    project = await _get_user_project_by_slug(user_id, slug)
    if project is None:
        return _json({"error": "Not found"}, 404)

    settings = get_settings()
    refresh = _truthy(request.query_params.get("refresh"))
    workspace = None if refresh else load_cached_project_vault(settings.vault_dir, project["slug"])
    if workspace is None:
        store = request.app.state.store
        memories = await store.list(user_id=user_id, project_id=project["id"], limit=200, offset=0)
        workspace = ensure_project_vault(project, memories, settings.vault_dir, force=True)

    return _json({"project": project, "workspace": build_project_vault_preview(workspace)})


async def route_project_knacks(request: Request) -> Response:
    """GET /api/projects/slug/{slug}/knacks — instinct list for a project."""
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    slug = (request.path_params.get("slug") or "").strip().lower()
    if not slug:
        return _json({"error": "project slug required"}, 400)

    user_id = _uid(user)
    project = await _get_user_project_by_slug(user_id, slug)
    if project is None:
        return _json({"error": "Not found"}, 404)

    instincts_store = getattr(request.app.state, "instincts_store", None)
    if instincts_store is None:
        return _json({"error": "instincts store not available"}, 503)

    rows = await instincts_store.list_instincts(
        user_id=user_id, project_id=project["id"], limit=200
    )
    return _json(
        {
            "project": project,
            "knacks": [
                {
                    "instinct_id": r.get("instinct_id"),
                    "trigger": r.get("trigger") or "",
                    "action": r.get("action") or "",
                    "domain": r.get("domain") or "other",
                    "evidence_note": r.get("evidence_note") or "",
                    "confidence": r.get("confidence", 0.0),
                    "instinct_count": r.get("instinct_count", 0),
                    "created_at": r.get("created_at", 0),
                }
                for r in rows
            ],
        }
    )


async def route_project_sessions(request: Request) -> Response:
    """GET /api/projects/slug/{slug}/sessions — raw transcript list (metadata only).

    Returns metadata for each RawSession row — owner can fetch full transcript
    via the per-row endpoint when needed.
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    slug = (request.path_params.get("slug") or "").strip().lower()
    if not slug:
        return _json({"error": "project slug required"}, 400)

    user_id = _uid(user)
    project = await _get_user_project_by_slug(user_id, slug)
    if project is None:
        return _json({"error": "Not found"}, 404)

    from sqlalchemy import select

    from piloci.db.models import RawSession

    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(RawSession)
                    .where(
                        RawSession.user_id == user_id,
                        RawSession.project_id == project["id"],
                    )
                    .order_by(RawSession.created_at.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
    return _json(
        {
            "project": project,
            "sessions": [
                {
                    "ingest_id": r.ingest_id,
                    "session_id": r.session_id,
                    "client": r.client,
                    "size_bytes": len(r.transcript_json or ""),
                    "created_at": r.created_at.isoformat(),
                    "processed_at": r.processed_at.isoformat() if r.processed_at else None,
                    "memories_extracted": r.memories_extracted,
                    "error": r.error,
                }
                for r in rows
            ],
        }
    )


async def route_raw_session_detail(request: Request) -> Response:
    """GET /api/raw-sessions/{ingest_id} — full transcript for owner/admin viewing.

    Owner-only — never exposes another user's transcripts. Returns the raw
    transcript_json plus metadata so the project view's "원본" tab can
    expand a row inline.
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    ingest_id = (request.path_params.get("ingest_id") or "").strip()
    if not ingest_id:
        return _json({"error": "ingest_id required"}, 400)

    user_id = _uid(user)

    from sqlalchemy import select

    from piloci.db.models import RawSession

    async with async_session() as db:
        row = (
            await db.execute(
                select(RawSession).where(
                    RawSession.ingest_id == ingest_id, RawSession.user_id == user_id
                )
            )
        ).scalar_one_or_none()

    if row is None:
        return _json({"error": "Not found"}, 404)

    return _json(
        {
            "ingest_id": row.ingest_id,
            "session_id": row.session_id,
            "client": row.client,
            "transcript": row.transcript_json,
            "created_at": row.created_at.isoformat(),
            "processed_at": row.processed_at.isoformat() if row.processed_at else None,
            "memories_extracted": row.memories_extracted,
            "error": row.error,
        }
    )


async def route_vault_export(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    slug = (request.path_params.get("slug") or "").strip().lower()
    if not slug:
        return _json({"error": "project slug required"}, 400)

    user_id = _uid(user)
    project = await _get_user_project_by_slug(user_id, slug)
    if project is None:
        return _json({"error": "Not found"}, 404)

    settings = get_settings()
    refresh = _truthy(request.query_params.get("refresh"))
    workspace = None if refresh else load_cached_project_vault(settings.vault_dir, project["slug"])
    if workspace is None:
        store = request.app.state.store
        memories = await store.list(user_id=user_id, project_id=project["id"], limit=200, offset=0)
        workspace = ensure_project_vault(project, memories, settings.vault_dir, force=True)
    archive = export_project_vault_zip(project, workspace)
    headers = {"Content-Disposition": f'attachment; filename="{project["slug"]}-vault.zip"'}
    return Response(archive, media_type="application/zip", headers=headers)


# ---------------------------------------------------------------------------
# Data portability — per-user export/import (Phase 10)
# ---------------------------------------------------------------------------


async def route_data_export(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    user_id = _uid(user)
    if not user_id:
        return _json({"error": "user_id required"}, 400)

    from piloci.api.data_portability import build_export_archive
    from piloci.version import __version__ as piloci_version

    settings = get_settings()
    store = request.app.state.store
    archive = await build_export_archive(
        user_id=user_id,
        store=store,
        settings=settings,
        piloci_version=piloci_version,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"piloci-export-{user_id[:8]}-{timestamp}.zip"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(archive, media_type="application/zip", headers=headers)


async def route_data_import(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    user_id = _uid(user)
    if not user_id:
        return _json({"error": "user_id required"}, 400)

    settings = get_settings()
    raw_body = await request.body()
    if not raw_body:
        return _json({"error": "empty body"}, 400)
    if len(raw_body) > settings.ingest_max_body_bytes:
        return _json({"error": "payload too large"}, 413)

    allow_reembed = _truthy(request.query_params.get("reembed"))

    from piloci.api.data_portability import ArchiveError, import_archive
    from piloci.storage import embed

    async def _embed_one(text: str) -> list[float]:
        return await embed.embed_one(
            text=text,
            model=settings.embed_model,
            cache_dir=settings.embed_cache_dir,
            lru_size=settings.embed_lru_size,
            executor_workers=settings.embed_executor_workers,
            max_concurrency=settings.embed_max_concurrency,
        )

    store = request.app.state.store
    try:
        summary = await import_archive(
            raw_body,
            user_id=user_id,
            store=store,
            settings=settings,
            embed_one_fn=_embed_one,
            allow_reembed=allow_reembed,
        )
    except ArchiveError as exc:
        return _json({"error": str(exc)}, exc.status)

    return _json(
        {
            "imported": True,
            "projects_imported": summary.projects_imported,
            "projects_renamed": summary.projects_renamed,
            "memories_imported": summary.memories_imported,
            "profiles_imported": summary.profiles_imported,
            "re_embedded": summary.re_embedded,
        }
    )


# ---------------------------------------------------------------------------
# Token API
# ---------------------------------------------------------------------------


async def route_create_token(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    token_name = (body.get("name") or "").strip()
    # Project-scoped issuance retired in v0.2.68 — projects are auto-classified
    # from cwd by ingest, so a single user-scoped token covers every workspace.
    # Existing project-scoped tokens stay valid until revoked.
    project_id = None
    scope = "user"

    if not token_name:
        return _json({"error": "name is required"}, 400)

    settings = get_settings()
    project_slug = None

    if project_id:
        from sqlalchemy import select

        from piloci.db.models import Project

        async with async_session() as db:
            result = await db.execute(
                select(Project).where(Project.id == project_id, Project.user_id == _uid(user))
            )
            proj = result.scalar_one_or_none()
        if not proj:
            return _json({"error": "Project not found"}, 404)
        project_slug = proj.slug

    # Resolve email — may not be present in session dict (only in JWT payload)
    user_id_val = _uid(user)
    user_email = user.get("email")
    if not user_email:
        from sqlalchemy import select as _sel

        from piloci.db.models import User as _User

        async with async_session() as _db:
            _r = await _db.execute(_sel(_User).where(_User.id == user_id_val))
            _u = _r.scalar_one_or_none()
            user_email = _u.email if _u else ""

    expire_days_raw = body.get("expire_days")
    if expire_days_raw is None:
        expire_days: int | None = 365
    else:
        expire_days = int(expire_days_raw)
        if expire_days < 0:
            expire_days = 365
        elif expire_days > 365:
            expire_days = 365

    token_id = str(uuid.uuid4())
    jwt_token = create_token(
        user_id=user_id_val,
        email=user_email,
        project_id=project_id,
        project_slug=project_slug,
        scope=scope,
        settings=settings,
        token_id=token_id,
        expire_days=expire_days,
    )

    # Store hash in api_tokens table
    import hashlib

    from piloci.db.models import ApiToken

    token_hash = hashlib.sha256(jwt_token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=expire_days) if expire_days and expire_days > 0 else None

    async with async_session() as db:
        db.add(
            ApiToken(
                token_id=token_id,
                user_id=_uid(user),
                project_id=project_id,
                name=token_name,
                token_hash=token_hash,
                scope=scope,
                created_at=now,
                expires_at=expires_at,
            )
        )

    base_url = _resolve_base_url(request, settings)
    # SessionStart hook (install once, global) applies to both user- and project-scoped
    # tokens. The user picks the scope; the install flow is identical.
    setup = _generate_token_setup(jwt_token, base_url)

    # One-time install code so the user copies a short URL instead of a JWT.
    # The token never appears in shell history, server logs, or copied URLs —
    # only the short-lived code does, and it works exactly once.
    try:
        from piloci.auth.install_pairing import get_install_pairing_store

        pairing = get_install_pairing_store(settings)
        install_code = await pairing.create(token=jwt_token, base_url=base_url)
        install_url = f"{base_url.rstrip('/')}/install/{install_code}"
        setup["install_code"] = install_code
        setup["install_url"] = install_url
        setup["install_command"] = f"curl -sSL {install_url} | bash"
        # Cross-platform fallback — pure-Python installer; works on Windows.
        setup["install_command_windows"] = f"uvx oc-piloci install {install_url}"
    except Exception:
        # Redis hiccup must not block token creation — the user can still
        # fall back to the manual setup snippets in ``setup``.
        logger.exception("install_code generation failed; manual setup still available")

    resp: dict[str, Any] = {
        "token": jwt_token,
        "token_id": token_id,
        "name": token_name,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
    if setup:
        resp["setup"] = setup
    return _json(resp, 201)


async def route_list_tokens(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    from sqlalchemy import select

    from piloci.db.models import ApiToken

    async with async_session() as db:
        result = await db.execute(
            select(ApiToken)
            .where(
                ApiToken.user_id == _uid(user),
                ApiToken.revoked == False,  # noqa: E712
            )
            .order_by(ApiToken.created_at.desc())
        )
        tokens = result.scalars().all()

    return _json(
        [
            {
                "token_id": t.token_id,
                "name": t.name,
                "scope": t.scope,
                "project_id": t.project_id,
                "created_at": t.created_at.isoformat(),
                "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
                "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                "installed_at": t.installed_at.isoformat() if t.installed_at else None,
                "client_kinds": (
                    [k for k in t.client_kinds.split(",") if k] if t.client_kinds else []
                ),
                "hostname": t.hostname,
            }
            for t in tokens
        ]
    )


_ALLOWED_CLIENT_KINDS = {"claude", "opencode"}


# ---------------------------------------------------------------------------
# LLM Providers — user-managed external OpenAI-compatible fallbacks
# ---------------------------------------------------------------------------


def _mask_api_key(key: str) -> str:
    """Show only first/last 4 chars so the UI can confirm 'this is the right one'
    without leaking the secret. Anything ≤8 chars is fully masked."""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}{'•' * 8}{key[-4:]}"


def _serialize_provider(p, *, masked_key: str | None = None) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "base_url": p.base_url,
        "model": p.model,
        "enabled": bool(p.enabled),
        "priority": p.priority,
        "api_key_masked": masked_key,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


async def route_list_llm_providers(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    from sqlalchemy import select

    from piloci.auth.crypto import decrypt_token
    from piloci.db.models import LLMProvider

    settings = get_settings()
    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(LLMProvider)
                    .where(LLMProvider.user_id == _uid(user))
                    .order_by(LLMProvider.priority.asc(), LLMProvider.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    out = []
    for p in rows:
        try:
            masked = _mask_api_key(decrypt_token(p.api_key_encrypted, settings))
        except Exception:
            masked = "(decrypt failed)"
        out.append(_serialize_provider(p, masked_key=masked))
    return _json(out)


async def route_create_llm_provider(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    name = (body.get("name") or "").strip()
    base_url = (body.get("base_url") or "").strip()
    model = (body.get("model") or "").strip()
    api_key = (body.get("api_key") or "").strip()
    if not name or not base_url or not model or not api_key:
        return _json({"error": "name, base_url, model, api_key are required"}, 400)
    if len(name) > 100 or len(base_url) > 500 or len(model) > 100 or len(api_key) > 500:
        return _json({"error": "field too long"}, 422)
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        return _json({"error": "base_url must start with http(s)://"}, 422)

    enabled = bool(body.get("enabled", True))
    priority_raw = body.get("priority", 100)
    try:
        priority = int(priority_raw)
    except (TypeError, ValueError):
        return _json({"error": "priority must be an integer"}, 422)
    if not 0 <= priority <= 1000:
        return _json({"error": "priority must be between 0 and 1000"}, 422)

    from piloci.auth.crypto import encrypt_token
    from piloci.db.models import LLMProvider

    settings = get_settings()
    encrypted = encrypt_token(api_key, settings)
    now = datetime.now(timezone.utc)
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        user_id=_uid(user),
        name=name,
        base_url=base_url,
        model=model,
        api_key_encrypted=encrypted,
        enabled=enabled,
        priority=priority,
        created_at=now,
        updated_at=now,
    )
    async with async_session() as db:
        db.add(provider)
        await db.flush()

    return _json(_serialize_provider(provider, masked_key=_mask_api_key(api_key)), 201)


async def route_update_llm_provider(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    provider_id = request.path_params.get("id")
    if not isinstance(provider_id, str) or not provider_id:
        return _json({"error": "provider id required"}, 400)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    from sqlalchemy import select, update

    from piloci.auth.crypto import encrypt_token
    from piloci.db.models import LLMProvider

    settings = get_settings()
    updates: dict[str, Any] = {}
    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name or len(name) > 100:
            return _json({"error": "name invalid"}, 422)
        updates["name"] = name
    if "base_url" in body:
        url = (body.get("base_url") or "").strip()
        if (
            not url
            or len(url) > 500
            or not (url.startswith("http://") or url.startswith("https://"))
        ):
            return _json({"error": "base_url invalid"}, 422)
        updates["base_url"] = url
    if "model" in body:
        model = (body.get("model") or "").strip()
        if not model or len(model) > 100:
            return _json({"error": "model invalid"}, 422)
        updates["model"] = model
    if "api_key" in body:
        key = (body.get("api_key") or "").strip()
        if not key or len(key) > 500:
            return _json({"error": "api_key invalid"}, 422)
        updates["api_key_encrypted"] = encrypt_token(key, settings)
    if "enabled" in body:
        updates["enabled"] = bool(body.get("enabled"))
    if "priority" in body:
        try:
            pri = int(body.get("priority"))
        except (TypeError, ValueError):
            return _json({"error": "priority must be an integer"}, 422)
        if not 0 <= pri <= 1000:
            return _json({"error": "priority must be between 0 and 1000"}, 422)
        updates["priority"] = pri

    if not updates:
        return _json({"error": "no editable fields supplied"}, 422)
    updates["updated_at"] = datetime.now(timezone.utc)

    async with async_session() as db:
        result = await db.execute(
            select(LLMProvider).where(
                LLMProvider.id == provider_id, LLMProvider.user_id == _uid(user)
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return _json({"error": "Not found"}, 404)
        await db.execute(update(LLMProvider).where(LLMProvider.id == provider_id).values(**updates))
        row = (
            await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
        ).scalar_one()

    from piloci.auth.crypto import decrypt_token

    try:
        masked = _mask_api_key(decrypt_token(row.api_key_encrypted, settings))
    except Exception:
        masked = "(decrypt failed)"
    return _json(_serialize_provider(row, masked_key=masked))


async def route_delete_llm_provider(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    provider_id = request.path_params.get("id")
    if not isinstance(provider_id, str) or not provider_id:
        return _json({"error": "provider id required"}, 400)

    from sqlalchemy import delete, select

    from piloci.db.models import LLMProvider

    async with async_session() as db:
        row = (
            await db.execute(
                select(LLMProvider).where(
                    LLMProvider.id == provider_id, LLMProvider.user_id == _uid(user)
                )
            )
        ).scalar_one_or_none()
        if not row:
            return _json({"error": "Not found"}, 404)
        await db.execute(delete(LLMProvider).where(LLMProvider.id == provider_id))

    return _json({"deleted": True})


async def route_install_heartbeat(request: Request) -> Response:
    """One-shot ping fired by the CLI after ``run_install`` succeeds.

    Stamps the calling token's row with ``installed_at`` (now), the comma-joined
    ``client_kinds`` (e.g. ``"claude,opencode"``), and a short ``hostname``.
    Auth is the existing Bearer flow — the JWT's ``jti`` claim identifies the
    token row to update.
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    token_id = user.get("jti") or user.get("token_id")
    if not token_id:
        return _json({"error": "Bearer token required"}, 401)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    raw_kinds = body.get("client_kinds")
    if not isinstance(raw_kinds, list):
        return _json({"error": "client_kinds must be a list"}, 422)
    kinds = sorted({str(k).strip().lower() for k in raw_kinds if str(k).strip()})
    if not kinds:
        return _json({"error": "client_kinds is empty"}, 422)
    if not set(kinds).issubset(_ALLOWED_CLIENT_KINDS):
        return _json(
            {"error": f"client_kinds must be subset of {sorted(_ALLOWED_CLIENT_KINDS)}"}, 422
        )

    hostname_raw = body.get("hostname")
    hostname = str(hostname_raw).strip()[:64] if isinstance(hostname_raw, str) else None

    from sqlalchemy import update

    from piloci.db.models import ApiToken

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        result = await db.execute(
            update(ApiToken)
            .where(ApiToken.token_id == token_id, ApiToken.user_id == _uid(user))
            .values(
                installed_at=now,
                client_kinds=",".join(kinds),
                hostname=hostname,
            )
        )
    if result.rowcount == 0:
        return _json({"error": "Token not found"}, 404)

    return _json({"installed_at": now.isoformat(), "client_kinds": kinds, "hostname": hostname})


async def route_revoke_token(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    token_id = request.path_params.get("id")

    from sqlalchemy import select, update

    from piloci.db.models import ApiToken

    async with async_session() as db:
        result = await db.execute(
            select(ApiToken).where(ApiToken.token_id == token_id, ApiToken.user_id == _uid(user))
        )
        token = result.scalar_one_or_none()
        if not token:
            return _json({"error": "Not found"}, 404)
        await db.execute(update(ApiToken).where(ApiToken.token_id == token_id).values(revoked=True))

    return _json({"revoked": True})


# ---------------------------------------------------------------------------
# Audit log API
# ---------------------------------------------------------------------------


async def route_list_audit(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    limit = min(int(request.query_params.get("limit", 50)), 200)
    offset = int(request.query_params.get("offset", 0))
    action_filter = request.query_params.get("action")

    from sqlalchemy import select

    from piloci.db.models import AuditLog

    async with async_session() as db:
        q = select(AuditLog).where(AuditLog.user_id == _uid(user))
        if action_filter:
            q = q.where(AuditLog.action == action_filter)
        q = q.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        result = await db.execute(q)
        logs = result.scalars().all()

    return _json(
        [
            {
                "id": log.id,
                "action": log.action,
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "meta_data": log.meta_data,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    )


# ---------------------------------------------------------------------------
# 2FA / TOTP routes
# ---------------------------------------------------------------------------


async def route_2fa_enable(request: Request) -> Response:
    """POST /api/account/2fa/enable — QR + secret 반환 (미확인 상태)"""
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    from sqlalchemy import select

    from piloci.auth.totp import generate_totp_secret, get_qr_base64
    from piloci.db.models import User

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == _uid(user)))
        db_user: User | None = result.scalar_one_or_none()
        if not db_user:
            return _json({"error": "User not found"}, 404)
        if db_user.totp_enabled:
            return _json({"error": "2FA is already enabled"}, 409)

        secret = generate_totp_secret()
        db_user.totp_secret = secret
        db_user.totp_enabled = False
        db.add(db_user)
        await db.commit()

    # Resolve email — may not be present in session dict (only in JWT payload)
    user_id_val = _uid(user)
    user_email = user.get("email")
    if not user_email:
        async with async_session() as _db2:
            _r2 = await _db2.execute(select(User).where(User.id == user_id_val))
            _u2 = _r2.scalar_one_or_none()
            user_email = _u2.email if _u2 else ""

    qr = get_qr_base64(secret, user_email)
    return _json({"qr": qr, "secret": secret})


async def route_2fa_confirm(request: Request) -> Response:
    """POST /api/account/2fa/confirm — body: {"code": "123456"}"""
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    code = (body.get("code") or "").strip()
    if not code:
        return _json({"error": "code is required"}, 400)

    from sqlalchemy import select

    from piloci.auth.totp import generate_backup_codes, hash_backup_codes, verify_totp
    from piloci.db.models import User

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == _uid(user)))
        db_user: User | None = result.scalar_one_or_none()
        if not db_user:
            return _json({"error": "User not found"}, 404)
        if not db_user.totp_secret or db_user.totp_enabled:
            return _json({"error": "2FA setup not initiated or already confirmed"}, 400)

        secret = db_user.totp_secret
        if secret is None:
            return _json({"error": "2FA secret missing"}, 400)
        if not verify_totp(secret, code):
            return _json({"error": "Invalid TOTP code"}, 422)

        backup_codes = generate_backup_codes(10)
        hashed = hash_backup_codes(backup_codes)

        db_user.totp_enabled = True
        db.add(db_user)
        await db.commit()

    return _json({"backup_codes": backup_codes, "backup_codes_hashed": hashed})


async def route_2fa_disable(request: Request) -> Response:
    """POST /api/account/2fa/disable — body: {"password": "...", "code": "123456"}"""
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    password = body.get("password") or ""
    code = (body.get("code") or "").strip()

    if not password or not code:
        return _json({"error": "password and code are required"}, 400)

    from sqlalchemy import select

    from piloci.auth.password import verify_password
    from piloci.auth.totp import verify_totp
    from piloci.db.models import User

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == _uid(user)))
        db_user: User | None = result.scalar_one_or_none()
        if not db_user:
            return _json({"error": "User not found"}, 404)
        if not db_user.totp_enabled:
            return _json({"error": "2FA is not enabled"}, 400)

        if not verify_password(password, db_user.password_hash or ""):
            return _json({"error": "Invalid password"}, 401)

        secret = db_user.totp_secret
        if secret is None:
            return _json({"error": "2FA secret missing"}, 400)

        if not verify_totp(secret, code):
            return _json({"error": "Invalid TOTP code"}, 422)

        db_user.totp_secret = None
        db_user.totp_enabled = False
        db.add(db_user)
        await db.commit()

    return _json({"disabled": True})


# ---------------------------------------------------------------------------
# Account routes
# ---------------------------------------------------------------------------


async def route_me(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    user_email = user.get("email")
    if not user_email:
        from sqlalchemy import select as _sel

        from piloci.db.models import User as _User

        async with async_session() as _db:
            _r = await _db.execute(_sel(_User).where(_User.id == _uid(user)))
            _u = _r.scalar_one_or_none()
            user_email = _u.email if _u else None

    return _json(
        {
            "user_id": _uid(user),
            "email": user_email,
            "scope": user.get("scope"),
            "is_admin": user.get("is_admin", False),
            "approval_status": user.get("approval_status", "approved"),
        }
    )


# POST /api/account/password  body: {"current_password": "...", "new_password": "..."}
async def route_change_password(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    body = orjson.loads(await request.body())
    current = body.get("current_password", "")
    new_pw = body.get("new_password", "")

    if not current or not new_pw:
        return _json({"error": "current_password and new_password required"}, 400)

    # 비밀번호 정책 검증 (12자, 대소문자, 숫자)

    if (
        len(new_pw) < 12
        or not re.search(r"[A-Z]", new_pw)
        or not re.search(r"[a-z]", new_pw)
        or not re.search(r"\d", new_pw)
    ):
        return _json(
            {"error": "Password must be 12+ chars with uppercase, lowercase, and digit"}, 422
        )

    from sqlalchemy import select

    from piloci.auth.password import hash_password, verify_password
    from piloci.db.models import User

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == _uid(user)))
        u = result.scalar_one_or_none()
        if not u or not verify_password(current, u.password_hash or ""):
            return _json({"error": "Current password is incorrect"}, 401)
        u.password_hash = hash_password(new_pw)
        db.add(u)

    return _json({"changed": True})


async def route_auth_providers(_: Request) -> Response:
    """GET /api/auth/providers — 노출 가능한 OAuth provider 상태 목록."""
    from piloci.auth.oauth import PROVIDERS, get_provider_credentials

    settings = get_settings()
    providers = [
        {
            "name": name,
            "configured": get_provider_credentials(settings, name) is not None,
            "login_path": f"/auth/{name}/login",
        }
        for name in PROVIDERS
    ]
    return _json({"providers": providers})


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

_OAUTH_STATE_PREFIX = "oauth_state:"


async def route_oauth_login(request: Request) -> Response:
    """GET /auth/{provider}/login — OAuth 로그인 시작."""
    settings = get_settings()

    from starlette.responses import RedirectResponse

    from piloci.auth.oauth import (
        PROVIDERS,
        build_auth_url,
        generate_state,
        get_provider_credentials,
    )

    provider = (request.path_params.get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        return _json({"error": "Unknown OAuth provider"}, 400)

    credentials = get_provider_credentials(settings, provider)
    if credentials is None:
        return _json({"error": f"{provider} OAuth is not configured"}, 503)
    client_id, _ = credentials

    state = generate_state()
    base_url = _resolve_base_url(request, settings)
    redirect_uri = f"{base_url}/auth/{provider}/callback"

    # state를 Redis에 5분 저장 (CSRF 방어)
    store = get_session_store(settings)
    await store._redis.setex(f"{_OAUTH_STATE_PREFIX}{state}", 300, "1")  # noqa: SLF001

    url = build_auth_url(provider, client_id, redirect_uri, state)
    return RedirectResponse(url, status_code=302)


async def route_oauth_callback(request: Request) -> Response:
    """GET /auth/{provider}/callback — OAuth 인가 코드 처리."""
    settings = get_settings()

    from starlette.responses import RedirectResponse

    from piloci.auth.oauth import (
        PROVIDERS,
        exchange_code,
        get_provider_credentials,
        get_userinfo,
        upsert_oauth_user,
    )

    provider = (request.path_params.get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        return _json({"error": "Unknown OAuth provider"}, 400)

    credentials = get_provider_credentials(settings, provider)
    if credentials is None:
        return _json({"error": f"{provider} OAuth is not configured"}, 503)
    client_id, client_secret = credentials

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error or not code or not state:
        return RedirectResponse("/login?error=oauth_cancelled", status_code=302)

    # state 검증
    store = get_session_store(settings)
    state_key = f"{_OAUTH_STATE_PREFIX}{state}"
    valid = await store._redis.get(state_key)  # noqa: SLF001
    if not valid:
        return RedirectResponse("/login?error=oauth_invalid_state", status_code=302)
    await store._redis.delete(state_key)  # noqa: SLF001

    base_url = _resolve_base_url(request, settings)
    redirect_uri = f"{base_url}/auth/{provider}/callback"

    try:
        tokens = await exchange_code(provider, code, client_id, client_secret, redirect_uri)
        userinfo = await get_userinfo(provider, tokens["access_token"])
    except Exception:
        return RedirectResponse("/login?error=oauth_failed", status_code=302)

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")

    try:
        async with async_session() as db:
            user = await upsert_oauth_user(
                db,
                provider,
                userinfo,
                settings,
                access_token=access_token,
                refresh_token=refresh_token,
            )
            # Detach attributes before session closes
            user_id = user.id
            user_is_admin = user.is_admin
            user_approval_status = user.approval_status
    except Exception:
        logger.exception("OAuth user upsert failed for provider=%s", provider)
        return RedirectResponse("/login?error=oauth_failed", status_code=302)

    if user_approval_status == "pending":
        return RedirectResponse("/login?error=approval_pending", status_code=302)
    if user_approval_status == "rejected":
        return RedirectResponse("/login?error=approval_rejected", status_code=302)

    # 세션 발급
    ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    try:
        session_id = await store.create_session(
            user_id,
            ip,
            user_agent,
            is_admin=user_is_admin,
            approval_status=user_approval_status,
        )
    except Exception:
        logger.exception("OAuth session creation failed for user=%s", user_id)
        return RedirectResponse("/login?error=oauth_failed", status_code=302)

    max_age = settings.session_expire_days * 86400

    base_url = _resolve_base_url(request, settings)
    is_https = base_url.startswith("https")

    response = RedirectResponse("/dashboard", status_code=302)
    response.set_cookie(
        "piloci_session",
        session_id,
        httponly=True,
        samesite="lax",
        secure=is_https,
        max_age=max_age,
        path="/",
    )
    return response


async def route_oauth_disconnect(request: Request) -> Response:
    settings = get_settings()

    from sqlalchemy import select

    from piloci.auth.crypto import decrypt_token
    from piloci.auth.oauth import PROVIDERS, get_provider_credentials, revoke_provider_token
    from piloci.db.models import User

    provider = (request.path_params.get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        return _json({"error": "Unknown OAuth provider"}, 400)

    session_id = request.cookies.get("piloci_session")
    if not session_id:
        return _json({"error": "Unauthorized"}, 401)

    store = get_session_store(settings)
    session = await store.get_session(session_id)
    if session is None:
        return _json({"error": "Unauthorized"}, 401)

    user_id = session.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        return _json({"error": "Unauthorized"}, 401)

    credentials = get_provider_credentials(settings, provider)
    if credentials is None:
        return _json({"error": f"{provider} OAuth is not configured"}, 503)
    client_id, client_secret = credentials

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return _json({"error": "Unauthorized"}, 401)
        if user.password_hash is None:
            return _json(
                {"error": "Cannot disconnect: no password set. Set a password first."},
                400,
            )
        if user.oauth_provider != provider:
            return _json({"error": "OAuth provider does not match connected account"}, 400)

        access_token: str | None = None
        if user.oauth_access_token:
            try:
                access_token = decrypt_token(user.oauth_access_token, settings)
            except InvalidToken:
                logger.warning(
                    "Failed to decrypt stored OAuth access token for user_id=%s provider=%s",
                    user.id,
                    provider,
                    exc_info=True,
                )

        if access_token:
            await revoke_provider_token(provider, access_token, client_id, client_secret)

        user.oauth_provider = None
        user.oauth_sub = None
        user.oauth_access_token = None
        user.oauth_refresh_token = None
        db.add(user)

    return _json({"status": "disconnected"})


async def route_naver_unlink_callback(request: Request) -> Response:
    """POST /auth/naver/unlink-callback — Naver-initiated account unlink."""
    settings = get_settings()

    from sqlalchemy import select

    from piloci.auth.oauth import get_provider_credentials, verify_naver_unlink_signature
    from piloci.db.models import User

    credentials = get_provider_credentials(settings, "naver")
    if credentials is None:
        return _json({"error": "naver OAuth is not configured"}, 503)
    client_id, client_secret = credentials

    form = await request.form()
    naver_client_id = str(form.get("client_id", ""))
    user_id = str(form.get("user_id", ""))
    timestamp = str(form.get("timestamp", ""))
    signature = str(form.get("signature", ""))
    svc_id = str(form.get("svc_id", ""))

    if not naver_client_id or not user_id or not timestamp or not signature:
        return _json({"error": "Missing required parameters"}, 400)

    if naver_client_id != client_id:
        return _json({"error": "Invalid client_id"}, 403)

    if not verify_naver_unlink_signature(
        client_id=naver_client_id,
        user_id=user_id,
        timestamp=timestamp,
        signature=signature,
        client_secret=client_secret,
        svc_id=svc_id,
    ):
        return _json({"error": "Invalid signature"}, 403)

    async with async_session() as db:
        result = await db.execute(
            select(User).where(
                User.oauth_provider == "naver",
                User.oauth_sub == user_id,
            )
        )
        user = result.scalar_one_or_none()
        if user is None:
            return _json({"result": "ok"})

        user.oauth_provider = None
        user.oauth_sub = None
        user.oauth_access_token = None
        user.oauth_refresh_token = None
        db.add(user)

    return _json({"result": "ok"})


async def route_kakao_unlink_callback(request: Request) -> Response:
    settings = get_settings()

    from sqlalchemy import select

    from piloci.auth.oauth import verify_kakao_unlink_auth
    from piloci.db.models import User

    admin_key = settings.kakao_admin_key
    if not admin_key:
        return _json({"error": "kakao OAuth is not configured"}, 503)

    authorization = request.headers.get("Authorization", "")
    if not verify_kakao_unlink_auth(authorization, admin_key):
        return _json({"error": "Invalid authorization"}, 403)

    if request.method == "GET":
        user_id = str(request.query_params.get("user_id", ""))
    else:
        form = await request.form()
        user_id = str(form.get("user_id", ""))

    if not user_id:
        return _json({"error": "Missing user_id"}, 400)

    async with async_session() as db:
        result = await db.execute(
            select(User).where(
                User.oauth_provider == "kakao",
                User.oauth_sub == user_id,
            )
        )
        user = result.scalar_one_or_none()
        if user is None:
            return _json({"result": "ok"})

        user.oauth_provider = None
        user.oauth_sub = None
        user.oauth_access_token = None
        user.oauth_refresh_token = None
        db.add(user)

    return _json({"result": "ok"})


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# /api/ingest — Stop-hook receiver for auto-capture
# ---------------------------------------------------------------------------


async def route_ingest(request: Request) -> Response:
    """Receive a raw session transcript from a client Stop hook.

    Body: {client, session_id?, transcript: [...], project_id?}
    Stores into raw_sessions and pushes job onto the curator queue.
    """
    settings = get_settings()
    user = request.state.user
    if user is None:
        return _json({"error": "unauthorized"}, 401)

    raw_body = await request.body()
    if len(raw_body) > settings.ingest_max_body_bytes:
        return _json({"error": "payload too large"}, 413)

    try:
        body = orjson.loads(raw_body)
    except Exception:
        return _json({"error": "invalid JSON"}, 400)

    client = (body.get("client") or "").strip() or "unknown"
    transcript = body.get("transcript")
    session_id = body.get("session_id")

    if not isinstance(transcript, list) or not transcript:
        return _json({"error": "transcript must be a non-empty list"}, 400)

    user_id = _uid(user)
    project_id = body.get("project_id") or user.get("project_id")
    if not user_id or not project_id:
        return _json({"error": "user_id and project_id required"}, 400)

    ingest_id = str(uuid.uuid4())
    from piloci.db.models import RawSession

    async with async_session() as db:
        db.add(
            RawSession(
                ingest_id=ingest_id,
                user_id=user_id,
                project_id=project_id,
                client=client[:50],
                session_id=(session_id or "")[:200] or None,
                transcript_json=orjson.dumps(transcript).decode(),
                created_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    queue = get_ingest_queue(settings.ingest_queue_maxsize)
    job = IngestJob(ingest_id=ingest_id, user_id=user_id, project_id=project_id)
    if not try_enqueue_job(job, maxsize=settings.ingest_queue_maxsize):
        async with async_session() as db:
            await db.execute(delete(RawSession).where(RawSession.ingest_id == ingest_id))
            await db.commit()
        response = _json(
            {
                "error": "ingest queue is full",
                "queued": False,
                "queue_depth": queue.qsize(),
                "queue_capacity": queue.maxsize,
                "retry_after_sec": settings.ingest_retry_after_sec,
            },
            429,
        )
        response.headers["Retry-After"] = str(settings.ingest_retry_after_sec)
        return response

    return _json(
        {
            "queued": True,
            "ingest_id": ingest_id,
            "queue_depth": queue.qsize(),
            "queue_capacity": queue.maxsize,
        },
        202,
    )


# ---------------------------------------------------------------------------
# /api/hook/script — download the generic SessionStart hook script
# ---------------------------------------------------------------------------


async def route_hook_script(request: Request) -> Response:
    """GET /api/hook/script — return the generic hook.py to save locally.

    The script reads ~/.config/piloci/config.json at runtime for token/URL.
    Install once; update config.json when the token rotates.

    Usage:
        curl "<base>/api/hook/script" -H "Authorization: Bearer <token>" \\
             -o ~/.config/piloci/hook.py
    """
    user = _require_user(request)
    if user is None:
        return Response("unauthorized", status_code=401)

    from piloci.tools.memory_tools import HOOK_SCRIPT

    return Response(
        HOOK_SCRIPT,
        media_type="text/x-python",
        headers={"Content-Disposition": 'attachment; filename="hook.py"'},
    )


async def route_hook_stop_script(request: Request) -> Response:
    """GET /api/hook/stop-script — return the generic stop-hook.sh to save locally.

    The script reads ~/.config/piloci/config.json at runtime for token + analyze_url.
    Companion to hook.py: SessionStart catches up, Stop pushes live per turn.
    """
    user = _require_user(request)
    if user is None:
        return Response("unauthorized", status_code=401)

    from piloci.tools.install_script import STOP_HOOK_SCRIPT

    return Response(
        STOP_HOOK_SCRIPT,
        media_type="text/x-shellscript",
        headers={"Content-Disposition": 'attachment; filename="stop-hook.sh"'},
    )


async def route_opencode_plugin(request: Request) -> Response:
    """GET /api/hook/opencode-plugin — OpenCode plugin TypeScript source.

    Plugin file is identical for every user; token comes from runtime via
    ``~/.config/piloci/config.json`` so revocation only requires updating
    that file (via ``piloci login``), not reinstalling the plugin.
    """
    user = _require_user(request)
    if user is None:
        return Response("unauthorized", status_code=401)

    from piloci.tools.opencode_plugin import OPENCODE_PLUGIN

    return Response(
        OPENCODE_PLUGIN,
        media_type="text/typescript",
        headers={"Content-Disposition": 'attachment; filename="piloci.ts"'},
    )


# ---------------------------------------------------------------------------
# /install/{code} — one-time install code → bash installer
# ---------------------------------------------------------------------------


async def route_install(request: Request) -> Response:
    """GET /install/{code} — exchange a one-time install code for a bash installer.

    The code is consumed atomically; subsequent requests with the same code
    return 410 Gone. No auth required — the code IS the credential.

    Response format is content-negotiated:
      * ``Accept: application/json`` (or ``?format=json``) → ``{token, base_url}``
        for the Python CLI installer.
      * default → bash one-liner that ``curl ... | bash`` consumes.
    """
    code = (request.path_params.get("code") or "").strip()
    accept = request.headers.get("accept", "").lower()
    fmt = request.query_params.get("format", "").lower()
    wants_json = "application/json" in accept or fmt == "json"

    if not code or len(code) > 64 or any(c.isspace() for c in code):
        if wants_json:
            return _json({"error": "invalid install code"}, 400)
        return Response(
            "#!/usr/bin/env bash\necho '[piloci] invalid install code' >&2\nexit 1\n",
            status_code=400,
            media_type="text/x-shellscript",
        )

    from piloci.auth.install_pairing import get_install_pairing_store
    from piloci.tools.install_script import build_install_script

    settings = get_settings()
    store = get_install_pairing_store(settings)
    payload = await store.consume(code)
    if payload is None:
        if wants_json:
            return _json(
                {"error": "이 install code는 만료되었거나 이미 사용됐습니다."},
                410,
            )
        gone = (
            "#!/usr/bin/env bash\n"
            "echo '[piloci] 이 install code는 만료되었거나 이미 사용됐습니다.' >&2\n"
            "echo '         웹에서 새 토큰을 발급해 주세요.' >&2\n"
            "exit 1\n"
        )
        return Response(gone, status_code=410, media_type="text/x-shellscript")

    if wants_json:
        return _json(
            {"token": payload["token"], "base_url": payload["base_url"]},
            200,
        )

    script = build_install_script(token=payload["token"], base_url=payload["base_url"])
    return Response(
        script,
        media_type="text/x-shellscript",
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# Device flow — /auth/device/code, /auth/device/poll, /api/device/approve
# ---------------------------------------------------------------------------


async def route_device_code(request: Request) -> Response:
    """POST /auth/device/code — start a device flow pairing. No auth required."""
    from piloci.auth.device_pairing import DEVICE_TTL_SEC, get_device_pairing_store

    settings = get_settings()
    store = get_device_pairing_store(settings)
    try:
        device_code, user_code = await store.create()
    except Exception:
        logger.exception("device flow create failed")
        return _json({"error": "could not allocate device code"}, 500)

    base_url = _resolve_base_url(request, settings).rstrip("/")
    return _json(
        {
            "device_code": device_code,
            "user_code": user_code,
            "verification_uri": f"{base_url}/device",
            "verification_uri_complete": f"{base_url}/device?code={user_code}",
            "expires_in": DEVICE_TTL_SEC,
            "interval": 3,
        },
        200,
    )


async def route_device_poll(request: Request) -> Response:
    """POST /auth/device/poll — CLI polls here with ``device_code``.

    Returns one of:
      ``{status: "pending"}`` — keep polling
      ``{status: "approved", token}`` — done; record is deleted server-side
      ``{status: "denied"}`` — user clicked deny
      ``{error: "expired"}`` (HTTP 410) — TTL elapsed or unknown code
    """
    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)

    device_code = (body.get("device_code") or "").strip()
    if not device_code:
        return _json({"error": "device_code required"}, 400)

    from piloci.auth.device_pairing import get_device_pairing_store

    settings = get_settings()
    store = get_device_pairing_store(settings)
    record = await store.poll(device_code)
    if record is None:
        return _json({"status": "expired"}, 410)

    status = record.get("status", "pending")
    if status == "approved":
        payload = {"status": "approved", "token": record.get("token", "")}
        targets = record.get("targets")
        if isinstance(targets, list):
            payload["targets"] = [str(t) for t in targets]
        return _json(payload)
    if status == "denied":
        return _json({"status": "denied"})
    return _json({"status": "pending"})


async def route_device_approve(request: Request) -> Response:
    """POST /api/device/approve — authenticated user approves/denies a code.

    Body: ``{user_code, action: "approve" | "deny"}``. On approve the server
    mints a fresh user-scoped JWT for the calling user and stores it on the
    device record so the CLI's next poll can pick it up.
    """
    user = _require_user(request)
    if user is None:
        return _json({"error": "Unauthorized"}, 401)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)

    user_code = (body.get("user_code") or "").strip().upper()
    action = (body.get("action") or "approve").strip().lower()
    if not user_code or action not in ("approve", "deny"):
        return _json({"error": "user_code and action(approve|deny) required"}, 422)

    # Optional install-target list — the /device form passes the kinds the
    # user ticked on the approval card. Filter to known kinds so a stale or
    # malicious client cannot smuggle arbitrary strings through to the CLI.
    raw_targets = body.get("targets")
    selected_targets: list[str] | None = None
    if isinstance(raw_targets, list):
        from piloci.installer import CLIENT_LABELS as _LABELS

        selected_targets = [str(t) for t in raw_targets if str(t) in _LABELS]
        if not selected_targets:
            return _json({"error": "targets must include at least one known client"}, 422)

    settings = get_settings()
    from piloci.auth.device_pairing import get_device_pairing_store

    store = get_device_pairing_store(settings)
    record = await store.lookup_user_code(user_code)
    if record is None:
        return _json({"error": "code not found or expired"}, 404)
    if record.get("status") != "pending":
        return _json({"error": "code already used"}, 409)

    device_code = record["device_code"]

    if action == "deny":
        await store.deny(device_code)
        return _json({"ok": True, "status": "denied"})

    # Approve: mint a fresh user-scoped token (1 year, like /api/tokens default)
    # and persist its hash in api_tokens so admin can revoke it later.
    user_id_val = _uid(user)
    user_email = user.get("email") or ""
    if not user_email:
        from sqlalchemy import select as _sel

        from piloci.db.models import User as _User

        async with async_session() as _db:
            _r = await _db.execute(_sel(_User).where(_User.id == user_id_val))
            _u = _r.scalar_one_or_none()
            user_email = _u.email if _u else ""

    token_id = str(uuid.uuid4())
    expire_days = 365
    jwt_token = create_token(
        user_id=user_id_val,
        email=user_email,
        project_id=None,
        project_slug=None,
        scope="user",
        settings=settings,
        token_id=token_id,
        expire_days=expire_days,
    )

    import hashlib

    from piloci.db.models import ApiToken

    token_hash = hashlib.sha256(jwt_token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=expire_days)

    async with async_session() as db:
        db.add(
            ApiToken(
                token_id=token_id,
                user_id=user_id_val,
                project_id=None,
                name=f"device:{user_code}",
                token_hash=token_hash,
                scope="user",
                created_at=now,
                expires_at=expires_at,
            )
        )

    ok = await store.approve(device_code, token=jwt_token, targets=selected_targets)
    if not ok:
        return _json({"error": "could not approve (race?)"}, 409)
    return _json({"ok": True, "status": "approved"})


# ---------------------------------------------------------------------------
# /api/sessions/ingest — SessionStart hook batch catch-up
# ---------------------------------------------------------------------------


async def route_sessions_ingest(request: Request) -> Response:
    """POST /api/sessions/ingest — SessionStart hook batch transcript catch-up.

    Body: {cwd: str, sessions: [{session_id: str, transcript: str}]}
    Deduplicates by (user_id, project_id, session_id). Queues new sessions.
    Accepts project-scoped tokens (project_id in JWT) or resolves project from
    cwd slug for user-scoped tokens.
    """
    user = _require_user(request)
    if user is None:
        return _json({"error": "unauthorized"}, 401)

    user_id = _uid(user)
    if not isinstance(user_id, str) or not user_id:
        return _json({"error": "user_id required"}, 400)

    settings = get_settings()
    raw_body = await request.body()
    if len(raw_body) > settings.ingest_max_body_bytes * 20:
        return _json({"error": "payload too large"}, 413)

    try:
        body = orjson.loads(raw_body)
    except Exception:
        return _json({"error": "invalid JSON"}, 400)

    project_id: str | None = user.get("project_id")

    # User-scoped token: resolve project from cwd, auto-creating a project on
    # first sight so the user never has to run init manually. Match by exact
    # cwd → cwd-less legacy slug → auto-create with disambiguated slug.
    if not project_id:
        cwd = (body.get("cwd") or "").strip()
        if not cwd:
            return _json({"error": "project-scoped token or cwd required"}, 400)
        project_id = await _resolve_or_create_project(user_id, cwd)
        if project_id is None:
            return _json(
                {
                    "error": f"refused to auto-create project for '{cwd}' — looks like a home or root dir"
                },
                422,
            )

    sessions = body.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        return _json({"error": "sessions must be a non-empty list"}, 400)

    from sqlalchemy import select as _sel

    from piloci.db.models import RawSession

    queued = 0
    skipped = 0

    for item in sessions[:50]:  # cap batch size
        session_id = (item.get("session_id") or "").strip()
        transcript_str = item.get("transcript") or ""
        if not session_id or not transcript_str:
            skipped += 1
            continue

        async with async_session() as db:
            existing = (
                await db.execute(
                    _sel(RawSession.ingest_id)
                    .where(
                        RawSession.user_id == user_id,
                        RawSession.project_id == project_id,
                        RawSession.session_id == session_id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()

        if existing is not None:
            skipped += 1
            continue

        try:
            messages = [orjson.loads(line) for line in transcript_str.splitlines() if line.strip()]
        except Exception:
            skipped += 1
            continue

        if len(messages) < 5:
            skipped += 1
            continue

        ingest_id = str(uuid.uuid4())
        async with async_session() as db:
            db.add(
                RawSession(
                    ingest_id=ingest_id,
                    user_id=user_id,
                    project_id=project_id,
                    client="session-start-hook",
                    session_id=session_id[:200],
                    transcript_json=orjson.dumps(messages).decode(),
                    created_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        job = IngestJob(ingest_id=ingest_id, user_id=user_id, project_id=project_id)
        if try_enqueue_job(job, maxsize=settings.ingest_queue_maxsize):
            queued += 1
        else:
            async with async_session() as db:
                await db.execute(delete(RawSession).where(RawSession.ingest_id == ingest_id))
                await db.commit()
            skipped += 1

    return _json({"queued": queued, "skipped": skipped})


# ---------------------------------------------------------------------------
# Memory management (REST — MCP-excluded admin surface)
# ---------------------------------------------------------------------------


async def route_create_memory(request: Request) -> Response:
    user = request.state.user
    if user is None:
        return _json({"error": "unauthorized"}, 401)
    user_id_value = _uid(user)
    project_id_value = user.get("project_id")
    if not isinstance(user_id_value, str) or not user_id_value:
        return _json({"error": "user_id required"}, 400)
    if not isinstance(project_id_value, str) or not project_id_value:
        return _json({"error": "project scope required"}, 400)
    user_id = user_id_value
    project_id = project_id_value
    try:
        body_obj = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)
    if not isinstance(body_obj, dict):
        return _json({"error": "invalid JSON"}, 400)
    body = cast(dict[str, object], body_obj)

    raw_content = body.get("content")
    if not isinstance(raw_content, str) or not raw_content.strip():
        return _json({"error": "content required"}, 400)
    content = raw_content.strip()

    raw_tags = body.get("tags")
    tags = [tag for tag in raw_tags if isinstance(tag, str)] if isinstance(raw_tags, list) else None
    raw_metadata = body.get("metadata")
    metadata = cast(dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else None

    from piloci.storage import embed

    settings = get_settings()
    vector = await embed.embed_one(
        text=content,
        model=settings.embed_model,
        cache_dir=settings.embed_cache_dir,
        lru_size=settings.embed_lru_size,
        executor_workers=settings.embed_executor_workers,
        max_concurrency=settings.embed_max_concurrency,
    )
    store = request.app.state.store
    memory_id = await store.save(
        user_id=user_id,
        project_id=project_id,
        content=content,
        vector=vector,
        tags=tags,
        metadata=metadata,
    )
    await invalidate_project_vault_cache(settings.vault_dir, user_id, project_id)
    return _json({"success": True, "memory_id": memory_id, "project_id": project_id}, 201)


async def route_get_memory(request: Request) -> Response:
    user = request.state.user
    if user is None:
        return _json({"error": "unauthorized"}, 401)
    user_id = _uid(user)
    project_id = user.get("project_id") or request.query_params.get("project_id")
    if not project_id:
        return _json({"error": "project_id required"}, 400)
    memory_id = request.path_params["id"]
    store = request.app.state.store
    result = await store.get(user_id=user_id, project_id=project_id, memory_id=memory_id)
    if result is None:
        return _json({"error": "not found"}, 404)
    return _json(result)


async def route_update_memory(request: Request) -> Response:
    user = request.state.user
    if user is None:
        return _json({"error": "unauthorized"}, 401)
    user_id = _uid(user)
    project_id = user.get("project_id")
    if not project_id:
        return _json({"error": "project scope required"}, 400)
    memory_id = request.path_params["id"]
    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)

    store = request.app.state.store
    new_vector = None
    content = body.get("content")
    if content is not None:
        from piloci.storage.embed import embed_one

        settings = get_settings()
        new_vector = await embed_one(
            content,
            model=settings.embed_model,
            cache_dir=settings.embed_cache_dir,
            lru_size=settings.embed_lru_size,
            executor_workers=settings.embed_executor_workers,
            max_concurrency=settings.embed_max_concurrency,
        )
    updated = await store.update(
        user_id=user_id,
        project_id=project_id,
        memory_id=memory_id,
        content=content,
        new_vector=new_vector,
        tags=body.get("tags"),
        metadata=body.get("metadata"),
    )
    if updated:
        await invalidate_project_vault_cache(get_settings().vault_dir, user_id, project_id)
    return _json({"updated": updated})


async def route_delete_memory(request: Request) -> Response:
    user = request.state.user
    if user is None:
        return _json({"error": "unauthorized"}, 401)
    user_id = _uid(user)
    project_id = user.get("project_id")
    if not project_id:
        return _json({"error": "project scope required"}, 400)
    memory_id = request.path_params["id"]
    store = request.app.state.store
    deleted = await store.delete(user_id=user_id, project_id=project_id, memory_id=memory_id)
    if not deleted:
        return _json({"error": "not found"}, 404)

    from sqlalchemy import update as _upd

    from piloci.db.models import Project

    async with async_session() as db:
        await db.execute(
            _upd(Project)
            .where(Project.id == project_id, Project.memory_count > 0)
            .values(memory_count=Project.memory_count - 1)
        )

    await invalidate_project_vault_cache(get_settings().vault_dir, user_id, project_id)
    return _json({"deleted": True})


async def route_clear_memories(request: Request) -> Response:
    user = request.state.user
    if user is None:
        return _json({"error": "unauthorized"}, 401)
    user_id = _uid(user)
    project_id = user.get("project_id")
    if not project_id:
        return _json({"error": "project scope required"}, 400)
    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)
    if body.get("confirm") is not True:
        return _json({"error": "confirm: true required"}, 400)
    store = request.app.state.store
    count = await store.clear_project(user_id=user_id, project_id=project_id)
    if count > 0:
        from sqlalchemy import update as _upd

        from piloci.db.models import Project

        async with async_session() as db:
            await db.execute(_upd(Project).where(Project.id == project_id).values(memory_count=0))
        await invalidate_project_vault_cache(get_settings().vault_dir, user_id, project_id)
    return _json({"cleared": True, "count": count})


async def route_chat(request: Request) -> Response:
    """POST /api/chat — RAG over project memories.

    Body: {"query": str, "top_k"?: int, "tags"?: [str], "stream"?: bool}
    Stream mode (default true) returns text/event-stream with three events:
      - ``citations`` : JSON array of memory snippets
      - ``token``     : streamed text chunks
      - ``done``      : end-of-response sentinel
    Non-stream mode returns ``{answer, citations}`` JSON.
    """
    from starlette.responses import StreamingResponse

    from piloci import chat as chat_mod
    from piloci.llm import get_chat_provider
    from piloci.storage.embed import embed_one

    user = _require_user(request)
    if user is None:
        return _json({"error": "unauthorized"}, 401)
    user_id = _uid(user)
    if not isinstance(user_id, str) or not user_id:
        return _json({"error": "user_id required"}, 400)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"error": "invalid JSON"}, 400)

    # Project resolution: prefer explicit project_slug from body (web flow),
    # fall back to project-scoped token's bound project_id (MCP flow).
    project_slug = body.get("project_slug")
    project_id_raw = user.get("project_id")
    project_id: str | None = None
    if isinstance(project_slug, str) and project_slug.strip():
        proj = await _get_user_project_by_slug(user_id, project_slug.strip())
        if proj is None:
            return _json({"error": "project not found"}, 404)
        project_id = proj["id"]
    elif isinstance(project_id_raw, str) and project_id_raw:
        project_id = project_id_raw
    if not project_id:
        return _json({"error": "project scope required"}, 400)

    raw_query = body.get("query")
    if not isinstance(raw_query, str) or not raw_query.strip():
        return _json({"error": "query required"}, 400)
    query = raw_query.strip()
    top_k = body.get("top_k") if isinstance(body.get("top_k"), int) else chat_mod.DEFAULT_TOP_K
    raw_tags = body.get("tags")
    tags = [t for t in raw_tags if isinstance(t, str)] if isinstance(raw_tags, list) else None
    stream_mode = body.get("stream", True) is not False

    settings = get_settings()
    store = request.app.state.store

    try:
        provider = get_chat_provider(settings)
    except ValueError as e:
        return _json({"error": f"chat provider misconfigured: {e}"}, 503)

    async def _embed(text: str) -> list[float]:
        return await embed_one(
            text=text,
            model=settings.embed_model,
            cache_dir=settings.embed_cache_dir,
            lru_size=settings.embed_lru_size,
            executor_workers=settings.embed_executor_workers,
            max_concurrency=settings.embed_max_concurrency,
        )

    try:
        memories = await chat_mod.retrieve(
            query=query,
            user_id=user_id,
            project_id=project_id,
            store=store,
            embed_fn=_embed,
            top_k=top_k,
            tags=tags,
        )
    except Exception:
        logger.exception("chat retrieval failed")
        return _json({"error": "retrieval failed"}, 500)

    citations = chat_mod.format_citations(memories)

    per_mem_limit = getattr(settings, "chat_max_memory_chars", chat_mod.DEFAULT_MAX_MEMORY_CHARS)
    total_limit = getattr(settings, "chat_max_context_chars", chat_mod.DEFAULT_MAX_CONTEXT_CHARS)

    if not stream_mode:
        chunks: list[str] = []
        try:
            async for chunk in chat_mod.stream_answer(
                query=query,
                memories=memories,
                provider=provider,
                per_memory_limit=per_mem_limit,
                total_context_limit=total_limit,
            ):
                chunks.append(chunk)
        except Exception:
            logger.exception("chat generation failed")
            return _json({"error": "generation failed"}, 502)
        return _json({"answer": "".join(chunks), "citations": citations})

    async def _sse() -> Any:
        # Emit citations first so the client can render before the first token.
        yield f"event: citations\ndata: {orjson.dumps(citations).decode()}\n\n"
        try:
            async for chunk in chat_mod.stream_answer(
                query=query,
                memories=memories,
                provider=provider,
                per_memory_limit=per_mem_limit,
                total_context_limit=total_limit,
            ):
                yield f"event: token\ndata: {orjson.dumps({'text': chunk}).decode()}\n\n"
        except Exception as e:
            logger.exception("chat stream failed")
            yield f"event: error\ndata: {orjson.dumps({'error': str(e)[:200]}).decode()}\n\n"
            return
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def route_analyze_session(request: Request) -> Response:
    """POST /api/sessions/analyze — extract instincts from a Claude Code session transcript.

    Body: {"transcript": "...", "project_id": "optional override"}
    Called by the piloci-stop-hook.sh script at end of each session.
    """
    user = _require_user(request)
    if user is None:
        return _json({"error": "unauthorized"}, 401)
    user_id = _uid(user)
    project_id = user.get("project_id")
    if not isinstance(user_id, str) or not user_id:
        return _json({"error": "user_id required"}, 400)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)

    transcript = body.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        return _json({"error": "transcript required"}, 400)

    # User-scoped token: same auto-create flow as ingest.
    if not isinstance(project_id, str) or not project_id:
        cwd = (body.get("cwd") or "").strip()
        if not cwd:
            return _json(
                {"error": "project scope required — use a project-scoped token or include cwd"},
                400,
            )
        project_id = await _resolve_or_create_project(user_id, cwd)
        if project_id is None:
            return _json(
                {
                    "error": f"refused to auto-create project for '{cwd}' — looks like a home or root dir"
                },
                422,
            )

    settings = get_settings()

    # Persist the transcript first, then enqueue. This way restarts and crashes
    # don't lose work — the worker's startup recovery re-queues unprocessed
    # rows. Returning 202 immediately escapes Cloudflare's 100s origin timeout
    # for the synchronous Gemma extraction path.
    from piloci.curator.analyze_queue import AnalyzeJob, try_enqueue_analyze
    from piloci.db.models import RawAnalysis

    analyze_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        db.add(
            RawAnalysis(
                analyze_id=analyze_id,
                user_id=user_id,
                project_id=project_id,
                transcript=transcript,
                created_at=now,
            )
        )
        await db.flush()

    job = AnalyzeJob(analyze_id=analyze_id, user_id=user_id, project_id=project_id)
    if not try_enqueue_analyze(job, maxsize=settings.analyze_queue_maxsize):
        # Queue saturated — row stays unprocessed in DB and the next startup or
        # the maintenance sweep will requeue. Tell the client to back off.
        return _json(
            {
                "error": "analyze queue full — try again shortly",
                "analyze_id": analyze_id,
                "retry_after_sec": settings.analyze_retry_after_sec,
            },
            503,
        )

    return _json({"queued": True, "analyze_id": analyze_id}, 202)


async def route_healthz(request: Request) -> Response:
    return _json({"status": "ok"})


async def route_readyz(request: Request) -> Response:
    settings = get_settings()
    checks: dict[str, Any] = {}
    causes: list[str] = []

    # Check LanceDB
    try:
        store = request.app.state.store
        await store._get_table()
        checks["lancedb"] = {"status": "ok"}
    except Exception:
        logger.exception("readyz: lancedb check failed")
        checks["lancedb"] = {"status": "error", "detail": "unavailable"}
        causes.append("lancedb_unavailable")

    # Check DB
    try:
        async with async_session() as db:
            from sqlalchemy import text

            await db.execute(text("SELECT 1"))
        checks["db"] = {"status": "ok"}
    except Exception:
        logger.exception("readyz: database check failed")
        checks["db"] = {"status": "error", "detail": "unavailable"}
        causes.append("database_unavailable")

    # Check Redis session store
    try:
        session_store = get_session_store(settings)
        await session_store.ping()
        checks["redis"] = {"status": "ok"}
    except Exception:
        logger.exception("readyz: redis check failed")
        checks["redis"] = {"status": "error", "detail": "unavailable"}
        causes.append("redis_unavailable")

    queue = get_ingest_queue(settings.ingest_queue_maxsize)
    queue_depth = queue.qsize()
    queue_capacity = queue.maxsize
    pressure = _queue_pressure(queue_depth, queue_capacity)
    checks["ingest_queue"] = {
        "status": "ok" if pressure != "full" else "error",
        "depth": queue_depth,
        "capacity": queue_capacity,
        "pressure": pressure,
    }
    if pressure == "full":
        causes.append("ingest_queue_full")

    ok = not causes
    return _json(
        {
            "status": "ok" if ok else "degraded",
            "checks": checks,
            "causes": causes,
        },
        200 if ok else 503,
    )


async def route_profilez(request: Request) -> Response:
    return _json(
        {
            "status": "ok",
            "profiling": get_runtime_profiler().snapshot(),
        }
    )


# ---------------------------------------------------------------------------
# Admin API routes
# ---------------------------------------------------------------------------


async def route_admin_list_users(request: Request) -> Response:
    admin = _require_admin(request)
    if admin is None:
        return _json({"error": "Forbidden"}, 403)

    from sqlalchemy import select

    from piloci.db.models import User

    status = request.query_params.get("status")
    async with async_session() as db:
        stmt = select(User).order_by(User.created_at.desc())
        if status and status != "all":
            stmt = stmt.where(User.approval_status == status)
        result = await db.execute(stmt)
        users = result.scalars().all()

    rows = [
        {
            "id": str(u.id),
            "email": u.email,
            "name": u.name,
            "is_admin": u.is_admin,
            "is_active": u.is_active,
            "approval_status": u.approval_status,
            "reviewed_by": u.reviewed_by,
            "reviewed_at": u.reviewed_at.isoformat() if u.reviewed_at else None,
            "rejection_reason": u.rejection_reason,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "oauth_provider": u.oauth_provider,
            "totp_enabled": u.totp_enabled,
        }
        for u in users
    ]
    return _json(rows)


async def route_admin_approve_user(request: Request) -> Response:
    admin = _require_admin(request)
    if admin is None:
        return _json({"error": "Forbidden"}, 403)

    from sqlalchemy import select

    from piloci.db.models import User

    user_id = request.path_params["id"]
    admin_id = admin.get("user_id") or admin.get("sub")
    async with async_session() as db:
        admin_result = await db.execute(select(User).where(User.id == admin_id))
        admin_user = admin_result.scalar_one_or_none()
        admin_email = admin_user.email if admin_user else "unknown"

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return _json({"error": "User not found"}, 404)
        user.approval_status = "approved"
        user.reviewed_by = admin_email
        user.reviewed_at = datetime.now(timezone.utc)
        user.rejection_reason = None
        await db.commit()
    return _json({"ok": True})


async def route_admin_reject_user(request: Request) -> Response:
    admin = _require_admin(request)
    if admin is None:
        return _json({"error": "Forbidden"}, 403)

    from sqlalchemy import select

    from piloci.db.models import User

    user_id = request.path_params["id"]
    body = orjson.loads(await request.body()) if await request.body() else {}
    reason = body.get("reason")

    admin_id = admin.get("user_id") or admin.get("sub")
    async with async_session() as db:
        admin_result = await db.execute(select(User).where(User.id == admin_id))
        admin_user = admin_result.scalar_one_or_none()
        admin_email = admin_user.email if admin_user else "unknown"

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return _json({"error": "User not found"}, 404)
        user.approval_status = "rejected"
        user.reviewed_by = admin_email
        user.reviewed_at = datetime.now(timezone.utc)
        user.rejection_reason = reason or None
        await db.commit()
    return _json({"ok": True})


async def _admin_audit(db: AsyncSession, admin_id: str, target_id: str, action: str) -> None:
    from piloci.db.models import AuditLog

    audit = AuditLog(
        user_id=admin_id,
        action=f"admin_{action}",
        meta_data=orjson.dumps({"target_user_id": target_id}).decode(),
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)


async def _invalidate_sessions(user_id: str) -> None:
    try:
        settings = get_settings()
        store = get_session_store(settings)
        await store.delete_all_user_sessions(user_id)
    except Exception:
        pass


async def route_admin_toggle_admin(request: Request) -> Response:
    admin = _require_admin(request)
    if admin is None:
        return _json({"error": "Forbidden"}, 403)

    from sqlalchemy import select

    from piloci.db.models import User

    user_id = request.path_params["id"]
    admin_id = admin.get("user_id") or admin.get("sub")

    if str(admin_id) == str(user_id):
        return _json({"error": "Cannot change own admin status"}, 400)

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return _json({"error": "User not found"}, 404)
        user.is_admin = not user.is_admin
        await _admin_audit(db, admin_id, user_id, "toggle_admin")
        await db.commit()
    await _invalidate_sessions(user_id)
    return _json({"ok": True})


async def route_admin_toggle_active(request: Request) -> Response:
    admin = _require_admin(request)
    if admin is None:
        return _json({"error": "Forbidden"}, 403)

    from sqlalchemy import select

    from piloci.db.models import User

    user_id = request.path_params["id"]
    admin_id = admin.get("user_id") or admin.get("sub")

    if str(admin_id) == str(user_id):
        return _json({"error": "Cannot deactivate yourself"}, 400)

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return _json({"error": "User not found"}, 404)
        user.is_active = not user.is_active
        user.locked_until = None
        user.failed_login_count = 0
        await _admin_audit(db, admin_id, user_id, "toggle_active")
        await db.commit()
    await _invalidate_sessions(user_id)
    return _json({"ok": True})


async def route_admin_delete_user(request: Request) -> Response:
    admin = _require_admin(request)
    if admin is None:
        return _json({"error": "Forbidden"}, 403)

    from sqlalchemy import select

    from piloci.db.models import User

    user_id = request.path_params["id"]
    admin_id = admin.get("user_id") or admin.get("sub")

    if str(admin_id) == str(user_id):
        return _json({"error": "Cannot delete yourself"}, 400)

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return _json({"error": "User not found"}, 404)
        await _admin_audit(db, admin_id, user_id, "delete_user")
        await db.delete(user)
        await db.commit()
    await _invalidate_sessions(user_id)
    return _json({"ok": True})


# ---------------------------------------------------------------------------
# Route list
# ---------------------------------------------------------------------------


def get_routes() -> list[Route]:
    signup_limited = limiter.limit(RATE_SIGNUP)(route_signup)
    login_limited = limiter.limit(RATE_LOGIN)(route_login)
    forgot_password_limited = limiter.limit(RATE_PASSWORD_RESET)(route_forgot_password)
    reset_password_limited = limiter.limit(RATE_PASSWORD_RESET)(route_reset_password)
    data_export_limited = limiter.limit(RATE_DATA_IO)(route_data_export)
    data_import_limited = limiter.limit(RATE_DATA_IO)(route_data_import)

    return [
        Route("/healthz", route_healthz),
        Route("/readyz", route_readyz),
        Route("/profilez", route_profilez),
        Route("/auth/signup", signup_limited, methods=["POST"]),
        Route("/auth/login", login_limited, methods=["POST"]),
        Route("/auth/logout", route_logout, methods=["POST"]),
        Route("/api/auth/providers", route_auth_providers, methods=["GET"]),
        Route("/auth/forgot-password", forgot_password_limited, methods=["POST"]),
        Route("/auth/reset-password", reset_password_limited, methods=["POST"]),
        Route("/api/dashboard/summary", route_dashboard_summary, methods=["GET"]),
        Route("/api/projects", route_list_projects, methods=["GET"]),
        Route("/api/projects", route_create_project, methods=["POST"]),
        Route(
            "/api/projects/slug/{slug}/workspace/preview",
            route_project_workspace_preview,
            methods=["GET"],
        ),
        Route("/api/projects/slug/{slug}/workspace", route_project_workspace, methods=["GET"]),
        Route("/api/projects/slug/{slug}/knacks", route_project_knacks, methods=["GET"]),
        Route("/api/projects/slug/{slug}/sessions", route_project_sessions, methods=["GET"]),
        Route("/api/raw-sessions/{ingest_id}", route_raw_session_detail, methods=["GET"]),
        Route("/api/vault/{slug}/export", route_vault_export, methods=["GET"]),
        Route("/api/data/export", data_export_limited, methods=["GET"]),
        Route("/api/data/import", data_import_limited, methods=["POST"]),
        Route("/api/projects/{id}", route_update_project, methods=["PATCH"]),
        Route("/api/projects/{id}", route_delete_project, methods=["DELETE"]),
        Route("/api/tokens", route_list_tokens, methods=["GET"]),
        Route("/api/tokens", route_create_token, methods=["POST"]),
        Route("/api/tokens/{id}", route_revoke_token, methods=["DELETE"]),
        Route("/api/install/heartbeat", route_install_heartbeat, methods=["POST"]),
        Route("/api/llm-providers", route_list_llm_providers, methods=["GET"]),
        Route("/api/llm-providers", route_create_llm_provider, methods=["POST"]),
        Route("/api/llm-providers/{id}", route_update_llm_provider, methods=["PATCH"]),
        Route("/api/llm-providers/{id}", route_delete_llm_provider, methods=["DELETE"]),
        Route("/api/audit", route_list_audit, methods=["GET"]),
        Route("/api/account/2fa/enable", route_2fa_enable, methods=["POST"]),
        Route("/api/account/2fa/confirm", route_2fa_confirm, methods=["POST"]),
        Route("/api/account/2fa/disable", route_2fa_disable, methods=["POST"]),
        Route("/api/me", route_me, methods=["GET"]),
        Route("/api/account/password", route_change_password, methods=["POST"]),
        Route("/auth/{provider}/login", route_oauth_login, methods=["GET"]),
        Route("/auth/{provider}/callback", route_oauth_callback, methods=["GET"]),
        Route("/auth/{provider}/disconnect", route_oauth_disconnect, methods=["POST"]),
        Route(
            "/auth/naver/unlink-callback",
            route_naver_unlink_callback,
            methods=["POST", "GET"],
        ),
        Route(
            "/auth/kakao/unlink-callback",
            route_kakao_unlink_callback,
            methods=["POST", "GET"],
        ),
        # v0.3: auto-capture + memory admin
        Route("/api/ingest", route_ingest, methods=["POST"]),
        Route("/api/memories", route_create_memory, methods=["POST"]),
        Route("/api/memories/{id}", route_get_memory, methods=["GET"]),
        Route("/api/memories/{id}", route_update_memory, methods=["PATCH"]),
        Route("/api/memories/{id}", route_delete_memory, methods=["DELETE"]),
        Route("/api/memories/clear", route_clear_memories, methods=["POST"]),
        Route("/api/sessions/analyze", route_analyze_session, methods=["POST"]),
        Route("/api/sessions/ingest", route_sessions_ingest, methods=["POST"]),
        Route("/api/hook/script", route_hook_script, methods=["GET"]),
        Route("/api/hook/stop-script", route_hook_stop_script, methods=["GET"]),
        Route("/api/hook/opencode-plugin", route_opencode_plugin, methods=["GET"]),
        Route("/install/{code}", route_install, methods=["GET"]),
        Route("/auth/device/code", route_device_code, methods=["POST"]),
        Route("/auth/device/poll", route_device_poll, methods=["POST"]),
        Route("/api/device/approve", route_device_approve, methods=["POST"]),
        Route("/api/chat", route_chat, methods=["POST"]),
        Route("/api/admin/users", route_admin_list_users, methods=["GET"]),
        Route("/api/admin/users/{id}/approve", route_admin_approve_user, methods=["POST"]),
        Route("/api/admin/users/{id}/reject", route_admin_reject_user, methods=["POST"]),
        Route("/api/admin/users/{id}/toggle-admin", route_admin_toggle_admin, methods=["POST"]),
        Route("/api/admin/users/{id}/toggle-active", route_admin_toggle_active, methods=["POST"]),
        Route("/api/admin/users/{id}", route_admin_delete_user, methods=["DELETE"]),
        # v1 SDK REST surface — thin shims over MCP tool handlers
        Route("/api/v1/memory", v1.route_v1_memory, methods=["POST"]),
        Route("/api/v1/recall", v1.route_v1_recall, methods=["POST"]),
        Route("/api/v1/projects", v1.route_v1_projects, methods=["GET"]),
        Route("/api/v1/whoami", v1.route_v1_whoami, methods=["GET"]),
        Route("/api/v1/init", v1.route_v1_init, methods=["POST"]),
        Route("/api/v1/recommend", v1.route_v1_recommend, methods=["POST"]),
        Route("/api/v1/contradict", v1.route_v1_contradict, methods=["POST"]),
    ]
