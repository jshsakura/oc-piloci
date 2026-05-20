import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import orjson
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from piloci.api import distillation_routes
from piloci.db.models import (
    ExternalLLMUsage,
    Project,
    RawSession,
    User,
    UserPreferences,
    WeeklyDigest,
)
from piloci.db.session import init_db


def _request(
    user=None,
    *,
    query: dict | None = None,
    app_state=None,
    path_params: dict | None = None,
    body: bytes | None = None,
):
    async def _body():
        return body if body is not None else b""

    req = SimpleNamespace(
        state=SimpleNamespace(user=user),
        query_params=query or {},
        path_params=path_params or {},
        body=_body,
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


# ---------------------------------------------------------------------------
# /api/distillation/status — lazy-pipeline observability (5 dims)
# ---------------------------------------------------------------------------


async def _seed_raw_session(
    factory,
    *,
    user_id: str,
    state: str,
    created_at: datetime,
    processed_at: datetime | None = None,
    project_id: str | None = None,
    memories: int = 0,
    instincts: int = 0,
    path: str | None = None,
) -> str:
    async with factory() as sess:
        row = RawSession(
            ingest_id=str(uuid.uuid4()),
            user_id=user_id,
            project_id=project_id,
            client="claude-code",
            transcript_json="{}",
            created_at=created_at,
            processed_at=processed_at,
            memories_extracted=memories,
            instincts_extracted=instincts,
            distillation_state=state,
            processing_path=path,
        )
        sess.add(row)
        await sess.commit()
        return row.ingest_id


@pytest.mark.asyncio
async def test_distillation_status_returns_shape_with_no_sessions(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    resp = await distillation_routes.route_distillation_status(_request({"user_id": user_id}))

    assert resp.status_code == 200
    body = orjson.loads(resp.body)
    # 5 observability dims must all be present so the dashboard never KeyErrors.
    assert set(body["counts"].keys()) == {
        "pending",
        "distilled",
        "filtered",
        "failed",
        "archived",
    }
    assert body["counts"]["pending"] == 0
    assert body["lag"]["oldest_pending_at"] is None
    assert body["lag"]["seconds_behind"] is None
    assert body["lag"]["sustained_busy_minutes"] is None
    assert body["throughput"]["last_1h"] == {"sessions": 0, "memories": 0, "instincts": 0}
    assert body["throughput"]["last_24h"] == {"sessions": 0, "memories": 0, "instincts": 0}
    assert body["throughput"]["eta_drain_minutes"] is None
    assert body["processing_path_30d"] == {}
    assert "max_pending_backlog" in body["thresholds"]
    assert "cpu_temp_c" in body["current"]
    assert "idle_window" in body["schedule"]
    assert "enabled" in body


@pytest.mark.asyncio
async def test_distillation_status_aggregates_state_lag_throughput_and_paths(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    now = datetime.now(timezone.utc)
    old_pending = now - timedelta(hours=3)
    recent_distill = now - timedelta(minutes=10)
    older_distill = now - timedelta(hours=12)

    # pending (oldest) → drives lag + sustained_busy_minutes
    await _seed_raw_session(isolated_db, user_id=user_id, state="pending", created_at=old_pending)
    # distilled within 1h → 1h+24h throughput, local path
    await _seed_raw_session(
        isolated_db,
        user_id=user_id,
        state="distilled",
        created_at=recent_distill - timedelta(seconds=5),
        processed_at=recent_distill,
        memories=4,
        instincts=2,
        path="local",
    )
    # distilled within 24h but not 1h → 24h-only, external path
    await _seed_raw_session(
        isolated_db,
        user_id=user_id,
        state="distilled",
        created_at=older_distill - timedelta(seconds=5),
        processed_at=older_distill,
        memories=3,
        instincts=1,
        path="external",
    )
    # filtered + failed → state counts (no LLM, prefilter/backlog respected)
    await _seed_raw_session(isolated_db, user_id=user_id, state="filtered", created_at=now)
    await _seed_raw_session(
        isolated_db, user_id=user_id, state="failed", created_at=now, processed_at=now
    )

    resp = await distillation_routes.route_distillation_status(_request({"user_id": user_id}))
    body = orjson.loads(resp.body)

    assert body["counts"]["pending"] == 1
    assert body["counts"]["distilled"] == 2
    assert body["counts"]["filtered"] == 1
    assert body["counts"]["failed"] == 1
    # Lag is computed from the oldest pending row (~3h)
    assert body["lag"]["seconds_behind"] is not None and body["lag"]["seconds_behind"] > 3000
    assert body["lag"]["sustained_busy_minutes"] is not None
    assert body["lag"]["sustained_busy_minutes"] > 150
    # Throughput windows reflect the seed rows.
    assert body["throughput"]["last_1h"] == {"sessions": 1, "memories": 4, "instincts": 2}
    assert body["throughput"]["last_24h"] == {"sessions": 2, "memories": 7, "instincts": 3}
    # ETA = pending(1) / rate_per_hour(1) * 60min = 60.0
    assert body["throughput"]["eta_drain_minutes"] == pytest.approx(60.0)
    # local + external 30d path split
    assert body["processing_path_30d"]["local"] == 1
    assert body["processing_path_30d"]["external"] == 1
    assert body["last_distilled_at"] is not None


@pytest.mark.asyncio
async def test_distillation_status_eta_is_none_when_no_recent_throughput(isolated_db) -> None:
    """Pending exists but no 1h throughput → ETA must be None, not infinity."""
    user_id = await _seed_user(isolated_db)
    await _seed_raw_session(
        isolated_db,
        user_id=user_id,
        state="pending",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    resp = await distillation_routes.route_distillation_status(_request({"user_id": user_id}))
    body = orjson.loads(resp.body)
    assert body["counts"]["pending"] == 1
    assert body["throughput"]["last_1h"]["sessions"] == 0
    assert body["throughput"]["eta_drain_minutes"] is None


@pytest.mark.asyncio
async def test_distillation_status_scopes_to_caller(isolated_db) -> None:
    alice = await _seed_user(isolated_db)
    bob = await _seed_user(isolated_db)
    await _seed_raw_session(
        isolated_db,
        user_id=alice,
        state="pending",
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    resp = await distillation_routes.route_distillation_status(_request({"user_id": bob}))
    body = orjson.loads(resp.body)
    assert body["counts"]["pending"] == 0
    assert body["lag"]["seconds_behind"] is None


# ---------------------------------------------------------------------------
# /api/projects/{id}/freshness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_freshness_requires_auth() -> None:
    resp = await distillation_routes.route_project_freshness(_request(path_params={"id": "p1"}))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_project_freshness_requires_project_id() -> None:
    resp = await distillation_routes.route_project_freshness(
        _request({"user_id": "u1"}, path_params={})
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_project_freshness_returns_zero_when_no_sessions(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    resp = await distillation_routes.route_project_freshness(
        _request({"user_id": user_id}, path_params={"id": "ghost"})
    )
    assert resp.status_code == 200
    body = orjson.loads(resp.body)
    assert body["project_id"] == "ghost"
    assert body["pending_count"] == 0
    assert body["last_distilled_at"] is None
    assert body["oldest_pending_age_seconds"] is None


@pytest.mark.asyncio
async def test_project_freshness_aggregates_per_project(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    now = datetime.now(timezone.utc)
    project_id = "proj-alpha"

    await _seed_raw_session(
        isolated_db,
        user_id=user_id,
        project_id=project_id,
        state="pending",
        created_at=now - timedelta(minutes=30),
    )
    await _seed_raw_session(
        isolated_db,
        user_id=user_id,
        project_id=project_id,
        state="distilled",
        created_at=now - timedelta(hours=2),
        processed_at=now - timedelta(hours=1),
    )
    # Other project's row must not bleed into the aggregation.
    await _seed_raw_session(
        isolated_db,
        user_id=user_id,
        project_id="proj-beta",
        state="pending",
        created_at=now - timedelta(days=1),
    )

    resp = await distillation_routes.route_project_freshness(
        _request({"user_id": user_id}, path_params={"id": project_id})
    )
    body = orjson.loads(resp.body)
    assert body["project_id"] == project_id
    assert body["pending_count"] == 1
    assert body["last_distilled_at"] is not None
    assert body["oldest_pending_age_seconds"] is not None
    # ~30 minutes ago → between 25 and 35 minutes in seconds.
    assert 1500 < body["oldest_pending_age_seconds"] < 2100


@pytest.mark.asyncio
async def test_project_freshness_never_leaks_other_users(isolated_db) -> None:
    alice = await _seed_user(isolated_db)
    bob = await _seed_user(isolated_db)
    await _seed_raw_session(
        isolated_db,
        user_id=alice,
        project_id="shared",
        state="pending",
        created_at=datetime.now(timezone.utc),
    )
    resp = await distillation_routes.route_project_freshness(
        _request({"user_id": bob}, path_params={"id": "shared"})
    )
    body = orjson.loads(resp.body)
    assert body["pending_count"] == 0


# ---------------------------------------------------------------------------
# /api/distillation/run-now
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_now_requires_auth() -> None:
    resp = await distillation_routes.route_run_now(_request())
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_run_now_returns_202_when_worker_not_listening(monkeypatch) -> None:
    """Worker absent (e.g. distillation disabled) → woken=False but still 202."""
    monkeypatch.setattr(distillation_routes._worker_mod, "request_wake", lambda: False)
    resp = await distillation_routes.route_run_now(_request({"user_id": "u1"}))
    assert resp.status_code == 202
    body = orjson.loads(resp.body)
    assert body["woken"] is False
    assert "Scheduler gates" in body["note"]


@pytest.mark.asyncio
async def test_run_now_returns_202_when_worker_woken(monkeypatch) -> None:
    monkeypatch.setattr(distillation_routes._worker_mod, "request_wake", lambda: True)
    resp = await distillation_routes.route_run_now(_request({"user_id": "u1"}))
    assert resp.status_code == 202
    body = orjson.loads(resp.body)
    assert body["woken"] is True


# ---------------------------------------------------------------------------
# /api/budget/usage — 5-dim spend observability
# ---------------------------------------------------------------------------


async def _seed_usage(
    factory,
    *,
    user_id: str,
    provider: str,
    cost: float,
    tokens_in: int = 0,
    tokens_out: int = 0,
    created_at: datetime | None = None,
) -> None:
    async with factory() as sess:
        sess.add(
            ExternalLLMUsage(
                user_id=user_id,
                provider_label=provider,
                model="m",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                estimated_cost_usd=cost,
                created_at=created_at or datetime.now(timezone.utc),
            )
        )
        await sess.commit()


@pytest.mark.asyncio
async def test_budget_usage_requires_auth() -> None:
    resp = await distillation_routes.route_budget_usage(_request())
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_budget_usage_reports_zero_when_no_calls(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    resp = await distillation_routes.route_budget_usage(_request({"user_id": user_id}))
    assert resp.status_code == 200
    body = orjson.loads(resp.body)
    assert body["spent_usd"] == 0.0
    assert body["by_provider"] == []
    assert "month_start_utc" in body
    assert "cap_usd" in body


@pytest.mark.asyncio
async def test_budget_usage_aggregates_per_provider(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    # Two calls to openai + one to anthropic in the current month
    await _seed_usage(
        isolated_db, user_id=user_id, provider="openai", cost=0.50, tokens_in=100, tokens_out=80
    )
    await _seed_usage(
        isolated_db, user_id=user_id, provider="openai", cost=0.25, tokens_in=40, tokens_out=20
    )
    await _seed_usage(
        isolated_db, user_id=user_id, provider="anthropic", cost=1.00, tokens_in=200, tokens_out=160
    )
    # Old usage from previous month must not be counted.
    await _seed_usage(
        isolated_db,
        user_id=user_id,
        provider="openai",
        cost=9.99,
        created_at=datetime.now(timezone.utc) - timedelta(days=60),
    )

    resp = await distillation_routes.route_budget_usage(_request({"user_id": user_id}))
    body = orjson.loads(resp.body)
    assert body["spent_usd"] == pytest.approx(1.75, rel=1e-3)
    by_provider = {row["provider"]: row for row in body["by_provider"]}
    assert by_provider["openai"]["calls"] == 2
    assert by_provider["openai"]["tokens_in"] == 140
    assert by_provider["openai"]["tokens_out"] == 100
    assert by_provider["openai"]["cost_usd"] == pytest.approx(0.75, rel=1e-3)
    assert by_provider["anthropic"]["calls"] == 1
    assert by_provider["anthropic"]["cost_usd"] == pytest.approx(1.00, rel=1e-3)


@pytest.mark.asyncio
async def test_budget_usage_remaining_reflects_user_cap(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    # Set a $10 cap via UserPreferences directly.
    async with isolated_db() as sess:
        sess.add(
            UserPreferences(
                user_id=user_id,
                external_budget_monthly_usd=10.0,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await sess.commit()
    await _seed_usage(isolated_db, user_id=user_id, provider="openai", cost=2.5)

    resp = await distillation_routes.route_budget_usage(_request({"user_id": user_id}))
    body = orjson.loads(resp.body)
    assert body["spent_usd"] == pytest.approx(2.5, rel=1e-3)
    assert body["remaining_usd"] == pytest.approx(7.5, rel=1e-3)


@pytest.mark.asyncio
async def test_budget_usage_scopes_to_caller(isolated_db) -> None:
    alice = await _seed_user(isolated_db)
    bob = await _seed_user(isolated_db)
    await _seed_usage(isolated_db, user_id=alice, provider="openai", cost=5.0)

    resp = await distillation_routes.route_budget_usage(_request({"user_id": bob}))
    body = orjson.loads(resp.body)
    assert body["spent_usd"] == 0.0
    assert body["by_provider"] == []


# ---------------------------------------------------------------------------
# GET / PATCH /api/preferences
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_preferences_requires_auth() -> None:
    resp = await distillation_routes.route_get_preferences(_request())
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_preferences_returns_nulls_when_no_row(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    resp = await distillation_routes.route_get_preferences(_request({"user_id": user_id}))
    body = orjson.loads(resp.body)
    # No row → all fields null (inherit Settings defaults).
    assert body == {k: None for k in distillation_routes._ALLOWED_PREF_FIELDS}


@pytest.mark.asyncio
async def test_get_preferences_returns_stored_values(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    async with isolated_db() as sess:
        sess.add(
            UserPreferences(
                user_id=user_id,
                distillation_idle_window="01:00-05:00",
                distillation_temp_ceiling_c=68.0,
                distillation_load_ceiling_1m=2.5,
                distillation_overflow_threshold=40,
                external_budget_monthly_usd=15.0,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await sess.commit()

    resp = await distillation_routes.route_get_preferences(_request({"user_id": user_id}))
    body = orjson.loads(resp.body)
    assert body["distillation_idle_window"] == "01:00-05:00"
    assert body["distillation_temp_ceiling_c"] == 68.0
    assert body["distillation_load_ceiling_1m"] == 2.5
    assert body["distillation_overflow_threshold"] == 40
    assert body["external_budget_monthly_usd"] == 15.0


@pytest.mark.asyncio
async def test_patch_preferences_requires_auth() -> None:
    resp = await distillation_routes.route_patch_preferences(_request(body=b"{}"))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_patch_preferences_rejects_invalid_json() -> None:
    resp = await distillation_routes.route_patch_preferences(
        _request({"user_id": "u1"}, body=b"not json")
    )
    assert resp.status_code == 400
    assert orjson.loads(resp.body)["error"] == "invalid JSON"


@pytest.mark.asyncio
async def test_patch_preferences_rejects_non_object_body() -> None:
    resp = await distillation_routes.route_patch_preferences(
        _request({"user_id": "u1"}, body=b"[1,2,3]")
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_preferences_rejects_unknown_field() -> None:
    resp = await distillation_routes.route_patch_preferences(
        _request({"user_id": "u1"}, body=orjson.dumps({"sneaky_column": "x"}))
    )
    assert resp.status_code == 400
    assert "unknown field" in orjson.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_patch_preferences_rejects_wrong_type() -> None:
    resp = await distillation_routes.route_patch_preferences(
        _request(
            {"user_id": "u1"},
            body=orjson.dumps({"distillation_overflow_threshold": "not-an-int"}),
        )
    )
    assert resp.status_code == 400
    assert "must be int" in orjson.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_patch_preferences_rejects_out_of_bounds_temp() -> None:
    resp = await distillation_routes.route_patch_preferences(
        _request({"user_id": "u1"}, body=orjson.dumps({"distillation_temp_ceiling_c": 150}))
    )
    assert resp.status_code == 400
    assert "temp_ceiling_c" in orjson.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_patch_preferences_rejects_out_of_bounds_load() -> None:
    resp = await distillation_routes.route_patch_preferences(
        _request({"user_id": "u1"}, body=orjson.dumps({"distillation_load_ceiling_1m": 999}))
    )
    assert resp.status_code == 400
    assert "load_ceiling_1m" in orjson.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_patch_preferences_rejects_negative_overflow() -> None:
    resp = await distillation_routes.route_patch_preferences(
        _request({"user_id": "u1"}, body=orjson.dumps({"distillation_overflow_threshold": -5}))
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_preferences_rejects_negative_budget() -> None:
    resp = await distillation_routes.route_patch_preferences(
        _request({"user_id": "u1"}, body=orjson.dumps({"external_budget_monthly_usd": -1}))
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_preferences_rejects_bad_idle_window() -> None:
    resp = await distillation_routes.route_patch_preferences(
        _request({"user_id": "u1"}, body=orjson.dumps({"distillation_idle_window": "bogus"}))
    )
    assert resp.status_code == 400
    assert "idle_window" in orjson.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_patch_preferences_creates_row_on_first_write(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    payload = {
        "distillation_idle_window": "23:00-06:00",
        "distillation_temp_ceiling_c": 65.0,
        "distillation_overflow_threshold": 30,
    }
    resp = await distillation_routes.route_patch_preferences(
        _request({"user_id": user_id}, body=orjson.dumps(payload))
    )
    assert resp.status_code == 200
    body = orjson.loads(resp.body)
    assert body["distillation_idle_window"] == "23:00-06:00"
    assert body["distillation_temp_ceiling_c"] == 65.0
    assert body["distillation_overflow_threshold"] == 30

    # Confirm a row was actually persisted (real DB state).
    from sqlalchemy import select as _select

    async with isolated_db() as sess:
        stored = (
            await sess.execute(_select(UserPreferences).where(UserPreferences.user_id == user_id))
        ).scalar_one()
    assert stored.distillation_idle_window == "23:00-06:00"
    assert stored.distillation_overflow_threshold == 30


@pytest.mark.asyncio
async def test_patch_preferences_updates_existing_and_clears_nulls(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    async with isolated_db() as sess:
        sess.add(
            UserPreferences(
                user_id=user_id,
                distillation_idle_window="02:00-05:00",
                distillation_temp_ceiling_c=70.0,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await sess.commit()

    # NULL clears, scalar updates.
    resp = await distillation_routes.route_patch_preferences(
        _request(
            {"user_id": user_id},
            body=orjson.dumps(
                {"distillation_idle_window": None, "distillation_temp_ceiling_c": 60.0}
            ),
        )
    )
    assert resp.status_code == 200
    body = orjson.loads(resp.body)
    assert body["distillation_idle_window"] is None
    assert body["distillation_temp_ceiling_c"] == 60.0


# ---------------------------------------------------------------------------
# Edge paths in already-covered handlers
# ---------------------------------------------------------------------------


def test_serialize_digest_recovers_from_corrupt_stats_json() -> None:
    row = WeeklyDigest(
        digest_id="d1",
        user_id="u1",
        week_start=date(2026, 5, 11),
        summary_text="ok",
        stats_json="<<not json>>",
        generated_at=datetime.now(timezone.utc),
    )
    out = distillation_routes._serialize_digest(row)
    assert out["stats"] == {}
    assert out["summary"] == "ok"


@pytest.mark.asyncio
async def test_weekly_digest_regenerate_requires_auth() -> None:
    resp = await distillation_routes.route_weekly_digest_regenerate(_request())
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_weekly_digest_regenerate_rejects_bad_week_format() -> None:
    app_state = SimpleNamespace(store=AsyncMock(), instincts_store=AsyncMock())
    resp = await distillation_routes.route_weekly_digest_regenerate(
        _request({"user_id": "u1"}, query={"week": "garbage"}, app_state=app_state)
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_weekly_digest_regenerate_returns_500_when_generator_raises(
    isolated_db, monkeypatch
) -> None:
    user_id = await _seed_user(isolated_db)

    async def boom(*args, **kwargs):
        raise RuntimeError("gemma offline")

    monkeypatch.setattr(distillation_routes._digest_mod, "generate_for_user", boom)
    app_state = SimpleNamespace(store=AsyncMock(), instincts_store=AsyncMock())
    resp = await distillation_routes.route_weekly_digest_regenerate(
        _request({"user_id": user_id}, app_state=app_state)
    )
    assert resp.status_code == 500
    assert orjson.loads(resp.body)["error"] == "regenerate failed"


@pytest.mark.asyncio
async def test_weekly_digest_regenerate_returns_500_when_row_missing_after_write(
    isolated_db, monkeypatch
) -> None:
    """Generator claims success but no row landed — surface as 500."""
    user_id = await _seed_user(isolated_db)

    async def fake_generate(*args, **kwargs):
        return True  # lie: don't actually insert the digest row

    monkeypatch.setattr(distillation_routes._digest_mod, "generate_for_user", fake_generate)
    app_state = SimpleNamespace(store=AsyncMock(), instincts_store=AsyncMock())
    resp = await distillation_routes.route_weekly_digest_regenerate(
        _request({"user_id": user_id}, app_state=app_state)
    )
    assert resp.status_code == 500
    assert "digest missing" in orjson.loads(resp.body)["error"]


# ---------------------------------------------------------------------------
# /api/raw-sessions — recent session inspector
# ---------------------------------------------------------------------------


async def _seed_session(
    factory,
    *,
    user_id: str,
    project_id: str | None,
    state: str,
    created_at: datetime,
    processed_at: datetime | None = None,
    error: str | None = None,
    memories: int = 0,
    instincts: int = 0,
    path: str | None = None,
) -> str:
    async with factory() as sess:
        row = RawSession(
            ingest_id=str(uuid.uuid4()),
            user_id=user_id,
            project_id=project_id,
            client="claude-code",
            transcript_json="{}",
            created_at=created_at,
            processed_at=processed_at,
            error=error,
            memories_extracted=memories,
            instincts_extracted=instincts,
            distillation_state=state,
            processing_path=path,
        )
        sess.add(row)
        await sess.commit()
        return row.ingest_id


@pytest.mark.asyncio
async def test_raw_sessions_requires_auth() -> None:
    resp = await distillation_routes.route_raw_sessions_list(_request())
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_raw_sessions_returns_empty_list(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    resp = await distillation_routes.route_raw_sessions_list(_request({"user_id": user_id}))
    assert resp.status_code == 200
    body = orjson.loads(resp.body)
    assert body == {"state": "any", "sessions": []}


@pytest.mark.asyncio
async def test_raw_sessions_filters_by_state(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    now = datetime.now(timezone.utc)
    await _seed_session(
        isolated_db,
        user_id=user_id,
        project_id=None,
        state="failed",
        created_at=now,
        processed_at=now,
        error="empty_extraction",
    )
    await _seed_session(
        isolated_db,
        user_id=user_id,
        project_id=None,
        state="distilled",
        created_at=now,
        processed_at=now,
        memories=8,
        instincts=3,
        path="external",
    )

    resp = await distillation_routes.route_raw_sessions_list(
        _request({"user_id": user_id}, query={"state": "failed"})
    )
    body = orjson.loads(resp.body)
    assert body["state"] == "failed"
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["state"] == "failed"
    assert body["sessions"][0]["error"] == "empty_extraction"


@pytest.mark.asyncio
async def test_raw_sessions_rejects_invalid_state() -> None:
    resp = await distillation_routes.route_raw_sessions_list(
        _request({"user_id": "u1"}, query={"state": "garbage"})
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_raw_sessions_caps_limit_at_max(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    now = datetime.now(timezone.utc)
    # Seed a single row so we can confirm the request shape is accepted.
    await _seed_session(
        isolated_db,
        user_id=user_id,
        project_id=None,
        state="distilled",
        created_at=now,
        processed_at=now,
    )
    resp = await distillation_routes.route_raw_sessions_list(
        _request({"user_id": user_id}, query={"limit": "9999"})
    )
    assert resp.status_code == 200
    assert orjson.loads(resp.body)["sessions"]  # got at least one row


@pytest.mark.asyncio
async def test_raw_sessions_rejects_non_integer_limit() -> None:
    resp = await distillation_routes.route_raw_sessions_list(
        _request({"user_id": "u1"}, query={"limit": "abc"})
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_raw_sessions_joins_project_name(isolated_db) -> None:
    user_id = await _seed_user(isolated_db)
    now = datetime.now(timezone.utc)

    async with isolated_db() as sess:
        proj = Project(
            id=str(uuid.uuid4()),
            user_id=user_id,
            slug="alpha",
            name="Alpha",
            created_at=now,
            updated_at=now,
        )
        sess.add(proj)
        await sess.commit()
        project_id = proj.id

    await _seed_session(
        isolated_db,
        user_id=user_id,
        project_id=project_id,
        state="distilled",
        created_at=now,
        processed_at=now,
        memories=5,
        instincts=2,
    )

    resp = await distillation_routes.route_raw_sessions_list(_request({"user_id": user_id}))
    body = orjson.loads(resp.body)
    assert body["sessions"][0]["project_name"] == "Alpha"


@pytest.mark.asyncio
async def test_raw_sessions_never_leaks_other_users_rows(isolated_db) -> None:
    """Cross-user gate — list endpoint must scope by caller id."""
    alice = await _seed_user(isolated_db)
    bob = await _seed_user(isolated_db)
    now = datetime.now(timezone.utc)
    await _seed_session(
        isolated_db,
        user_id=alice,
        project_id=None,
        state="failed",
        created_at=now,
        processed_at=now,
        error="alice secret",
    )

    resp = await distillation_routes.route_raw_sessions_list(
        _request({"user_id": bob}, query={"state": "failed"})
    )
    body = orjson.loads(resp.body)
    assert body["sessions"] == []
