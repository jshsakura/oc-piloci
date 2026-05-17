from __future__ import annotations

"""Two-way Telegram bot for piLoci ops.

Long-polls Telegram's ``getUpdates`` and routes a handful of slash commands
back to the user. Designed for *one operator* (the ``TELEGRAM_CHAT_ID``
configured in env) — anything from a different chat is dropped with a
warning, so an exposed bot token can't be turned into a back-door into the
distillation pipeline.

Why long-poll instead of webhook:
- Pi 5 typically sits behind Cloudflare Tunnel / NAT — exposing an HTTPS
  webhook adds infra. Long-poll just opens an outbound connection.
- httpx is already a dependency; no python-telegram-bot package needed.

Commands:
  /status    — counts, sustained busy minutes, throughput, ETA
  /backlog   — short backlog snapshot + ETA
  /digest    — last weekly digest summary
  /pause     — set distillation_enabled=False at runtime (process-local)
  /resume    — re-enable
  /help      — list of commands
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import func, select

from piloci.config import Settings, get_settings
from piloci.db.models import RawSession, User, WeeklyDigest
from piloci.db.session import async_session

logger = logging.getLogger(__name__)


# Telegram getUpdates long-poll timeout (server-side). 30s is the safe sweet
# spot — long enough that idle polling doesn't hammer Telegram, short enough
# that a stop_event request lands within a poll cycle.
_LONG_POLL_TIMEOUT_SEC = 30
_HTTP_TIMEOUT_SEC = _LONG_POLL_TIMEOUT_SEC + 10

# Track manual pause state. The distillation worker reads
# ``settings.distillation_enabled`` once per cycle, so flipping this flag
# on the live Settings object takes effect on the next scheduler poll.
_paused_runtime = False


def is_runtime_paused() -> bool:
    return _paused_runtime


# ---------------------------------------------------------------------------
# Telegram API helpers
# ---------------------------------------------------------------------------


async def _api_call(
    settings: Settings, method: str, payload: dict[str, Any], *, timeout: float
) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


async def _send_message(settings: Settings, chat_id: int | str, text: str) -> None:
    # Telegram caps a single message at 4096 chars. Truncate so a wall-of-stats
    # response from /status doesn't blow up the bot.
    if len(text) > 4000:
        text = text[:3997] + "..."
    try:
        await _api_call(
            settings,
            "sendMessage",
            {"chat_id": chat_id, "text": text, "disable_notification": True},
            timeout=settings.telegram_timeout_sec,
        )
    except Exception:
        logger.exception("telegram_bot: sendMessage failed")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _fmt_minutes(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    if minutes < 60:
        return f"{int(minutes)}분"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f}시간"
    return f"{hours / 24:.1f}일"


async def _resolve_admin_user_id() -> str | None:
    """Find a user id to scope queries against.

    The bot is owner-only (single chat id); we pick the *first admin* in the
    user table as the subject. Quiet noop when no admin exists yet.
    """
    async with async_session() as db:
        row = (
            await db.execute(
                select(User.id).where(User.is_admin).order_by(User.created_at.asc()).limit(1)
            )
        ).first()
    return row[0] if row else None


async def _handle_status(settings: Settings) -> str:
    user_id = await _resolve_admin_user_id()
    if user_id is None:
        return "사용자가 아직 없습니다."

    now = datetime.now(timezone.utc)
    from datetime import timedelta

    one_hour_ago = now - timedelta(hours=1)

    async with async_session() as db:
        counts = dict(
            (r.distillation_state, int(r.n))
            for r in (
                await db.execute(
                    select(
                        RawSession.distillation_state,
                        func.count().label("n"),
                    )
                    .where(RawSession.user_id == user_id)
                    .group_by(RawSession.distillation_state)
                )
            ).all()
        )
        oldest_pending = (
            await db.execute(
                select(func.min(RawSession.created_at))
                .where(RawSession.user_id == user_id)
                .where(RawSession.distillation_state == "pending")
            )
        ).scalar()
        rate_row = (
            await db.execute(
                select(
                    func.count().label("sessions"),
                    func.coalesce(func.sum(RawSession.memories_extracted), 0).label("mems"),
                    func.coalesce(func.sum(RawSession.instincts_extracted), 0).label("insts"),
                )
                .where(RawSession.user_id == user_id)
                .where(RawSession.distillation_state == "distilled")
                .where(RawSession.processed_at >= one_hour_ago)
            )
        ).first()

    pending = counts.get("pending", 0)
    sustained = None
    if oldest_pending is not None:
        oldest_aware = (
            oldest_pending if oldest_pending.tzinfo else oldest_pending.replace(tzinfo=timezone.utc)
        )
        sustained = (now - oldest_aware).total_seconds() / 60.0
    rate_per_hour = int(rate_row.sessions) if rate_row else 0
    eta_min = (pending / rate_per_hour) * 60.0 if pending > 0 and rate_per_hour > 0 else None

    pause_note = " (수동 일시정지 중)" if _paused_runtime else ""
    lines = [
        f"🧠 piLoci 상태{pause_note}",
        f"대기 {pending} · 증류됨 {counts.get('distilled', 0)} · "
        f"실패 {counts.get('failed', 0)} · 필터 {counts.get('filtered', 0)}",
        f"가장 오래된 대기: {_fmt_minutes(sustained)}째",
        f"최근 1시간: 세션 {rate_per_hour} · 메모리 "
        f"{int(rate_row.mems) if rate_row else 0} · 패턴 "
        f"{int(rate_row.insts) if rate_row else 0}",
        f"백로그 ETA: {_fmt_minutes(eta_min)}",
    ]
    return "\n".join(lines)


async def _handle_backlog(settings: Settings) -> str:
    user_id = await _resolve_admin_user_id()
    if user_id is None:
        return "사용자가 아직 없습니다."

    async with async_session() as db:
        pending = (
            await db.execute(
                select(func.count())
                .select_from(RawSession)
                .where(RawSession.user_id == user_id)
                .where(RawSession.distillation_state == "pending")
            )
        ).scalar() or 0
        failed = (
            await db.execute(
                select(func.count())
                .select_from(RawSession)
                .where(RawSession.user_id == user_id)
                .where(RawSession.distillation_state == "failed")
            )
        ).scalar() or 0
    return (
        f"📦 백로그\n"
        f"대기 {pending}건 · 실패 {failed}건\n"
        f"overflow_threshold={settings.distillation_overflow_threshold}"
    )


async def _handle_digest(settings: Settings) -> str:
    user_id = await _resolve_admin_user_id()
    if user_id is None:
        return "사용자가 아직 없습니다."

    async with async_session() as db:
        row = (
            await db.execute(
                select(WeeklyDigest)
                .where(WeeklyDigest.user_id == user_id)
                .order_by(WeeklyDigest.week_start.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    if row is None:
        return "📅 아직 정리된 주간 회고가 없습니다."

    # Truncate to leave room for the header.
    body = row.summary_text
    if len(body) > 3500:
        body = body[:3497] + "..."
    return f"📅 {row.week_start.isoformat()} 주간 회고\n\n{body}"


async def _handle_pause(settings: Settings) -> str:
    global _paused_runtime
    _paused_runtime = True
    # Flip the live Settings flag too — the worker re-reads it each poll.
    settings.distillation_enabled = False
    return "⏸ distillation 일시정지 (런타임). /resume 으로 재개."


async def _handle_resume(settings: Settings) -> str:
    global _paused_runtime
    _paused_runtime = False
    settings.distillation_enabled = True
    return "▶️ distillation 재개. 워커가 다음 폴 사이클에 반응합니다."


def _handle_help() -> str:
    return (
        "📖 piLoci 명령\n"
        "/status — 현황 + ETA\n"
        "/backlog — 백로그 짧은 요약\n"
        "/digest — 가장 최근 주간 회고\n"
        "/pause — distillation 일시정지\n"
        "/resume — distillation 재개\n"
        "/help — 이 도움말"
    )


_COMMANDS = {
    "/status": _handle_status,
    "/backlog": _handle_backlog,
    "/digest": _handle_digest,
    "/pause": _handle_pause,
    "/resume": _handle_resume,
}


async def _dispatch(text: str, settings: Settings) -> str | None:
    """Route a raw message body to a handler. Returns None for non-commands.

    Telegram includes the bot's @-handle when the message comes through a
    group ('/status@piloci_bot'); strip it so we still match.
    """
    body = (text or "").strip()
    if not body.startswith("/"):
        return None
    first = body.split()[0]
    if "@" in first:
        first = first.split("@", 1)[0]
    if first == "/help" or first == "/start":
        return _handle_help()
    handler = _COMMANDS.get(first)
    if handler is None:
        return f"알 수 없는 명령: {first}. /help 참고."
    return await handler(settings)


# ---------------------------------------------------------------------------
# Long-poll loop
# ---------------------------------------------------------------------------


async def _allowed_chat(settings: Settings, chat_id: int | str) -> bool:
    """Single-operator gate. Anything off-list is silently dropped."""
    if not settings.telegram_chat_id:
        return False
    return str(chat_id) == str(settings.telegram_chat_id)


async def _process_update(update: dict[str, Any], settings: Settings) -> None:
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    text = message.get("text") or ""

    if not await _allowed_chat(settings, chat_id):
        logger.warning("telegram_bot: rejecting message from unauthorized chat_id=%s", chat_id)
        return

    try:
        reply = await _dispatch(text, settings)
    except Exception:
        logger.exception("telegram_bot: handler crashed for text=%r", text)
        reply = "⚠️ 명령 처리 중 오류가 발생했습니다."

    if reply is not None:
        await _send_message(settings, chat_id, reply)


async def run_telegram_bot(settings: Settings, stop_event: asyncio.Event) -> None:
    """Long-poll Telegram for slash commands. Quiet no-op when not configured."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.info("telegram_bot: token or chat_id missing — bot disabled")
        return
    if not getattr(settings, "telegram_bot_enabled", True):
        logger.info("telegram_bot: disabled via settings.telegram_bot_enabled")
        return

    offset: int | None = None
    logger.info("telegram_bot: long-poll worker started")
    while not stop_event.is_set():
        try:
            payload: dict[str, Any] = {"timeout": _LONG_POLL_TIMEOUT_SEC}
            if offset is not None:
                payload["offset"] = offset
            data = await _api_call(settings, "getUpdates", payload, timeout=_HTTP_TIMEOUT_SEC)
        except Exception as exc:
            # Telegram occasionally 502s / rate-limits; back off without spamming
            # the logger so an outage doesn't bury actually useful messages.
            logger.warning("telegram_bot: getUpdates failed: %s", exc)
            await asyncio.sleep(5)
            continue

        if not data.get("ok"):
            logger.warning("telegram_bot: API returned ok=false: %s", data)
            await asyncio.sleep(5)
            continue

        for update in data.get("result") or []:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                # Telegram requires acking via the *next* offset; +1 marks
                # this update as consumed regardless of handler outcome so
                # we never re-run a poison message in a loop.
                offset = update_id + 1
            await _process_update(update, settings)

    # Best-effort: re-enable distillation if we paused at runtime, so a
    # shutdown doesn't leave the system silently halted on next boot.
    if _paused_runtime:
        try:
            settings = get_settings()
            settings.distillation_enabled = True
        except Exception:
            pass
    logger.info("telegram_bot: long-poll worker stopped")
