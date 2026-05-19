from __future__ import annotations

"""Team wiki generator — clusters team memory + documents, asks an external
LLM (GLM via OpenAI-compatible, with local Gemma fallback) to write Korean
wiki articles, and persists them in ``team_wiki_articles`` with revision
history.

Heavy LLM work runs on external providers by default so the Pi doesn't have
to chew through it. Local Gemma stays as the safety net.
"""

import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import orjson

from piloci.config import get_settings
from piloci.curator.gemma import ProviderTarget, chat_json
from piloci.curator.llm_providers import load_user_fallbacks
from piloci.curator.team_vault import build_team_vault, merge_wiki_articles, save_team_vault

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9가-힣]+")


def _slugify(value: str, fallback: str = "article") -> str:
    """Article slug — keeps Hangul. URL-safe enough for path params."""
    slug = _SLUG_RE.sub("-", (value or "").strip().lower()).strip("-")
    return slug[:80] or fallback


def _safe_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


# ---------------------------------------------------------------------------
# Clustering — turn raw memory/doc rows into topic groups for the LLM to
# write an article about. Cheap heuristic: docs cluster by their top folder,
# memories cluster by their primary tag (or "untagged" bucket).
# ---------------------------------------------------------------------------


def _doc_top_folder(path: str) -> str:
    parts = [p for p in (path or "").split("/") if p]
    if len(parts) <= 1:
        return "_root"
    return parts[0]


def _memory_primary_tag(tags: list[str]) -> str:
    return tags[0] if tags else "_misc"


def _cluster(memories: list[dict[str, Any]], docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Returns clusters: ``[{category, label, sources: [{kind, id, ...}]}, ...]``"""

    clusters: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for doc in docs:
        path = _safe_text(doc.get("path"))
        if not path:
            continue
        bucket = ("folder", _doc_top_folder(path))
        clusters[bucket].append(
            {
                "kind": "doc",
                "id": doc.get("id"),
                "path": path,
                "title": path.rsplit("/", 1)[-1],
                "content": _safe_text(doc.get("content"))[:4000],
            }
        )

    for memory in memories:
        tags = memory.get("tags") or []
        bucket = ("tag", _memory_primary_tag([str(t) for t in tags]))
        clusters[bucket].append(
            {
                "kind": "memory",
                "id": memory.get("id") or memory.get("memory_id"),
                "title": (
                    _safe_text((memory.get("metadata") or {}).get("doc_title"))
                    or _safe_text(memory.get("content")).splitlines()[0][:80]
                    if memory.get("content")
                    else "Untitled"
                ),
                "content": _safe_text(memory.get("content"))[:4000],
                "tags": [str(t) for t in tags],
            }
        )

    out: list[dict[str, Any]] = []
    for (category, label), sources in clusters.items():
        if not sources:
            continue
        out.append({"category": category, "label": label, "sources": sources})
    return out


# ---------------------------------------------------------------------------
# Prompt — Korean-first, JSON-output.
# ---------------------------------------------------------------------------

_WIKI_SYSTEM = (
    "당신은 팀이 공유한 자료(메모리·문서)를 바탕으로 한국어 위키 아티클을 "
    "쓰는 편집자입니다. 출력은 반드시 JSON. 사용자의 언어를 그대로 따르되, "
    "한국어 자료가 다수이면 한국어로 씁니다.\n"
    '스키마: {"title": str, "slug": str, "summary": str, '
    '"content": str(markdown), "category": str, '
    '"linked_topics": [str]}\n'
    "규칙: 1) content는 markdown. 2) 다른 아티클 후보를 가리킬 때 "
    "`[[topic]]` 위키링크 문법. 3) 사실만, 추측 금지. 4) summary는 1-2문장. "
    "5) category는 cluster의 폴더/태그 이름을 그대로 사용."
)


def _user_prompt(cluster: dict[str, Any]) -> str:
    parts = [
        f"카테고리: {cluster['category']}/{cluster['label']}",
        "다음 자료를 종합해 위키 아티클 1개를 작성하세요.",
        "---",
    ]
    for source in cluster["sources"][:8]:
        if source["kind"] == "doc":
            parts.append(f"[문서 {source.get('path')}]")
        else:
            tags = ", ".join(source.get("tags") or [])
            parts.append(f"[메모 tags={tags}]")
        parts.append((source.get("content") or "")[:1500])
        parts.append("---")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


async def _list_team_memories(team_id: str, store) -> list[dict[str, Any]]:
    """Pull every team memory in batches. team_count + team_list paginate."""
    out: list[dict[str, Any]] = []
    offset = 0
    page = 200
    while True:
        batch = await store.team_list(team_id, limit=page, offset=offset)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return out


async def _list_team_documents(team_id: str) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from piloci.db.models import TeamDocument
    from piloci.db.session import async_session

    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(TeamDocument).where(
                        TeamDocument.team_id == team_id,
                        TeamDocument.is_deleted == False,  # noqa: E712
                    )
                )
            )
            .scalars()
            .all()
        )
    return [
        {
            "id": row.id,
            "path": row.path,
            "content": row.content,
            "version": row.version,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


async def _resolve_team(team_id: str) -> dict[str, Any] | None:
    from sqlalchemy import select

    from piloci.db.models import Team
    from piloci.db.session import async_session

    async with async_session() as db:
        team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    if team is None:
        return None
    return {
        "id": team.id,
        "name": team.name,
        "owner_id": team.owner_id,
        "auto_wiki_enabled": bool(team.auto_wiki_enabled),
        "last_wiki_built_at": (
            team.last_wiki_built_at.isoformat() if team.last_wiki_built_at else None
        ),
    }


async def _upsert_article(
    team_id: str,
    payload: dict[str, Any],
    *,
    generated_by: str,
) -> dict[str, Any]:
    """Insert a fresh row or bump revision. Returns the persisted dict."""
    from sqlalchemy import select

    from piloci.db.models import TeamWikiArticle, TeamWikiRevision
    from piloci.db.session import async_session

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    slug = _slugify(payload.get("slug") or payload.get("title") or "article")
    title = _safe_text(payload.get("title")) or slug
    content = _safe_text(payload.get("content")) or "(empty)"
    summary = _safe_text(payload.get("summary")) or None
    category = _safe_text(payload.get("category")) or None
    sources = payload.get("sources") or []

    async with async_session() as db:
        existing = (
            await db.execute(
                select(TeamWikiArticle).where(
                    TeamWikiArticle.team_id == team_id,
                    TeamWikiArticle.slug == slug,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            # Snapshot the old revision first
            db.add(
                TeamWikiRevision(
                    id=str(uuid.uuid4()),
                    article_id=existing.id,
                    team_id=team_id,
                    revision=existing.revision,
                    title=existing.title,
                    content=existing.content,
                    author_kind=existing.author_kind,
                    author_id=existing.author_id,
                    created_at=now,
                )
            )
            existing.title = title
            existing.summary = summary
            existing.content = content
            existing.category = category
            existing.sources_json = orjson.dumps(sources).decode()
            existing.revision = (existing.revision or 1) + 1
            existing.author_kind = "llm"
            existing.generated_by = generated_by
            existing.updated_at = now
            article_id = existing.id
            revision = existing.revision
        else:
            article_id = str(uuid.uuid4())
            db.add(
                TeamWikiArticle(
                    id=article_id,
                    team_id=team_id,
                    slug=slug,
                    title=title,
                    summary=summary,
                    content=content,
                    category=category,
                    sources_json=orjson.dumps(sources).decode(),
                    revision=1,
                    author_kind="llm",
                    author_id=None,
                    generated_by=generated_by,
                    created_at=now,
                    updated_at=now,
                )
            )
            revision = 1

    return {
        "id": article_id,
        "slug": slug,
        "title": title,
        "summary": summary,
        "category": category,
        "revision": revision,
        "generated_by": generated_by,
        "sources": sources,
    }


async def _mark_team_built(team_id: str) -> None:
    from sqlalchemy import update

    from piloci.db.models import Team
    from piloci.db.session import async_session

    async with async_session() as db:
        await db.execute(
            update(Team)
            .where(Team.id == team_id)
            .values(last_wiki_built_at=datetime.now(timezone.utc).replace(tzinfo=None))
        )


async def build_team_wiki(team_id: str, store) -> dict[str, Any]:
    """End-to-end: cluster → generate articles via LLM → persist → cache.

    Returns a summary dict the caller (manual button, daily worker) can show.
    """
    team = await _resolve_team(team_id)
    if not team:
        return {"success": False, "error": f"team {team_id} not found"}

    memories = await _list_team_memories(team_id, store)
    documents = await _list_team_documents(team_id)
    workspace = build_team_vault(team, memories, documents)

    settings = get_settings()
    save_team_vault(settings.vault_dir, team_id, workspace)

    clusters = _cluster(memories, documents)
    if not clusters:
        return {
            "success": True,
            "team_id": team_id,
            "articles_built": 0,
            "reason": "no source material",
        }

    # GLM-5.1 (or equivalent external) is required. Local Gemma is too weak
    # for whole-article generation and is reserved for cheap distillation.
    # If the team owner hasn't registered an external provider, fail loudly
    # rather than silently downgrading.
    fallbacks = await load_user_fallbacks(team["owner_id"])
    if not fallbacks:
        return {
            "success": False,
            "team_id": team_id,
            "articles_built": 0,
            "error": (
                "팀 위키 생성은 외부 LLM(GLM 등) 등록이 필요합니다. "
                "설정 > LLM 제공자에서 등록해 주세요."
            ),
        }
    targets = list(fallbacks)

    articles_built: list[dict[str, Any]] = []
    failures: list[str] = []

    for cluster in clusters:
        messages = [
            {"role": "system", "content": _WIKI_SYSTEM},
            {"role": "user", "content": _user_prompt(cluster)},
        ]
        record: list[str] = []
        try:
            response = await chat_json(
                messages,
                temperature=0.2,
                max_tokens=1800,
                fallbacks=None if targets else None,
                targets=targets,
                record_target=record,
            )
        except Exception as exc:
            logger.warning("team_wiki cluster %s failed: %s", cluster["label"], exc)
            failures.append(cluster["label"])
            continue

        # Attach which sources this article was synthesized from so the UI
        # can show "근거 자료" footers and let users jump back.
        response["sources"] = [
            {"kind": s["kind"], "id": s["id"], "title": s.get("title") or s.get("path")}
            for s in cluster["sources"]
        ]
        # Override LLM-suggested category with cluster label to keep the
        # taxonomy stable across runs.
        response.setdefault("category", f"{cluster['category']}/{cluster['label']}")
        try:
            persisted = await _upsert_article(
                team_id,
                response,
                generated_by=record[-1] if record else "gemma_local",
            )
            articles_built.append(persisted)
        except Exception:
            logger.exception("team_wiki upsert failed for cluster %s", cluster["label"])
            failures.append(cluster["label"])

    # Push the freshly-built article list into the cached vault so frontend
    # `/api/teams/{tid}/workspace` can render it without an extra DB hop.
    merge_wiki_articles(
        settings.vault_dir,
        team_id,
        [
            {
                "id": a["id"],
                "slug": a["slug"],
                "title": a["title"],
                "summary": a["summary"],
                "category": a["category"],
                "revision": a["revision"],
                "generated_by": a["generated_by"],
            }
            for a in articles_built
        ],
    )
    await _mark_team_built(team_id)

    return {
        "success": True,
        "team_id": team_id,
        "articles_built": len(articles_built),
        "clusters": len(clusters),
        "failures": failures,
        "generated_by": (articles_built[0]["generated_by"] if articles_built else None),
    }


_DEFAULT_PROVIDER_LABEL = "gemma_local"


def _provider_label(targets: list[ProviderTarget] | None) -> str:
    if not targets:
        return _DEFAULT_PROVIDER_LABEL
    return targets[0].label


# ---------------------------------------------------------------------------
# Daily worker — picks teams with the auto-wiki toggle on and a stale build.
# ---------------------------------------------------------------------------

_DAILY_POLL_INTERVAL_SEC = 3600  # hourly heartbeat
# Dawn-only build window. The worker checks every hour, but the
# `_in_dawn_window()` gate ensures GLM only fires once during 03:00–05:59
# local time, so users wake up to a fresh wiki without paying for daytime
# rebuilds.
_DAWN_START_HOUR = 3
_DAWN_END_HOUR = 6  # exclusive
_STALENESS_HOURS = 20  # safety net: any team unbuilt for ~a day is re-checked


def _in_dawn_window() -> bool:
    """Local clock is within the auto-build window. UTC-naive — picks up the
    container's TZ. ``settings.timezone`` overrides the host TZ in main."""
    from datetime import datetime

    hour = datetime.now().hour
    return _DAWN_START_HOUR <= hour < _DAWN_END_HOUR


async def _team_has_new_content(team_id: str, since) -> bool:
    """True if any team document was updated after ``since``.

    Used as a cheap change signal so we don't burn GLM tokens regenerating a
    wiki that has nothing new to say. ``since=None`` means "never built" →
    treat anything as new.
    """
    from sqlalchemy import func, select

    from piloci.db.models import TeamDocument
    from piloci.db.session import async_session

    async with async_session() as db:
        stmt = (
            select(func.count())
            .select_from(TeamDocument)
            .where(
                TeamDocument.team_id == team_id,
                TeamDocument.is_deleted == False,  # noqa: E712
            )
        )
        if since is not None:
            stmt = stmt.where(TeamDocument.updated_at > since)
        count = (await db.execute(stmt)).scalar_one()
    return bool(count)


async def _teams_due_for_wiki() -> list[str]:
    """Teams to rebuild now: auto_wiki_enabled, last build is older than the
    staleness window (or never built), AND there is fresh content since the
    last build. The change-gate keeps GLM traffic proportional to actual
    activity — a team that hasn't touched docs in a week stays untouched."""

    from datetime import datetime as _dt
    from datetime import timedelta

    from sqlalchemy import select

    from piloci.db.models import Team
    from piloci.db.session import async_session

    cutoff = _dt.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=_STALENESS_HOURS)
    async with async_session() as db:
        rows = (
            await db.execute(
                select(Team.id, Team.last_wiki_built_at).where(Team.auto_wiki_enabled.is_(True))
            )
        ).all()
    due: list[str] = []
    for row in rows:
        last = row.last_wiki_built_at
        if last is not None and last >= cutoff:
            continue  # still within the staleness window
        if not await _team_has_new_content(row.id, last):
            continue  # nothing new to write about
        due.append(row.id)
    return due


async def run_team_wiki_worker(settings: Any, store: Any, stop_event: Any) -> None:
    """Background daemon — daily auto-build for teams with the flag on."""
    import asyncio

    logger.info("team_wiki: worker started")
    while not stop_event.is_set():
        try:
            if _in_dawn_window():
                team_ids = await _teams_due_for_wiki()
                for team_id in team_ids:
                    if stop_event.is_set():
                        break
                    try:
                        summary = await build_team_wiki(team_id, store)
                        logger.info(
                            "team_wiki: built team=%s articles=%s via=%s",
                            team_id,
                            summary.get("articles_built"),
                            summary.get("generated_by"),
                        )
                    except Exception:
                        logger.exception("team_wiki: build failed (team=%s)", team_id)
        except Exception:
            logger.exception("team_wiki: cycle failed")

        slept = 0
        while slept < _DAILY_POLL_INTERVAL_SEC and not stop_event.is_set():
            await asyncio.sleep(10)
            slept += 10
    logger.info("team_wiki: worker stopped")
