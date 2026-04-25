from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import orjson
from sqlalchemy import delete
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from piloci.auth.jwt_utils import create_token
from piloci.auth.local import (
    AccountLockedError,
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
from piloci.curator.vault import (
    ensure_project_vault,
    export_project_vault_zip,
    invalidate_project_vault_cache,
    load_cached_project_vault,
)
from piloci.db.session import async_session
from piloci.utils.logging import get_runtime_profiler


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
        return _json({"user_id": user.id, "email": user.email}, 201)
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
        response = _json({"user_id": user.id, "email": user.email})
        response.set_cookie(
            "piloci_session",
            session_id,
            httponly=True,
            samesite="lax",
            secure=True,
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
            select(Project).where(Project.user_id == user["sub"]).order_by(Project.created_at)
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
        user_id=user["sub"],
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
            select(Project).where(Project.id == project_id, Project.user_id == user["sub"])
        )
        project = result.scalar_one_or_none()
        if not project:
            return _json({"error": "Not found"}, 404)
        await db.execute(delete(Project).where(Project.id == project_id))

    await invalidate_project_vault_cache(
        get_settings().vault_dir,
        user["sub"],
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

    user_id = user["sub"]
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


async def route_vault_export(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    slug = (request.path_params.get("slug") or "").strip().lower()
    if not slug:
        return _json({"error": "project slug required"}, 400)

    user_id = user["sub"]
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
                select(Project).where(Project.id == project_id, Project.user_id == user["sub"])
            )
            proj = result.scalar_one_or_none()
        if not proj:
            return _json({"error": "Project not found"}, 404)
        project_slug = proj.slug

    token_id = str(uuid.uuid4())
    jwt_token = create_token(
        user_id=user["sub"],
        email=user["email"],
        project_id=project_id,
        project_slug=project_slug,
        scope=scope,
        settings=settings,
        token_id=token_id,
    )

    # Store hash in api_tokens table
    import hashlib

    from piloci.db.models import ApiToken

    token_hash = hashlib.sha256(jwt_token.encode()).hexdigest()
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        db.add(
            ApiToken(
                token_id=token_id,
                user_id=user["sub"],
                project_id=project_id,
                name=token_name,
                token_hash=token_hash,
                scope=scope,
                created_at=now,
            )
        )

    return _json({"token": jwt_token, "token_id": token_id, "name": token_name}, 201)


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
                ApiToken.user_id == user["sub"],
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
            select(ApiToken).where(ApiToken.token_id == token_id, ApiToken.user_id == user["sub"])
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
        q = select(AuditLog).where(AuditLog.user_id == user["sub"])
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
        result = await db.execute(select(User).where(User.id == user["sub"]))
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

    qr = get_qr_base64(secret, user["email"])
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
        result = await db.execute(select(User).where(User.id == user["sub"]))
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
        result = await db.execute(select(User).where(User.id == user["sub"]))
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
    return _json({"user_id": user["sub"], "email": user.get("email"), "scope": user.get("scope")})


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
        result = await db.execute(select(User).where(User.id == user["sub"]))
        u = result.scalar_one_or_none()
        if not u or not verify_password(current, u.password_hash or ""):
            return _json({"error": "Current password is incorrect"}, 401)
        u.password_hash = hash_password(new_pw)
        db.add(u)

    return _json({"changed": True})


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

_OAUTH_STATE_PREFIX = "oauth_state:"


async def route_google_auth(request: Request) -> Response:
    """GET /auth/google — Google 로그인 시작. redirect_uri 쿼리 파라미터 옵션."""
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        return _json({"error": "Google OAuth is not configured"}, 503)

    from starlette.responses import RedirectResponse

    from piloci.auth.oauth import build_auth_url, generate_state

    state = generate_state()
    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/auth/google/callback"

    # state를 Redis에 5분 저장 (CSRF 방어)
    store = get_session_store(settings)
    await store._redis.setex(f"{_OAUTH_STATE_PREFIX}{state}", 300, "1")  # noqa: SLF001

    url = build_auth_url(settings.google_client_id, redirect_uri, state)
    return RedirectResponse(url, status_code=302)


async def route_google_callback(request: Request) -> Response:
    """GET /auth/google/callback — Google 인가 코드 처리."""
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        return _json({"error": "Google OAuth is not configured"}, 503)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    from starlette.responses import RedirectResponse

    if error or not code or not state:
        return RedirectResponse("/login?error=oauth_cancelled", status_code=302)

    # state 검증
    store = get_session_store(settings)
    state_key = f"{_OAUTH_STATE_PREFIX}{state}"
    valid = await store._redis.get(state_key)  # noqa: SLF001
    if not valid:
        return RedirectResponse("/login?error=oauth_invalid_state", status_code=302)
    await store._redis.delete(state_key)  # noqa: SLF001

    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/auth/google/callback"

    try:
        from piloci.auth.oauth import exchange_code, get_userinfo, upsert_google_user

        tokens = await exchange_code(
            code, settings.google_client_id, settings.google_client_secret, redirect_uri
        )
        userinfo = await get_userinfo(tokens["access_token"])
    except Exception:
        return RedirectResponse("/login?error=oauth_failed", status_code=302)

    from piloci.db.models import User  # noqa: F401

    async with async_session() as db:
        user = await upsert_google_user(db, userinfo)

    # 세션 발급
    ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    session_id = await store.create_session(user.id, ip, user_agent)
    settings2 = get_settings()
    max_age = settings2.session_expire_days * 86400

    response = RedirectResponse("/dashboard", status_code=302)
    response.set_cookie(
        "session_id",
        session_id,
        httponly=True,
        samesite="lax",
        max_age=max_age,
        path="/",
    )
    return response


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

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "invalid JSON"}, 400)

    client = (body.get("client") or "").strip() or "unknown"
    transcript = body.get("transcript")
    session_id = body.get("session_id")

    if not isinstance(transcript, list) or not transcript:
        return _json({"error": "transcript must be a non-empty list"}, 400)

    user_id = user.get("sub") or user.get("user_id")
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
# Memory management (REST — MCP-excluded admin surface)
# ---------------------------------------------------------------------------


async def route_get_memory(request: Request) -> Response:
    user = request.state.user
    if user is None:
        return _json({"error": "unauthorized"}, 401)
    user_id = user.get("sub") or user.get("user_id")
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
    user_id = user.get("sub") or user.get("user_id")
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
    user_id = user.get("sub") or user.get("user_id")
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
    user_id = user.get("sub") or user.get("user_id")
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
    except Exception as e:
        checks["lancedb"] = {"status": "error", "detail": str(e)}
        causes.append("lancedb_unavailable")

    # Check DB
    try:
        async with async_session() as db:
            from sqlalchemy import text

            await db.execute(text("SELECT 1"))
        checks["db"] = {"status": "ok"}
    except Exception as e:
        checks["db"] = {"status": "error", "detail": str(e)}
        causes.append("database_unavailable")

    # Check Redis session store
    try:
        session_store = get_session_store(settings)
        await session_store.ping()
        checks["redis"] = {"status": "ok"}
    except Exception as e:
        checks["redis"] = {"status": "error", "detail": str(e)}
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
# Route list
# ---------------------------------------------------------------------------


def get_routes() -> list[Route]:
    return [
        Route("/healthz", route_healthz),
        Route("/readyz", route_readyz),
        Route("/profilez", route_profilez),
        Route("/auth/signup", route_signup, methods=["POST"]),
        Route("/auth/login", route_login, methods=["POST"]),
        Route("/auth/logout", route_logout, methods=["POST"]),
        Route("/auth/forgot-password", route_forgot_password, methods=["POST"]),
        Route("/auth/reset-password", route_reset_password, methods=["POST"]),
        Route("/api/projects", route_list_projects, methods=["GET"]),
        Route("/api/projects", route_create_project, methods=["POST"]),
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
        Route("/auth/google", route_google_auth, methods=["GET"]),
        Route("/auth/google/callback", route_google_callback, methods=["GET"]),
        # v0.3: auto-capture + memory admin
        Route("/api/ingest", route_ingest, methods=["POST"]),
        Route("/api/memories/{id}", route_get_memory, methods=["GET"]),
        Route("/api/memories/{id}", route_update_memory, methods=["PATCH"]),
        Route("/api/memories/{id}", route_delete_memory, methods=["DELETE"]),
        Route("/api/memories/clear", route_clear_memories, methods=["POST"]),
    ]
