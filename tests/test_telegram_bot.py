from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from piloci.db.models import RawSession, User, WeeklyDigest
from piloci.db.session import init_db
from piloci.notify import telegram_bot


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _reset_pause():
    """Each test starts with the bot's pause flag cleared.

    Pause state is module-level; without this reset a test that exercises
    /pause leaks into every later test on the same worker.
    """
    telegram_bot._paused_runtime = False
    yield
    telegram_bot._paused_runtime = False


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_db(engine=eng)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_factory(engine):
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest.fixture
def settings():
    return SimpleNamespace(
        telegram_bot_token="t-abc",
        telegram_chat_id="42",
        telegram_timeout_sec=5.0,
        telegram_bot_enabled=True,
        distillation_enabled=True,
        distillation_overflow_threshold=25,
    )


@pytest.fixture(autouse=True)
def _bind_session(db_factory, monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        async with db_factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    monkeypatch.setattr(telegram_bot, "async_session", fake_session)


async def _seed_admin(db_factory) -> str:
    async with db_factory() as sess:
        u = User(
            id=str(uuid.uuid4()),
            email="a@x.com",
            password_hash="$argon2id$x",
            created_at=_now(),
            is_admin=True,
        )
        sess.add(u)
        await sess.commit()
        return u.id


# ---------------------------------------------------------------------------
# _fmt_minutes
# ---------------------------------------------------------------------------


def test_fmt_minutes_none():
    assert telegram_bot._fmt_minutes(None) == "—"


def test_fmt_minutes_under_hour():
    assert telegram_bot._fmt_minutes(45) == "45분"


def test_fmt_minutes_under_day():
    assert telegram_bot._fmt_minutes(90) == "1.5시간"


def test_fmt_minutes_over_day():
    assert telegram_bot._fmt_minutes(60 * 24 * 3) == "3.0일"


# ---------------------------------------------------------------------------
# Authorization gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allowed_chat_matches_string_or_int(settings):
    assert await telegram_bot._allowed_chat(settings, 42) is True
    assert await telegram_bot._allowed_chat(settings, "42") is True


@pytest.mark.asyncio
async def test_allowed_chat_rejects_other(settings):
    assert await telegram_bot._allowed_chat(settings, 99) is False


@pytest.mark.asyncio
async def test_allowed_chat_returns_false_when_unconfigured():
    s = SimpleNamespace(telegram_chat_id=None)
    assert await telegram_bot._allowed_chat(s, 42) is False


# ---------------------------------------------------------------------------
# Dispatcher routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_returns_none_for_non_command(settings):
    assert await telegram_bot._dispatch("hello", settings) is None


@pytest.mark.asyncio
async def test_dispatch_unknown_command_says_so(settings):
    out = await telegram_bot._dispatch("/nope", settings)
    assert out is not None and "알 수 없는" in out


@pytest.mark.asyncio
async def test_dispatch_strips_bot_handle(settings):
    """Group chats append @bot_name — must still route."""
    out = await telegram_bot._dispatch("/help@piloci_bot", settings)
    assert out is not None and "piLoci 명령" in out


@pytest.mark.asyncio
async def test_dispatch_start_aliases_to_help(settings):
    out = await telegram_bot._dispatch("/start", settings)
    assert out is not None and "piLoci 명령" in out


# ---------------------------------------------------------------------------
# /pause + /resume — runtime flag flip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_sets_runtime_flag_and_disables_settings(settings):
    out = await telegram_bot._dispatch("/pause", settings)
    assert "일시정지" in out
    assert telegram_bot.is_runtime_paused() is True
    assert settings.distillation_enabled is False


@pytest.mark.asyncio
async def test_resume_clears_runtime_flag(settings):
    await telegram_bot._dispatch("/pause", settings)
    out = await telegram_bot._dispatch("/resume", settings)
    assert "재개" in out
    assert telegram_bot.is_runtime_paused() is False
    assert settings.distillation_enabled is True


# ---------------------------------------------------------------------------
# /status — DB-backed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_handles_empty_db(settings):
    out = await telegram_bot._handle_status(settings)
    assert "사용자가 아직 없습니다" in out


@pytest.mark.asyncio
async def test_status_reflects_pause_state(settings, db_factory):
    await _seed_admin(db_factory)
    telegram_bot._paused_runtime = True
    out = await telegram_bot._handle_status(settings)
    assert "일시정지" in out


@pytest.mark.asyncio
async def test_status_reports_pending_count(settings, db_factory):
    user_id = await _seed_admin(db_factory)
    async with db_factory() as sess:
        for _ in range(3):
            sess.add(
                RawSession(
                    ingest_id=str(uuid.uuid4()),
                    user_id=user_id,
                    project_id=None,
                    client="claude-code",
                    transcript_json="{}",
                    created_at=_now(),
                )
            )
        await sess.commit()
    out = await telegram_bot._handle_status(settings)
    assert "대기 3" in out


# ---------------------------------------------------------------------------
# /digest — server-scoped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_digest_returns_friendly_message_when_missing(settings, db_factory):
    await _seed_admin(db_factory)
    out = await telegram_bot._handle_digest(settings)
    assert "아직" in out


@pytest.mark.asyncio
async def test_digest_returns_latest_for_admin(settings, db_factory):
    from datetime import date

    user_id = await _seed_admin(db_factory)
    async with db_factory() as sess:
        sess.add(
            WeeklyDigest(
                digest_id=str(uuid.uuid4()),
                user_id=user_id,
                week_start=date(2026, 5, 4),
                summary_text="이번 주는 무난했음",
                stats_json="{}",
                generated_at=_now(),
            )
        )
        await sess.commit()

    out = await telegram_bot._handle_digest(settings)
    assert "2026-05-04" in out
    assert "이번 주는 무난했음" in out


# ---------------------------------------------------------------------------
# _process_update — gate + handler coordination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_update_drops_messages_from_other_chats(monkeypatch, settings):
    sent = []

    async def fake_send(s, chat_id, text):
        sent.append((chat_id, text))

    monkeypatch.setattr(telegram_bot, "_send_message", fake_send)
    update = {"message": {"chat": {"id": 999}, "text": "/help"}}
    await telegram_bot._process_update(update, settings)
    assert sent == []  # silently dropped, no reply


@pytest.mark.asyncio
async def test_process_update_replies_to_authorized_chat(monkeypatch, settings):
    sent = []

    async def fake_send(s, chat_id, text):
        sent.append((chat_id, text))

    monkeypatch.setattr(telegram_bot, "_send_message", fake_send)
    update = {"message": {"chat": {"id": 42}, "text": "/help"}}
    await telegram_bot._process_update(update, settings)
    assert len(sent) == 1
    assert "piLoci 명령" in sent[0][1]


@pytest.mark.asyncio
async def test_process_update_recovers_from_handler_crash(monkeypatch, settings):
    sent = []

    async def fake_send(s, chat_id, text):
        sent.append(text)

    async def boom(text, s):
        raise RuntimeError("boom")

    monkeypatch.setattr(telegram_bot, "_send_message", fake_send)
    monkeypatch.setattr(telegram_bot, "_dispatch", boom)
    update = {"message": {"chat": {"id": 42}, "text": "/status"}}
    await telegram_bot._process_update(update, settings)
    assert any("오류" in s for s in sent)


# ---------------------------------------------------------------------------
# run_telegram_bot — short-circuit conditions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_telegram_bot_noop_without_credentials():
    s = SimpleNamespace(telegram_bot_token=None, telegram_chat_id=None)
    stop = asyncio.Event()
    # Returns immediately — would otherwise hang waiting on getUpdates.
    await asyncio.wait_for(telegram_bot.run_telegram_bot(s, stop), timeout=1.0)


@pytest.mark.asyncio
async def test_run_telegram_bot_noop_when_disabled():
    s = SimpleNamespace(
        telegram_bot_token="t",
        telegram_chat_id="42",
        telegram_bot_enabled=False,
    )
    stop = asyncio.Event()
    await asyncio.wait_for(telegram_bot.run_telegram_bot(s, stop), timeout=1.0)
