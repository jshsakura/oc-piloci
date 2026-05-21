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
from piloci.curator.gemma import ProviderTarget, chat_json, chat_text
from piloci.curator.llm_providers import load_user_fallbacks
from piloci.curator.team_vault import build_team_vault, merge_wiki_articles, save_team_vault
from piloci.storage.embed import embed_one


def _make_embed_fn():
    """Tiny closure binding settings so the worker can call ``embed_one`` the
    same way the MCP server does (LRU + executor + concurrency caps)."""
    settings = get_settings()

    async def _embed(text: str) -> list[float]:
        return await embed_one(
            text,
            model=settings.embed_model,
            cache_dir=settings.embed_cache_dir,
            lru_size=settings.embed_lru_size,
            executor_workers=settings.embed_executor_workers,
            max_concurrency=settings.embed_max_concurrency,
        )

    return _embed


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


# A cluster with less than this much combined source text isn't worth an article
# — it just yields a near-empty "folder-level garbage" page. Skip it.
_MIN_CLUSTER_CHARS = 400
# A generated article body shorter than this is treated as junk (the old
# "(empty)" fallback, a one-liner, or a failed generation) and never persisted.
_MIN_ARTICLE_CHARS = 150


def _human_category(cluster: dict[str, Any]) -> str | None:
    """Human-facing category for an article. The clustering uses internal
    bucket labels (``_root`` for top-level docs, ``_misc`` for untagged
    memories); surfacing those as sidebar folders reads as junk, so map them to
    None and let the UI show its localized '기타' instead."""
    label = str(cluster.get("label") or "").strip()
    if label in ("", "_root", "_misc"):
        return None
    return label


def _cluster(memories: list[dict[str, Any]], docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Returns clusters: ``[{category, label, sources: [{kind, id, ...}]}, ...]``"""

    clusters: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for doc in docs:
        path = _safe_text(doc.get("path"))
        if not path:
            continue
        # Binary uploads (PDF/img/zip) have no inline text — feeding their empty
        # content to the LLM only produces empty/garbage articles, so skip them
        # from wiki digestion. They stay discoverable via the recall file stub.
        if doc.get("is_binary") or not _safe_text(doc.get("content")):
            continue
        bucket = ("folder", _doc_top_folder(path))
        clusters[bucket].append(
            {
                "kind": "doc",
                "id": doc.get("id"),
                "path": path,
                "title": path.rsplit("/", 1)[-1],
                # Full content — no char cap. The old [:4000] silently dropped
                # everything past the first 4000 chars of an uploaded document.
                # Budgeting/chunking happens at prompt-assembly time instead.
                "content": _safe_text(doc.get("content")),
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
                "content": _safe_text(memory.get("content")),
                "tags": [str(t) for t in tags],
            }
        )

    out: list[dict[str, Any]] = []
    for (category, label), sources in clusters.items():
        if not sources:
            continue
        # Minimum-substance gate: a folder/tag holding only a stray line isn't
        # an article, it's noise. Skip it instead of minting empty pages.
        total_chars = sum(len(_safe_text(s.get("content"))) for s in sources)
        if total_chars < _MIN_CLUSTER_CHARS:
            continue
        out.append({"category": category, "label": label, "sources": sources})
    return out


# ---------------------------------------------------------------------------
# Prompts — Korean-first, JSON-output. Three roles: draft / critique / revise,
# plus a judge pass. The flow per cluster is intentionally Karpathy-style:
# draft → fetch related topics (tool aug) → critique → revise → judge.
# Hourly cost is negligible (one team builds at most once per dawn window)
# so we invest in quality over single-shot speed.
# ---------------------------------------------------------------------------

_CRITIQUE_SYSTEM = (
    "당신은 위키 초안을 검수하는 편집자입니다. 출력은 JSON.\n"
    '스키마: {"issues": [str], "missing": [str], "style": [str], '
    '"severity": "low"|"medium"|"high"}\n'
    "검사 기준: (1) 출처 자료에 없는 사실이 본문에 나오는지, "
    "(2) 출처에는 있는데 본문에 빠진 핵심이 있는지, "
    "(3) 문체·표제·요약 일관성이 깨졌는지. 한국어로 짧게 적어주세요."
)

_JUDGE_SYSTEM = (
    "당신은 위키 아티클을 0~5점으로 평가합니다. 출력은 JSON.\n"
    '스키마: {"accuracy": 0-5, "completeness": 0-5, "clarity": 0-5, '
    '"action": "accept"|"retry"|"review", "reason": str}\n'
    "기준: accuracy=출처 충실도, completeness=핵심 누락 여부, clarity=한국어 "
    "독해 난이도. 3점 미만 항목이 하나라도 있으면 action=retry. 모든 항목 "
    "4점 이상이면 accept. 그 사이면 review."
)

# Quality threshold for accepting a generated article without retry. We retry
# at most once per cluster — past that, accept what we have and flag for
# human review. Karpathy: "set a budget; let humans review the long tail."
_JUDGE_MIN_AVG = 3.5
_MAX_RETRIES = 1

# Output budget for article body generation (draft / revise / retry). The
# prompt asks for "rulebook-level, deep, no summarizing" Korean articles, and a
# thorough one wrapped in a JSON string easily blows past a few thousand tokens.
# At 3200 the response was truncated mid-body — or the cut JSON failed to parse
# and the article was saved empty ("본문이 안 나온다"). These are external-GLM
# calls (the worker requires an external provider), so the Pi-local llama-server
# limits don't apply here.
_ARTICLE_MAX_TOKENS = 8000

# Body is generated as PLAIN MARKDOWN (not inside a JSON string) and continued
# if it hits the cap — so it can never be silently cut mid-sentence. Metadata is
# a separate tiny JSON call. This replaces the old single JSON object whose long
# `content` field the model self-truncated to keep the JSON valid.
_BODY_SYSTEM = (
    "당신은 팀이 공유한 자료(문서·메모리)를 깊이 분석해 한국어 위키 아티클 **본문**을 "
    "쓰는 전문 편집자입니다. 단순 요약이 아니라 자료를 종합·분석한 '룰북/레퍼런스 "
    "수준'의 글을 씁니다.\n"
    "출력은 **마크다운 본문 텍스트만** — JSON, 코드펜스(```), 머리말/맺음말 없이 본문만.\n"
    "구조(가능하면 ## 헤딩): ## 개요 / ## 핵심 규칙·결정 / ## 세부 / ## 예외·주의 / ## 출처\n"
    "규칙: 1) 충분히 깊고 구체적으로(요약 금지). 2) 사실을 단언할 때마다 근거 문서를 "
    "`[출처: <문서경로>]`로 인라인 인용. 3) 다른 아티클 후보는 `[[topic]]` 위키링크. "
    "4) 자료에 없는 사실·추측 금지."
)

_BODY_REVISE_SYSTEM = (
    "당신은 위키 본문 초안과 검수 의견을 받아 개정한 **마크다운 본문 텍스트만** "
    "출력합니다. JSON·머리말 없이 본문만. 새 사실을 추가하지 말고, 빠진 출처 사실을 "
    "채우고 지적된 문제만 고치세요. 기존 구조·헤딩은 유지하고 글을 끝까지 완성하세요."
)

_META_SYSTEM = (
    "당신은 완성된 한국어 위키 본문을 받아 메타데이터만 추출합니다. 출력은 JSON만.\n"
    '스키마: {"title": str, "slug": str, "summary": str, "linked_topics": [str]}\n'
    "title: 본문 주제를 한 줄 명사구로(<=60자, 끝 문장부호 없음). "
    "slug: 영문 소문자·숫자·하이픈. summary: 본문 핵심 1~2문장. "
    "linked_topics: 본문의 `[[topic]]` 또는 관련 주제명."
)

_BODY_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


def _body_links(body: str) -> list[str]:
    """Extract `[[topic]]` references from a markdown body (for tool-aug)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _BODY_LINK_RE.findall(body or ""):
        label = m.strip()
        if label and label not in seen:
            seen.add(label)
            out.append(label)
    return out


def _meta_user(body: str) -> str:
    return f"## 위키 본문\n{body}\n\n위 본문의 메타데이터를 JSON으로 추출하세요."


# Input assembly budget (chars) for one article's source material. Sized to sit
# well inside a large external-model context (GLM ~128k tokens) with room left
# for the generated article. Replaces the old per-source [:4000]/[:1200] hard
# cuts that silently dropped everything past the cap of an uploaded document.
# When a cluster's full material exceeds this we DON'T truncate — we chunk and
# map-reduce it into compact notes (below) so nothing is lost. The same
# mechanism scales to a small-context model: shrink the budget and it just
# chunks more often.
_INPUT_CHAR_BUDGET = 60000
_MAP_CHUNK_CHARS = 20000
_MAX_COMPRESS_DEPTH = 3

_MAP_SYSTEM = (
    "당신은 긴 자료의 한 조각을 받아 그 안의 사실·규칙·결정·합의·맥락·예외를 "
    "빠짐없이 항목별로 추출하는 분석가입니다. 문장은 압축하되 핵심 사실은 절대 "
    "생략하지 마세요(요약본이 아니라 무손실 노트). 출력은 JSON: "
    '{"notes": str(markdown)}. 조각에 문서 경로가 보이면 각 항목 끝에 '
    "`[출처: <경로>]`로 붙이세요."
)


def _source_blocks(cluster: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Full-content, labeled source blocks (no truncation). Docs first (primary,
    distilled facts), memories second (episodic context)."""
    docs = [s for s in cluster["sources"] if s.get("kind") == "doc"]
    mems = [s for s in cluster["sources"] if s.get("kind") == "memory"]
    doc_blocks = [f"### `{s.get('path')}`\n{_safe_text(s.get('content'))}" for s in docs]
    mem_blocks: list[str] = []
    for s in mems:
        tags = ", ".join(s.get("tags") or [])
        mem_blocks.append(f"### 메모 (tags: {tags or '없음'})\n{_safe_text(s.get('content'))}")
    return doc_blocks, mem_blocks


def _assemble_source_text(cluster: dict[str, Any], budget: int) -> tuple[str, bool]:
    """Build the full source material text for a cluster and report whether it
    exceeds ``budget``. Nothing is dropped here — the caller compresses (chunks
    + map-reduce) when the flag is set, so over-budget clusters lose no content.
    """
    doc_blocks, mem_blocks = _source_blocks(cluster)
    parts: list[str] = ["## 1차 출처 (팀 문서 — 정제된 사실)"]
    if doc_blocks:
        parts.extend(f"{b}\n" for b in doc_blocks)
    else:
        parts.append("_없음_\n")
    if mem_blocks:
        parts.append("## 2차 출처 (팀 메모리 — 회의·결정·일화)")
        parts.extend(f"{b}\n" for b in mem_blocks)
    text = "\n".join(parts)
    return text, len(text) > budget


async def _compress_text(
    text: str,
    budget: int,
    targets: list[ProviderTarget],
    record: list[str] | None = None,
    depth: int = 0,
) -> str:
    """No-loss size reduction: split oversized source text into chunks, extract
    every fact/rule from each chunk (map), concatenate the notes (reduce), and
    recurse until it fits ``budget``. A chunk that fails to map keeps its raw
    text — never dropped. A depth cap + a no-shrink guard guarantee termination.
    """
    if len(text) <= budget or depth >= _MAX_COMPRESS_DEPTH:
        return text
    chunks = [text[i : i + _MAP_CHUNK_CHARS] for i in range(0, len(text), _MAP_CHUNK_CHARS)]
    notes: list[str] = []
    for idx, chunk in enumerate(chunks):
        try:
            res = await chat_json(
                [
                    {"role": "system", "content": _MAP_SYSTEM},
                    {"role": "user", "content": f"조각 {idx + 1}/{len(chunks)}:\n\n{chunk}"},
                ],
                temperature=0.1,
                max_tokens=_ARTICLE_MAX_TOKENS,
                targets=targets,
                record_target=record,
            )
            note = _safe_text(res.get("notes"))
            notes.append(note if note else chunk)
        except Exception as exc:
            logger.warning("team_wiki: map chunk %d/%d failed: %s", idx + 1, len(chunks), exc)
            notes.append(chunk)  # never drop content on failure
    combined = "\n\n".join(notes)
    if len(combined) >= len(text):
        return combined  # compression didn't shrink — stop rather than loop
    return await _compress_text(combined, budget, targets, record, depth + 1)


async def _cluster_source_text(
    cluster: dict[str, Any],
    targets: list[ProviderTarget],
    record: list[str] | None = None,
) -> str:
    """Assemble a cluster's full source material; map-reduce it down only if it
    overflows the budget. The returned text always fits the budget and never
    silently loses content."""
    text, overflowed = _assemble_source_text(cluster, _INPUT_CHAR_BUDGET)
    if overflowed:
        text = await _compress_text(text, _INPUT_CHAR_BUDGET, targets, record)
    return text


def _user_prompt(
    cluster: dict[str, Any],
    source_text: str,
    extra_context: list[dict[str, Any]] | None = None,
) -> str:
    """Build the draft / revise user prompt around pre-assembled source text.

    `extra_context` is what we fetched via tool-aug on linked_topics — appended
    last so it informs but doesn't dominate.
    """
    parts = [
        f"카테고리: {cluster['category']}/{cluster['label']}",
        "다음 자료를 깊이 분석·종합해 룰북/레퍼런스 수준의 위키 아티클 1개를 "
        "작성하세요. 각 문서에는 경로가 붙어 있으니, 본문에서 사실을 단언할 때 "
        "`[출처: <문서경로>]` 로 인라인 인용해 추적 가능하게 하세요.",
        "",
        source_text,
    ]
    if extra_context:
        parts.append("")
        parts.append("## 참고 (관련 토픽의 다른 아티클 발췌 — 일관성 확보용)")
        for ctx in extra_context[:4]:
            title = ctx.get("title") or ctx.get("slug") or "기타"
            parts.append(f"### {title}")
            parts.append((ctx.get("excerpt") or ctx.get("content") or "")[:600])
            parts.append("")
    return "\n".join(parts)


def _critique_prompt(source_text: str, body: str) -> str:
    """Ask the LLM to find issues in the body against the source material."""
    return "\n".join(["## 검수 대상 본문", body, "", "## 원본 출처", source_text])


def _revise_prompt(source_text: str, body: str, critique: dict[str, Any]) -> str:
    issues = critique.get("issues") or []
    missing = critique.get("missing") or []
    style = critique.get("style") or []
    return "\n".join(
        [
            "## 본문 초안",
            body,
            "",
            "## 검수 의견",
            f"- 사실 오류: {issues or '없음'}",
            f"- 누락 핵심: {missing or '없음'}",
            f"- 문체/표제: {style or '없음'}",
            "",
            "## 원본 출처 (재확인용)",
            source_text,
        ]
    )


def _judge_prompt(source_text: str, body: str) -> str:
    return "\n".join(["## 평가 대상 본문", body, "", "## 원본 출처", source_text])


async def _fetch_linked_topic_context(
    team_id: str,
    store,
    embed_fn,
    linked_topics: list[str],
) -> list[dict[str, Any]]:
    """Poor-man's tool augmentation: after the draft proposes `[[topics]]`,
    fetch matching team memories so the revise pass can keep references
    grounded. Reuses the existing team hybrid search so cost is low.
    """
    if not linked_topics:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for topic in linked_topics[:4]:  # cap fan-out
        try:
            vector = await embed_fn(topic)
            rows = await store.team_hybrid_search(
                team_id=team_id,
                query_text=topic,
                query_vector=vector,
                top_k=2,
            )
        except Exception:
            continue
        for row in rows:
            mid = row.get("id") or row.get("memory_id")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            out.append(
                {
                    "title": topic,
                    "excerpt": (row.get("content") or "")[:600],
                }
            )
    return out


async def _recent_human_edits(team_id: str, limit: int = 3) -> list[dict[str, Any]]:
    """Look up the most recent human-authored revisions to use as few-shot
    style hints. We don't compute true diffs — the body itself is the
    "this is how a human said it should read" signal.
    """
    try:
        from sqlalchemy import select

        from piloci.db.models import TeamWikiRevision
        from piloci.db.session import async_session

        async with async_session() as db:
            rows = (
                (
                    await db.execute(
                        select(TeamWikiRevision)
                        .where(
                            TeamWikiRevision.team_id == team_id,
                            TeamWikiRevision.author_kind == "human",
                        )
                        .order_by(TeamWikiRevision.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [{"title": r.title, "content": (r.content or "")[:600]} for r in rows]
    except Exception:
        return []


def _judge_passes(score: dict[str, Any]) -> tuple[bool, float]:
    """Return (passes_threshold, average_score). Missing scores treated as 0."""
    a = float(score.get("accuracy") or 0)
    c = float(score.get("completeness") or 0)
    cl = float(score.get("clarity") or 0)
    avg = (a + c + cl) / 3.0
    return avg >= _JUDGE_MIN_AVG, avg


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
            "is_binary": row.is_binary,
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
            # Hash-skip dedup: if the new content is byte-identical to what
            # we already stored, treat this build as a no-op. Keeps revision
            # numbers stable across rebuilds when source material hasn't
            # actually changed — the "증류는 중복 없이" guarantee.
            if (existing.content or "") == content and (existing.title or "") == title:
                return {
                    "id": existing.id,
                    "slug": existing.slug,
                    "title": existing.title,
                    "summary": existing.summary,
                    "category": existing.category,
                    "revision": existing.revision,
                    "generated_by": existing.generated_by,
                    "sources": sources,
                    "unchanged": True,
                }

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


async def _cleanup_thin_llm_articles(team_id: str, min_chars: int) -> int:
    """Delete LLM-authored articles whose body is empty/one-liner junk (incl. the
    legacy ``(empty)`` placeholder). Human-edited articles are never touched.
    Returns the number removed."""
    from sqlalchemy import delete, func, or_, select

    from piloci.db.models import TeamWikiArticle
    from piloci.db.session import async_session

    try:
        async with async_session() as db:
            condition = (
                (TeamWikiArticle.team_id == team_id)
                & (TeamWikiArticle.author_kind == "llm")
                & or_(
                    TeamWikiArticle.content.is_(None),
                    func.length(func.trim(TeamWikiArticle.content)) < min_chars,
                    TeamWikiArticle.content == "(empty)",
                )
            )
            ids = (await db.execute(select(TeamWikiArticle.id).where(condition))).scalars().all()
            if ids:
                await db.execute(delete(TeamWikiArticle).where(condition))
            return len(ids)
    except Exception:
        logger.exception("team_wiki: cleanup of thin articles failed team=%s", team_id)
        return 0


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
                "팀 위키 생성은 외부 AI 모델 등록이 필요합니다. "
                "설정 > LLM 제공자에서 사용할 모델을 등록해 주세요."
            ),
        }
    targets = list(fallbacks)

    articles_built: list[dict[str, Any]] = []
    # Article dicts (with body + sources) for the wiki graph rebuild below.
    graph_articles: list[dict[str, Any]] = []
    failures: list[str] = []
    flagged: list[dict[str, Any]] = []
    unchanged_count = 0

    # Human-edited revisions function as style hints — the prompt steals
    # phrasing patterns the team has already approved. Loaded once per
    # build so all clusters share the same hints.
    human_hints = await _recent_human_edits(team_id)
    embed_fn = _make_embed_fn()

    for cluster in clusters:
        category_label = f"{cluster['category']}/{cluster['label']}"
        record: list[str] = []

        # Full source material — no char cap. Fits the budget whole when it can;
        # chunk+map-reduced (no content dropped) only when it overflows. Built
        # once and reused across draft/critique/revise/judge.
        source_text = await _cluster_source_text(cluster, targets, record)

        # --- Stage 1: draft body (PLAIN markdown, continued if it hits the
        # cap) — so the body can never be silently cut mid-sentence the way a
        # long JSON `content` string was. -----------------------------------
        body_messages: list[dict[str, str]] = [{"role": "system", "content": _BODY_SYSTEM}]
        if human_hints:
            body_messages.append(
                {
                    "role": "system",
                    "content": (
                        "참고: 이 팀은 과거에 다음과 같은 스타일·표현을 사용했어요. "
                        "표제·문장 길이를 비슷한 결로 맞춰주세요.\n"
                        + "\n---\n".join(f"### {h['title']}\n{h['content']}" for h in human_hints)
                    ),
                }
            )
        body_messages.append({"role": "user", "content": _user_prompt(cluster, source_text)})
        try:
            body = await chat_text(
                body_messages,
                temperature=0.2,
                max_tokens=_ARTICLE_MAX_TOKENS,
                targets=targets,
                record_target=record,
            )
        except Exception as exc:
            logger.warning("team_wiki[%s] draft failed: %s", category_label, exc)
            failures.append(category_label)
            continue

        # --- Stage 2: tool-augmented context from the body's [[links]] ----
        extra_context = await _fetch_linked_topic_context(
            team_id, store, embed_fn, _body_links(body)
        )
        extra_block = (
            "\n\n## 참고 토픽 발췌\n"
            + "\n---\n".join(f"### {c['title']}\n{c['excerpt']}" for c in extra_context)
            if extra_context
            else ""
        )

        # --- Stage 3: critique --------------------------------------------
        critique: dict[str, Any] = {}
        try:
            critique = await chat_json(
                [
                    {"role": "system", "content": _CRITIQUE_SYSTEM},
                    {"role": "user", "content": _critique_prompt(source_text, body)},
                ],
                temperature=0.0,
                max_tokens=600,
                targets=targets,
            )
        except Exception as exc:
            logger.warning("team_wiki[%s] critique failed: %s", category_label, exc)

        # --- Stage 4: revise (plain markdown, continued) ------------------
        if critique.get("issues") or critique.get("missing") or critique.get("style"):
            try:
                body = await chat_text(
                    [
                        {"role": "system", "content": _BODY_REVISE_SYSTEM},
                        {
                            "role": "user",
                            "content": _revise_prompt(source_text, body, critique) + extra_block,
                        },
                    ],
                    temperature=0.15,
                    max_tokens=_ARTICLE_MAX_TOKENS,
                    targets=targets,
                )
            except Exception as exc:
                logger.warning("team_wiki[%s] revise failed: %s", category_label, exc)

        # --- Stage 5: judge → optional retry ------------------------------
        score: dict[str, Any] = {}
        try:
            score = await chat_json(
                [
                    {"role": "system", "content": _JUDGE_SYSTEM},
                    {"role": "user", "content": _judge_prompt(source_text, body)},
                ],
                temperature=0.0,
                max_tokens=300,
                targets=targets,
            )
        except Exception as exc:
            logger.warning("team_wiki[%s] judge failed: %s", category_label, exc)

        passes, avg = _judge_passes(score)
        retries = 0
        while not passes and retries < _MAX_RETRIES:
            retries += 1
            logger.info(
                "team_wiki[%s] judge avg=%.2f, retrying (%d/%d)",
                category_label,
                avg,
                retries,
                _MAX_RETRIES,
            )
            try:
                body = await chat_text(
                    [
                        {"role": "system", "content": _BODY_REVISE_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"이전 평가: {orjson.dumps(score).decode()}\n\n"
                                + _revise_prompt(source_text, body, critique)
                            ),
                        },
                    ],
                    temperature=0.2,
                    max_tokens=_ARTICLE_MAX_TOKENS,
                    targets=targets,
                )
                score = await chat_json(
                    [
                        {"role": "system", "content": _JUDGE_SYSTEM},
                        {"role": "user", "content": _judge_prompt(source_text, body)},
                    ],
                    temperature=0.0,
                    max_tokens=300,
                    targets=targets,
                )
                passes, avg = _judge_passes(score)
            except Exception as exc:
                logger.warning("team_wiki[%s] retry failed: %s", category_label, exc)
                break

        # Junk gate: never persist an empty/one-liner body.
        body = _safe_text(body)
        if len(body) < _MIN_ARTICLE_CHARS:
            logger.info("team_wiki[%s] skipped — body too thin to be an article", category_label)
            failures.append(category_label)
            continue

        # Metadata from the finished body — a tiny JSON call (no truncation risk).
        meta: dict[str, Any] = {}
        try:
            meta = await chat_json(
                [
                    {"role": "system", "content": _META_SYSTEM},
                    {"role": "user", "content": _meta_user(body)},
                ],
                temperature=0.0,
                max_tokens=400,
                targets=targets,
                expand_on_truncation=1,
            )
        except Exception as exc:
            logger.warning("team_wiki[%s] meta failed: %s", category_label, exc)

        title = _safe_text(meta.get("title")) or _human_category(cluster) or "팀 위키"
        # Force a clean, human category (drop internal _root/_misc bucket labels).
        revised = {
            "title": title,
            "slug": _safe_text(meta.get("slug")) or _slugify(title),
            "summary": _safe_text(meta.get("summary")) or None,
            "content": body,
            "category": _human_category(cluster),
            "sources": [
                {"kind": s["kind"], "id": s["id"], "title": s.get("title") or s.get("path")}
                for s in cluster["sources"]
            ],
        }

        try:
            persisted = await _upsert_article(
                team_id,
                revised,
                generated_by=record[-1] if record else "gemma_local",
            )
        except Exception:
            logger.exception("team_wiki[%s] upsert failed", category_label)
            failures.append(category_label)
            continue

        # Surface judge metadata on the persisted dict so the dashboard /
        # daily report can flag "이 아티클은 사람 검토 필요" rows.
        persisted["judge"] = {
            "average": round(avg, 2),
            "action": score.get("action"),
            "reason": score.get("reason"),
            "retries": retries,
        }
        if persisted.get("unchanged"):
            unchanged_count += 1
        elif not passes:
            flagged.append(persisted)
        articles_built.append(persisted)
        graph_articles.append(
            {
                "slug": persisted["slug"],
                "title": persisted["title"],
                "category": persisted.get("category"),
                "summary": persisted.get("summary"),
                "content": revised.get("content") or "",
                "sources": persisted.get("sources") or [],
            }
        )

    # Sweep out junk left by earlier builds: empty / one-liner LLM articles
    # (the old "(empty)" fallback, thin clusters that are now gated out).
    # Human-edited articles are never touched.
    cleaned = await _cleanup_thin_llm_articles(team_id, _MIN_ARTICLE_CHARS)

    # Rebuild the graph with article nodes now that they exist, so the cached
    # vault's map *is* the wiki (article nodes + source/wikilink edges).
    if graph_articles:
        workspace = build_team_vault(team, memories, documents, articles=graph_articles)
        save_team_vault(settings.vault_dir, team_id, workspace)

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
        "unchanged": unchanged_count,
        "flagged_for_review": [a["slug"] for a in flagged],
        "failures": failures,
        "cleaned_thin": cleaned,
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
