from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import orjson
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from piloci.db.models import Project, RawSession, User
from piloci.db.session import init_db
from piloci.ops import backfill


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _transcript(cwds: list[str]) -> str:
    """Synthesize a Claude Code-style transcript whose entries advertise ``cwds``."""
    entries: list[dict] = [{"type": "summary"}]
    for c in cwds:
        entries.append({"type": "user", "cwd": c})
    return orjson.dumps(entries).decode()


@pytest.fixture
async def factory(monkeypatch, tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'backfill.db'}"
    eng: AsyncEngine = create_async_engine(
        database_url, echo=False, connect_args={"check_same_thread": False}
    )
    await init_db(engine=eng)

    sm = async_sessionmaker(
        bind=eng, class_=AsyncSession, expire_on_commit=False, autoflush=False, autocommit=False
    )

    @asynccontextmanager
    async def _test_async_session() -> AsyncGenerator[AsyncSession, None]:
        async with sm() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    monkeypatch.setattr(backfill, "async_session", _test_async_session)
    try:
        yield sm
    finally:
        await eng.dispose()


async def _add(sm, *objs):
    async with sm() as db:
        for o in objs:
            db.add(o)
        await db.commit()


@pytest.mark.asyncio
async def test_backfill_stamps_majority_cwd_when_no_split(factory):
    user = User(
        id="u1",
        email="a@b.c",
        password_hash="x",
        created_at=_now(),
    )
    project = Project(
        id="p1",
        user_id="u1",
        slug="foo",
        name="foo",
        cwd=None,
        created_at=_now(),
        updated_at=_now(),
    )
    sessions = [
        RawSession(
            ingest_id=str(uuid.uuid4()),
            user_id="u1",
            project_id="p1",
            client="claude-code",
            transcript_json=_transcript(["/work/foo"]),
            created_at=_now(),
        )
        for _ in range(2)
    ]
    await _add(factory, user, project, *sessions)

    report = await backfill.backfill_cwd()

    assert report["projects_examined"] == 1
    assert report["projects_stamped"] == 1
    assert report["projects_split"] == 0
    assert report["new_projects"] == 0
    assert report["sessions_moved"] == 0

    async with factory() as db:
        live = (await db.execute(select(Project).where(Project.id == "p1"))).scalar_one()
        assert live.cwd == "/work/foo"


@pytest.mark.asyncio
async def test_backfill_splits_minority_cwd(factory):
    user = User(
        id="u1",
        email="a@b.c",
        password_hash="x",
        created_at=_now(),
    )
    project = Project(
        id="p1",
        user_id="u1",
        slug="foo",
        name="foo",
        cwd=None,
        created_at=_now(),
        updated_at=_now(),
    )
    majority = [
        RawSession(
            ingest_id=str(uuid.uuid4()),
            user_id="u1",
            project_id="p1",
            client="claude-code",
            transcript_json=_transcript(["/code/foo"]),
            created_at=_now(),
        )
        for _ in range(3)
    ]
    minority = [
        RawSession(
            ingest_id=str(uuid.uuid4()),
            user_id="u1",
            project_id="p1",
            client="claude-code",
            transcript_json=_transcript(["/work/foo"]),
            created_at=_now(),
        )
    ]
    moved_ids = {s.ingest_id for s in minority}
    await _add(factory, user, project, *majority, *minority)

    report = await backfill.backfill_cwd()

    assert report["projects_split"] == 1
    assert report["new_projects"] == 1
    assert report["sessions_moved"] == 1

    async with factory() as db:
        live = (await db.execute(select(Project).where(Project.id == "p1"))).scalar_one()
        assert live.cwd == "/code/foo"
        assert live.slug == "foo"

        new_proj = (
            await db.execute(select(Project).where(Project.cwd == "/work/foo"))
        ).scalar_one()
        assert new_proj.id != "p1"
        assert new_proj.slug.startswith("foo")

        moved = (
            (await db.execute(select(RawSession).where(RawSession.ingest_id.in_(list(moved_ids)))))
            .scalars()
            .all()
        )
        assert all(s.project_id == new_proj.id for s in moved)


@pytest.mark.asyncio
async def test_backfill_skips_projects_with_cwd_already_set(factory):
    user = User(
        id="u1",
        email="a@b.c",
        password_hash="x",
        created_at=_now(),
    )
    project = Project(
        id="p1",
        user_id="u1",
        slug="foo",
        name="foo",
        cwd="/already/set",
        created_at=_now(),
        updated_at=_now(),
    )
    await _add(factory, user, project)

    report = await backfill.backfill_cwd()
    assert report["projects_examined"] == 0


@pytest.mark.asyncio
async def test_backfill_dry_run_makes_no_writes(factory):
    user = User(
        id="u1",
        email="a@b.c",
        password_hash="x",
        created_at=_now(),
    )
    project = Project(
        id="p1",
        user_id="u1",
        slug="foo",
        name="foo",
        cwd=None,
        created_at=_now(),
        updated_at=_now(),
    )
    sess = RawSession(
        ingest_id=str(uuid.uuid4()),
        user_id="u1",
        project_id="p1",
        client="claude-code",
        transcript_json=_transcript(["/code/foo"]),
        created_at=_now(),
    )
    await _add(factory, user, project, sess)

    report = await backfill.backfill_cwd(dry_run=True)
    assert report["projects_stamped"] == 1

    async with factory() as db:
        live = (await db.execute(select(Project).where(Project.id == "p1"))).scalar_one()
        assert live.cwd is None
