from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from piloci.curator.weekly_digest_worker import (
    WeeklyStats,
    _fallback_summary,
    _format_top_projects,
    aggregate_week_for_user,
    digest_exists,
    generate_for_user,
    previous_week_start,
    render_summary,
    upsert_digest,
    week_bounds_utc,
)
from piloci.db.models import Project, RawSession, User, WeeklyDigest
from piloci.db.session import init_db

# ---------------------------------------------------------------------------
# Fixtures — in-memory DB
# ---------------------------------------------------------------------------


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_db(engine=eng)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine) -> AsyncSession:
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    async with factory() as sess:
        yield sess


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _make_user(db: AsyncSession, *, email: str = "u@example.com") -> User:
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        password_hash="$argon2id$x",
        created_at=_now(),
    )
    db.add(user)
    await db.flush()
    return user


async def _make_project(db: AsyncSession, *, user_id: str, name: str) -> Project:
    proj = Project(
        id=str(uuid.uuid4()),
        user_id=user_id,
        slug=name.lower(),
        name=name,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(proj)
    await db.flush()
    return proj


async def _make_session(
    db: AsyncSession,
    *,
    user_id: str,
    project_id: str | None,
    created_at: datetime,
) -> RawSession:
    row = RawSession(
        ingest_id=str(uuid.uuid4()),
        user_id=user_id,
        project_id=project_id,
        client="claude-code",
        transcript_json="{}",
        created_at=created_at,
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# Week math
# ---------------------------------------------------------------------------


def test_previous_week_start_from_midweek():
    # Thursday → Monday of the previous week
    thu = date(2026, 5, 14)  # Thu
    assert previous_week_start(thu) == date(2026, 5, 4)


def test_previous_week_start_from_monday():
    # Mon → previous Mon (today's week is in-progress, so we cover last week)
    mon = date(2026, 5, 18)
    assert previous_week_start(mon) == date(2026, 5, 11)


def test_previous_week_start_from_sunday():
    sun = date(2026, 5, 17)
    assert previous_week_start(sun) == date(2026, 5, 4)


def test_week_bounds_utc_is_half_open_seven_days():
    week_start = date(2026, 5, 4)
    start, end = week_bounds_utc(week_start)
    assert start == datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 5, 11, 0, 0, tzinfo=timezone.utc)
    assert end - start == timedelta(days=7)


# ---------------------------------------------------------------------------
# Aggregation — exercises DB queries against real (in-memory) SQLite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate_zero_activity(db):
    user = await _make_user(db)
    memory_store = AsyncMock()
    instincts_store = AsyncMock()
    memory_store.list.return_value = []
    instincts_store.list_instincts.return_value = []

    stats = await aggregate_week_for_user(
        db, memory_store, instincts_store, user.id, date(2026, 5, 4)
    )
    assert stats.sessions == 0
    assert stats.feedback_count == 0
    assert stats.reaction_count == 0
    assert stats.top_projects == []


@pytest.mark.asyncio
async def test_aggregate_counts_sessions_in_week_only(db):
    user = await _make_user(db)
    proj_a = await _make_project(db, user_id=user.id, name="alpha")
    proj_b = await _make_project(db, user_id=user.id, name="bravo")

    week_start = date(2026, 5, 4)
    inside_a = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
    inside_b = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    before_window = datetime(2026, 5, 3, 23, 0, tzinfo=timezone.utc)
    after_window = datetime(2026, 5, 11, 0, 1, tzinfo=timezone.utc)

    await _make_session(db, user_id=user.id, project_id=proj_a.id, created_at=inside_a)
    await _make_session(db, user_id=user.id, project_id=proj_a.id, created_at=inside_b)
    await _make_session(db, user_id=user.id, project_id=proj_b.id, created_at=inside_b)
    await _make_session(db, user_id=user.id, project_id=proj_a.id, created_at=before_window)
    await _make_session(db, user_id=user.id, project_id=proj_a.id, created_at=after_window)
    await db.flush()

    memory_store = AsyncMock()
    instincts_store = AsyncMock()
    memory_store.list.return_value = []
    instincts_store.list_instincts.return_value = []

    stats = await aggregate_week_for_user(db, memory_store, instincts_store, user.id, week_start)

    # Only the 3 in-window sessions count, split alpha=2 / bravo=1
    assert stats.sessions == 3
    names = dict(stats.top_projects)
    assert names == {"alpha": 2, "bravo": 1}


@pytest.mark.asyncio
async def test_aggregate_pulls_only_feedback_memories_in_window(db):
    user = await _make_user(db)
    proj = await _make_project(db, user_id=user.id, name="alpha")
    week_start = date(2026, 5, 4)
    in_week = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    await _make_session(db, user_id=user.id, project_id=proj.id, created_at=in_week)
    await db.flush()

    week_start_unix = int(datetime.combine(week_start, time.min, tzinfo=timezone.utc).timestamp())

    memory_store = AsyncMock()
    memory_store.list.return_value = [
        # Feedback inside the week — should be picked.
        {
            "content": "씨발 또 빌드 깨졌어",
            "metadata": {"category": "feedback"},
            "created_at": week_start_unix + 3600,
        },
        # Coding fact inside the week — should be skipped (not private).
        {
            "content": "uses argon2id",
            "metadata": {"category": "preference"},
            "created_at": week_start_unix + 7200,
        },
        # Feedback outside the week — should be skipped.
        {
            "content": "지난주 회고",
            "metadata": {"category": "feedback"},
            "created_at": week_start_unix - 86400,
        },
    ]
    instincts_store = AsyncMock()
    instincts_store.list_instincts.return_value = [
        {
            "trigger": "빌드 실패",
            "action": "사용자 짜증",
            "updated_at": week_start_unix + 1800,
        },
    ]

    stats = await aggregate_week_for_user(db, memory_store, instincts_store, user.id, week_start)
    assert stats.feedback_excerpts == ["씨발 또 빌드 깨졌어"]
    assert stats.feedback_count == 1
    assert stats.reaction_excerpts == ["빌드 실패 → 사용자 짜증"]
    assert stats.reaction_count == 1


# ---------------------------------------------------------------------------
# Summary rendering
# ---------------------------------------------------------------------------


def test_format_top_projects_empty():
    assert _format_top_projects([]) == "없음"


def test_format_top_projects_orders_given():
    assert _format_top_projects([("alpha", 4), ("bravo", 2)]) == "alpha(4), bravo(2)"


def test_fallback_summary_zero_sessions_is_friendly():
    stats = WeeklyStats(
        sessions=0,
        feedback_count=0,
        reaction_count=0,
        top_projects=[],
        feedback_excerpts=[],
        reaction_excerpts=[],
    )
    text = _fallback_summary(stats)
    assert "활동이 거의 없었습니다" in text


def test_fallback_summary_with_activity_mentions_stats():
    stats = WeeklyStats(
        sessions=12,
        feedback_count=3,
        reaction_count=1,
        top_projects=[("piloci", 9)],
        feedback_excerpts=["짜증"],
        reaction_excerpts=["빌드 실패 → 짜증"],
    )
    text = _fallback_summary(stats)
    assert "12건" in text
    assert "piloci" in text


@pytest.mark.asyncio
async def test_render_summary_returns_summary_field_from_llm(monkeypatch):
    mock_chat = AsyncMock(return_value={"summary": "이번 주 수고했어요"})
    monkeypatch.setattr("piloci.curator.weekly_digest_worker.chat_json", mock_chat)
    settings = MagicMock(gemma_endpoint="x", gemma_model="gemma")
    stats = WeeklyStats(
        sessions=5,
        feedback_count=0,
        reaction_count=0,
        top_projects=[("alpha", 5)],
        feedback_excerpts=[],
        reaction_excerpts=[],
    )
    out = await render_summary(stats, settings)
    assert out == "이번 주 수고했어요"


@pytest.mark.asyncio
async def test_render_summary_falls_back_when_llm_raises(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("LLM offline")

    monkeypatch.setattr("piloci.curator.weekly_digest_worker.chat_json", boom)
    settings = MagicMock(gemma_endpoint="x", gemma_model="gemma")
    stats = WeeklyStats(
        sessions=3,
        feedback_count=1,
        reaction_count=0,
        top_projects=[("alpha", 3)],
        feedback_excerpts=["x"],
        reaction_excerpts=[],
    )
    out = await render_summary(stats, settings)
    assert "3건" in out  # fallback summary, not the LLM payload


@pytest.mark.asyncio
async def test_render_summary_falls_back_on_non_string_summary(monkeypatch):
    mock_chat = AsyncMock(return_value={"summary": None})
    monkeypatch.setattr("piloci.curator.weekly_digest_worker.chat_json", mock_chat)
    settings = MagicMock(gemma_endpoint="x", gemma_model="gemma")
    stats = WeeklyStats(
        sessions=1,
        feedback_count=0,
        reaction_count=0,
        top_projects=[("a", 1)],
        feedback_excerpts=[],
        reaction_excerpts=[],
    )
    out = await render_summary(stats, settings)
    assert "1건" in out


# ---------------------------------------------------------------------------
# Upsert + digest_exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_inserts_then_updates(db):
    user = await _make_user(db)
    await db.flush()

    week = date(2026, 5, 4)
    stats = WeeklyStats(
        sessions=1,
        feedback_count=0,
        reaction_count=0,
        top_projects=[],
        feedback_excerpts=[],
        reaction_excerpts=[],
    )
    await upsert_digest(db, user_id=user.id, week_start=week, summary="v1", stats=stats)
    assert await digest_exists(db, user.id, week) is True

    # Second call should overwrite the summary, not insert a duplicate row.
    await upsert_digest(db, user_id=user.id, week_start=week, summary="v2", stats=stats)
    rows = (
        await db.execute(WeeklyDigest.__table__.select().where(WeeklyDigest.user_id == user.id))
    ).all()
    assert len(rows) == 1
    assert rows[0].summary_text == "v2"


# ---------------------------------------------------------------------------
# generate_for_user — end-to-end glue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_for_user_skips_when_no_activity(monkeypatch, db):
    # Bind the worker's module-level async_session to our in-memory db.
    user = await _make_user(db)
    await db.commit()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield db
        await db.flush()

    monkeypatch.setattr("piloci.curator.weekly_digest_worker.async_session", fake_session)

    memory_store = AsyncMock()
    memory_store.list.return_value = []
    instincts_store = AsyncMock()
    instincts_store.list_instincts.return_value = []
    settings = MagicMock(gemma_endpoint="x", gemma_model="gemma")

    wrote = await generate_for_user(
        user.id, date(2026, 5, 4), settings, memory_store, instincts_store
    )
    assert wrote is False


@pytest.mark.asyncio
async def test_generate_for_user_writes_when_active(monkeypatch, db):
    user = await _make_user(db)
    proj = await _make_project(db, user_id=user.id, name="alpha")
    await _make_session(
        db,
        user_id=user.id,
        project_id=proj.id,
        created_at=datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
    )
    await db.commit()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield db
        await db.flush()

    monkeypatch.setattr("piloci.curator.weekly_digest_worker.async_session", fake_session)

    memory_store = AsyncMock()
    memory_store.list.return_value = []
    instincts_store = AsyncMock()
    instincts_store.list_instincts.return_value = []

    mock_chat = AsyncMock(return_value={"summary": "한 주 잘 보냈어요"})
    monkeypatch.setattr("piloci.curator.weekly_digest_worker.chat_json", mock_chat)
    settings = MagicMock(gemma_endpoint="x", gemma_model="gemma")

    wrote = await generate_for_user(
        user.id, date(2026, 5, 4), settings, memory_store, instincts_store
    )
    assert wrote is True
    assert await digest_exists(db, user.id, date(2026, 5, 4)) is True

    # Second call without force should detect the existing row and skip.
    mock_chat.reset_mock()
    wrote_again = await generate_for_user(
        user.id, date(2026, 5, 4), settings, memory_store, instincts_store
    )
    assert wrote_again is False
    mock_chat.assert_not_called()
