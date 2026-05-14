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
    now = datetime.now(timezone.utc)
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
        db.add(team)

    return _json(
        {
            "id": team.id,
            "name": team.name,
            "description": team.description,
            "avatar": team.avatar,
            "color": team.color,
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

        now = datetime.now(timezone.utc)
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

        now = datetime.now(timezone.utc)
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

        now = datetime.now(timezone.utc)
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

        now = datetime.now(timezone.utc)
        new_hash = _content_hash(content)
        old_hash = doc.content_hash
        doc.content = content
        doc.content_hash = new_hash
        doc.version = doc.version + 1
        doc.parent_hash = old_hash
        doc.author_id = user_id
        doc.updated_at = now
        db.add(doc)

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
        doc.updated_at = datetime.now(timezone.utc)
        db.add(doc)

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

    now = datetime.now(timezone.utc)
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

    now = datetime.now(timezone.utc)
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
# Route list (exported for registration in routes.py)
# ---------------------------------------------------------------------------

TEAM_ROUTES = [
    # Teams
    Route("/api/teams", route_create_team, methods=["POST"]),
    Route("/api/teams", route_list_teams, methods=["GET"]),
    Route("/api/teams/{team_id}", route_get_team, methods=["GET"]),
    Route("/api/teams/{team_id}", route_patch_team, methods=["PATCH"]),
    Route("/api/teams/{team_id}", route_delete_team, methods=["DELETE"]),
    # Invites — in-site flow (auth only, no token)
    Route("/api/invites/pending", route_my_pending_invites, methods=["GET"]),
    Route("/api/invites/{invite_id}/respond", route_respond_invite, methods=["POST"]),
    # Invites (team-scoped management)
    Route("/api/teams/{team_id}/invites", route_create_invite, methods=["POST"]),
    Route("/api/teams/{team_id}/invites", route_list_invites, methods=["GET"]),
    Route(
        "/api/teams/{team_id}/invites/{invite_id}",
        route_cancel_invite,
        methods=["DELETE"],
    ),
    # Invites (legacy token-based — kept for MCP tool compatibility)
    Route("/api/invites/{token}/accept", route_accept_invite, methods=["POST"]),
    Route("/api/invites/{token}/reject", route_reject_invite, methods=["POST"]),
    # Members
    Route(
        "/api/teams/{team_id}/members/{user_id}",
        route_remove_member,
        methods=["DELETE"],
    ),
    # Documents
    Route("/api/teams/{team_id}/documents", route_create_document, methods=["POST"]),
    Route("/api/teams/{team_id}/documents", route_list_documents, methods=["GET"]),
    Route(
        "/api/teams/{team_id}/documents/pull",
        route_pull_documents,
        methods=["POST"],
    ),
    Route(
        "/api/teams/{team_id}/documents/{doc_id}",
        route_update_document,
        methods=["PUT"],
    ),
    Route(
        "/api/teams/{team_id}/documents/{doc_id}",
        route_delete_document,
        methods=["DELETE"],
    ),
]
