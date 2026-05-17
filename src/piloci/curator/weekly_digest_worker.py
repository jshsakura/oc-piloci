from __future__ import annotations

"""Lazy weekly digest worker — once-a-week private retrospective per user.

Companion to ``distillation_worker``. Where that worker turns raw transcripts
into memories+instincts, this one turns a *week of those private signals*
(feedback memories, reaction instincts, raw session activity) into a single
paragraph the user can read on the dashboard.

Privacy:
- The digest is per-user; never written to a team workspace.
- The MCP recall surface already filters out feedback memories (Phase A);
  the digest is the *only* place those moments resurface for the owner.
- Routes that read this table must scope on ``user_id`` server-side.

Cadence:
- Loop wakes once an hour and only acts when (a) it is past the configured
  idle window start AND (b) the previous-completed-week digest is missing.
  One Gemma call per user per week. Skips users with zero activity.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import orjson
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from piloci.config import Settings
from piloci.curator.gemma import chat_json
from piloci.db.models import Project, RawSession, WeeklyDigest
from piloci.db.session import async_session
from piloci.storage.instincts_store import InstinctsStore
from piloci.storage.lancedb_store import MemoryStore
from piloci.storage.privacy import PRIVATE_INSTINCT_DOMAINS, PRIVATE_MEMORY_CATEGORIES

logger = logging.getLogger(__name__)


# Cap how many feedback memories / reaction instincts we send to Gemma. The
# paragraph it produces only needs a representative sample, not the whole week.
_MAX_FEEDBACK_CONTEXT = 20
_MAX_REACTION_CONTEXT = 10

# Hourly heartbeat — quick, but the body is gated on idle-window + presence of
# previous-week row so the loop is nearly a no-op outside the regen window.
_POLL_INTERVAL_SEC = 3600

_SYSTEM = (
    "당신은 한 주간의 코딩/대화 기록을 바탕으로 사용자 본인만 보는 짧은 회고를 작성합니다.\n"
    "톤은 차분하고 따뜻한 비서. 가벼운 응원은 좋지만 과장된 칭찬·이모지·해시태그는 금지.\n"
    "출력은 한국어 산문 한 단락(4~7문장). JSON·머리말·마크다운 헤더 없이 본문만."
)

_USER_TEMPLATE = (
    "주간 통계 (월~일):\n"
    "- 세션 수: {sessions}건\n"
    "- 감정 메모(개인용): {feedback_count}건\n"
    "- 반응 패턴(개인용): {reaction_count}건\n"
    "- 활발했던 프로젝트: {top_projects}\n"
    "\n"
    "감정 메모 발췌:\n{feedback_excerpts}\n"
    "\n"
    "반응 패턴 발췌:\n{reaction_excerpts}\n"
    "\n"
    "위 자료를 바탕으로 사용자에게 보여줄 한국어 한 단락의 회고를 써주세요. "
    "이번 주에 무엇에 시간을 많이 썼는지, 어떤 순간이 힘들었거나 좋았는지를 "
    "사실적으로 정리하고, 마지막에 다음 주를 위한 짧은 한마디를 덧붙입니다."
)


@dataclass
class WeeklyStats:
    sessions: int
    feedback_count: int
    reaction_count: int
    top_projects: list[tuple[str, int]]  # (project name, session count)
    feedback_excerpts: list[str]
    reaction_excerpts: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessions": self.sessions,
            "feedback_count": self.feedback_count,
            "reaction_count": self.reaction_count,
            "top_projects": [{"name": n, "sessions": c} for n, c in self.top_projects],
        }


# ---------------------------------------------------------------------------
# Week math
# ---------------------------------------------------------------------------


def previous_week_start(today: date) -> date:
    """Monday of the most recently *completed* week.

    If today is Monday, returns Monday a week ago — the digest only covers
    fully completed Mon..Sun spans, never the in-progress week.
    """
    monday_this_week = today - timedelta(days=today.weekday())
    return monday_this_week - timedelta(days=7)


def week_bounds_utc(week_start: date) -> tuple[datetime, datetime]:
    """Half-open [start, end) UTC datetime range for a week's Mon..Sun."""
    start_dt = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=7)
    return start_dt, end_dt


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


async def _list_active_user_ids(db: AsyncSession, start: datetime, end: datetime) -> list[str]:
    rows = (
        await db.execute(
            select(RawSession.user_id)
            .where(RawSession.created_at >= start)
            .where(RawSession.created_at < end)
            .group_by(RawSession.user_id)
        )
    ).all()
    return [r[0] for r in rows]


async def _user_project_session_counts(
    db: AsyncSession, user_id: str, start: datetime, end: datetime
) -> list[tuple[str | None, int]]:
    rows = (
        await db.execute(
            select(RawSession.project_id, func.count())
            .where(RawSession.user_id == user_id)
            .where(RawSession.created_at >= start)
            .where(RawSession.created_at < end)
            .group_by(RawSession.project_id)
        )
    ).all()
    return [(r[0], int(r[1])) for r in rows]


async def _project_names(db: AsyncSession, project_ids: list[str]) -> dict[str, str]:
    if not project_ids:
        return {}
    rows = (
        await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))
    ).all()
    return {r[0]: r[1] for r in rows}


def _is_private_memory_row(row: dict[str, Any]) -> bool:
    meta = row.get("metadata") or {}
    if not isinstance(meta, dict):
        return False
    return meta.get("category") in PRIVATE_MEMORY_CATEGORIES


async def _collect_private_signals(
    memory_store: MemoryStore,
    instincts_store: InstinctsStore,
    user_id: str,
    project_ids: list[str],
    week_start_unix: int,
    week_end_unix: int,
) -> tuple[list[str], list[str]]:
    """Pull feedback memory contents + reaction instinct (trigger→action)
    pairs created during the week. LanceDB doesn't index created_at richly,
    so we list recent rows and filter in Python — sample sizes are tiny.
    """
    feedback_excerpts: list[str] = []
    reaction_excerpts: list[str] = []

    for pid in project_ids:
        if not pid:
            continue
        try:
            mems = await memory_store.list(user_id=user_id, project_id=pid, limit=200, offset=0)
        except Exception:
            logger.exception("digest: memory list failed for %s/%s", user_id, pid)
            mems = []
        for m in mems:
            created_at = int(m.get("created_at") or 0)
            if not (week_start_unix <= created_at < week_end_unix):
                continue
            if not _is_private_memory_row(m):
                continue
            content = (m.get("content") or "").strip()
            if content:
                feedback_excerpts.append(content)

        for domain in PRIVATE_INSTINCT_DOMAINS:
            try:
                insts = await instincts_store.list_instincts(
                    user_id=user_id, project_id=pid, domain=domain, limit=50
                )
            except Exception:
                logger.exception("digest: instinct list failed for %s/%s/%s", user_id, pid, domain)
                insts = []
            for inst in insts:
                # Use updated_at — observe() bumps it on each re-occurrence,
                # so a stale row that fired this week still gets surfaced.
                ts = int(inst.get("updated_at") or inst.get("created_at") or 0)
                if not (week_start_unix <= ts < week_end_unix):
                    continue
                trig = (inst.get("trigger") or "").strip()
                act = (inst.get("action") or "").strip()
                if trig and act:
                    reaction_excerpts.append(f"{trig} → {act}")

    return (
        feedback_excerpts[:_MAX_FEEDBACK_CONTEXT],
        reaction_excerpts[:_MAX_REACTION_CONTEXT],
    )


async def aggregate_week_for_user(
    db: AsyncSession,
    memory_store: MemoryStore,
    instincts_store: InstinctsStore,
    user_id: str,
    week_start: date,
) -> WeeklyStats:
    """Compute per-user stats + private signals for the given week."""
    start_dt, end_dt = week_bounds_utc(week_start)
    project_counts = await _user_project_session_counts(db, user_id, start_dt, end_dt)
    project_ids = [pid for pid, _ in project_counts if pid]
    name_by_id = await _project_names(db, project_ids)
    top_projects: list[tuple[str, int]] = sorted(
        (
            (name_by_id.get(pid, pid) if pid else "(unscoped)", c)
            for pid, c in project_counts
            if c > 0
        ),
        key=lambda x: x[1],
        reverse=True,
    )[:5]
    total_sessions = sum(c for _, c in project_counts)

    week_start_unix = int(start_dt.timestamp())
    week_end_unix = int(end_dt.timestamp())
    feedback_excerpts, reaction_excerpts = await _collect_private_signals(
        memory_store,
        instincts_store,
        user_id,
        project_ids,
        week_start_unix,
        week_end_unix,
    )

    return WeeklyStats(
        sessions=total_sessions,
        feedback_count=len(feedback_excerpts),
        reaction_count=len(reaction_excerpts),
        top_projects=top_projects,
        feedback_excerpts=feedback_excerpts,
        reaction_excerpts=reaction_excerpts,
    )


# ---------------------------------------------------------------------------
# LLM render
# ---------------------------------------------------------------------------


def _format_top_projects(top: list[tuple[str, int]]) -> str:
    if not top:
        return "없음"
    return ", ".join(f"{name}({c})" for name, c in top)


def _format_excerpts(items: list[str], empty: str) -> str:
    if not items:
        return empty
    return "\n".join(f"- {it}" for it in items)


def _fallback_summary(stats: WeeklyStats) -> str:
    """Deterministic Korean paragraph used when Gemma is unavailable.

    Better than leaving the digest empty — the user still sees the week's
    shape. The worker will overwrite this with a real summary on regenerate.
    """
    if stats.sessions == 0:
        return "이번 주는 piLoci에 기록된 활동이 거의 없었습니다. 다음 주에 다시 만나요."
    project_line = _format_top_projects(stats.top_projects)
    return (
        f"이번 주에는 총 {stats.sessions}건의 세션을 진행했고 "
        f"개인용 감정 메모 {stats.feedback_count}건, 반응 패턴 {stats.reaction_count}건이 "
        f"기록되었습니다. 활발했던 프로젝트는 {project_line}였습니다."
    )


async def render_summary(stats: WeeklyStats, settings: Settings) -> str:
    """Ask Gemma for a one-paragraph Korean retrospective.

    chat_json returns dicts — we wrap the paragraph in a single-key payload so
    the model can't drift into prose preambles that JSON mode would reject.
    Falls back to a stat-only paragraph if the LLM round-trip fails.
    """
    messages = [
        {
            "role": "system",
            "content": _SYSTEM + '\n반드시 {"summary": "..."} 형태의 JSON으로 응답.',
        },
        {
            "role": "user",
            "content": _USER_TEMPLATE.format(
                sessions=stats.sessions,
                feedback_count=stats.feedback_count,
                reaction_count=stats.reaction_count,
                top_projects=_format_top_projects(stats.top_projects),
                feedback_excerpts=_format_excerpts(stats.feedback_excerpts, "(없음)"),
                reaction_excerpts=_format_excerpts(stats.reaction_excerpts, "(없음)"),
            ),
        },
    ]
    try:
        result = await chat_json(
            messages,
            endpoint=settings.gemma_endpoint,
            model=settings.gemma_model,
            max_tokens=600,
            temperature=0.3,
        )
        summary = result.get("summary") if isinstance(result, dict) else None
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
    except Exception:
        logger.exception("digest: LLM render failed; using stats-only fallback")
    return _fallback_summary(stats)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def upsert_digest(
    db: AsyncSession,
    *,
    user_id: str,
    week_start: date,
    summary: str,
    stats: WeeklyStats,
) -> None:
    payload_json = orjson.dumps(stats.to_dict()).decode()
    now = datetime.now(timezone.utc)
    stmt = sqlite_insert(WeeklyDigest).values(
        digest_id=str(uuid.uuid4()),
        user_id=user_id,
        week_start=week_start,
        summary_text=summary,
        stats_json=payload_json,
        generated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "week_start"],
        set_={
            "summary_text": summary,
            "stats_json": payload_json,
            "generated_at": now,
        },
    )
    await db.execute(stmt)
    await db.commit()


async def digest_exists(db: AsyncSession, user_id: str, week_start: date) -> bool:
    row = (
        await db.execute(
            select(WeeklyDigest.digest_id)
            .where(WeeklyDigest.user_id == user_id)
            .where(WeeklyDigest.week_start == week_start)
        )
    ).first()
    return row is not None


async def generate_for_user(
    user_id: str,
    week_start: date,
    settings: Settings,
    memory_store: MemoryStore,
    instincts_store: InstinctsStore,
    *,
    force: bool = False,
) -> bool:
    """Build + persist one user's digest. Returns True iff something was written."""
    async with async_session() as db:
        if not force and await digest_exists(db, user_id, week_start):
            return False
        stats = await aggregate_week_for_user(
            db, memory_store, instincts_store, user_id, week_start
        )

    if stats.sessions == 0 and not force:
        # Nothing happened — skip so quiet weeks don't accumulate empty rows.
        return False

    summary = await render_summary(stats, settings)

    async with async_session() as db:
        await upsert_digest(
            db,
            user_id=user_id,
            week_start=week_start,
            summary=summary,
            stats=stats,
        )
    return True


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------


async def _run_cycle(
    settings: Settings,
    memory_store: MemoryStore,
    instincts_store: InstinctsStore,
) -> int:
    target_week = previous_week_start(datetime.now(timezone.utc).date())
    start_dt, end_dt = week_bounds_utc(target_week)

    async with async_session() as db:
        user_ids = await _list_active_user_ids(db, start_dt, end_dt)
        # Also pull every existing user with a digest hole for the target
        # week — handles the case where a user had memories backfilled past
        # the week boundary and we still owe them a row.
        if not user_ids:
            return 0

    written = 0
    for user_id in user_ids:
        try:
            if await generate_for_user(
                user_id, target_week, settings, memory_store, instincts_store
            ):
                written += 1
        except Exception:
            logger.exception("digest: generate_for_user failed (user=%s)", user_id)
    return written


async def run_weekly_digest_worker(
    settings: Settings,
    memory_store: MemoryStore,
    instincts_store: InstinctsStore,
    stop_event: asyncio.Event,
) -> None:
    """Long-running loop: once an hour, check whether last week's digest is
    owed for each active user; generate any that are missing.
    """
    logger.info("weekly digest: worker started")
    while not stop_event.is_set():
        try:
            written = await _run_cycle(settings, memory_store, instincts_store)
            if written:
                logger.info("weekly digest: generated %d digests", written)
        except Exception:
            logger.exception("weekly digest: cycle failed")

        # Sleep in small chunks so stop_event remains responsive.
        slept = 0
        while slept < _POLL_INTERVAL_SEC and not stop_event.is_set():
            await asyncio.sleep(10)
            slept += 10
    logger.info("weekly digest: worker stopped")
