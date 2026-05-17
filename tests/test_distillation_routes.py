import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import orjson
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from piloci.api import distillation_routes
from piloci.db.models import User, WeeklyDigest
from piloci.db.session import init_db


def _request(user=None, *, query: dict | None = None, app_state=None):
    req = SimpleNamespace(
        state=SimpleNamespace(user=user),
        query_params=query or {},
        app=SimpleNamespace(state=app_state or SimpleNamespace(store=None, instincts_store=None)),
    )
    return req


def test_require_user_and_uid_helpers_handle_session_shapes() -> None:
    assert distillation_routes._require_user(_request()) is None
    assert distillation_routes._require_user(_request({"user_id": "user-1"})) == {
        "user_id": "user-1"
    }
    assert distillation_routes._uid({"user_id": "user-1", "id": "fallback"}) == "user-1"
    assert distillation_routes._uid({"id": 42}) == "42"
    assert distillation_routes._uid({}) == ""


def test_next_idle_window_returns_none_for_unset_or_invalid_specs() -> None:
    now = datetime(2026, 5, 15, 13, 0)

    assert distillation_routes._next_idle_window(now, None) is None
    assert distillation_routes._next_idle_window(now, "not-a-window") is None


def test_next_idle_window_uses_today_or_tomorrow_start() -> None:
    before_window = datetime(2026, 5, 15, 1, 30)
    after_window = datetime(2026, 5, 15, 4, 0)

    assert distillation_routes._next_idle_window(before_window, "02:00-03:00") == datetime(
        2026, 5, 15, 2, 0
    )
    assert distillation_routes._next_idle_window(after_window, "02:00-03:00") == datetime(
        2026, 5, 16, 2, 0
    )


@pytest.mark.asyncio
async def test_distillation_status_rejects_unauthenticated_request() -> None:
    response = await distillation_routes.route_distillation_status(_request())

    assert response.status_code == 401
    assert orjson.loads(response.body) == {"error": "unauthorized"}


# ---------------------------------------------------------------------------
# Weekly digest routes
# ---------------------------------------------------------------------------


def test_parse_week_query_snaps_to_monday() -> None:
    # Thu 2026-05-14 → Mon 2026-05-11
    assert distillation_routes._parse_week_query("2026-05-14") == date(2026, 5, 11)
    # Mon stays Mon
    assert distillation_routes._parse_week_query("2026-05-11") == date(2026, 5, 11)
    # Empty / invalid → None (handler turns invalid into 400)
    assert distillation_routes._parse_week_query(None) is None
    assert distillation_routes._parse_week_query("garbage") is None
    assert distillation_routes._parse_week_query("") is None


@pytest.fixture
async def isolated_db(monkeypatch):
    """Bind distillation_routes.async_session to a fresh in-memory DB so
    digest route handlers read/write a real WeeklyDigest row.
    """
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_db(engine=eng)
    factory = async_sessionmaker(
        bind=eng, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        async with factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    monkeypatch.setattr(distillation_routes, "async_session", fake_session)
    yield factory
    await eng.dispose()


async def _seed_user(factory) -> str:
    async with factory() as sess:
        user = User(
            id=str(uuid.uuid4()),
            email=f"u-{uuid.uuid4().hex[:6]}@x.com",
            password_hash="$argon2id$x",
            created_at=datetime.now(timezone.utc),
        )
        sess.add(user)
        await sess.commit()
        return user.id


async def _seed_digest(factory, user_id: str, week_start: date, summary: str) -> None:
    async with factory() as sess:
        sess.add(
            WeeklyDigest(
                digest_id=str(uuid.uuid4()),
                user_id=user_id,
                week_start=week_start,
                summary_text=summary,
                stats_json='{"sessions": 3}',
                generated_at=datetime.now(timezone.utc),
            )
        )
        await sess.commit()


@pytest.mark.asyncio
async def test_weekly_digest_get_requires_auth() -> None:
    resp = await distillation_routes.route_weekly_digest_get(_request())
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_weekly_digest_get_returns_null_when_no_rows(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    resp = await distillation_routes.route_weekly_digest_get(_request({"user_id": user_id}))
    assert resp.status_code == 200
    assert orjson.loads(resp.body) == {"digest": None}


@pytest.mark.asyncio
async def test_weekly_digest_get_returns_latest_by_default(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    await _seed_digest(isolated_db, user_id, date(2026, 4, 27), "older")
    await _seed_digest(isolated_db, user_id, date(2026, 5, 4), "newer")

    resp = await distillation_routes.route_weekly_digest_get(_request({"user_id": user_id}))
    assert resp.status_code == 200
    body = orjson.loads(resp.body)
    assert body["digest"]["summary"] == "newer"
    assert body["digest"]["week_start"] == "2026-05-04"
    assert body["digest"]["stats"] == {"sessions": 3}


@pytest.mark.asyncio
async def test_weekly_digest_get_with_week_404s_when_missing(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    await _seed_digest(isolated_db, user_id, date(2026, 5, 4), "newer")

    resp = await distillation_routes.route_weekly_digest_get(
        _request({"user_id": user_id}, query={"week": "2026-01-05"})
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_weekly_digest_get_never_returns_other_users_row(isolated_db) -> None:
    """Privacy non-negotiable — feedback memories surface here only for the owner."""
    alice = await _seed_user(isolated_db)
    bob = await _seed_user(isolated_db)
    await _seed_digest(isolated_db, alice, date(2026, 5, 4), "alice secret")

    # Bob asks → must not see alice's digest, even though bob has no row.
    resp = await distillation_routes.route_weekly_digest_get(_request({"user_id": bob}))
    assert resp.status_code == 200
    assert orjson.loads(resp.body) == {"digest": None}


@pytest.mark.asyncio
async def test_weekly_digest_get_rejects_bad_week_format() -> None:
    resp = await distillation_routes.route_weekly_digest_get(
        _request({"user_id": "u1"}, query={"week": "not-a-date"})
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_weekly_digest_regenerate_returns_503_when_stores_missing() -> None:
    resp = await distillation_routes.route_weekly_digest_regenerate(_request({"user_id": "u1"}))
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_weekly_digest_regenerate_writes_and_returns_row(isolated_db, monkeypatch) -> None:
    user_id = await _seed_user(isolated_db)

    # Stub the generator so we don't run the Gemma round-trip; assert it was
    # invoked with force=True and that the route reads back the persisted row.
    async def fake_generate(uid, week, settings, memory_store, instincts_store, *, force):
        assert uid == user_id
        assert force is True
        await _seed_digest(isolated_db, user_id, week, "regen-ok")
        return True

    monkeypatch.setattr(distillation_routes._digest_mod, "generate_for_user", fake_generate)

    app_state = SimpleNamespace(store=AsyncMock(), instincts_store=AsyncMock())
    resp = await distillation_routes.route_weekly_digest_regenerate(
        _request({"user_id": user_id}, app_state=app_state)
    )
    assert resp.status_code == 202
    body = orjson.loads(resp.body)
    assert body["digest"]["summary"] == "regen-ok"


@pytest.mark.asyncio
async def test_weekly_digest_regenerate_reports_no_activity(isolated_db, monkeypatch) -> None:
    user_id = await _seed_user(isolated_db)

    async def fake_generate(*args, **kwargs):
        return False

    monkeypatch.setattr(distillation_routes._digest_mod, "generate_for_user", fake_generate)

    app_state = SimpleNamespace(store=AsyncMock(), instincts_store=AsyncMock())
    resp = await distillation_routes.route_weekly_digest_regenerate(
        _request({"user_id": user_id}, app_state=app_state)
    )
    assert resp.status_code == 200
    body = orjson.loads(resp.body)
    assert body["digest"] is None
    assert "no activity" in body["note"]
