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
# Prompts — Korean-first, JSON-output. Three roles: draft / critique / revise,
# plus a judge pass. The flow per cluster is intentionally Karpathy-style:
# draft → fetch related topics (tool aug) → critique → revise → judge.
# Hourly cost is negligible (one team builds at most once per dawn window)
# so we invest in quality over single-shot speed.
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

_CRITIQUE_SYSTEM = (
    "당신은 위키 초안을 검수하는 편집자입니다. 출력은 JSON.\n"
    '스키마: {"issues": [str], "missing": [str], "style": [str], '
    '"severity": "low"|"medium"|"high"}\n'
    "검사 기준: (1) 출처 자료에 없는 사실이 본문에 나오는지, "
    "(2) 출처에는 있는데 본문에 빠진 핵심이 있는지, "
    "(3) 문체·표제·요약 일관성이 깨졌는지. 한국어로 짧게 적어주세요."
)

_REVISE_SYSTEM = (
    "당신은 위키 초안과 검수 의견을 받아 개정판을 작성합니다. 출력은 초안과 "
    "동일한 JSON 스키마({title,slug,summary,content,category,linked_topics}). "
    "초안의 slug는 그대로 유지하고, 검수 의견 중 합리적인 것을 반영해 본문만 "
    "고쳐주세요. 새 사실을 추가하지 말고, 빠진 출처 사실을 채우는 정도로만."
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


def _user_prompt(cluster: dict[str, Any], extra_context: list[dict[str, Any]] | None = None) -> str:
    """Build the draft / revise user prompt.

    Hierarchical memory: docs (semantic, distilled) come first since they're
    the more authoritative source. Memories (episodic, raw events) follow
    as supporting context. `extra_context` is what we fetched via tool-aug
    on linked_topics — appended last so it informs but doesn't dominate.
    """
    parts = [
        f"카테고리: {cluster['category']}/{cluster['label']}",
        "다음 자료를 종합해 위키 아티클 1개를 작성하세요.",
        "",
        "## 1차 출처 (팀 문서 — 정제된 사실)",
    ]
    docs = [s for s in cluster["sources"] if s.get("kind") == "doc"]
    mems = [s for s in cluster["sources"] if s.get("kind") == "memory"]
    if docs:
        for source in docs[:8]:
            parts.append(f"### `{source.get('path')}`")
            parts.append((source.get("content") or "")[:1500])
            parts.append("")
    else:
        parts.append("_없음_")
        parts.append("")

    if mems:
        parts.append("## 2차 출처 (팀 메모리 — 회의·결정·일화)")
        for source in mems[:6]:
            tags = ", ".join(source.get("tags") or [])
            parts.append(f"### 메모 (tags: {tags or '없음'})")
            parts.append((source.get("content") or "")[:1200])
            parts.append("")

    if extra_context:
        parts.append("## 참고 (관련 토픽의 다른 아티클 발췌 — 일관성 확보용)")
        for ctx in extra_context[:4]:
            title = ctx.get("title") or ctx.get("slug") or "기타"
            parts.append(f"### {title}")
            parts.append((ctx.get("excerpt") or ctx.get("content") or "")[:600])
            parts.append("")

    return "\n".join(parts)


def _critique_prompt(cluster: dict[str, Any], draft: dict[str, Any]) -> str:
    """Ask the LLM to find issues in the draft against the source material."""
    parts = [
        f"## 검수 대상 초안 (제목: {draft.get('title')})",
        draft.get("content") or "",
        "",
        "## 원본 출처",
    ]
    for source in cluster["sources"][:8]:
        kind = source.get("kind")
        head = f"[문서 {source.get('path')}]" if kind == "doc" else "[메모]"
        parts.append(head)
        parts.append((source.get("content") or "")[:1200])
        parts.append("---")
    return "\n".join(parts)


def _revise_prompt(
    cluster: dict[str, Any],
    draft: dict[str, Any],
    critique: dict[str, Any],
) -> str:
    issues = critique.get("issues") or []
    missing = critique.get("missing") or []
    style = critique.get("style") or []
    parts = [
        "## 초안",
        orjson.dumps(draft, option=orjson.OPT_INDENT_2).decode(),
        "",
        "## 검수 의견",
        f"- 사실 오류: {issues or '없음'}",
        f"- 누락 핵심: {missing or '없음'}",
        f"- 문체/표제: {style or '없음'}",
        "",
        "## 원본 출처 (재확인용)",
    ]
    for source in cluster["sources"][:6]:
        kind = source.get("kind")
        head = f"[문서 {source.get('path')}]" if kind == "doc" else "[메모]"
        parts.append(head)
        parts.append((source.get("content") or "")[:1200])
        parts.append("---")
    return "\n".join(parts)


def _judge_prompt(article: dict[str, Any], cluster: dict[str, Any]) -> str:
    parts = [
        f"## 평가 대상 (제목: {article.get('title')})",
        article.get("content") or "",
        "",
        "## 원본 출처",
    ]
    for source in cluster["sources"][:6]:
        kind = source.get("kind")
        head = f"[문서 {source.get('path')}]" if kind == "doc" else "[메모]"
        parts.append(head)
        parts.append((source.get("content") or "")[:1000])
        parts.append("---")
    return "\n".join(parts)


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

        # --- Stage 1: draft ------------------------------------------------
        draft_messages = [
            {"role": "system", "content": _WIKI_SYSTEM},
        ]
        if human_hints:
            draft_messages.append(
                {
                    "role": "system",
                    "content": (
                        "참고: 이 팀은 과거에 다음과 같은 스타일·표현을 사용했어요. "
                        "표제·문장 길이를 비슷한 결로 맞춰주세요.\n"
                        + "\n---\n".join(f"### {h['title']}\n{h['content']}" for h in human_hints)
                    ),
                }
            )
        draft_messages.append({"role": "user", "content": _user_prompt(cluster)})
        record: list[str] = []
        try:
            draft = await chat_json(
                draft_messages,
                temperature=0.2,
                max_tokens=1800,
                targets=targets,
                record_target=record,
            )
        except Exception as exc:
            logger.warning("team_wiki[%s] draft failed: %s", category_label, exc)
            failures.append(category_label)
            continue

        # --- Stage 2: tool-augmented context (poor-man's agent loop) ------
        extra_context = await _fetch_linked_topic_context(
            team_id, store, embed_fn, draft.get("linked_topics") or []
        )

        # --- Stage 3: critique --------------------------------------------
        critique: dict[str, Any] = {}
        try:
            critique = await chat_json(
                [
                    {"role": "system", "content": _CRITIQUE_SYSTEM},
                    {"role": "user", "content": _critique_prompt(cluster, draft)},
                ],
                temperature=0.0,
                max_tokens=600,
                targets=targets,
            )
        except Exception as exc:
            logger.warning("team_wiki[%s] critique failed: %s", category_label, exc)

        # --- Stage 4: revise ----------------------------------------------
        revised = draft
        if critique.get("issues") or critique.get("missing") or critique.get("style"):
            try:
                revised = await chat_json(
                    [
                        {"role": "system", "content": _REVISE_SYSTEM},
                        {
                            "role": "user",
                            "content": _revise_prompt(cluster, draft, critique)
                            + (
                                "\n\n## 참고 토픽 발췌\n"
                                + "\n---\n".join(
                                    f"### {c['title']}\n{c['excerpt']}" for c in extra_context
                                )
                                if extra_context
                                else ""
                            ),
                        },
                    ],
                    temperature=0.15,
                    max_tokens=1800,
                    targets=targets,
                )
            except Exception as exc:
                logger.warning("team_wiki[%s] revise failed: %s", category_label, exc)
                revised = draft  # fall back to the draft

        # --- Stage 5: judge → optional retry ------------------------------
        score: dict[str, Any] = {}
        try:
            score = await chat_json(
                [
                    {"role": "system", "content": _JUDGE_SYSTEM},
                    {"role": "user", "content": _judge_prompt(revised, cluster)},
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
                revised = await chat_json(
                    [
                        {"role": "system", "content": _REVISE_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"이전 평가: {orjson.dumps(score).decode()}\n\n"
                                + _revise_prompt(cluster, revised, critique)
                            ),
                        },
                    ],
                    temperature=0.2,
                    max_tokens=1800,
                    targets=targets,
                )
                score = await chat_json(
                    [
                        {"role": "system", "content": _JUDGE_SYSTEM},
                        {"role": "user", "content": _judge_prompt(revised, cluster)},
                    ],
                    temperature=0.0,
                    max_tokens=300,
                    targets=targets,
                )
                passes, avg = _judge_passes(score)
            except Exception as exc:
                logger.warning("team_wiki[%s] retry failed: %s", category_label, exc)
                break

        # Always attach sources + category, even when we fall back to draft.
        revised["sources"] = [
            {"kind": s["kind"], "id": s["id"], "title": s.get("title") or s.get("path")}
            for s in cluster["sources"]
        ]
        revised.setdefault("category", category_label)

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
