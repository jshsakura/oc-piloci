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

from piloci.api.ratelimit import RATE_LOGIN, RATE_PASSWORD_RESET, RATE_SIGNUP, limiter
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


async def route_list_projects(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    from sqlalchemy import select

    from piloci.db.models import Project

    async with async_session() as db:
        result = await db.execute(
            select(Project).where(Project.user_id == _uid(user)).order_by(Project.created_at)
        )
        projects = result.scalars().all()

    return _json(
        [
            {
                "id": p.id,
                "slug": p.slug,
                "name": p.name,
                "description": p.description,
                "memory_count": p.memory_count,
                "created_at": p.created_at.isoformat(),
            }
            for p in projects
        ]
    )


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

    if not slug or not name:
        return _json({"error": "slug and name are required"}, 400)

    import re

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
    project_id = body.get("project_id")
    scope = body.get("scope", "project")

    if not token_name:
        return _json({"error": "name is required"}, 400)
    if scope not in ("project", "user"):
        return _json({"error": "scope must be 'project' or 'user'"}, 422)
    if scope == "project" and not project_id:
        return _json({"error": "project_id required for project scope"}, 422)

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
    setup = _generate_token_setup(jwt_token, base_url) if scope == "project" else None
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
            }
            for t in tokens
        ]
    )


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
    import re

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

    # User-scoped token: resolve project from cwd slug
    if not project_id:
        cwd = (body.get("cwd") or "").strip()
        if not cwd:
            return _json({"error": "project-scoped token or cwd required"}, 400)
        slug = (
            re.sub(r"[^a-zA-Z0-9]+", "-", cwd.rsplit("/", 1)[-1].encode("ascii", "ignore").decode())
            .strip("-")
            .lower()[:40]
            or "project"
        )
        from sqlalchemy import select as _slug_sel

        from piloci.db.models import Project

        async with async_session() as db:
            row = (
                await db.execute(
                    _slug_sel(Project.id)
                    .where(
                        Project.user_id == user_id,
                        Project.slug == slug,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
        if row is None:
            return _json({"error": f"no project found for slug '{slug}' — run init first"}, 404)
        project_id = row

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
    if not isinstance(project_id, str) or not project_id:
        return _json({"error": "project scope required — use a project-scoped token"}, 400)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)

    transcript = body.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        return _json({"error": "transcript required"}, 400)

    instincts_store = getattr(request.app.state, "instincts_store", None)
    if instincts_store is None:
        return _json({"error": "instincts store not available"}, 503)

    settings = get_settings()

    try:
        from piloci.curator.session_analyzer import extract_instincts
        from piloci.storage import embed as _embed_mod

        raw_instincts = await extract_instincts(
            transcript=transcript,
            endpoint=settings.gemma_endpoint,
            model=settings.gemma_model,
        )
    except Exception:
        logger.exception("session_analyze: extraction failed")
        return _json({"error": "extraction failed"}, 500)

    saved = []
    for inst in raw_instincts:
        try:
            combined = f"{inst['trigger']} {inst['action']}"
            vector = await _embed_mod.embed_one(
                text=combined,
                model=settings.embed_model,
                cache_dir=settings.embed_cache_dir,
                lru_size=settings.embed_lru_size,
                executor_workers=settings.embed_executor_workers,
                max_concurrency=settings.embed_max_concurrency,
            )
            result = await instincts_store.observe(
                user_id=user_id,
                project_id=project_id,
                trigger=inst["trigger"],
                action=inst["action"],
                domain=inst.get("domain", "other"),
                evidence_note=inst.get("evidence", ""),
                vector=vector,
            )
            saved.append(
                {
                    "instinct_id": result["instinct_id"],
                    "domain": result["domain"],
                    "confidence": result["confidence"],
                    "instinct_count": result["instinct_count"],
                }
            )
        except Exception:
            logger.exception("session_analyze: failed to store instinct")

    return _json({"extracted": len(raw_instincts), "saved": len(saved), "instincts": saved})


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
        Route("/api/projects", route_list_projects, methods=["GET"]),
        Route("/api/projects", route_create_project, methods=["POST"]),
        Route(
            "/api/projects/slug/{slug}/workspace/preview",
            route_project_workspace_preview,
            methods=["GET"],
        ),
        Route("/api/projects/slug/{slug}/workspace", route_project_workspace, methods=["GET"]),
        Route("/api/vault/{slug}/export", route_vault_export, methods=["GET"]),
        Route("/api/projects/{id}", route_delete_project, methods=["DELETE"]),
        Route("/api/tokens", route_list_tokens, methods=["GET"]),
        Route("/api/tokens", route_create_token, methods=["POST"]),
        Route("/api/tokens/{id}", route_revoke_token, methods=["DELETE"]),
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
        Route("/api/chat", route_chat, methods=["POST"]),
        Route("/api/admin/users", route_admin_list_users, methods=["GET"]),
        Route("/api/admin/users/{id}/approve", route_admin_approve_user, methods=["POST"]),
        Route("/api/admin/users/{id}/reject", route_admin_reject_user, methods=["POST"]),
        Route("/api/admin/users/{id}/toggle-admin", route_admin_toggle_admin, methods=["POST"]),
        Route("/api/admin/users/{id}/toggle-active", route_admin_toggle_active, methods=["POST"]),
        Route("/api/admin/users/{id}", route_admin_delete_user, methods=["DELETE"]),
    ]
