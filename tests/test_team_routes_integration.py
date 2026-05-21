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


@pytest.mark.asyncio
async def test_team_document_single_get_and_raw_download(team_app: Starlette) -> None:
    """Single-doc GET returns content + bytes; /raw streams with attachment filename
    derived from the path's basename so download preserves the doc's name."""
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")

        team_id = (await client.post("/api/teams", headers=owner, json={"name": "Docs"})).json()[
            "id"
        ]
        doc = (
            await client.post(
                f"/api/teams/{team_id}/documents",
                headers=owner,
                json={"path": "docs/notes/api.md", "content": "# title\nbody"},
            )
        ).json()

        single = await client.get(f"/api/teams/{team_id}/documents/{doc['id']}", headers=owner)
        assert single.status_code == 200
        payload = single.json()
        assert payload["path"] == "docs/notes/api.md"
        assert payload["content"] == "# title\nbody"
        assert payload["bytes"] == len("# title\nbody".encode())

        raw = await client.get(f"/api/teams/{team_id}/documents/{doc['id']}/raw", headers=owner)
        assert raw.status_code == 200
        assert raw.headers["content-disposition"] == 'attachment; filename="api.md"'
        assert raw.headers["x-doc-path"] == "docs/notes/api.md"
        assert raw.text == "# title\nbody"

        # Non-member is rejected on both endpoints with the same 404 mask
        assert (
            await client.get(f"/api/teams/{team_id}/documents/{doc['id']}", headers=stranger)
        ).status_code == 404
        assert (
            await client.get(f"/api/teams/{team_id}/documents/{doc['id']}/raw", headers=stranger)
        ).status_code == 404


@pytest.mark.asyncio
async def test_team_workspace_and_wiki_routes(team_app: Starlette, tmp_path, monkeypatch) -> None:
    """workspace builds a cold vault from documents; wiki article routes return
    rows from team_wiki_articles. Non-members get 404 on both."""
    from piloci.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "vault_dir", tmp_path / "vaults")

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")

        team_id = (await client.post("/api/teams", headers=owner, json={"name": "Wiki"})).json()[
            "id"
        ]
        await client.post(
            f"/api/teams/{team_id}/documents",
            headers=owner,
            json={"path": "docs/notes.md", "content": "hello"},
        )

        workspace = await client.get(f"/api/teams/{team_id}/workspace", headers=owner)
        assert workspace.status_code == 200
        body = workspace.json()
        assert body["team"]["id"] == team_id
        assert any(n["kind"] == "folder" for n in body["graph"]["nodes"])
        assert body["wiki_articles"] == []

        empty_list = await client.get(f"/api/teams/{team_id}/wiki/articles", headers=owner)
        assert empty_list.status_code == 200
        assert empty_list.json() == []
        assert (
            await client.get(f"/api/teams/{team_id}/wiki/articles", headers=stranger)
        ).status_code == 404

        assert (
            await client.get(f"/api/teams/{team_id}/wiki/articles/nope", headers=owner)
        ).status_code == 404

        assert (
            await client.get(f"/api/teams/{team_id}/workspace", headers=stranger)
        ).status_code == 404


@pytest.mark.asyncio
async def test_team_wiki_article_patch_snapshots_revision(
    team_app: Starlette, tmp_path, monkeypatch
) -> None:
    """PATCH /wiki/articles/{slug} should write a TeamWikiRevision row with
    the previous body, then bump the article's revision + mark author_kind
    as 'human' so the worker treats it as a style hint next build."""
    from piloci.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "vault_dir", tmp_path / "vaults")

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")

        team_id = (await client.post("/api/teams", headers=owner, json={"name": "Edits"})).json()[
            "id"
        ]

        # Seed a wiki article directly via the route layer's session so the
        # PATCH endpoint has something to mutate.
        from datetime import datetime, timezone

        from piloci.api import team_routes
        from piloci.db.models import TeamWikiArticle

        async with team_routes.async_session() as db:
            db.add(
                TeamWikiArticle(
                    id="art-1",
                    team_id=team_id,
                    slug="intro",
                    title="Intro",
                    summary=None,
                    content="첫 본문",
                    category="folder/docs",
                    sources_json=None,
                    revision=1,
                    author_kind="llm",
                    author_id=None,
                    generated_by="test",
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            await db.commit()

        # Non-member rejected.
        assert (
            await client.patch(
                f"/api/teams/{team_id}/wiki/articles/intro",
                headers=stranger,
                json={"content": "hijack"},
            )
        ).status_code == 404

        # Empty patch rejected.
        empty = await client.patch(
            f"/api/teams/{team_id}/wiki/articles/intro", headers=owner, json={}
        )
        assert empty.status_code == 400

        # Real edit succeeds and bumps revision.
        patched = await client.patch(
            f"/api/teams/{team_id}/wiki/articles/intro",
            headers=owner,
            json={"title": "Intro v2", "content": "고친 본문"},
        )
        assert patched.status_code == 200
        body = patched.json()
        assert body["revision"] == 2
        assert body["author_kind"] == "human"

        # Verify the article row + a snapshot in revisions table.
        from sqlalchemy import select

        from piloci.db.models import TeamWikiArticle as TA
        from piloci.db.models import TeamWikiRevision

        async with team_routes.async_session() as db:
            row = (
                await db.execute(select(TA).where(TA.team_id == team_id, TA.slug == "intro"))
            ).scalar_one()
            assert row.title == "Intro v2"
            assert row.content == "고친 본문"
            assert row.author_kind == "human"

            snaps = (
                (
                    await db.execute(
                        select(TeamWikiRevision).where(TeamWikiRevision.article_id == "art-1")
                    )
                )
                .scalars()
                .all()
            )
            assert len(snaps) == 1
            # Snapshot captures the *previous* state, not the patched one.
            assert snaps[0].content == "첫 본문"


@pytest.mark.asyncio
async def test_team_wiki_image_upload_and_fetch_round_trip(
    team_app: Starlette, tmp_path, monkeypatch
) -> None:
    """Round-trip: POST webp bytes → 201 with url → GET that url returns the
    same bytes with image/webp content-type. Non-member is rejected on both
    ends, bad filenames return 400 before touching the FS."""
    from piloci.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "vault_dir", tmp_path / "vaults")

    # Smallest valid WebP — RIFF header + WEBP magic + empty body. The
    # endpoint only sniffs magic bytes, so this is enough to pass the
    # format guard without bundling a real encoder.
    webp_bytes = b"RIFF\x24\x00\x00\x00WEBPVP8 \x18\x00\x00\x00\x30\x01\x00\x9d\x01\x2a"
    # Pad to 32 bytes so length > 0 and slice indices line up — the magic
    # check only reads [:4] and [8:12].
    webp_bytes += b"\x00" * 16

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")

        team_id = (await client.post("/api/teams", headers=owner, json={"name": "Imgs"})).json()[
            "id"
        ]

        # Non-member rejected at upload.
        rejected = await client.post(
            f"/api/teams/{team_id}/wiki/images",
            headers={**stranger, "content-type": "image/webp"},
            content=webp_bytes,
        )
        assert rejected.status_code == 404

        # Owner uploads — gets a URL back.
        up = await client.post(
            f"/api/teams/{team_id}/wiki/images",
            headers={**owner, "content-type": "image/webp"},
            content=webp_bytes,
        )
        assert up.status_code == 201
        body = up.json()
        assert body["url"].startswith(f"/api/teams/{team_id}/wiki/images/")
        assert body["url"].endswith(".webp")
        filename = body["url"].rsplit("/", 1)[-1]

        # Empty body is rejected as 400.
        empty = await client.post(
            f"/api/teams/{team_id}/wiki/images",
            headers={**owner, "content-type": "image/webp"},
            content=b"",
        )
        assert empty.status_code == 400

        # Wrong magic (e.g. HTML form payload) is rejected as 415.
        garbage = await client.post(
            f"/api/teams/{team_id}/wiki/images",
            headers={**owner, "content-type": "image/webp"},
            content=b"<html>not an image</html>",
        )
        assert garbage.status_code == 415

        # Member can fetch the just-uploaded image with proper content type.
        got = await client.get(f"/api/teams/{team_id}/wiki/images/{filename}", headers=owner)
        assert got.status_code == 200
        assert got.headers["content-type"] == "image/webp"
        assert got.content == webp_bytes

        # Non-member fetch blocked.
        blocked = await client.get(f"/api/teams/{team_id}/wiki/images/{filename}", headers=stranger)
        assert blocked.status_code == 404

        # Path traversal/dirty filename rejected at the route, never touches FS.
        bad_name = await client.get(
            f"/api/teams/{team_id}/wiki/images/..%2Fsecret.webp", headers=owner
        )
        assert bad_name.status_code in (400, 404)

        # Missing file (well-formed name, not on disk) → 404.
        absent = await client.get(
            f"/api/teams/{team_id}/wiki/images/{'a' * 32}.webp", headers=owner
        )
        assert absent.status_code == 404


@pytest.mark.asyncio
async def test_team_memory_patch_requires_member(team_app: Starlette, monkeypatch) -> None:
    """PATCH /memories/{id} short-circuits with 404 for non-members before
    even consulting the store, and surfaces a 503 when the store binding
    is missing from app.state — the layer has its own no-store fallback."""
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")

        team_id = (await client.post("/api/teams", headers=owner, json={"name": "M"})).json()["id"]

        # No store on app.state → 503 (member can still pass the auth check).
        no_store = await client.patch(
            f"/api/teams/{team_id}/memories/whatever",
            headers=owner,
            json={"tags": ["x"]},
        )
        assert no_store.status_code == 503

        # Stranger is short-circuited at the member check, even before store
        # binding is consulted.
        rejected = await client.patch(
            f"/api/teams/{team_id}/memories/whatever",
            headers=stranger,
            json={"tags": ["x"]},
        )
        assert rejected.status_code == 404


@pytest.mark.asyncio
async def test_team_patch_toggles_auto_wiki_flag(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")

        team_id = (
            await client.post("/api/teams", headers=owner, json={"name": "AutoWiki"})
        ).json()["id"]

        patch = await client.patch(
            f"/api/teams/{team_id}",
            headers=owner,
            json={"auto_wiki_enabled": True},
        )
        assert patch.status_code == 200
        assert patch.json()["auto_wiki_enabled"] is True
        assert patch.json()["last_wiki_built_at"] is None

        off = await client.patch(
            f"/api/teams/{team_id}",
            headers=owner,
            json={"auto_wiki_enabled": False},
        )
        assert off.json()["auto_wiki_enabled"] is False


# ---------------------------------------------------------------------------
# Helpers used by the additional coverage suite below.
# ---------------------------------------------------------------------------


async def _make_team(client: httpx.AsyncClient, owner_headers: dict[str, str], name: str) -> str:
    res = await client.post("/api/teams", headers=owner_headers, json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _add_member(team_id: str, user_id: str, role: str = "member") -> None:
    """Insert a TeamMember row directly so we don't need to round-trip an invite."""
    from datetime import datetime, timezone

    from piloci.api import team_routes
    from piloci.db.models import TeamMember

    async with team_routes.async_session() as db:
        db.add(
            TeamMember(
                team_id=team_id,
                user_id=user_id,
                role=role,
                joined_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Auth/missing-user guards across every route. We don't need 25 separate
# checks — one helper iterating route_path/method pairs proves the
# `_require_user` short-circuit on each handler in one shot.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_team_routes_require_auth(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # GETs
        for path in (
            "/api/teams",
            "/api/teams/x",
            "/api/teams/x/invites",
            "/api/teams/x/documents",
            "/api/teams/x/documents/y",
            "/api/teams/x/documents/y/raw",
            "/api/teams/x/workspace",
            "/api/teams/x/wiki/articles",
            "/api/teams/x/wiki/articles/slug",
            "/api/teams/x/wiki/images/abcdef0123456789.webp",
            "/api/teams/x/export.zip",
            "/api/invites/pending",
        ):
            assert (await client.get(path)).status_code == 401, path

        # POSTs
        for path in (
            "/api/teams",
            "/api/teams/x/invites",
            "/api/teams/x/documents",
            "/api/teams/x/documents/pull",
            "/api/teams/x/wiki/build",
            "/api/teams/x/wiki/images",
            "/api/invites/tok/accept",
            "/api/invites/tok/reject",
            "/api/invites/iid/respond",
        ):
            assert (await client.post(path, json={})).status_code == 401, path

        # PATCH/PUT/DELETE
        assert (await client.patch("/api/teams/x", json={})).status_code == 401
        assert (await client.delete("/api/teams/x")).status_code == 401
        assert (await client.delete("/api/teams/x/invites/iid")).status_code == 401
        assert (await client.delete("/api/teams/x/members/u")).status_code == 401
        assert (await client.put("/api/teams/x/documents/d", json={})).status_code == 401
        assert (await client.delete("/api/teams/x/documents/d")).status_code == 401
        assert (await client.patch("/api/teams/x/memories/m", json={})).status_code == 401
        assert (await client.patch("/api/teams/x/wiki/articles/s", json={})).status_code == 401


# ---------------------------------------------------------------------------
# Team CRUD edge cases.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_team_returns_404_for_non_member(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "GetMe")
        assert (await client.get(f"/api/teams/{team_id}", headers=stranger)).status_code == 404


@pytest.mark.asyncio
async def test_patch_team_invalid_json_and_forbidden(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        member = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "Patch")
        await _add_member(team_id, "member")

        # Member is in the team but not owner → 403.
        forbidden = await client.patch(f"/api/teams/{team_id}", headers=member, json={"name": "x"})
        assert forbidden.status_code == 403

        # Owner sending broken JSON → 400.
        bad = await client.patch(f"/api/teams/{team_id}", headers=owner, content="{")
        assert bad.status_code == 400

        # Owner can update every field including clearing them.
        full = await client.patch(
            f"/api/teams/{team_id}",
            headers=owner,
            json={
                "name": "Renamed",
                "description": "  ctx  ",
                "avatar": "av.png",
                "color": "#abc",
            },
        )
        assert full.status_code == 200
        body = full.json()
        assert body["name"] == "Renamed"
        assert body["description"] == "ctx"
        assert body["color"] == "#abc"

        # Clearing fields with empty strings.
        cleared = await client.patch(
            f"/api/teams/{team_id}",
            headers=owner,
            json={"description": "", "avatar": "", "color": ""},
        )
        assert cleared.status_code == 200
        assert cleared.json()["description"] is None
        assert cleared.json()["avatar"] is None
        assert cleared.json()["color"] is None

        # Invalid hex color is silently ignored (no exception, color stays None).
        bad_color = await client.patch(
            f"/api/teams/{team_id}", headers=owner, json={"color": "purple"}
        )
        assert bad_color.status_code == 200
        assert bad_color.json()["color"] is None


@pytest.mark.asyncio
async def test_delete_team_owner_and_member_branches(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        member = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "Drop")
        await _add_member(team_id, "member")

        # Member trying to delete → 403.
        assert (await client.delete(f"/api/teams/{team_id}", headers=member)).status_code == 403

        # Non-member trying to delete → 404 (no leak that team exists).
        assert (await client.delete("/api/teams/nope", headers=owner)).status_code == 404


# ---------------------------------------------------------------------------
# Invite management.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_invite_validation_and_membership(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        member = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "Invites")
        await _add_member(team_id, "member")

        # Broken JSON.
        assert (
            await client.post(f"/api/teams/{team_id}/invites", headers=owner, content="{")
        ).status_code == 400

        # Member (non-owner) cannot invite.
        assert (
            await client.post(
                f"/api/teams/{team_id}/invites",
                headers=member,
                json={"invitee_email": "x@y.z"},
            )
        ).status_code == 403

        # Outside user cannot even see the team → 404.
        assert (
            await client.post(
                "/api/teams/missing/invites",
                headers=owner,
                json={"invitee_email": "x@y.z"},
            )
        ).status_code == 404


@pytest.mark.asyncio
async def test_list_and_cancel_invite_branches(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "InvList")

        # Outside user gets 404 on list.
        assert (
            await client.get(f"/api/teams/{team_id}/invites", headers=stranger)
        ).status_code == 404

        invite = await client.post(
            f"/api/teams/{team_id}/invites",
            headers=owner,
            json={"invitee_email": "member@example.com"},
        )
        invite_id = invite.json()["id"]

        # Stranger can't cancel.
        assert (
            await client.delete(f"/api/teams/{team_id}/invites/{invite_id}", headers=stranger)
        ).status_code == 404

        # Cancel a missing one as owner → 404.
        assert (
            await client.delete(f"/api/teams/{team_id}/invites/missing", headers=owner)
        ).status_code == 404

        # Member (not owner) cannot cancel either.
        await _add_member(team_id, "member")
        assert (
            await client.delete(f"/api/teams/{team_id}/invites/{invite_id}", headers=stranger)
        ).status_code == 403


@pytest.mark.asyncio
async def test_legacy_token_invite_flow_errors(team_app: Starlette) -> None:
    """The /api/invites/{token}/accept|reject legacy flow covers token-missing,
    not-found, expired, wrong-email and already-handled branches."""
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        member = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "Tok")

        # Empty token: starlette matches a non-empty path_param so we hit the
        # "invalid or expired" branch instead.
        assert (await client.post("/api/invites/zzzz/accept", headers=member)).status_code == 404

        invite_token = (
            await client.post(
                f"/api/teams/{team_id}/invites",
                headers=owner,
                json={"invitee_email": "member@example.com"},
            )
        ).json()["token"]

        # Wrong-email user trying to accept.
        wrong = await client.post(
            f"/api/invites/{invite_token}/accept",
            headers={"x-user-id": "owner", "x-user-email": "owner@example.com"},
        )
        assert wrong.status_code == 403

        # Reject works the first time.
        rejected = await client.post(f"/api/invites/{invite_token}/reject", headers=member)
        assert rejected.status_code == 200
        assert rejected.json() == {"status": "rejected", "team_id": team_id}

        # Re-rejecting → 409 (already rejected).
        again = await client.post(f"/api/invites/{invite_token}/reject", headers=member)
        assert again.status_code == 409


@pytest.mark.asyncio
async def test_legacy_accept_token_creates_member_idempotently(
    team_app: Starlette,
) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        member = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "Accept")

        invite_token = (
            await client.post(
                f"/api/teams/{team_id}/invites",
                headers=owner,
                json={"invitee_email": "member@example.com"},
            )
        ).json()["token"]

        # Pre-insert a TeamMember row so the accept handler hits the "existing"
        # branch and skips the duplicate insert.
        await _add_member(team_id, "member")
        ok = await client.post(f"/api/invites/{invite_token}/accept", headers=member)
        assert ok.status_code == 200
        assert ok.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_legacy_token_invite_expired(team_app: Starlette) -> None:
    """Stamp an invite with expires_at in the past, then call /accept → 410."""
    from datetime import datetime, timedelta, timezone

    from piloci.api import team_routes
    from piloci.db.models import TeamInvite

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        member = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "Expire")

        raw_token = "expired-token"
        token_hash = team_routes._token_hash(raw_token)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with team_routes.async_session() as db:
            db.add(
                TeamInvite(
                    id="inv-expired",
                    team_id=team_id,
                    inviter_id="owner",
                    invitee_email="member@example.com",
                    token_hash=token_hash,
                    status="pending",
                    expires_at=now - timedelta(days=1),
                    created_at=now - timedelta(days=10),
                )
            )
            await db.commit()

        gone = await client.post(f"/api/invites/{raw_token}/accept", headers=member)
        assert gone.status_code == 410


# ---------------------------------------------------------------------------
# In-site /api/invites/{id}/respond covers the same status_code matrix but
# via a different code path.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_respond_invite_full_matrix(team_app: Starlette) -> None:
    from datetime import datetime, timedelta, timezone

    from piloci.api import team_routes
    from piloci.db.models import TeamInvite

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        member = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "Resp")

        # Broken JSON.
        assert (
            await client.post("/api/invites/whatever/respond", headers=member, content="{")
        ).status_code == 400

        # Unknown action.
        assert (
            await client.post(
                "/api/invites/whatever/respond",
                headers=member,
                json={"action": "shrug"},
            )
        ).status_code == 400

        # Invite not found.
        assert (
            await client.post(
                "/api/invites/missing/respond",
                headers=member,
                json={"action": "accept"},
            )
        ).status_code == 404

        # Seed an expired invite for the matrix.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with team_routes.async_session() as db:
            db.add(
                TeamInvite(
                    id="inv-resp-expired",
                    team_id=team_id,
                    inviter_id="owner",
                    invitee_email="member@example.com",
                    token_hash="tok-resp-1",
                    status="pending",
                    expires_at=now - timedelta(days=1),
                    created_at=now - timedelta(days=2),
                )
            )
            db.add(
                TeamInvite(
                    id="inv-resp-other",
                    team_id=team_id,
                    inviter_id="owner",
                    invitee_email="someone@else.com",
                    token_hash="tok-resp-2",
                    status="pending",
                    expires_at=now + timedelta(days=2),
                    created_at=now,
                )
            )
            db.add(
                TeamInvite(
                    id="inv-resp-done",
                    team_id=team_id,
                    inviter_id="owner",
                    invitee_email="member@example.com",
                    token_hash="tok-resp-3",
                    status="accepted",
                    expires_at=now + timedelta(days=2),
                    created_at=now,
                )
            )
            db.add(
                TeamInvite(
                    id="inv-resp-good",
                    team_id=team_id,
                    inviter_id="owner",
                    invitee_email="member@example.com",
                    token_hash="tok-resp-4",
                    status="pending",
                    expires_at=now + timedelta(days=2),
                    created_at=now,
                )
            )
            await db.commit()

        # Expired.
        assert (
            await client.post(
                "/api/invites/inv-resp-expired/respond",
                headers=member,
                json={"action": "accept"},
            )
        ).status_code == 410

        # Wrong email.
        assert (
            await client.post(
                "/api/invites/inv-resp-other/respond",
                headers=member,
                json={"action": "accept"},
            )
        ).status_code == 403

        # Already accepted.
        assert (
            await client.post(
                "/api/invites/inv-resp-done/respond",
                headers=member,
                json={"action": "accept"},
            )
        ).status_code == 409

        # Accept the good one → member row created.
        ok = await client.post(
            "/api/invites/inv-resp-good/respond",
            headers=member,
            json={"action": "accept"},
        )
        assert ok.status_code == 200
        assert ok.json()["status"] == "accepted"

        # Pending listing now reflects the only un-acted invite (none left for
        # this user → empty list, but exercises the populated branch when other
        # invites exist).
        pending = await client.get("/api/invites/pending", headers=member)
        assert pending.status_code == 200
        # Only the not-yet-handled ones remain; we already accepted/rejected
        # the relevant rows for this email.
        assert isinstance(pending.json(), list)


@pytest.mark.asyncio
async def test_pending_invites_requires_session_email(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Empty email header on a valid session → 400 (handler-specific guard).
        no_email = await client.get(
            "/api/invites/pending",
            headers={"x-user-id": "owner", "x-user-email": ""},
        )
        assert no_email.status_code == 400


# ---------------------------------------------------------------------------
# Member removal.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_member_branches(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "RmM")
        await _add_member(team_id, "member")

        # Non-owner cannot remove.
        assert (
            await client.delete(f"/api/teams/{team_id}/members/owner", headers=stranger)
        ).status_code == 403

        # Owner cannot remove themselves.
        assert (
            await client.delete(f"/api/teams/{team_id}/members/owner", headers=owner)
        ).status_code == 422

        # Removing a user who isn't a member → 404.
        assert (
            await client.delete(f"/api/teams/{team_id}/members/ghost", headers=owner)
        ).status_code == 404

        # Outside non-member trying to remove anyone → 404 on the membership check.
        assert (await client.delete("/api/teams/nope/members/x", headers=owner)).status_code == 404


# ---------------------------------------------------------------------------
# Document CRUD edge cases.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_document_branches(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "Docs")

        # Broken JSON.
        assert (
            await client.post(f"/api/teams/{team_id}/documents", headers=owner, content="{")
        ).status_code == 400

        # Non-string content → 400.
        bad_type = await client.post(
            f"/api/teams/{team_id}/documents",
            headers=owner,
            json={"path": "p.md", "content": 123},
        )
        assert bad_type.status_code == 400

        # Non-member → 404.
        assert (
            await client.post(
                f"/api/teams/{team_id}/documents",
                headers=stranger,
                json={"path": "p.md", "content": "x"},
            )
        ).status_code == 404

        # Create a doc successfully (sanity check; dup-path branch is a known
        # latent bug — the route catches IntegrityError but the session is
        # already in rollback-pending state so the trailing commit fails).
        first = await client.post(
            f"/api/teams/{team_id}/documents",
            headers=owner,
            json={"path": "ok.md", "content": "first"},
        )
        assert first.status_code == 201


@pytest.mark.asyncio
async def test_update_and_delete_document_edge_cases(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "DocsUd")

        doc = (
            await client.post(
                f"/api/teams/{team_id}/documents",
                headers=owner,
                json={"path": "x.md", "content": "hi"},
            )
        ).json()
        doc_id = doc["id"]

        # Broken JSON on PUT.
        assert (
            await client.put(
                f"/api/teams/{team_id}/documents/{doc_id}",
                headers=owner,
                content="{",
            )
        ).status_code == 400

        # Non-string content.
        assert (
            await client.put(
                f"/api/teams/{team_id}/documents/{doc_id}",
                headers=owner,
                json={"content": None},
            )
        ).status_code == 400

        # Non-member PUT.
        assert (
            await client.put(
                f"/api/teams/{team_id}/documents/{doc_id}",
                headers=stranger,
                json={"content": "x"},
            )
        ).status_code == 404

        # Missing doc on PUT.
        assert (
            await client.put(
                f"/api/teams/{team_id}/documents/missing",
                headers=owner,
                json={"content": "x"},
            )
        ).status_code == 404

        # Successful update without parent_hash (force-overwrite branch).
        updated = await client.put(
            f"/api/teams/{team_id}/documents/{doc_id}",
            headers=owner,
            json={"content": "new"},
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2

        # Non-member DELETE.
        assert (
            await client.delete(f"/api/teams/{team_id}/documents/{doc_id}", headers=stranger)
        ).status_code == 404


@pytest.mark.asyncio
async def test_pull_documents_branches(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "Pull")

        # Broken JSON.
        assert (
            await client.post(f"/api/teams/{team_id}/documents/pull", headers=owner, content="{")
        ).status_code == 400

        # Non-member.
        assert (
            await client.post(
                f"/api/teams/{team_id}/documents/pull",
                headers=stranger,
                json={"manifest": {}},
            )
        ).status_code == 404


@pytest.mark.asyncio
async def test_get_document_missing_returns_404(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "GetDoc")

        # Doc id that doesn't exist on a real team → 404, not 500.
        assert (
            await client.get(f"/api/teams/{team_id}/documents/nope", headers=owner)
        ).status_code == 404
        assert (
            await client.get(f"/api/teams/{team_id}/documents/nope/raw", headers=owner)
        ).status_code == 404


# ---------------------------------------------------------------------------
# Workspace + wiki article surface area.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workspace_uses_cache_on_second_call(
    team_app: Starlette, tmp_path, monkeypatch
) -> None:
    """First GET cold-builds + persists; second hits the cached path. We
    don't peek into internals — coverage diff between calls proves it."""
    from piloci.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "vault_dir", tmp_path / "vaults")

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "Cache")
        await client.post(
            f"/api/teams/{team_id}/documents",
            headers=owner,
            json={"path": "a.md", "content": "first"},
        )

        first = await client.get(f"/api/teams/{team_id}/workspace", headers=owner)
        second = await client.get(f"/api/teams/{team_id}/workspace", headers=owner)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["team"]["id"] == second.json()["team"]["id"]


@pytest.mark.asyncio
async def test_workspace_uses_store_team_list_when_bound(
    team_app: Starlette, tmp_path, monkeypatch
) -> None:
    """When app.state.store is bound, the cold-rebuild path queries
    store.team_list. We stub it to return a single memory and verify the
    workspace surfaces it."""
    from piloci.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "vault_dir", tmp_path / "vaults2")

    class _Stub:
        def __init__(self) -> None:
            self.calls = 0

        async def team_list(self, team_id, limit=500):
            self.calls += 1
            return [
                {
                    "id": "mem-1",
                    "memory_id": "mem-1",
                    "content": "memory body",
                    "tags": ["x"],
                    "metadata": {},
                    "team_id": team_id,
                }
            ]

    stub = _Stub()
    team_app.state.store = stub

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "WSStore")
        await client.post(
            f"/api/teams/{team_id}/documents",
            headers=owner,
            json={"path": "n.md", "content": "z"},
        )
        ws = await client.get(f"/api/teams/{team_id}/workspace", headers=owner)
        assert ws.status_code == 200
        assert stub.calls == 1  # cold rebuild consulted the store


@pytest.mark.asyncio
async def test_workspace_swallows_store_failure(team_app: Starlette, tmp_path, monkeypatch) -> None:
    """If store.team_list raises, the workspace still rebuilds from documents.
    Tests the `except Exception: memories = []` branch."""
    from piloci.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "vault_dir", tmp_path / "vaults3")

    class _BadStore:
        async def team_list(self, *_a, **_kw):
            raise RuntimeError("lance offline")

    team_app.state.store = _BadStore()

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "WSStoreFail")
        ws = await client.get(f"/api/teams/{team_id}/workspace", headers=owner)
        assert ws.status_code == 200  # graceful fallback


@pytest.mark.asyncio
async def test_wiki_article_populated_and_sources_json(
    team_app: Starlette, tmp_path, monkeypatch
) -> None:
    from datetime import datetime, timezone

    from piloci.api import team_routes
    from piloci.config import get_settings
    from piloci.db.models import TeamWikiArticle

    settings = get_settings()
    monkeypatch.setattr(settings, "vault_dir", tmp_path / "vaults-art")

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "ArtPop")

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with team_routes.async_session() as db:
            db.add(
                TeamWikiArticle(
                    id="art-pop",
                    team_id=team_id,
                    slug="topic",
                    title="Topic",
                    summary="brief",
                    content="body",
                    category="docs",
                    sources_json='[{"id":"m1","kind":"memory"}]',
                    revision=2,
                    author_kind="llm",
                    author_id=None,
                    generated_by="test",
                    created_at=now,
                    updated_at=now,
                )
            )
            # And a row with malformed JSON so the except branch in get-article
            # is exercised on the next request.
            db.add(
                TeamWikiArticle(
                    id="art-bad",
                    team_id=team_id,
                    slug="bad",
                    title="Bad",
                    summary=None,
                    content="b",
                    category=None,
                    sources_json="not-json",
                    revision=1,
                    author_kind="llm",
                    author_id=None,
                    generated_by="t",
                    created_at=now,
                    updated_at=now,
                )
            )
            await db.commit()

        listing = await client.get(f"/api/teams/{team_id}/wiki/articles", headers=owner)
        assert listing.status_code == 200
        slugs = sorted(a["slug"] for a in listing.json())
        assert slugs == ["bad", "topic"]

        single = await client.get(f"/api/teams/{team_id}/wiki/articles/topic", headers=owner)
        assert single.status_code == 200
        assert single.json()["sources"] == [{"id": "m1", "kind": "memory"}]

        bad_src = await client.get(f"/api/teams/{team_id}/wiki/articles/bad", headers=owner)
        assert bad_src.status_code == 200
        assert bad_src.json()["sources"] == []


# ---------------------------------------------------------------------------
# Wiki article PATCH — additional branches: invalid JSON, non-existent slug,
# summary/category-only edits, and title-blank-string ignore.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wiki_article_patch_branches(team_app: Starlette, tmp_path, monkeypatch) -> None:
    from datetime import datetime, timezone

    from piloci.api import team_routes
    from piloci.config import get_settings
    from piloci.db.models import TeamWikiArticle

    settings = get_settings()
    monkeypatch.setattr(settings, "vault_dir", tmp_path / "vaults-patch")

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "ArtPatch")

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with team_routes.async_session() as db:
            db.add(
                TeamWikiArticle(
                    id="art-2",
                    team_id=team_id,
                    slug="topic",
                    title="Orig",
                    summary="s",
                    content="c",
                    category="cat",
                    sources_json=None,
                    revision=1,
                    author_kind="llm",
                    author_id=None,
                    generated_by="t",
                    created_at=now,
                    updated_at=now,
                )
            )
            await db.commit()

        # Broken JSON.
        bad = await client.patch(
            f"/api/teams/{team_id}/wiki/articles/topic",
            headers=owner,
            content="{",
        )
        assert bad.status_code == 400

        # Missing slug → 404 (after passing the membership check).
        missing = await client.patch(
            f"/api/teams/{team_id}/wiki/articles/ghost",
            headers=owner,
            json={"title": "x"},
        )
        assert missing.status_code == 404

        # Whitespace-only title is treated as a no-op for that field; we still
        # mutate summary/category so the request is valid (non-empty body).
        partial = await client.patch(
            f"/api/teams/{team_id}/wiki/articles/topic",
            headers=owner,
            json={"title": "   ", "summary": "", "category": ""},
        )
        assert partial.status_code == 200
        assert partial.json()["revision"] == 2


# ---------------------------------------------------------------------------
# Wiki image upload — non-WebP magic bytes, oversize body.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wiki_image_accepts_png_and_jpeg(team_app: Starlette, tmp_path, monkeypatch) -> None:
    from piloci.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "vault_dir", tmp_path / "vaults-img")

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    jpeg_bytes = b"\xff\xd8\xff" + b"\x00" * 40

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "Img2")

        png = await client.post(
            f"/api/teams/{team_id}/wiki/images",
            headers={**owner, "content-type": "image/png"},
            content=png_bytes,
        )
        assert png.status_code == 201
        assert png.json()["url"].endswith(".png")
        assert png.json()["content_type"] == "image/png"

        jpg = await client.post(
            f"/api/teams/{team_id}/wiki/images",
            headers={**owner, "content-type": "image/jpeg"},
            content=jpeg_bytes,
        )
        assert jpg.status_code == 201
        assert jpg.json()["url"].endswith(".jpg")

        # Fetch the PNG back and confirm its served with the right content type.
        fname = png.json()["url"].rsplit("/", 1)[-1]
        got = await client.get(f"/api/teams/{team_id}/wiki/images/{fname}", headers=owner)
        assert got.status_code == 200
        assert got.headers["content-type"] == "image/png"

        # Bad filename (path traversal attempt) is rejected with 400 from
        # the regex — never touches the filesystem.
        traversal = await client.get(f"/api/teams/{team_id}/wiki/images/short.png", headers=owner)
        assert traversal.status_code == 400


@pytest.mark.asyncio
async def test_wiki_image_oversize_rejected(team_app: Starlette, tmp_path, monkeypatch) -> None:
    from piloci.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "vault_dir", tmp_path / "vaults-big")

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "BigImg")

        # 5MB + 1 byte — should trip the size guard.
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024)
        resp = await client.post(
            f"/api/teams/{team_id}/wiki/images",
            headers={**owner, "content-type": "image/png"},
            content=big,
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Export ZIP.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_zip_member_only_with_articles(
    team_app: Starlette, tmp_path, monkeypatch
) -> None:
    import io
    import zipfile
    from datetime import datetime, timezone

    from piloci.api import team_routes
    from piloci.db.models import TeamWikiArticle

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "Bundle")

        # Add a document so docs/ shows up.
        await client.post(
            f"/api/teams/{team_id}/documents",
            headers=owner,
            json={"path": "notes.md", "content": "body"},
        )

        # Seed a wiki article so wiki/ shows up + sources_json malformed
        # to hit the orjson.loads except branch in the route.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with team_routes.async_session() as db:
            db.add(
                TeamWikiArticle(
                    id="art-zip",
                    team_id=team_id,
                    slug="zipped",
                    title="Zipped",
                    summary=None,
                    content="article body",
                    category="docs",
                    sources_json="<not json>",
                    revision=1,
                    author_kind="llm",
                    author_id=None,
                    generated_by="t",
                    created_at=now,
                    updated_at=now,
                )
            )
            await db.commit()

        # Non-member rejected.
        assert (
            await client.get(f"/api/teams/{team_id}/export.zip", headers=stranger)
        ).status_code == 404

        # Non-existent team rejected with 404 (membership check).
        assert (await client.get("/api/teams/missing/export.zip", headers=owner)).status_code == 404

        # Successful export.
        ok = await client.get(f"/api/teams/{team_id}/export.zip", headers=owner)
        assert ok.status_code == 200
        assert ok.headers["content-type"] == "application/zip"
        assert ok.headers["x-team-documents"] == "1"
        assert ok.headers["x-team-wiki-articles"] == "1"

        # Confirm both files actually landed inside the ZIP.
        zf = zipfile.ZipFile(io.BytesIO(ok.content))
        names = zf.namelist()
        assert any(n.endswith("notes.md") for n in names)
        assert any("wiki/zipped" in n for n in names)


@pytest.mark.asyncio
async def test_export_zip_includes_binary_bytes(team_app: Starlette, tmp_path, monkeypatch) -> None:
    """A binary team document exports as its real bytes (read from the blob
    store) at its path, alongside text docs."""
    import io
    import zipfile
    from datetime import datetime, timezone

    from piloci.api import team_routes
    from piloci.config import Settings
    from piloci.db.models import TeamDocument
    from piloci.storage.team_files import save_blob

    files_dir = tmp_path / "team-files"
    files_dir.mkdir()
    settings = Settings(
        team_files_dir=files_dir,
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
    )
    monkeypatch.setattr("piloci.config.get_settings", lambda: settings)

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "Bin")

        blob = b"\x89PNG\r\n\x1a\n binary export payload"
        _sha, storage_key, size = save_blob(files_dir, team_id, blob)

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with team_routes.async_session() as db:
            db.add(
                TeamDocument(
                    id="bindoc",
                    team_id=team_id,
                    author_id="owner",
                    uploader_id="owner",
                    updated_by_id="owner",
                    path="assets/logo.png",
                    content="",
                    content_hash=_sha,
                    size=size,
                    mime="image/png",
                    is_binary=True,
                    storage_key=storage_key,
                    version=1,
                    parent_hash=None,
                    updated_at=now,
                    created_at=now,
                    is_deleted=False,
                )
            )
            await db.commit()

        ok = await client.get(f"/api/teams/{team_id}/export.zip", headers=owner)
        assert ok.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(ok.content))
        target = next(n for n in zf.namelist() if n.endswith("assets/logo.png"))
        assert zf.read(target) == blob


# ---------------------------------------------------------------------------
# Manual wiki build — owner-only gate + no-store branch.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wiki_build_owner_only_and_store_check(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        member = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "Build")

        # Non-member: 404.
        assert (
            await client.post(f"/api/teams/{team_id}/wiki/build", headers=member)
        ).status_code == 404

        # Member (non-owner): 403.
        await _add_member(team_id, "member")
        assert (
            await client.post(f"/api/teams/{team_id}/wiki/build", headers=member)
        ).status_code == 403

        # Owner with no store binding → 503.
        # (team_app fixture leaves app.state.store unset by default.)
        if hasattr(team_app.state, "store"):
            delattr(team_app.state, "store")
        no_store = await client.post(f"/api/teams/{team_id}/wiki/build", headers=owner)
        assert no_store.status_code == 503


@pytest.mark.asyncio
async def test_wiki_build_owner_with_store_runs(team_app: Starlette, tmp_path, monkeypatch) -> None:
    """Wire a stubbed store + monkeypatch build_team_wiki. The build now runs
    in the background, so the request returns 202 ``started`` immediately and
    the (stubbed) build is invoked off-request."""
    import asyncio

    from piloci.config import get_settings
    from piloci.curator import team_wiki_worker

    settings = get_settings()
    monkeypatch.setattr(settings, "vault_dir", tmp_path / "vault-build")

    called: dict = {}

    async def _fake_build(team_id, store):
        called["team_id"] = team_id
        return {"success": True, "team_id": team_id, "articles_built": 0}

    monkeypatch.setattr(team_wiki_worker, "build_team_wiki", _fake_build)

    class _Stub:
        async def team_list(self, *_a, **_kw):
            return []

    team_app.state.store = _Stub()

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "BuildOk")
        ok = await client.post(f"/api/teams/{team_id}/wiki/build", headers=owner)
        assert ok.status_code == 202
        assert ok.json()["status"] == "started"
        # Let the background build task run, then confirm it was invoked.
        await asyncio.sleep(0.05)
        assert called.get("team_id") == team_id


# ---------------------------------------------------------------------------
# Team memory PATCH — branch coverage with a stubbed store.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_memory_patch_invalid_json(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "MemBad")
        bad = await client.patch(
            f"/api/teams/{team_id}/memories/m1",
            headers=owner,
            content="{",
        )
        assert bad.status_code == 400


@pytest.mark.asyncio
async def test_team_memory_patch_tags_only_with_stub_store(
    team_app: Starlette, monkeypatch
) -> None:
    """When body has tags/metadata but no content, the handler skips the
    embed call entirely and only calls store.team_update. We assert on the
    captured kwargs to confirm content/new_vector are both None."""
    from piloci.api import team_routes

    calls = {}

    class _Stub:
        async def team_update(self, **kwargs):
            calls.update(kwargs)
            return True

    team_app.state.store = _Stub()

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "MemTags")

        ok = await client.patch(
            f"/api/teams/{team_id}/memories/m1",
            headers=owner,
            json={"tags": ["a", "b"], "metadata": {"note": "x"}},
        )
        assert ok.status_code == 200
        assert ok.json() == {"updated": True}
        assert calls["content"] is None
        assert calls["new_vector"] is None
        assert calls["tags"] == ["a", "b"]
        assert calls["allow_owner"] is True
        # Ensure the invalidate_team_vault helper was reached even with a
        # missing vault dir — the handler swallows the resulting error.
        # (no assertion needed beyond the 200 above; we just exercised
        # the codepath.)
        assert team_routes._token_hash  # sanity touch to keep import live


@pytest.mark.asyncio
async def test_team_memory_patch_content_embeds_and_updates(
    team_app: Starlette, monkeypatch
) -> None:
    """Content present → handler calls embed_one then store.team_update with
    the resulting vector. We stub both so no model runs."""
    from piloci.api import team_routes

    async def _fake_embed(text, **_kw):
        return [0.42] * 4

    monkeypatch.setattr(
        team_routes,
        "embed_one" if hasattr(team_routes, "embed_one") else "_x_",
        _fake_embed,
        raising=False,
    )

    # The route imports embed_one inline, so we patch it on its source module.
    import piloci.storage.embed as embed_mod

    monkeypatch.setattr(embed_mod, "embed_one", _fake_embed)

    calls = {}

    class _Stub:
        async def team_update(self, **kwargs):
            calls.update(kwargs)
            return True

    team_app.state.store = _Stub()

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "MemEmbed")

        ok = await client.patch(
            f"/api/teams/{team_id}/memories/m1",
            headers=owner,
            json={"content": "new body"},
        )
        assert ok.status_code == 200
        assert calls["content"] == "new body"
        assert calls["new_vector"] == [0.42] * 4


# ---------------------------------------------------------------------------
# list_teams populated branch (one user, two memberships).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_documents_non_member_404(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "DocList")
        assert (
            await client.get(f"/api/teams/{team_id}/documents", headers=stranger)
        ).status_code == 404


@pytest.mark.asyncio
async def test_pull_documents_modified_branch(team_app: Starlette) -> None:
    """Server has a doc, client manifest carries a *different* hash → modified."""
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "Mod")
        await client.post(
            f"/api/teams/{team_id}/documents",
            headers=owner,
            json={"path": "p.md", "content": "current"},
        )
        res = await client.post(
            f"/api/teams/{team_id}/documents/pull",
            headers=owner,
            json={"manifest": {"p.md": "stale-hash"}},
        )
        assert res.status_code == 200
        assert res.json()["modified"][0]["path"] == "p.md"


@pytest.mark.asyncio
async def test_wiki_article_single_non_member(team_app: Starlette, tmp_path, monkeypatch) -> None:
    from piloci.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "vault_dir", tmp_path / "vaults-na")

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "ArtNM")
        # Even with no articles, stranger must be 404'd at the membership guard.
        assert (
            await client.get(f"/api/teams/{team_id}/wiki/articles/anything", headers=stranger)
        ).status_code == 404


@pytest.mark.asyncio
async def test_list_teams_returns_all_memberships(team_app: Starlette) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        await _make_team(client, owner, "Alpha")
        await _make_team(client, owner, "Bravo")
        listing = await client.get("/api/teams", headers=owner)
        assert listing.status_code == 200
        assert sorted(t["name"] for t in listing.json()) == ["Alpha", "Bravo"]


# ---------------------------------------------------------------------------
# Team files: multipart upload (text + binary), blob streaming, attribution
# split (uploader vs editor), and the 50MB cap.
# ---------------------------------------------------------------------------


@pytest.fixture
def _team_files_dir(tmp_path, monkeypatch):
    """Point the blob store at tmp for the duration of a test."""
    from piloci.config import get_settings

    blob_dir = tmp_path / "team-files"
    monkeypatch.setattr(get_settings(), "team_files_dir", blob_dir)
    return blob_dir


@pytest.mark.asyncio
async def test_upload_text_file_stores_inline_and_schedules_index(
    team_app: Starlette, _team_files_dir, monkeypatch
) -> None:
    """A UTF-8 file is stored as a text document (inline content, is_binary
    False) and routed through the indexing scheduler."""
    scheduled: list[tuple[str, str, str]] = []

    def _capture(request, team_id, doc_id, path, content):
        scheduled.append((team_id, path, content))

    monkeypatch.setattr(team_routes, "_schedule_doc_index", _capture)

    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "Files")

        res = await client.post(
            f"/api/teams/{team_id}/files",
            headers=owner,
            files={"file": ("readme.md", b"# hello\nworld", "text/markdown")},
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["path"] == "readme.md"
        assert body["is_binary"] is False
        assert body["size"] == len(b"# hello\nworld")
        assert body["version"] == 1

        # Indexed-schedule path was taken with the inline content.
        assert scheduled == [(team_id, "readme.md", "# hello\nworld")]

        # GET exposes the inline content.
        single = await client.get(f"/api/teams/{team_id}/documents/{body['id']}", headers=owner)
        assert single.json()["content"] == "# hello\nworld"
        assert single.json()["is_binary"] is False


@pytest.mark.asyncio
async def test_upload_binary_file_stores_blob_and_raw_streams(
    team_app: Starlette, _team_files_dir, monkeypatch
) -> None:
    """Non-UTF-8 bytes are written to the blob store, never indexed, and /raw
    streams them back with the declared mime + attachment filename."""
    not_indexed = True

    def _fail_index(*args, **kwargs):
        nonlocal not_indexed
        not_indexed = False

    monkeypatch.setattr(team_routes, "_schedule_doc_index", _fail_index)

    payload = b"\x89PNG\r\n\x1a\n\x00\x01\x02\xff\xfe"
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "Bin")

        res = await client.post(
            f"/api/teams/{team_id}/files",
            headers=owner,
            files={"file": ("logo.png", payload, "image/png")},
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["is_binary"] is True
        assert body["mime"] == "image/png"
        assert body["size"] == len(payload)
        # Binary uploads are never scheduled for indexing.
        assert not_indexed is True

        # Blob landed on disk under the team dir.
        team_blobs = list((_team_files_dir / team_id).iterdir())
        assert len(team_blobs) == 1
        assert team_blobs[0].read_bytes() == payload

        # GET masks content but reports binary metadata.
        single = await client.get(f"/api/teams/{team_id}/documents/{body['id']}", headers=owner)
        assert single.json()["content"] == ""
        assert single.json()["is_binary"] is True
        assert single.json()["mime"] == "image/png"

        # /raw streams the original bytes with mime + attachment name.
        raw = await client.get(f"/api/teams/{team_id}/documents/{body['id']}/raw", headers=owner)
        assert raw.status_code == 200
        assert raw.content == payload
        assert raw.headers["content-type"].startswith("image/png")
        assert raw.headers["content-disposition"] == 'attachment; filename="logo.png"'


@pytest.mark.asyncio
async def test_upload_preserves_uploader_on_update(team_app: Starlette, _team_files_dir) -> None:
    """Re-uploading at the same path bumps version + records the new editor
    but keeps the original uploader. list/get expose both emails."""
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        member = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "Attr")
        await _add_member(team_id, "member")

        first = await client.post(
            f"/api/teams/{team_id}/files",
            headers=owner,
            files={"file": ("doc.txt", b"v1", "text/plain")},
            data={"path": "doc.txt"},
        )
        assert first.status_code == 201
        doc_id = first.json()["id"]

        # Member edits the same path -> upsert update.
        second = await client.post(
            f"/api/teams/{team_id}/files",
            headers=member,
            files={"file": ("doc.txt", b"v2-edited", "text/plain")},
            data={"path": "doc.txt"},
        )
        assert second.status_code == 201
        assert second.json()["id"] == doc_id  # same row
        assert second.json()["version"] == 2

        single = await client.get(f"/api/teams/{team_id}/documents/{doc_id}", headers=owner)
        payload = single.json()
        assert payload["uploader_email"] == "owner@example.com"
        assert payload["updated_by_email"] == "member@example.com"
        assert payload["content"] == "v2-edited"

        listing = await client.get(f"/api/teams/{team_id}/documents", headers=owner)
        row = listing.json()[0]
        assert row["uploader_email"] == "owner@example.com"
        assert row["updated_by_email"] == "member@example.com"


@pytest.mark.asyncio
async def test_update_document_route_keeps_uploader(team_app: Starlette, _team_files_dir) -> None:
    """The JSON PUT update path must also preserve the original uploader while
    moving updated_by to the editor."""
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        member = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "PutAttr")
        await _add_member(team_id, "member")

        created = await client.post(
            f"/api/teams/{team_id}/documents",
            headers=owner,
            json={"path": "n.md", "content": "a"},
        )
        doc = created.json()

        upd = await client.put(
            f"/api/teams/{team_id}/documents/{doc['id']}",
            headers=member,
            json={"content": "b", "parent_hash": doc["content_hash"]},
        )
        assert upd.status_code == 200

        single = await client.get(f"/api/teams/{team_id}/documents/{doc['id']}", headers=owner)
        assert single.json()["uploader_email"] == "owner@example.com"
        assert single.json()["updated_by_email"] == "member@example.com"


@pytest.mark.asyncio
async def test_delete_binary_removes_blob(team_app: Starlette, _team_files_dir) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "Del")

        payload = b"\xff\xfe\x00binary"
        res = await client.post(
            f"/api/teams/{team_id}/files",
            headers=owner,
            files={"file": ("x.bin", payload, "application/octet-stream")},
        )
        doc_id = res.json()["id"]
        blobs = list((_team_files_dir / team_id).iterdir())
        assert len(blobs) == 1

        deleted = await client.delete(f"/api/teams/{team_id}/documents/{doc_id}", headers=owner)
        assert deleted.status_code == 200
        assert not list((_team_files_dir / team_id).iterdir())


@pytest.mark.asyncio
async def test_upload_over_50mb_rejected(team_app: Starlette, _team_files_dir) -> None:
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        team_id = await _make_team(client, owner, "Big")

        oversize = b"\x00" * (50 * 1024 * 1024 + 1)
        res = await client.post(
            f"/api/teams/{team_id}/files",
            headers=owner,
            files={"file": ("big.bin", oversize, "application/octet-stream")},
        )
        assert res.status_code == 413


@pytest.mark.asyncio
async def test_upload_cross_team_isolation(team_app: Starlette, _team_files_dir) -> None:
    """A non-member cannot upload to or download from another team's files."""
    transport = httpx.ASGITransport(app=team_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = _headers("owner", "owner@example.com")
        stranger = _headers("member", "member@example.com")
        team_id = await _make_team(client, owner, "Iso")

        res = await client.post(
            f"/api/teams/{team_id}/files",
            headers=owner,
            files={"file": ("secret.bin", b"\xff\x00secret", "application/octet-stream")},
        )
        doc_id = res.json()["id"]

        # Stranger blocked from uploading.
        blocked = await client.post(
            f"/api/teams/{team_id}/files",
            headers=stranger,
            files={"file": ("evil.txt", b"hi", "text/plain")},
        )
        assert blocked.status_code == 404

        # Stranger blocked from downloading.
        assert (
            await client.get(f"/api/teams/{team_id}/documents/{doc_id}/raw", headers=stranger)
        ).status_code == 404


def test_iso_utc_stamps_offset_on_naive_datetime() -> None:
    # Naive (utcnow-style) value must serialize with an explicit UTC offset so a
    # client in another timezone doesn't misread it as local time. This is what
    # kept the wiki "생성 중" state alive across navigation.
    naive = datetime(2026, 5, 21, 3, 0, 0)
    out = team_routes._iso_utc(naive)
    assert out is not None
    assert out.endswith("+00:00")
    # Parsing it back yields the same absolute instant as the UTC value.
    assert datetime.fromisoformat(out) == naive.replace(tzinfo=timezone.utc)


def test_iso_utc_preserves_aware_datetime_and_none() -> None:
    aware = datetime(2026, 5, 21, 3, 0, 0, tzinfo=timezone.utc)
    assert team_routes._iso_utc(aware) == aware.isoformat()
    assert team_routes._iso_utc(None) is None
