from __future__ import annotations

"""Team memory API routes.

Follows the same Starlette Request/Response + orjson + async_session pattern
as routes.py. All endpoints require Bearer token authentication.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import orjson
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from piloci.api.ratelimit import RATE_MUTATION, limiter
from piloci.db.session import async_session

# ---------------------------------------------------------------------------
# Helpers (mirrored from routes.py)
# ---------------------------------------------------------------------------


def _json(data: Any, status: int = 200) -> Response:
    return Response(orjson.dumps(data), status_code=status, media_type="application/json")


def _require_user(request: Request) -> dict[str, Any] | None:
    return getattr(request.state, "user", None)


def _uid(user: dict[str, Any]) -> str:
    return user.get("sub") or user.get("user_id") or ""


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _get_team_member(db, team_id: str, user_id: str):
    """Return TeamMember row or None if user is not a member of this team."""
    from sqlalchemy import select

    from piloci.db.models import TeamMember

    result = await db.execute(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Team CRUD
# ---------------------------------------------------------------------------


async def route_create_team(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    name = (body.get("name") or "").strip()
    if not name:
        return _json({"error": "name is required"}, 400)

    from piloci.db.models import Team, TeamMember

    user_id = _uid(user)
    now = _utcnow()
    team_id = str(uuid.uuid4())

    try:
        async with async_session() as db:
            team = Team(id=team_id, name=name, owner_id=user_id, created_at=now)
            db.add(team)
            await db.flush()
            member = TeamMember(team_id=team_id, user_id=user_id, role="owner", joined_at=now)
            db.add(member)

        return _json({"id": team_id, "name": name, "created_at": now.isoformat()}, 201)
    except Exception:
        return _json({"error": "Internal server error"}, 500)


async def route_list_teams(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    from sqlalchemy import select

    from piloci.db.models import Team, TeamMember

    user_id = _uid(user)
    async with async_session() as db:
        result = await db.execute(
            select(Team)
            .join(TeamMember, Team.id == TeamMember.team_id)
            .where(TeamMember.user_id == user_id)
            .order_by(Team.created_at)
        )
        teams = result.scalars().all()

    return _json(
        [
            {
                "id": t.id,
                "name": t.name,
                "owner_id": t.owner_id,
                "created_at": t.created_at.isoformat(),
            }
            for t in teams
        ]
    )


async def route_get_team(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    user_id = _uid(user)

    from sqlalchemy import select

    from piloci.db.models import Team, TeamMember, User

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

        result = await db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one_or_none()
        if not team:
            return _json({"error": "Not found"}, 404)

        result = await db.execute(
            select(TeamMember, User.email)
            .join(User, TeamMember.user_id == User.id)
            .where(TeamMember.team_id == team_id)
        )
        rows = result.all()

    members = [
        {
            "user_id": row.TeamMember.user_id,
            "email": row.email,
            "role": row.TeamMember.role,
            "joined_at": row.TeamMember.joined_at.isoformat(),
        }
        for row in rows
    ]

    return _json(
        {
            "id": team.id,
            "name": team.name,
            "owner_id": team.owner_id,
            "created_at": team.created_at.isoformat(),
            "description": team.description,
            "avatar": team.avatar,
            "color": team.color,
            "members": members,
        }
    )


async def route_patch_team(request: Request) -> Response:
    """PATCH /api/teams/{team_id} — owner-only: update name/description/avatar/color."""
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    user_id = _uid(user)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    from sqlalchemy import select

    from piloci.db.models import Team

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)
        if member.role != "owner":
            return _json({"error": "Forbidden — owner only"}, 403)

        result = await db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one_or_none()
        if not team:
            return _json({"error": "Not found"}, 404)

        if "name" in body:
            name = (body["name"] or "").strip()
            if name:
                team.name = name
        if "description" in body:
            team.description = (body["description"] or "").strip() or None
        if "avatar" in body:
            team.avatar = (body["avatar"] or "").strip() or None
        if "color" in body:
            color = (body["color"] or "").strip()
            if color and (color.startswith("#") and len(color) in (4, 7)):
                team.color = color
            elif not color:
                team.color = None
        if "auto_wiki_enabled" in body:
            team.auto_wiki_enabled = bool(body["auto_wiki_enabled"])
        db.add(team)

    return _json(
        {
            "id": team.id,
            "name": team.name,
            "description": team.description,
            "avatar": team.avatar,
            "color": team.color,
            "auto_wiki_enabled": bool(team.auto_wiki_enabled),
            "last_wiki_built_at": (
                team.last_wiki_built_at.isoformat() if team.last_wiki_built_at else None
            ),
        }
    )


async def route_delete_team(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    user_id = _uid(user)

    from sqlalchemy import delete

    from piloci.db.models import Team

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)
        if member.role != "owner":
            return _json({"error": "Forbidden — owner only"}, 403)

        await db.execute(delete(Team).where(Team.id == team_id))

    return _json({"deleted": True})


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


async def route_create_invite(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    user_id = _uid(user)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    invitee_email = (body.get("invitee_email") or "").strip().lower()
    if not invitee_email:
        return _json({"error": "invitee_email is required"}, 400)

    from piloci.db.models import TeamInvite

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)
        if member.role != "owner":
            return _json({"error": "Forbidden — owner only"}, 403)

        now = _utcnow()
        token = str(uuid.uuid4())
        invite_id = str(uuid.uuid4())
        invite = TeamInvite(
            id=invite_id,
            team_id=team_id,
            inviter_id=user_id,
            invitee_email=invitee_email,
            token_hash=_token_hash(token),
            status="pending",
            expires_at=now + timedelta(days=7),
            created_at=now,
        )
        db.add(invite)

    return _json(
        {
            "id": invite_id,
            "team_id": team_id,
            "invitee_email": invitee_email,
            "token": token,
            "expires_at": invite.expires_at.isoformat(),
        },
        201,
    )


async def route_list_invites(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    user_id = _uid(user)

    from sqlalchemy import select

    from piloci.db.models import TeamInvite

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

        result = await db.execute(
            select(TeamInvite)
            .where(TeamInvite.team_id == team_id)
            .order_by(TeamInvite.created_at.desc())
        )
        invites = result.scalars().all()

    return _json(
        [
            {
                "id": inv.id,
                "invitee_email": inv.invitee_email,
                "status": inv.status,
                "expires_at": inv.expires_at.isoformat(),
                "created_at": inv.created_at.isoformat(),
            }
            for inv in invites
        ]
    )


async def route_cancel_invite(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    invite_id = request.path_params.get("invite_id", "")
    user_id = _uid(user)

    from sqlalchemy import delete, select

    from piloci.db.models import TeamInvite

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)
        if member.role != "owner":
            return _json({"error": "Forbidden — owner only"}, 403)

        result = await db.execute(
            select(TeamInvite).where(TeamInvite.id == invite_id, TeamInvite.team_id == team_id)
        )
        invite = result.scalar_one_or_none()
        if not invite:
            return _json({"error": "Not found"}, 404)

        await db.execute(delete(TeamInvite).where(TeamInvite.id == invite_id))

    return _json({"cancelled": True})


# ---------------------------------------------------------------------------
# Accept / reject invite (by token)
# ---------------------------------------------------------------------------


async def _handle_invite_response(request: Request, new_status: str) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    token = request.path_params.get("token", "")
    if not token:
        return _json({"error": "token required"}, 400)

    user_id = _uid(user)
    user_email = (user.get("email") or "").strip().lower()
    th = _token_hash(token)

    from sqlalchemy import select

    from piloci.db.models import TeamInvite, TeamMember

    async with async_session() as db:
        result = await db.execute(select(TeamInvite).where(TeamInvite.token_hash == th))
        invite = result.scalar_one_or_none()
        if not invite:
            return _json({"error": "Invalid or expired invite token"}, 404)

        if invite.status != "pending":
            return _json({"error": f"Invite already {invite.status}"}, 409)

        now = _utcnow()
        if invite.expires_at < now:
            return _json({"error": "Invite has expired"}, 410)

        if invite.invitee_email != user_email:
            return _json({"error": "Forbidden — invite is for a different email"}, 403)

        invite.status = new_status
        db.add(invite)

        if new_status == "accepted":
            existing = await _get_team_member(db, invite.team_id, user_id)
            if not existing:
                member = TeamMember(
                    team_id=invite.team_id,
                    user_id=user_id,
                    role="member",
                    joined_at=now,
                )
                db.add(member)

    return _json({"status": new_status, "team_id": invite.team_id})


async def route_accept_invite(request: Request) -> Response:
    return await _handle_invite_response(request, "accepted")


async def route_reject_invite(request: Request) -> Response:
    return await _handle_invite_response(request, "rejected")


# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------


async def route_remove_member(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    target_user_id = request.path_params.get("user_id", "")
    user_id = _uid(user)

    from sqlalchemy import delete

    from piloci.db.models import TeamMember

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)
        if member.role != "owner":
            return _json({"error": "Forbidden — owner only"}, 403)
        if target_user_id == user_id:
            return _json({"error": "Owner cannot remove themselves"}, 422)

        target = await _get_team_member(db, team_id, target_user_id)
        if not target:
            return _json({"error": "Member not found"}, 404)

        await db.execute(
            delete(TeamMember).where(
                TeamMember.team_id == team_id, TeamMember.user_id == target_user_id
            )
        )

    return _json({"removed": True})


# ---------------------------------------------------------------------------
# Team documents
# ---------------------------------------------------------------------------


async def route_create_document(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    user_id = _uid(user)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    path = (body.get("path") or "").strip()
    content = body.get("content") or ""
    parent_hash = body.get("parent_hash") or None

    if not path:
        return _json({"error": "path is required"}, 400)
    if not isinstance(content, str):
        return _json({"error": "content must be a string"}, 400)

    from sqlalchemy.exc import IntegrityError

    from piloci.db.models import TeamDocument

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

        now = _utcnow()
        doc_id = str(uuid.uuid4())
        ch = _content_hash(content)
        doc = TeamDocument(
            id=doc_id,
            team_id=team_id,
            author_id=user_id,
            path=path,
            content=content,
            content_hash=ch,
            version=1,
            parent_hash=parent_hash,
            updated_at=now,
            created_at=now,
            is_deleted=False,
        )
        db.add(doc)
        try:
            await db.flush()
        except IntegrityError:
            return _json({"error": "A document at this path already exists"}, 409)

    await _invalidate_team_vault(team_id)

    return _json(
        {
            "id": doc_id,
            "team_id": team_id,
            "path": path,
            "content_hash": ch,
            "version": 1,
            "created_at": now.isoformat(),
        },
        201,
    )


async def _invalidate_team_vault(team_id: str) -> None:
    """Drop the cached team workspace so the next GET rebuilds with fresh
    documents. Fail-open: cache miss is harmless."""
    try:
        from piloci.config import get_settings
        from piloci.curator.team_vault import invalidate_team_vault_cache

        await invalidate_team_vault_cache(get_settings().vault_dir, team_id)
    except Exception:
        pass


async def route_list_documents(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    user_id = _uid(user)

    from sqlalchemy import select

    from piloci.db.models import TeamDocument, User

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

        result = await db.execute(
            select(TeamDocument, User.email)
            .join(User, TeamDocument.author_id == User.id)
            .where(TeamDocument.team_id == team_id, TeamDocument.is_deleted == False)  # noqa: E712
            .order_by(TeamDocument.path)
        )
        rows = result.all()

    return _json(
        [
            {
                "id": row.TeamDocument.id,
                "path": row.TeamDocument.path,
                "content_hash": row.TeamDocument.content_hash,
                "version": row.TeamDocument.version,
                "author_email": row.email,
                "updated_at": row.TeamDocument.updated_at.isoformat(),
            }
            for row in rows
        ]
    )


async def route_pull_documents(request: Request) -> Response:
    """POST /api/teams/{team_id}/documents/pull

    Body: {"manifest": {"path": "content_hash", ...}}
    Returns diff: added, modified, deleted, unchanged.
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    user_id = _uid(user)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    manifest: dict[str, str] = body.get("manifest") or {}

    from sqlalchemy import select

    from piloci.db.models import TeamDocument, User

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

        result = await db.execute(
            select(TeamDocument, User.email)
            .join(User, TeamDocument.author_id == User.id)
            .where(TeamDocument.team_id == team_id, TeamDocument.is_deleted == False)  # noqa: E712
        )
        rows = result.all()

    server_docs = {
        row.TeamDocument.path: {
            "id": row.TeamDocument.id,
            "path": row.TeamDocument.path,
            "content": row.TeamDocument.content,
            "content_hash": row.TeamDocument.content_hash,
            "version": row.TeamDocument.version,
            "author_email": row.email,
        }
        for row in rows
    }

    added = []
    modified = []
    unchanged = []

    for path, doc in server_docs.items():
        if path not in manifest:
            added.append(doc)
        elif manifest[path] != doc["content_hash"]:
            modified.append(doc)
        else:
            unchanged.append({"path": path, "content_hash": doc["content_hash"]})

    deleted = [{"path": p} for p in manifest if p not in server_docs]

    return _json(
        {
            "added": added,
            "modified": modified,
            "deleted": deleted,
            "unchanged": unchanged,
        }
    )


async def route_update_document(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    doc_id = request.path_params.get("doc_id", "")
    user_id = _uid(user)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    content = body.get("content")
    parent_hash = body.get("parent_hash") or None

    if not isinstance(content, str):
        return _json({"error": "content is required"}, 400)

    from sqlalchemy import select

    from piloci.db.models import TeamDocument

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

        result = await db.execute(
            select(TeamDocument).where(
                TeamDocument.id == doc_id,
                TeamDocument.team_id == team_id,
                TeamDocument.is_deleted == False,  # noqa: E712
            )
        )
        doc = result.scalar_one_or_none()
        if not doc:
            return _json({"error": "Not found"}, 404)

        if parent_hash is not None and parent_hash != doc.content_hash:
            return _json(
                {
                    "error": "conflict",
                    "server_hash": doc.content_hash,
                    "server_version": doc.version,
                },
                409,
            )

        now = _utcnow()
        new_hash = _content_hash(content)
        old_hash = doc.content_hash
        doc.content = content
        doc.content_hash = new_hash
        doc.version = doc.version + 1
        doc.parent_hash = old_hash
        doc.author_id = user_id
        doc.updated_at = now
        db.add(doc)

    await _invalidate_team_vault(team_id)

    return _json(
        {
            "id": doc_id,
            "content_hash": new_hash,
            "version": doc.version,
            "updated_at": now.isoformat(),
        }
    )


async def route_delete_document(request: Request) -> Response:
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    doc_id = request.path_params.get("doc_id", "")
    user_id = _uid(user)

    from sqlalchemy import select

    from piloci.db.models import TeamDocument

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

        result = await db.execute(
            select(TeamDocument).where(
                TeamDocument.id == doc_id,
                TeamDocument.team_id == team_id,
                TeamDocument.is_deleted == False,  # noqa: E712
            )
        )
        doc = result.scalar_one_or_none()
        if not doc:
            return _json({"error": "Not found"}, 404)

        doc.is_deleted = True
        doc.updated_at = _utcnow()
        db.add(doc)

    await _invalidate_team_vault(team_id)
    return _json({"deleted": True})


# ---------------------------------------------------------------------------
# In-site invite flow (no token sharing required)
# ---------------------------------------------------------------------------


async def route_my_pending_invites(request: Request) -> Response:
    """GET /api/invites/pending — invites addressed to the current user's email."""
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    user_email = (user.get("email") or "").strip().lower()
    if not user_email:
        return _json({"error": "No email on session"}, 400)

    from sqlalchemy import select

    from piloci.db.models import Team, TeamInvite

    now = _utcnow()
    async with async_session() as db:
        result = await db.execute(
            select(TeamInvite, Team.name)
            .join(Team, TeamInvite.team_id == Team.id)
            .where(
                TeamInvite.invitee_email == user_email,
                TeamInvite.status == "pending",
                TeamInvite.expires_at > now,
            )
            .order_by(TeamInvite.created_at.desc())
        )
        rows = result.all()

    return _json(
        [
            {
                "id": row.TeamInvite.id,
                "team_id": row.TeamInvite.team_id,
                "team_name": row.name,
                "expires_at": row.TeamInvite.expires_at.isoformat(),
                "created_at": row.TeamInvite.created_at.isoformat(),
            }
            for row in rows
        ]
    )


async def route_respond_invite(request: Request) -> Response:
    """POST /api/invites/{invite_id}/respond  body: {"action": "accept"|"reject"}

    Auth-only — no raw token needed. Email must match the invite.
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    invite_id = request.path_params.get("invite_id", "")
    user_id = _uid(user)
    user_email = (user.get("email") or "").strip().lower()

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    action = (body.get("action") or "").strip()
    if action not in ("accept", "reject"):
        return _json({"error": "action must be 'accept' or 'reject'"}, 400)

    from sqlalchemy import select

    from piloci.db.models import TeamInvite, TeamMember

    now = _utcnow()
    async with async_session() as db:
        result = await db.execute(select(TeamInvite).where(TeamInvite.id == invite_id))
        invite = result.scalar_one_or_none()
        if not invite:
            return _json({"error": "Invite not found"}, 404)
        if invite.invitee_email != user_email:
            return _json({"error": "Forbidden — invite is for a different email"}, 403)
        if invite.status != "pending":
            return _json({"error": f"Invite already {invite.status}"}, 409)
        if invite.expires_at < now:
            return _json({"error": "Invite has expired"}, 410)

        new_status = "accepted" if action == "accept" else "rejected"
        invite.status = new_status
        db.add(invite)

        if new_status == "accepted":
            existing = await _get_team_member(db, invite.team_id, user_id)
            if not existing:
                db.add(
                    TeamMember(
                        team_id=invite.team_id,
                        user_id=user_id,
                        role="member",
                        joined_at=now,
                    )
                )

    return _json({"status": new_status, "team_id": invite.team_id})


# ---------------------------------------------------------------------------
# Single document fetch + raw download
# ---------------------------------------------------------------------------


async def route_get_document(request: Request) -> Response:
    """GET /api/teams/{team_id}/documents/{doc_id} — return single doc with content."""
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    doc_id = request.path_params.get("doc_id", "")
    user_id = _uid(user)

    from sqlalchemy import select

    from piloci.db.models import TeamDocument, User

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

        result = await db.execute(
            select(TeamDocument, User.email)
            .join(User, TeamDocument.author_id == User.id)
            .where(
                TeamDocument.id == doc_id,
                TeamDocument.team_id == team_id,
                TeamDocument.is_deleted == False,  # noqa: E712
            )
        )
        row = result.first()

    if not row:
        return _json({"error": "Not found"}, 404)

    doc = row.TeamDocument
    return _json(
        {
            "id": doc.id,
            "team_id": doc.team_id,
            "path": doc.path,
            "content": doc.content,
            "content_hash": doc.content_hash,
            "version": doc.version,
            "author_email": row.email,
            "updated_at": doc.updated_at.isoformat(),
            "bytes": len(doc.content.encode()) if doc.content else 0,
        }
    )


async def route_team_workspace(request: Request) -> Response:
    """GET /api/teams/{tid}/workspace — folder tree + graph + wiki article list.

    Builds from cache when available; rebuilds fresh otherwise. Wiki articles
    are surfaced as a flat list with category — the frontend handles grouping.
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    user_id = _uid(user)

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

    from piloci.config import get_settings
    from piloci.curator.team_vault import build_team_vault, load_cached_team_vault, save_team_vault

    settings = get_settings()
    workspace = load_cached_team_vault(settings.vault_dir, team_id)
    if workspace is None:
        # Cold rebuild — fetch the source rows and assemble. No LLM call.
        from sqlalchemy import select

        from piloci.db.models import Team, TeamDocument

        async with async_session() as db:
            team_row = (
                await db.execute(select(Team).where(Team.id == team_id))
            ).scalar_one_or_none()
            doc_rows = (
                (
                    await db.execute(
                        select(TeamDocument).where(
                            TeamDocument.team_id == team_id,
                            TeamDocument.is_deleted == False,  # noqa: E712
                        )
                    )
                )
                .scalars()
                .all()
            )

        team_dict = {
            "id": team_row.id,
            "name": team_row.name,
            "auto_wiki_enabled": bool(team_row.auto_wiki_enabled),
            "last_wiki_built_at": (
                team_row.last_wiki_built_at.isoformat() if team_row.last_wiki_built_at else None
            ),
        }
        documents = [
            {
                "id": d.id,
                "path": d.path,
                "content": d.content,
                "version": d.version,
                "updated_at": d.updated_at,
            }
            for d in doc_rows
        ]
        # Team-scoped LanceDB memories require the store; fall back to empty
        # if the request didn't pass one (workspace is still useful from docs).
        memories: list[dict[str, Any]] = []
        store = getattr(request.app.state, "store", None)
        if store is not None:
            try:
                memories = await store.team_list(team_id, limit=500)
            except Exception:
                memories = []

        workspace = build_team_vault(team_dict, memories, documents)
        save_team_vault(settings.vault_dir, team_id, workspace)

    return _json(workspace)


async def route_team_wiki_articles(request: Request) -> Response:
    """GET /api/teams/{tid}/wiki/articles — list of generated articles."""
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    user_id = _uid(user)

    from sqlalchemy import select

    from piloci.db.models import TeamWikiArticle

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)
        rows = (
            (
                await db.execute(
                    select(TeamWikiArticle)
                    .where(TeamWikiArticle.team_id == team_id)
                    .order_by(TeamWikiArticle.category, TeamWikiArticle.title)
                )
            )
            .scalars()
            .all()
        )

    return _json(
        [
            {
                "id": r.id,
                "slug": r.slug,
                "title": r.title,
                "summary": r.summary,
                "category": r.category,
                "revision": r.revision,
                "generated_by": r.generated_by,
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]
    )


async def route_team_wiki_article(request: Request) -> Response:
    """GET /api/teams/{tid}/wiki/articles/{slug} — single article body."""
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    slug = request.path_params.get("slug", "")
    user_id = _uid(user)

    from sqlalchemy import select

    from piloci.db.models import TeamWikiArticle

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)
        row = (
            await db.execute(
                select(TeamWikiArticle).where(
                    TeamWikiArticle.team_id == team_id,
                    TeamWikiArticle.slug == slug,
                )
            )
        ).scalar_one_or_none()

    if row is None:
        return _json({"error": "Not found"}, 404)

    sources: list[dict[str, Any]] = []
    if row.sources_json:
        try:
            sources = orjson.loads(row.sources_json)
        except Exception:
            sources = []

    return _json(
        {
            "id": row.id,
            "slug": row.slug,
            "title": row.title,
            "summary": row.summary,
            "content": row.content,
            "category": row.category,
            "sources": sources,
            "revision": row.revision,
            "generated_by": row.generated_by,
            "author_kind": row.author_kind,
            "author_id": row.author_id,
            "updated_at": row.updated_at.isoformat(),
            "created_at": row.created_at.isoformat(),
        }
    )


async def route_update_team_memory(request: Request) -> Response:
    """PATCH /api/teams/{tid}/memories/{id} — author-only edit of a team memory.

    Re-embeds when content changes. Tags/metadata can be patched alone without
    paying for an embedding. Vault cache is invalidated so the next workspace
    GET rebuilds with fresh content.
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    memory_id = request.path_params.get("id", "")
    user_id = _uid(user)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

    store = getattr(request.app.state, "store", None)
    if store is None:
        return _json({"error": "memory store unavailable"}, 503)

    content = body.get("content")
    tags = body.get("tags")
    metadata = body.get("metadata")
    new_vector = None
    if content is not None:
        from piloci.config import get_settings
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

    updated = await store.team_update(
        team_id=team_id,
        memory_id=memory_id,
        requester_id=user_id,
        content=content,
        new_vector=new_vector,
        tags=tags,
        metadata=metadata,
        allow_owner=member.role == "owner",
    )
    if updated:
        await _invalidate_team_vault(team_id)
    return _json({"updated": updated})


async def route_upload_team_wiki_image(request: Request) -> Response:
    """POST /api/teams/{tid}/wiki/images — body is the raw image bytes
    (already WebP from the client). Returns ``{url, id, bytes}``.

    Storage: ``settings.vault_dir / team_{team_id} / wiki / images / {id}.webp``.
    Filesystem-only — no DB row, the markdown body that references the URL
    is the only source of truth. Orphan cleanup happens in the maintenance
    worker (compares image files against article body references).
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    user_id = _uid(user)

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

    body = await request.body()
    if not body or len(body) > 5 * 1024 * 1024:  # 5 MB ceiling
        return _json({"error": "Image must be 1B-5MB"}, 400)

    # Quick magic-byte sniff so we don't write arbitrary uploads to disk
    # when a misbehaving client sends, say, an HTML form. WebP starts
    # with RIFF...WEBP. PNG/JPEG accepted too as a fallback (client may
    # downgrade if canvas WebP fails).
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        ext = "webp"
        ctype = "image/webp"
    elif body[:8] == b"\x89PNG\r\n\x1a\n":
        ext = "png"
        ctype = "image/png"
    elif body[:3] == b"\xff\xd8\xff":
        ext = "jpg"
        ctype = "image/jpeg"
    else:
        return _json({"error": "Unsupported image format (webp/png/jpeg only)"}, 415)

    from piloci.config import get_settings

    settings = get_settings()
    image_id = uuid.uuid4().hex
    out_dir = settings.vault_dir / f"team_{team_id}" / "wiki" / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{image_id}.{ext}"
    out_path.write_bytes(body)

    return _json(
        {
            "id": image_id,
            "url": f"/api/teams/{team_id}/wiki/images/{image_id}.{ext}",
            "content_type": ctype,
            "bytes": len(body),
        },
        201,
    )


async def route_get_team_wiki_image(request: Request) -> Response:
    """GET /api/teams/{tid}/wiki/images/{filename} — serve a previously
    uploaded image. Member-only, filename sanitized to refuse path traversal.
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    filename = request.path_params.get("filename", "")
    user_id = _uid(user)

    # Hex-id.ext only — no slashes, no `..`. Strictest filter for static reads.
    import re

    if not re.match(r"^[a-f0-9]{16,64}\.(webp|png|jpg|jpeg)$", filename):
        return _json({"error": "Bad filename"}, 400)

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

    from piloci.config import get_settings

    settings = get_settings()
    path = settings.vault_dir / f"team_{team_id}" / "wiki" / "images" / filename
    if not path.is_file():
        return _json({"error": "Not found"}, 404)

    ext = filename.rsplit(".", 1)[-1].lower()
    media_type = {
        "webp": "image/webp",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
    }.get(ext, "application/octet-stream")
    return Response(
        path.read_bytes(),
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


async def route_update_team_wiki_article(request: Request) -> Response:
    """PATCH /api/teams/{tid}/wiki/articles/{slug} — human edit of a wiki article.

    Captures the previous revision into ``team_wiki_revisions`` and stamps the
    new row with ``author_kind="human"``. The team_wiki_worker pulls recent
    human-edited revisions as few-shot style hints, so editing here feeds
    back into the LLM's next draft pass.
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    slug = request.path_params.get("slug", "")
    user_id = _uid(user)

    try:
        body = orjson.loads(await request.body())
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)

    from sqlalchemy import select

    from piloci.db.models import TeamWikiArticle, TeamWikiRevision

    title = body.get("title")
    summary = body.get("summary")
    content = body.get("content")
    category = body.get("category")
    if all(v is None for v in (title, summary, content, category)):
        return _json({"error": "Nothing to update"}, 400)

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

        row = (
            await db.execute(
                select(TeamWikiArticle).where(
                    TeamWikiArticle.team_id == team_id,
                    TeamWikiArticle.slug == slug,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return _json({"error": "Not found"}, 404)

        now = _utcnow()
        db.add(
            TeamWikiRevision(
                id=str(uuid.uuid4()),
                article_id=row.id,
                team_id=team_id,
                revision=row.revision,
                title=row.title,
                content=row.content,
                author_kind=row.author_kind,
                author_id=row.author_id,
                created_at=now,
            )
        )

        if title is not None and title.strip():
            row.title = title.strip()
        if summary is not None:
            row.summary = summary.strip() or None
        if content is not None:
            row.content = content
        if category is not None:
            row.category = category.strip() or None
        row.revision = (row.revision or 1) + 1
        row.author_kind = "human"
        row.author_id = user_id
        row.updated_at = now
        db.add(row)
        article_id = row.id
        revision = row.revision

    await _invalidate_team_vault(team_id)

    return _json(
        {
            "id": article_id,
            "slug": slug,
            "revision": revision,
            "updated_at": now.isoformat(),
            "author_kind": "human",
        }
    )


async def route_team_export_zip(request: Request) -> Response:
    """GET /api/teams/{tid}/export.zip — bundle docs + wiki + AGENTS.md.

    What lands on disk after extracting::

        {team_name}/
            AGENTS.md          # briefing the agent reads first
            index.md           # flat index with one-line summaries
            docs/              # team_documents, original paths preserved
            wiki/              # GLM-distilled articles

    Folder structure under ``docs/`` mirrors what people uploaded, so a user
    who prefers raw paths gets exactly what they put in. Wiki sits next to
    it, never replacing — both views ship together so the consumer picks.
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    user_id = _uid(user)

    from sqlalchemy import select

    from piloci.curator.team_export import pack_team_zip
    from piloci.db.models import Team, TeamDocument, TeamMember, TeamWikiArticle, User

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

        team_row = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
        if team_row is None:
            return _json({"error": "Not found"}, 404)

        doc_rows = (
            (
                await db.execute(
                    select(TeamDocument).where(
                        TeamDocument.team_id == team_id,
                        TeamDocument.is_deleted == False,  # noqa: E712
                    )
                )
            )
            .scalars()
            .all()
        )

        article_rows = (
            (
                await db.execute(
                    select(TeamWikiArticle)
                    .where(TeamWikiArticle.team_id == team_id)
                    .order_by(TeamWikiArticle.category, TeamWikiArticle.title)
                )
            )
            .scalars()
            .all()
        )

        email_rows = (
            await db.execute(
                select(User.email)
                .join(TeamMember, TeamMember.user_id == User.id)
                .where(TeamMember.team_id == team_id)
            )
        ).all()

    team = {
        "id": team_row.id,
        "name": team_row.name,
        "last_wiki_built_at": (
            team_row.last_wiki_built_at.isoformat() if team_row.last_wiki_built_at else None
        ),
    }
    documents = [
        {
            "id": d.id,
            "path": d.path,
            "content": d.content,
            "version": d.version,
            "updated_at": d.updated_at,
        }
        for d in doc_rows
    ]
    articles: list[dict[str, Any]] = []
    for a in article_rows:
        sources: list[dict[str, Any]] = []
        if a.sources_json:
            try:
                sources = orjson.loads(a.sources_json)
            except Exception:
                sources = []
        articles.append(
            {
                "id": a.id,
                "slug": a.slug,
                "title": a.title,
                "summary": a.summary,
                "content": a.content,
                "category": a.category,
                "revision": a.revision,
                "generated_by": a.generated_by,
                "updated_at": a.updated_at.isoformat() if a.updated_at else None,
                "sources": sources,
            }
        )
    member_emails = [row.email for row in email_rows if row.email]

    filename, payload = pack_team_zip(team, documents, articles, member_emails)
    safe_filename = filename.replace('"', "")
    return Response(
        payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "X-Team-Documents": str(len(documents)),
            "X-Team-Wiki-Articles": str(len(articles)),
        },
    )


async def route_team_wiki_build(request: Request) -> Response:
    """POST /api/teams/{tid}/wiki/build — owner-only manual trigger.

    Returns immediately with the build summary; LLM work runs synchronously
    within the request. UI shows a spinner while the request is in flight.
    """
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    user_id = _uid(user)

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)
        if member.role != "owner":
            return _json({"error": "Forbidden — owner only"}, 403)

    store = getattr(request.app.state, "store", None)
    if store is None:
        return _json({"error": "memory store unavailable"}, 503)

    from piloci.curator.team_wiki_worker import build_team_wiki

    summary = await build_team_wiki(team_id, store)
    return _json(summary)


async def route_download_document(request: Request) -> Response:
    """GET /api/teams/{team_id}/documents/{doc_id}/raw — stream raw file body."""
    user = _require_user(request)
    if not user:
        return _json({"error": "Unauthorized"}, 401)

    team_id = request.path_params.get("team_id", "")
    doc_id = request.path_params.get("doc_id", "")
    user_id = _uid(user)

    from sqlalchemy import select

    from piloci.db.models import TeamDocument

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return _json({"error": "Not found"}, 404)

        result = await db.execute(
            select(TeamDocument).where(
                TeamDocument.id == doc_id,
                TeamDocument.team_id == team_id,
                TeamDocument.is_deleted == False,  # noqa: E712
            )
        )
        doc = result.scalar_one_or_none()

    if not doc:
        return _json({"error": "Not found"}, 404)

    # basename of stored path so filename matches the document's name; the
    # full path is still surfaced as X-Doc-Path for clients that want the
    # folder context when bulk-downloading.
    import os.path

    filename = os.path.basename(doc.path) or "document.md"
    safe_filename = filename.replace('"', "")
    body = (doc.content or "").encode("utf-8")
    return Response(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "X-Doc-Path": doc.path,
            "X-Content-Hash": doc.content_hash or "",
            "X-Doc-Version": str(doc.version or 1),
        },
    )


# ---------------------------------------------------------------------------
# Route list (exported for registration in routes.py)
# ---------------------------------------------------------------------------

_create_team_limited = limiter.limit(RATE_MUTATION)(route_create_team)
_patch_team_limited = limiter.limit(RATE_MUTATION)(route_patch_team)
_delete_team_limited = limiter.limit(RATE_MUTATION)(route_delete_team)
_respond_invite_limited = limiter.limit(RATE_MUTATION)(route_respond_invite)
_create_invite_limited = limiter.limit(RATE_MUTATION)(route_create_invite)
_cancel_invite_limited = limiter.limit(RATE_MUTATION)(route_cancel_invite)
_accept_invite_limited = limiter.limit(RATE_MUTATION)(route_accept_invite)
_reject_invite_limited = limiter.limit(RATE_MUTATION)(route_reject_invite)
_remove_member_limited = limiter.limit(RATE_MUTATION)(route_remove_member)
_create_document_limited = limiter.limit(RATE_MUTATION)(route_create_document)
_pull_documents_limited = limiter.limit(RATE_MUTATION)(route_pull_documents)
_update_document_limited = limiter.limit(RATE_MUTATION)(route_update_document)
_delete_document_limited = limiter.limit(RATE_MUTATION)(route_delete_document)


TEAM_ROUTES = [
    # Teams
    Route("/api/teams", _create_team_limited, methods=["POST"]),
    Route("/api/teams", route_list_teams, methods=["GET"]),
    Route("/api/teams/{team_id}", route_get_team, methods=["GET"]),
    Route("/api/teams/{team_id}", _patch_team_limited, methods=["PATCH"]),
    Route("/api/teams/{team_id}", _delete_team_limited, methods=["DELETE"]),
    # Invites — in-site flow (auth only, no token)
    Route("/api/invites/pending", route_my_pending_invites, methods=["GET"]),
    Route("/api/invites/{invite_id}/respond", _respond_invite_limited, methods=["POST"]),
    # Invites (team-scoped management)
    Route("/api/teams/{team_id}/invites", _create_invite_limited, methods=["POST"]),
    Route("/api/teams/{team_id}/invites", route_list_invites, methods=["GET"]),
    Route(
        "/api/teams/{team_id}/invites/{invite_id}",
        _cancel_invite_limited,
        methods=["DELETE"],
    ),
    # Invites (legacy token-based — kept for MCP tool compatibility)
    Route("/api/invites/{token}/accept", _accept_invite_limited, methods=["POST"]),
    Route("/api/invites/{token}/reject", _reject_invite_limited, methods=["POST"]),
    # Members
    Route(
        "/api/teams/{team_id}/members/{user_id}",
        _remove_member_limited,
        methods=["DELETE"],
    ),
    # Documents
    Route("/api/teams/{team_id}/documents", _create_document_limited, methods=["POST"]),
    Route("/api/teams/{team_id}/documents", route_list_documents, methods=["GET"]),
    Route(
        "/api/teams/{team_id}/documents/pull",
        _pull_documents_limited,
        methods=["POST"],
    ),
    Route(
        "/api/teams/{team_id}/documents/{doc_id}",
        _update_document_limited,
        methods=["PUT"],
    ),
    Route(
        "/api/teams/{team_id}/documents/{doc_id}",
        _delete_document_limited,
        methods=["DELETE"],
    ),
    Route(
        "/api/teams/{team_id}/documents/{doc_id}",
        route_get_document,
        methods=["GET"],
    ),
    Route(
        "/api/teams/{team_id}/documents/{doc_id}/raw",
        route_download_document,
        methods=["GET"],
    ),
    # Workspace + wiki
    Route("/api/teams/{team_id}/workspace", route_team_workspace, methods=["GET"]),
    Route("/api/teams/{team_id}/wiki/articles", route_team_wiki_articles, methods=["GET"]),
    Route(
        "/api/teams/{team_id}/wiki/articles/{slug}",
        route_team_wiki_article,
        methods=["GET"],
    ),
    Route(
        "/api/teams/{team_id}/wiki/build",
        limiter.limit(RATE_MUTATION)(route_team_wiki_build),
        methods=["POST"],
    ),
    Route("/api/teams/{team_id}/export.zip", route_team_export_zip, methods=["GET"]),
    Route(
        "/api/teams/{team_id}/memories/{id}",
        limiter.limit(RATE_MUTATION)(route_update_team_memory),
        methods=["PATCH"],
    ),
    Route(
        "/api/teams/{team_id}/wiki/articles/{slug}",
        limiter.limit(RATE_MUTATION)(route_update_team_wiki_article),
        methods=["PATCH"],
    ),
    Route(
        "/api/teams/{team_id}/wiki/images",
        limiter.limit(RATE_MUTATION)(route_upload_team_wiki_image),
        methods=["POST"],
    ),
    Route(
        "/api/teams/{team_id}/wiki/images/{filename}",
        route_get_team_wiki_image,
        methods=["GET"],
    ),
]
