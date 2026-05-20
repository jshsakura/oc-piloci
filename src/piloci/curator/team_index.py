"""Auto-maintained team entry-point map: ``LOCI.md``.

A fresh agent (or a teammate opening the vault in Obsidian) faces a pile of
files and doesn't know *where to start*. ``LOCI.md`` is that starting point —
a deterministic, always-current map of the team: one-line purpose, a
``[[wikilink]]`` document tree, the wiki index, and the natural-language
recall hint.

Why ``[[wikilinks]]``: the team document tree IS an Obsidian vault. Wikilinks
render as a navigable graph in Obsidian while an LLM reads the exact same
string as plain text — one structure, two consumers (human graph + agent
search). Why deterministic (not LLM-authored): it must be free and always
fresh, even for a brand-new team with no wiki yet; narrative is delegated to
the AI wiki, which ``LOCI.md`` links to.

The file is persisted as a normal team document so it is recall-searchable,
``piloci pull``-able, and graphable — all at once. It is regenerated
(fire-and-forget) whenever a team document changes, except when the change is
``LOCI.md`` itself (no self-trigger loop).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Single source of truth for the filename. Uppercase + non-product-generic so
# it never collides with a user's own index.md or an LLM's CLAUDE.md/AGENTS.md.
LOCI_FILENAME = "LOCI.md"


def _wikilink(path: str) -> str:
    """Obsidian wikilink for a doc path (strip the .md so the graph resolves;
    LLMs read it verbatim either way)."""
    stem = path[:-3] if path.endswith(".md") else path
    return f"[[{stem}]]"


def build_loci_md(
    team: dict,
    documents: list[dict],
    articles: list[dict],
) -> str:
    """Render the in-vault entry-point map. Pure + deterministic (no I/O)."""
    name = team.get("name") or team.get("id", "team")
    team_id = team.get("id", "")
    docs = [d for d in documents if (d.get("path") or "") and d.get("path") != LOCI_FILENAME]

    lines: list[str] = []
    lines.append(f"# {name} — 팀 맥락 지도")
    lines.append("")
    desc = (team.get("description") or "").strip()
    if desc:
        lines.append(desc)
        lines.append("")
    lines.append("이 파일은 piLoci가 자동으로 유지하는 팀의 시작점입니다. 어디서부터")
    lines.append("봐야 할지 모를 때 여기서 출발하세요. Obsidian으로 이 폴더를 열면")
    lines.append("`[[링크]]`가 그래프로 보이고, 에이전트는 같은 파일을 검색해 읽습니다.")
    lines.append("")

    lines.append("## 여기서 시작")
    lines.append("필요한 걸 자연어로 물으면 됩니다 — 경로를 몰라도 됩니다.")
    lines.append("")
    lines.append("```")
    lines.append('recall(team_id="' + team_id + '", query="결제 설계 어디 있어?")')
    lines.append("```")
    lines.append("")
    lines.append("관련 문서의 발췌만 토큰 한도 내로 돌려줍니다. 더 보고 싶으면 그 경로를")
    lines.append("이어서 물어보거나 `piloci pull` 로 받으세요.")
    lines.append("")

    # Document tree grouped by top-level folder for scan-ability.
    if docs:
        lines.append(f"## 문서 ({len(docs)}건)")
        groups: dict[str, list[str]] = {}
        for d in sorted(docs, key=lambda x: x.get("path") or ""):
            path = d["path"]
            top = path.split("/", 1)[0] if "/" in path else "(루트)"
            groups.setdefault(top, []).append(path)
        for top in sorted(groups):
            if top != "(루트)":
                lines.append(f"- **{top}/**")
                for p in groups[top]:
                    lines.append(f"  - {_wikilink(p)}")
            else:
                for p in groups[top]:
                    lines.append(f"- {_wikilink(p)}")
        lines.append("")
    else:
        lines.append("## 문서")
        lines.append("_아직 공유된 문서가 없습니다. `piloci push` 또는 웹에서 올려보세요._")
        lines.append("")

    if articles:
        lines.append(f"## 위키 ({len(articles)}건) — AI가 정리한 한국어 요약")
        for art in articles:
            slug = art.get("slug") or "article"
            title = art.get("title") or slug
            summary = (art.get("summary") or "").strip()
            line = f"- [[wiki/{slug}|{title}]]"
            if summary:
                line += f" — {summary}"
            lines.append(line)
        lines.append("")

    lines.append("---")
    # No timestamp here on purpose: the content must be a pure function of the
    # team's docs/articles so an unchanged team hashes identically and refresh
    # is idempotent (no version churn, no needless re-index). Freshness lives
    # in the row's updated_at.
    lines.append(
        "_piLoci가 자동으로 만들고 유지하는 진입점입니다. 팀 문서가 바뀌면 다시 그려집니다._"
    )
    return "\n".join(lines) + "\n"


async def refresh_team_index(store, team_id: str, *, settings) -> bool:
    """Rebuild ``LOCI.md`` for a team and persist it as a team document.

    Loads the team, its (non-deleted) documents, and wiki articles; renders the
    map; upserts the ``LOCI.md`` row (author = team owner); then schedules the
    search index so the map itself is recall-able. Fire-and-forget safe — any
    failure is logged, never raised.
    """
    try:
        from sqlalchemy import select

        from piloci.curator.team_doc_index import index_team_document
        from piloci.db.models import Team, TeamDocument, TeamWikiArticle
        from piloci.db.session import async_session

        async with async_session() as db:
            team_row = (
                await db.execute(select(Team).where(Team.id == team_id))
            ).scalar_one_or_none()
            if not team_row:
                return False

            doc_rows = (
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
            article_rows = (
                (
                    await db.execute(
                        select(TeamWikiArticle)
                        .where(TeamWikiArticle.team_id == team_id)
                        .order_by(TeamWikiArticle.category, TeamWikiArticle.title)
                    )
                )
                .scalars()
                .all()
            )

            team = {"id": team_row.id, "name": team_row.name, "description": team_row.description}
            documents = [
                {"path": d.path, "version": d.version, "is_binary": bool(d.is_binary)}
                for d in doc_rows
            ]
            articles = [
                {"slug": a.slug, "title": a.title, "summary": a.summary} for a in article_rows
            ]

            content = build_loci_md(team, documents, articles)
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            now = datetime.now(timezone.utc)

            existing = next((d for d in doc_rows if d.path == LOCI_FILENAME), None)
            if existing:
                if existing.content_hash == content_hash:
                    return True  # unchanged — skip churn
                existing.content = content
                existing.content_hash = content_hash
                existing.version = existing.version + 1
                existing.updated_by_id = team_row.owner_id
                existing.updated_at = now
                db.add(existing)
                doc_id = existing.id
            else:
                doc_id = str(uuid.uuid4())
                db.add(
                    TeamDocument(
                        id=doc_id,
                        team_id=team_id,
                        author_id=team_row.owner_id,
                        uploader_id=team_row.owner_id,
                        updated_by_id=team_row.owner_id,
                        path=LOCI_FILENAME,
                        content=content,
                        content_hash=content_hash,
                        version=1,
                        is_binary=False,
                        size=len(content.encode()),
                        updated_at=now,
                        created_at=now,
                        is_deleted=False,
                    )
                )

        # Index the map itself so "recall" can surface it. Outside the write tx.
        await index_team_document(store, team_id, doc_id, LOCI_FILENAME, content, settings=settings)
        return True
    except Exception:
        logger.exception("refresh_team_index failed team=%s", team_id)
        return False
