from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, cast

import orjson
from sqlalchemy import delete
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from piloci.api.ratelimit import RATE_LOGIN, RATE_PASSWORD_RESET, RATE_SIGNUP, limiter
from piloci.auth.session import get_session_store
from piloci.config import get_settings
from piloci.curator.queue import IngestJob, get_ingest_queue, try_enqueue_job
from piloci.curator.vault import (
    invalidate_project_vault_cache,
)

logger = logging.getLogger(__name__)
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


async def route_create_memory(request: Request) -> Response:
    user = request.state.user
    if user is None:
        return _json({"error": "unauthorized"}, 401)
    user_id_value = user.get("sub") or user.get("user_id")
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
    except Exception:
        logger.exception("LanceDB health check failed")
        checks["lancedb"] = {"status": "error", "detail": "unavailable"}
        causes.append("lancedb_unavailable")

    # Check DB
    try:
        async with async_session() as db:
            from sqlalchemy import text

            await db.execute(text("SELECT 1"))
        checks["db"] = {"status": "ok"}
    except Exception:
        logger.exception("Database health check failed")
        checks["db"] = {"status": "error", "detail": "unavailable"}
        causes.append("database_unavailable")

    # Check Redis session store
    try:
        session_store = get_session_store(settings)
        await session_store.ping()
        checks["redis"] = {"status": "ok"}
    except Exception:
        logger.exception("Redis health check failed")
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
        Route("/api/auth/providers", route_auth_providers, methods=["GET"]),
        Route("/auth/signup", signup_limited, methods=["POST"]),
        Route("/auth/login", login_limited, methods=["POST"]),
        Route("/auth/logout", route_logout, methods=["POST"]),
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
        # v0.3: auto-capture + memory admin
        Route("/api/ingest", route_ingest, methods=["POST"]),
        Route("/api/memories", route_create_memory, methods=["POST"]),
        Route("/api/memories/{id}", route_get_memory, methods=["GET"]),
        Route("/api/memories/{id}", route_update_memory, methods=["PATCH"]),
        Route("/api/memories/{id}", route_delete_memory, methods=["DELETE"]),
        Route("/api/memories/clear", route_clear_memories, methods=["POST"]),
    ]
