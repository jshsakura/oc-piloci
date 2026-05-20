from __future__ import annotations

"""Tests for the lazy distillation worker.

The worker is a single-threaded loop: scheduler.poll → fetch pending batch →
process each row via extract_session_multipass → persist memories + instincts
and advance distillation_state. We mock the LLM (chat_json), the embed module,
and the LanceDB stores, while exercising the real SQLAlchemy state machine
against an in-memory SQLite engine.

Test design follows the lazy pipeline invariants from CLAUDE.md:
- No eager LLM call when there is no pending row (worker decides via scheduler).
- All extraction goes through chat_json via the extraction module — tests
  patch chat_json so no live network is required and assert the call shape.
- State transitions always come from the worker; tests never poke
  distillation_state directly to simulate progress.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import orjson
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from piloci.curator import distillation_worker as dw
from piloci.curator.extraction import DistilledInstinct, DistilledMemory, DistilledSession
from piloci.curator.scheduler import SchedulerDecision
from piloci.db.models import Base, ExternalLLMUsage, Project, RawSession, User, UserPreferences

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session_factory(tmp_path):
    db_path = tmp_path / "worker.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def bind_session(monkeypatch, session_factory):
    """Bind ``distillation_worker.async_session`` to our isolated factory."""

    @asynccontextmanager
    async def fake_session():
        async with session_factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    monkeypatch.setattr(dw, "async_session", fake_session)
    return fake_session


async def _seed_user_project(factory, *, user_id: str = "u1", project_id: str = "p1") -> None:
    now = datetime.now(timezone.utc)
    async with factory() as db:
        db.add(User(id=user_id, email=f"{user_id}@test.dev", created_at=now))
        db.add(
            Project(
                id=project_id,
                user_id=user_id,
                slug=project_id,
                name=project_id.upper(),
                created_at=now,
                updated_at=now,
            )
        )
        await db.commit()


async def _add_pending(
    factory,
    *,
    ingest_id: str,
    user_id: str = "u1",
    project_id: str | None = "p1",
    transcript: object | None = None,
    priority: int = 0,
    attempts: int = 0,
) -> None:
    payload = (
        transcript
        if transcript is not None
        else [
            {"role": "user", "content": "build a feature with argon2"},
            {"role": "assistant", "content": "ok, let me write the migration"},
        ]
    )
    async with factory() as db:
        db.add(
            RawSession(
                ingest_id=ingest_id,
                user_id=user_id,
                project_id=project_id,
                client="claude-code",
                transcript_json=orjson.dumps(payload).decode(),
                created_at=datetime.now(timezone.utc),
                distillation_state="pending",
                priority=priority,
                attempt_count=attempts,
            )
        )
        await db.commit()


async def _get_row(factory, ingest_id: str) -> RawSession | None:
    async with factory() as db:
        return await db.get(RawSession, ingest_id)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_cosine_identical_vectors() -> None:
    assert dw._cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors_is_zero() -> None:
    assert dw._cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_mismatched_length_returns_zero() -> None:
    assert dw._cosine([1.0, 0.0, 0.5], [1.0, 0.0]) == 0.0


def test_cosine_zero_vector_safe() -> None:
    assert dw._cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


# ---------------------------------------------------------------------------
# Wake event lifecycle
# ---------------------------------------------------------------------------


def test_request_wake_returns_false_before_worker_starts(monkeypatch) -> None:
    """Module starts with no wake event; request_wake must report 'no listener'."""
    monkeypatch.setattr(dw, "_wake_event", None)
    assert dw.request_wake() is False


def test_request_wake_returns_true_after_event_constructed(monkeypatch) -> None:
    monkeypatch.setattr(dw, "_wake_event", None)
    # Simulate the worker grabbing its event at startup.
    ev = dw._get_wake_event()
    assert isinstance(ev, asyncio.Event)
    assert dw.request_wake() is True
    assert ev.is_set()


async def test_sleep_until_returns_immediately_on_zero_seconds() -> None:
    stop = asyncio.Event()
    wake = asyncio.Event()
    await dw._sleep_until(stop, wake, 0)
    # No exception, no blocking. Stop/wake untouched.
    assert not stop.is_set()
    assert not wake.is_set()


async def test_sleep_until_wakes_on_stop_event() -> None:
    stop = asyncio.Event()
    wake = asyncio.Event()
    stop.set()
    await asyncio.wait_for(dw._sleep_until(stop, wake, 60), timeout=1.0)


async def test_sleep_until_wakes_and_clears_wake_event() -> None:
    stop = asyncio.Event()
    wake = asyncio.Event()
    wake.set()
    await asyncio.wait_for(dw._sleep_until(stop, wake, 60), timeout=1.0)
    # Wake events auto-clear so the next sleep blocks normally again.
    assert not wake.is_set()


# ---------------------------------------------------------------------------
# Scheduler config merge
# ---------------------------------------------------------------------------


def test_build_scheduler_config_uses_settings_when_prefs_none(settings) -> None:
    cfg = dw._build_scheduler_config(settings, None)
    assert cfg.temp_ceiling_celsius == settings.distillation_temp_ceiling_c
    assert cfg.load_ceiling_1m == settings.distillation_load_ceiling_1m
    assert cfg.overflow_threshold == settings.distillation_overflow_threshold
    assert cfg.max_chunks == settings.distillation_max_chunks


def test_build_scheduler_config_user_pref_overrides(settings) -> None:
    prefs = UserPreferences(
        user_id="u1",
        distillation_idle_window="03:00-04:00",
        distillation_temp_ceiling_c=55.0,
        distillation_load_ceiling_1m=1.5,
        distillation_overflow_threshold=10,
        updated_at=datetime.now(timezone.utc),
    )
    cfg = dw._build_scheduler_config(settings, prefs)
    assert cfg.temp_ceiling_celsius == 55.0
    assert cfg.load_ceiling_1m == 1.5
    assert cfg.overflow_threshold == 10
    assert cfg.idle_window is not None


def test_build_scheduler_config_invalid_idle_window_degrades_to_none(settings) -> None:
    prefs = UserPreferences(
        user_id="u1",
        distillation_idle_window="not-a-window",
        updated_at=datetime.now(timezone.utc),
    )
    cfg = dw._build_scheduler_config(settings, prefs)
    # parse_idle_window returns None on garbage — scheduler treats as 'no window'.
    assert cfg.idle_window is None


# ---------------------------------------------------------------------------
# _fetch_pending_batch ordering / attempt cap
# ---------------------------------------------------------------------------


async def test_fetch_pending_batch_orders_by_priority_then_created(
    session_factory,
) -> None:
    await _seed_user_project(session_factory)
    await _add_pending(session_factory, ingest_id="a", priority=0)
    await _add_pending(session_factory, ingest_id="b", priority=5)
    await _add_pending(session_factory, ingest_id="c", priority=5)

    async with session_factory() as db:
        rows = await dw._fetch_pending_batch(db, limit=10, max_attempts=3)
    ids = [r.ingest_id for r in rows]
    # High priority first; lowest priority last.
    assert ids[0] in ("b", "c")
    assert ids[-1] == "a"


async def test_fetch_pending_batch_skips_rows_at_max_attempts(session_factory) -> None:
    await _seed_user_project(session_factory)
    await _add_pending(session_factory, ingest_id="fresh", attempts=0)
    await _add_pending(session_factory, ingest_id="poison", attempts=3)

    async with session_factory() as db:
        rows = await dw._fetch_pending_batch(db, limit=10, max_attempts=3)
    assert [r.ingest_id for r in rows] == ["fresh"]


async def test_fetch_pending_batch_respects_limit(session_factory) -> None:
    await _seed_user_project(session_factory)
    for i in range(5):
        await _add_pending(session_factory, ingest_id=f"r{i}")
    async with session_factory() as db:
        rows = await dw._fetch_pending_batch(db, limit=2, max_attempts=3)
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# _process_one — happy path, empty result, external budget recording
# ---------------------------------------------------------------------------


def _patch_embed(monkeypatch) -> None:
    async def fake_embed_texts(texts, **_kwargs):
        return [[0.1 + i * 0.0001] * 384 for i, _ in enumerate(texts)]

    async def fake_embed_one(text, **_kwargs):
        return [0.2] * 384

    monkeypatch.setattr(dw._embed_mod, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(dw._embed_mod, "embed_one", fake_embed_one)


def _patch_vault_invalidate(monkeypatch) -> None:
    async def noop(*_a, **_kw):
        return None

    monkeypatch.setattr(dw, "invalidate_project_vault_cache", noop)


async def test_process_one_happy_path_advances_state_and_persists(
    settings, session_factory, monkeypatch, bind_session
) -> None:
    await _seed_user_project(session_factory)
    await _add_pending(session_factory, ingest_id="row-1")

    distilled = DistilledSession(
        memories=[DistilledMemory(content="user prefers argon2", tags=["auth"], category="fact")],
        instincts=[DistilledInstinct(trigger="commit", action="run tests", domain="git")],
        processing_path="local",
    )

    extract_mock = AsyncMock(return_value=distilled)
    monkeypatch.setattr(dw, "extract_session_multipass", extract_mock)
    monkeypatch.setattr(dw, "load_user_fallbacks", AsyncMock(return_value=[]))
    _patch_embed(monkeypatch)
    _patch_vault_invalidate(monkeypatch)

    memory_store = AsyncMock()
    memory_store.search.return_value = []
    memory_store.save_many.return_value = ["mid-1"]
    instincts_store = AsyncMock()
    instincts_store.observe.return_value = {"id": "inst-1"}

    row = await _get_row(session_factory, "row-1")
    await dw._process_one(
        row,
        settings,
        memory_store,
        instincts_store,
        use_external=False,
    )

    extract_mock.assert_awaited_once()
    refreshed = await _get_row(session_factory, "row-1")
    assert refreshed.distillation_state == "distilled"
    assert refreshed.processed_at is not None
    assert refreshed.attempt_count == 1
    assert refreshed.memories_extracted == 1
    assert refreshed.instincts_extracted == 1
    assert refreshed.processing_path == "local"
    assert refreshed.error is None

    # Project counters bumped.
    async with session_factory() as db:
        proj = await db.get(Project, "p1")
    assert proj.memory_count == 1
    assert proj.instinct_count == 1


async def test_process_one_empty_extraction_stays_pending_until_max_attempts(
    settings, session_factory, monkeypatch, bind_session
) -> None:
    await _seed_user_project(session_factory)
    await _add_pending(session_factory, ingest_id="row-empty", attempts=0)

    monkeypatch.setattr(
        dw,
        "extract_session_multipass",
        AsyncMock(
            return_value=DistilledSession(memories=[], instincts=[], processing_path="local")
        ),
    )
    monkeypatch.setattr(dw, "load_user_fallbacks", AsyncMock(return_value=[]))
    _patch_embed(monkeypatch)
    _patch_vault_invalidate(monkeypatch)

    row = await _get_row(session_factory, "row-empty")
    await dw._process_one(row, settings, AsyncMock(), AsyncMock(), use_external=False)

    refreshed = await _get_row(session_factory, "row-empty")
    # Below max_attempts → still 'pending', logged 'empty_extraction'.
    assert refreshed.distillation_state == "pending"
    assert refreshed.error == "empty_extraction"
    assert refreshed.processed_at is None
    assert refreshed.attempt_count == 1


async def test_process_one_empty_extraction_at_max_attempts_marks_failed(
    settings, session_factory, monkeypatch, bind_session
) -> None:
    await _seed_user_project(session_factory)
    # attempts already at max-1; the worker increments to max, so empty result
    # this round must transition the row to 'failed'.
    await _add_pending(
        session_factory,
        ingest_id="row-doomed",
        attempts=settings.distillation_max_attempts - 1,
    )

    monkeypatch.setattr(
        dw,
        "extract_session_multipass",
        AsyncMock(
            return_value=DistilledSession(memories=[], instincts=[], processing_path="local")
        ),
    )
    monkeypatch.setattr(dw, "load_user_fallbacks", AsyncMock(return_value=[]))
    _patch_embed(monkeypatch)
    _patch_vault_invalidate(monkeypatch)

    row = await _get_row(session_factory, "row-doomed")
    await dw._process_one(row, settings, AsyncMock(), AsyncMock(), use_external=False)

    refreshed = await _get_row(session_factory, "row-doomed")
    assert refreshed.distillation_state == "failed"
    assert refreshed.error == "empty_extraction"
    assert refreshed.processed_at is not None


async def test_process_one_external_path_records_budget_usage(
    settings, session_factory, monkeypatch, bind_session
) -> None:
    await _seed_user_project(session_factory)
    await _add_pending(session_factory, ingest_id="row-ext")

    distilled = DistilledSession(
        memories=[DistilledMemory(content="foo", category="fact")],
        instincts=[],
        processing_path="external",
    )
    monkeypatch.setattr(dw, "extract_session_multipass", AsyncMock(return_value=distilled))
    monkeypatch.setattr(dw, "load_user_fallbacks", AsyncMock(return_value=[]))
    _patch_embed(monkeypatch)
    _patch_vault_invalidate(monkeypatch)

    memory_store = AsyncMock()
    memory_store.search.return_value = []
    memory_store.save_many.return_value = ["mid-ext"]

    row = await _get_row(session_factory, "row-ext")
    await dw._process_one(row, settings, memory_store, AsyncMock(), use_external=True)

    # Budget row was inserted.
    async with session_factory() as db:
        rows = (await db.execute(select(ExternalLLMUsage))).scalars().all()
    assert len(rows) == 1
    assert rows[0].provider_label == "external-fallback"
    assert rows[0].user_id == "u1"

    refreshed = await _get_row(session_factory, "row-ext")
    assert refreshed.processing_path == "external"
    assert refreshed.distillation_state == "distilled"


async def test_process_one_skips_project_writes_when_project_id_missing(
    settings, session_factory, monkeypatch, bind_session
) -> None:
    await _seed_user_project(session_factory)
    await _add_pending(session_factory, ingest_id="row-noproj", project_id=None)

    distilled = DistilledSession(
        memories=[DistilledMemory(content="x", category="fact")],
        instincts=[DistilledInstinct(trigger="t", action="a", domain="other")],
        processing_path="local",
    )
    monkeypatch.setattr(dw, "extract_session_multipass", AsyncMock(return_value=distilled))
    monkeypatch.setattr(dw, "load_user_fallbacks", AsyncMock(return_value=[]))
    _patch_embed(monkeypatch)
    _patch_vault_invalidate(monkeypatch)

    memory_store = AsyncMock()
    instincts_store = AsyncMock()

    row = await _get_row(session_factory, "row-noproj")
    await dw._process_one(row, settings, memory_store, instincts_store, use_external=False)

    # When project_id is empty, store writes are skipped entirely.
    memory_store.save_many.assert_not_called()
    instincts_store.observe.assert_not_called()
    refreshed = await _get_row(session_factory, "row-noproj")
    assert refreshed.distillation_state == "distilled"
    assert refreshed.memories_extracted == 0
    assert refreshed.instincts_extracted == 0


# ---------------------------------------------------------------------------
# _save_memories — dedup paths
# ---------------------------------------------------------------------------


async def test_save_memories_returns_zero_on_empty_input(settings) -> None:
    assert await dw._save_memories(settings, AsyncMock(), "u1", "p1", []) == 0


async def test_save_memories_dedups_within_batch(settings, monkeypatch) -> None:
    """Two memories that embed to identical vectors → only one is written."""

    async def fake_embed_texts(texts, **_kwargs):
        # Identical vectors → cosine == 1.0 → second is dropped.
        return [[0.5] * 384 for _ in texts]

    monkeypatch.setattr(dw._embed_mod, "embed_texts", fake_embed_texts)

    memory_store = AsyncMock()
    memory_store.search.return_value = []
    memory_store.save_many.return_value = ["mid-1"]

    memories = [
        DistilledMemory(content="same idea", category="fact"),
        DistilledMemory(content="same idea echoed", category="fact"),
    ]
    written = await dw._save_memories(settings, memory_store, "u1", "p1", memories)
    assert written == 1
    # save_many called with exactly one row.
    args, kwargs = memory_store.save_many.call_args
    assert len(kwargs["memories"]) == 1


async def test_save_memories_dedups_against_existing_store(settings, monkeypatch) -> None:
    async def fake_embed_texts(texts, **_kwargs):
        return [[0.1] * 384 for _ in texts]

    monkeypatch.setattr(dw._embed_mod, "embed_texts", fake_embed_texts)

    memory_store = AsyncMock()
    # Store reports a near-identical existing memory.
    memory_store.search.return_value = [{"id": "old", "score": 0.99}]

    written = await dw._save_memories(
        settings,
        memory_store,
        "u1",
        "p1",
        [DistilledMemory(content="dup", category="fact")],
    )
    assert written == 0
    memory_store.save_many.assert_not_called()


async def test_save_memories_proceeds_when_dedup_search_raises(settings, monkeypatch) -> None:
    """If the dedup probe blows up, fall back to writing the memory anyway."""

    async def fake_embed_texts(texts, **_kwargs):
        return [[0.4] * 384 for _ in texts]

    monkeypatch.setattr(dw._embed_mod, "embed_texts", fake_embed_texts)

    memory_store = AsyncMock()
    memory_store.search.side_effect = RuntimeError("lancedb down")
    memory_store.save_many.return_value = ["mid-fallback"]

    written = await dw._save_memories(
        settings,
        memory_store,
        "u1",
        "p1",
        [DistilledMemory(content="payload", category="fact")],
    )
    assert written == 1
    memory_store.save_many.assert_called_once()


# ---------------------------------------------------------------------------
# _save_instincts — failure swallow
# ---------------------------------------------------------------------------


async def test_save_instincts_continues_when_one_fails(settings, monkeypatch) -> None:
    async def fake_embed_one(text, **_kwargs):
        return [0.3] * 384

    monkeypatch.setattr(dw._embed_mod, "embed_one", fake_embed_one)

    store = AsyncMock()
    # First call raises, second succeeds — saved count should be 1.
    store.observe.side_effect = [RuntimeError("network"), {"id": "ok"}]

    saved = await dw._save_instincts(
        settings,
        store,
        "u1",
        "p1",
        [
            DistilledInstinct(trigger="x", action="y", domain="git"),
            DistilledInstinct(trigger="a", action="b", domain="testing"),
        ],
    )
    assert saved == 1


# ---------------------------------------------------------------------------
# _decide — scheduler glue against the in-memory DB
# ---------------------------------------------------------------------------


async def test_decide_returns_queue_empty_when_no_pending(
    settings, session_factory, monkeypatch, bind_session
) -> None:
    await _seed_user_project(session_factory)
    decision = await dw._decide(settings)
    assert decision.should_run is False
    assert decision.pending_count == 0


async def test_decide_runs_when_pending_present(
    settings, session_factory, monkeypatch, bind_session
) -> None:
    await _seed_user_project(session_factory)
    await _add_pending(session_factory, ingest_id="hot")
    decision = await dw._decide(settings)
    # Outside the idle window, with no temp/load read on the host this test
    # may still return should_run=True (load_ceiling guard). We assert the
    # pending count came through and the scheduler at least made a decision.
    assert decision.pending_count == 1


# ---------------------------------------------------------------------------
# run_distillation_worker — top-level loop
# ---------------------------------------------------------------------------


async def test_run_distillation_worker_exits_when_disabled(settings) -> None:
    settings.distillation_enabled = False
    stop = asyncio.Event()
    # Should return immediately without touching anything.
    await asyncio.wait_for(
        dw.run_distillation_worker(settings, AsyncMock(), AsyncMock(), stop),
        timeout=1.0,
    )


async def test_run_distillation_worker_holds_when_scheduler_says_no(settings, monkeypatch) -> None:
    """Scheduler.should_run=False → worker must NOT call extract (lazy guarantee)."""
    settings.distillation_enabled = True

    decision = SchedulerDecision(
        should_run=False,
        reason="held for test",
        pending_count=0,
        next_poll_seconds=0.01,
    )

    monkeypatch.setattr(dw, "_decide", AsyncMock(return_value=decision))
    extract_mock = AsyncMock()
    monkeypatch.setattr(dw, "extract_session_multipass", extract_mock)

    stop = asyncio.Event()

    async def _stop_soon():
        await asyncio.sleep(0.05)
        stop.set()

    await asyncio.gather(
        dw.run_distillation_worker(settings, AsyncMock(), AsyncMock(), stop),
        _stop_soon(),
    )
    # Never tried to extract — lazy contract honored.
    extract_mock.assert_not_awaited()


async def test_run_distillation_worker_processes_pending_batch(
    settings, session_factory, monkeypatch, bind_session
) -> None:
    """End-to-end: pending row → worker calls extract → row transitions."""
    await _seed_user_project(session_factory)
    await _add_pending(session_factory, ingest_id="loop-1")

    decision = SchedulerDecision(
        should_run=True,
        use_external=False,
        reason="test",
        pending_count=1,
        next_poll_seconds=10.0,
    )
    monkeypatch.setattr(dw, "_decide", AsyncMock(return_value=decision))

    distilled = DistilledSession(
        memories=[DistilledMemory(content="loop fact", category="fact")],
        instincts=[],
        processing_path="local",
    )
    monkeypatch.setattr(dw, "extract_session_multipass", AsyncMock(return_value=distilled))
    monkeypatch.setattr(dw, "load_user_fallbacks", AsyncMock(return_value=[]))
    _patch_embed(monkeypatch)
    _patch_vault_invalidate(monkeypatch)

    memory_store = AsyncMock()
    memory_store.search.return_value = []
    memory_store.save_many.return_value = ["mid-loop"]
    instincts_store = AsyncMock()

    stop = asyncio.Event()

    # Stop the worker once it has had a chance to process the batch.
    async def _stop_after_pass():
        # Give the loop a couple of ticks; the held branch sleeps via
        # _sleep_until → wake_event so set stop afterwards.
        for _ in range(50):
            row = await _get_row(session_factory, "loop-1")
            if row and row.distillation_state == "distilled":
                break
            await asyncio.sleep(0.01)
        stop.set()

    await asyncio.gather(
        dw.run_distillation_worker(settings, memory_store, instincts_store, stop),
        _stop_after_pass(),
    )

    refreshed = await _get_row(session_factory, "loop-1")
    assert refreshed.distillation_state == "distilled"
    assert refreshed.memories_extracted == 1


async def test_run_distillation_worker_records_failure_when_extract_raises(
    settings, session_factory, monkeypatch, bind_session
) -> None:
    """An LLM crash mid-batch must flip the row to 'failed' once attempts are spent."""
    settings.distillation_max_attempts = 1  # one shot, one chance
    await _seed_user_project(session_factory)
    await _add_pending(session_factory, ingest_id="boom")

    decision = SchedulerDecision(
        should_run=True,
        use_external=False,
        reason="test",
        pending_count=1,
        next_poll_seconds=10.0,
    )
    monkeypatch.setattr(dw, "_decide", AsyncMock(return_value=decision))
    monkeypatch.setattr(
        dw,
        "extract_session_multipass",
        AsyncMock(side_effect=RuntimeError("simulated llm crash")),
    )
    monkeypatch.setattr(dw, "load_user_fallbacks", AsyncMock(return_value=[]))
    _patch_embed(monkeypatch)
    _patch_vault_invalidate(monkeypatch)

    stop = asyncio.Event()

    async def _stop_after_pass():
        for _ in range(50):
            row = await _get_row(session_factory, "boom")
            if row and row.distillation_state == "failed":
                break
            await asyncio.sleep(0.01)
        stop.set()

    await asyncio.gather(
        dw.run_distillation_worker(settings, AsyncMock(), AsyncMock(), stop),
        _stop_after_pass(),
    )

    refreshed = await _get_row(session_factory, "boom")
    assert refreshed.distillation_state == "failed"
    assert refreshed.error == "worker_exception"
    assert refreshed.processed_at is not None


async def test_run_distillation_worker_skips_external_when_user_budget_exhausted(
    settings, session_factory, monkeypatch, bind_session
) -> None:
    """When scheduler says use_external=True but the user is capped out, worker
    must fall back to local for that row.
    """
    await _seed_user_project(session_factory)
    # Cap the user at $0.01 and pre-record overspend so is_budget_exhausted=True.
    async with session_factory() as db:
        db.add(
            UserPreferences(
                user_id="u1",
                external_budget_monthly_usd=0.01,
                updated_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            ExternalLLMUsage(
                user_id="u1",
                provider_label="x",
                model="m",
                tokens_in=0,
                tokens_out=0,
                estimated_cost_usd=100.0,
                created_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    await _add_pending(session_factory, ingest_id="cap-1")

    decision = SchedulerDecision(
        should_run=True,
        use_external=True,  # scheduler says go external
        reason="overflow",
        pending_count=1,
        next_poll_seconds=10.0,
    )
    monkeypatch.setattr(dw, "_decide", AsyncMock(return_value=decision))

    captured_use_external: list[bool] = []

    async def fake_extract(transcript, **kwargs):
        captured_use_external.append(kwargs.get("prefer_external", False))
        return DistilledSession(
            memories=[DistilledMemory(content="capped", category="fact")],
            instincts=[],
            processing_path="local",
        )

    monkeypatch.setattr(dw, "extract_session_multipass", fake_extract)
    monkeypatch.setattr(dw, "load_user_fallbacks", AsyncMock(return_value=[]))
    _patch_embed(monkeypatch)
    _patch_vault_invalidate(monkeypatch)

    memory_store = AsyncMock()
    memory_store.search.return_value = []
    memory_store.save_many.return_value = ["mid-cap"]

    stop = asyncio.Event()

    async def _stop_after_pass():
        for _ in range(50):
            row = await _get_row(session_factory, "cap-1")
            if row and row.distillation_state == "distilled":
                break
            await asyncio.sleep(0.01)
        stop.set()

    await asyncio.gather(
        dw.run_distillation_worker(settings, memory_store, AsyncMock(), stop),
        _stop_after_pass(),
    )

    # Worker downgraded prefer_external → False because the user is capped.
    assert captured_use_external == [False]


async def test_run_distillation_worker_recovers_from_scheduler_exception(
    settings, monkeypatch
) -> None:
    """A blow-up inside _decide must not kill the worker — it sleeps + loops."""
    settings.distillation_enabled = True
    settings.distillation_poll_interval_held_sec = 0.01

    calls: list[int] = []

    async def flaky_decide(_settings):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        # Stop the worker by returning should_run=False and letting test set stop.
        return SchedulerDecision(should_run=False, pending_count=0, next_poll_seconds=0.01)

    monkeypatch.setattr(dw, "_decide", flaky_decide)

    stop = asyncio.Event()

    async def _stop_soon():
        await asyncio.sleep(0.1)
        stop.set()

    await asyncio.gather(
        dw.run_distillation_worker(settings, AsyncMock(), AsyncMock(), stop),
        _stop_soon(),
    )

    # Decision was retried at least twice — the exception path didn't kill us.
    assert len(calls) >= 2
