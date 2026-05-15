from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware

from piloci.api import team_routes
from piloci.db.models import User
from piloci.db.session import init_db


class _UserHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        user_id = request.headers.get("x-user-id")
        if user_id:
            request.state.user = {
                "sub": user_id,
                "user_id": user_id,
                "email": request.headers.get("x-user-email", f"{user_id}@example.com"),
            }
        return await call_next(request)


@pytest.fixture
async def team_app(monkeypatch, tmp_path) -> AsyncGenerator[Starlette, None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'teams.db'}")
    await init_db(engine=engine)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _test_async_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setattr(team_routes, "async_session", _test_async_session)

    now = datetime.now(timezone.utc)
    async with factory() as session:
        session.add_all(
            [
                User(
                    id="owner",
                    email="owner@example.com",
                    created_at=now,
                    is_active=True,
                    approval_status="approved",
                ),
                User(
                    id="member",
                    email="member@example.com",
                    created_at=now,
                    is_active=True,
                    approval_status="approved",
                ),
            ]
        )
        await session.commit()

    yield Starlette(routes=team_routes.TEAM_ROUTES, middleware=[Middleware(_UserHeaderMiddleware)])
    await engine.dispose()


def _headers(user_id: str, email: str) -> dict[str, str]:
    return {"x-user-id": user_id, "x-user-email": email}


@pytest.mark.asyncio
async def test_team_invite_and_document_flow(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        member = _headers("member", "member@example.com")

        create_team = await client.post("/api/teams", headers=owner, json={"name": "Research"})
        assert create_team.status_code == 201
        team_id = create_team.json()["id"]

        list_teams = await client.get("/api/teams", headers=owner)
        assert [team["name"] for team in list_teams.json()] == ["Research"]

        patch_team = await client.patch(
            f"/api/teams/{team_id}",
            headers=owner,
            json={"name": "Field Notes", "description": "Shared context", "color": "#123456"},
        )
        assert patch_team.status_code == 200
        assert patch_team.json()["color"] == "#123456"

        invite = await client.post(
            f"/api/teams/{team_id}/invites",
            headers=owner,
            json={"invitee_email": "MEMBER@example.com"},
        )
        assert invite.status_code == 201
        invite_token = invite.json()["token"]

        listed_invites = await client.get(f"/api/teams/{team_id}/invites", headers=owner)
        assert listed_invites.status_code == 200
        assert listed_invites.json()[0]["invitee_email"] == "member@example.com"

        pending = await client.get("/api/invites/pending", headers=member)
        assert pending.status_code == 200
        assert pending.json()[0]["team_id"] == team_id

        accepted = await client.post(f"/api/invites/{invite_token}/accept", headers=member)
        assert accepted.status_code == 200
        assert accepted.json() == {"status": "accepted", "team_id": team_id}

        team_detail = await client.get(f"/api/teams/{team_id}", headers=member)
        assert team_detail.status_code == 200
        assert {entry["role"] for entry in team_detail.json()["members"]} == {"owner", "member"}

        create_doc = await client.post(
            f"/api/teams/{team_id}/documents",
            headers=member,
            json={"path": "notes.md", "content": "hello"},
        )
        assert create_doc.status_code == 201
        doc = create_doc.json()

        docs = await client.get(f"/api/teams/{team_id}/documents", headers=owner)
        assert docs.status_code == 200
        assert docs.json()[0]["path"] == "notes.md"

        pull_added = await client.post(
            f"/api/teams/{team_id}/documents/pull", headers=owner, json={"manifest": {}}
        )
        assert pull_added.status_code == 200
        assert pull_added.json()["added"][0]["content"] == "hello"

        conflict = await client.put(
            f"/api/teams/{team_id}/documents/{doc['id']}",
            headers=owner,
            json={"content": "new", "parent_hash": "stale"},
        )
        assert conflict.status_code == 409

        updated = await client.put(
            f"/api/teams/{team_id}/documents/{doc['id']}",
            headers=owner,
            json={"content": "new", "parent_hash": doc["content_hash"]},
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2

        pull_unchanged = await client.post(
            f"/api/teams/{team_id}/documents/pull",
            headers=owner,
            json={"manifest": {"notes.md": updated.json()["content_hash"], "old.md": "gone"}},
        )
        assert pull_unchanged.status_code == 200
        assert pull_unchanged.json()["unchanged"] == [
            {"path": "notes.md", "content_hash": updated.json()["content_hash"]}
        ]
        assert pull_unchanged.json()["deleted"] == [{"path": "old.md"}]

        delete_doc = await client.delete(
            f"/api/teams/{team_id}/documents/{doc['id']}", headers=owner
        )
        assert delete_doc.status_code == 200
        assert delete_doc.json() == {"deleted": True}

        remove_member = await client.delete(f"/api/teams/{team_id}/members/member", headers=owner)
        assert remove_member.status_code == 200
        assert remove_member.json() == {"removed": True}

        delete_team = await client.delete(f"/api/teams/{team_id}", headers=owner)
        assert delete_team.status_code == 200
        assert delete_team.json() == {"deleted": True}


@pytest.mark.asyncio
async def test_team_routes_validate_common_error_paths(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        member = _headers("member", "member@example.com")

        assert (await client.get("/api/teams")).status_code == 401
        assert (await client.post("/api/teams", headers=owner, content="{")).status_code == 400
        assert (
            await client.post("/api/teams", headers=owner, json={"name": ""})
        ).status_code == 400

        create_team = await client.post("/api/teams", headers=owner, json={"name": "Errors"})
        team_id = create_team.json()["id"]

        forbidden_patch = await client.patch(
            f"/api/teams/{team_id}", headers=member, json={"name": "Nope"}
        )
        assert forbidden_patch.status_code == 404

        bad_invite = await client.post(
            f"/api/teams/{team_id}/invites", headers=owner, json={"invitee_email": ""}
        )
        assert bad_invite.status_code == 400

        invite = await client.post(
            f"/api/teams/{team_id}/invites",
            headers=owner,
            json={"invitee_email": "member@example.com"},
        )
        invite_id = (await client.get(f"/api/teams/{team_id}/invites", headers=owner)).json()[0][
            "id"
        ]

        wrong_email = await client.post(
            f"/api/invites/{invite.json()['token']}/accept",
            headers={"x-user-id": "owner", "x-user-email": "owner@example.com"},
        )
        assert wrong_email.status_code == 403

        rejected = await client.post(
            f"/api/invites/{invite_id}/respond", headers=member, json={"action": "reject"}
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"

        invalid_action = await client.post(
            f"/api/invites/{invite_id}/respond", headers=member, json={"action": "maybe"}
        )
        assert invalid_action.status_code == 400

        cancel = await client.delete(f"/api/teams/{team_id}/invites/{invite_id}", headers=owner)
        assert cancel.status_code == 200

        bad_doc = await client.post(
            f"/api/teams/{team_id}/documents", headers=owner, json={"path": "", "content": ""}
        )
        assert bad_doc.status_code == 400

        missing_doc = await client.delete(f"/api/teams/{team_id}/documents/missing", headers=owner)
        assert missing_doc.status_code == 404
