from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from piloci.curator.backlog import archive_overflow, count_pending, enforce_ceiling_after_ingest
from piloci.db.models import Base, RawSession, User


@pytest.fixture
async def session_factory(tmp_path):
    db_path = tmp_path / "backlog.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed(factory, user_id: str = "u1") -> None:
    async with factory() as db:
        db.add(User(id=user_id, email=f"{user_id}@test", created_at=datetime.now(timezone.utc)))
        await db.commit()


async def _add_pending(
    factory,
    *,
    n: int,
    user_id: str = "u1",
    minutes_back_start: int = 0,
    priority: int = 0,
) -> None:
    base = datetime.now(timezone.utc) - timedelta(minutes=minutes_back_start)
    async with factory() as db:
        for i in range(n):
            db.add(
                RawSession(
                    ingest_id=f"row-{minutes_back_start}-{i}",
                    user_id=user_id,
                    project_id="p1",
                    client="test",
                    transcript_json="{}",
                    created_at=base - timedelta(seconds=i),
                    distillation_state="pending",
                    priority=priority,
                )
            )
        await db.commit()


@pytest.mark.asyncio
async def test_count_pending_zero_initially(session_factory) -> None:
    await _seed(session_factory)
    async with session_factory() as db:
        assert await count_pending(db) == 0


@pytest.mark.asyncio
async def test_count_pending_user_scoped(session_factory) -> None:
    await _seed(session_factory, "u1")
    await _seed(session_factory, "u2")
    await _add_pending(session_factory, n=3, user_id="u1")
    await _add_pending(session_factory, n=5, user_id="u2", minutes_back_start=10)
    async with session_factory() as db:
        assert await count_pending(db) == 8
        assert await count_pending(db, user_id="u1") == 3
        assert await count_pending(db, user_id="u2") == 5


@pytest.mark.asyncio
async def test_archive_noop_when_under_cap(session_factory) -> None:
    await _seed(session_factory)
    await _add_pending(session_factory, n=3)
    async with session_factory() as db:
        archived = await archive_overflow(db, max_pending=10)
        await db.commit()
    assert archived == 0


@pytest.mark.asyncio
async def test_archive_drops_oldest_first(session_factory) -> None:
    await _seed(session_factory)
    # 5 rows, oldest first
    await _add_pending(session_factory, n=5, minutes_back_start=100)
    # 3 newer rows
    await _add_pending(session_factory, n=3, minutes_back_start=10)
    async with session_factory() as db:
        archived = await archive_overflow(db, max_pending=4)
        await db.commit()
    assert archived == 4

    async with session_factory() as db:
        states = (
            await db.execute(select(RawSession.ingest_id, RawSession.distillation_state))
        ).all()
    state_map = {ingest_id: state for ingest_id, state in states}
    archived_ids = [k for k, v in state_map.items() if v == "archived"]
    pending_ids = [k for k, v in state_map.items() if v == "pending"]
    assert len(archived_ids) == 4
    assert len(pending_ids) == 4
    # All archived should be from the older batch (minutes_back_start=100).
    assert all(k.startswith("row-100-") for k in archived_ids)


@pytest.mark.asyncio
async def test_archive_respects_priority(session_factory) -> None:
    await _seed(session_factory)
    # 5 oldest rows but high priority — should survive.
    await _add_pending(session_factory, n=5, minutes_back_start=100, priority=10)
    # 5 newer rows, normal priority.
    await _add_pending(session_factory, n=5, minutes_back_start=5, priority=0)
    async with session_factory() as db:
        archived = await archive_overflow(db, max_pending=5)
        await db.commit()
    assert archived == 5

    async with session_factory() as db:
        archived_rows = (
            (
                await db.execute(
                    select(RawSession.ingest_id).where(RawSession.distillation_state == "archived")
                )
            )
            .scalars()
            .all()
        )
    # The 5 archived should be the lower-priority newer rows.
    assert all(r.startswith("row-5-") for r in archived_rows)


@pytest.mark.asyncio
async def test_enforce_ceiling_after_ingest_calls_archive(session_factory) -> None:
    await _seed(session_factory)
    await _add_pending(session_factory, n=10)
    async with session_factory() as db:
        archived = await enforce_ceiling_after_ingest(db, max_pending=6)
        await db.commit()
    assert archived == 4
