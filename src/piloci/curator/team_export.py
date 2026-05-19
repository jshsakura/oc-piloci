from __future__ import annotations

"""Team bundle exporter.

Packs everything a team has — original documents at their stored paths plus
the GLM-distilled wiki articles plus a single ``index.md`` that doubles as
briefing + table of contents + "how to add more" guide — into one ZIP.

Layout inside the ZIP::

    {team_name}/
        index.md           # entry point: TOC + agent guide + how-to-add
        docs/              # team_documents, original paths preserved
            api/auth.md
            notes/meeting.md
        wiki/              # GLM-distilled articles, slug-based
            intro.md
            api-design.md

One file at the root, not two — the agent reads ``index.md`` first, follows
links into ``docs/`` and ``wiki/`` for the actual content, and gets explicit
guidance at the bottom on how to extend the bundle (upload a doc, fold a
memory in, regenerate the wiki).

The exporter is intentionally pure: it takes already-fetched rows and returns
bytes. Route handlers do the SQL + auth + streaming wrapper.
"""

import io
import re
import zipfile
from datetime import datetime, timezone
from typing import Any, Iterable

_SAFE_PATH_RE = re.compile(r"[^A-Za-z0-9가-힣._\-/]+")


def _safe_path(path: str) -> str:
    """Coerce a stored path into something a filesystem will accept.

    Hangul stays so the ZIP file names are still readable in Korean. Anything
    else weird collapses to ``_``. Leading slashes and ``..`` segments are
    stripped to prevent zip-slip when the user/agent extracts.
    """
    cleaned = _SAFE_PATH_RE.sub("_", path.strip().lstrip("/"))
    return "/".join(part for part in cleaned.split("/") if part and part != "..")


def _slugify_team_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9가-힣]+", "-", (name or "team").strip()).strip("-")
    return cleaned[:60] or "team"


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()  # type: ignore[no-any-return]
        except Exception:
            return str(value)
    return str(value)


# ---------------------------------------------------------------------------
# Markdown builders
# ---------------------------------------------------------------------------


def build_index_md(
    team: dict[str, Any],
    documents: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    member_emails: list[str],
) -> str:
    """Single entry-point file. Order: brief → docs index → wiki index →
    팀 정보 → how-to-extend guide. The agent (or human) needs only this to
    navigate the bundle and to know what next step is available.
    """
    name = team.get("name") or team.get("id", "team")
    team_id = team.get("id", "")
    lines: list[str] = []

    lines.append(f"# {name} — 팀 지식 묶음")
    lines.append("")
    lines.append("이 묶음은 piLoci가 내려준 팀 공유 자료입니다. 사람이 직접 올린")
    lines.append("문서(`docs/`)와 GLM-5.1이 한국어로 정리한 위키(`wiki/`)가 한 벌로")
    lines.append("들어 있어요. 같은 내용을 원본/증류 두 결로 볼 수 있도록 설계했습니다.")
    lines.append("")
    lines.append("**먼저 읽기**")
    lines.append("- 빠르게 훑고 싶다면 → `wiki/` (한국어 요약 아티클)")
    lines.append("- 원문 그대로 보려면 → `docs/` (사용자가 올린 경로 그대로)")
    lines.append("")

    if documents:
        lines.append(f"## 문서 ({len(documents)}건)")
        for doc in sorted(documents, key=lambda d: d.get("path") or ""):
            path = doc.get("path") or ""
            if not path:
                continue
            updated = _isoformat(doc.get("updated_at"))
            version = doc.get("version")
            tail: list[str] = []
            if version:
                tail.append(f"v{version}")
            if updated:
                tail.append(updated)
            suffix = f" _({', '.join(tail)})_" if tail else ""
            lines.append(f"- [`docs/{path}`](docs/{path}){suffix}")
        lines.append("")
    else:
        lines.append("## 문서")
        lines.append("_아직 공유된 문서가 없습니다._")
        lines.append("")

    if articles:
        lines.append(f"## 위키 ({len(articles)}건)")
        for art in articles:
            slug = art.get("slug") or "article"
            title = art.get("title") or slug
            summary = (art.get("summary") or "").strip()
            line = f"- [`wiki/{slug}.md`](wiki/{slug}.md) — **{title}**"
            if summary:
                line += f" — {summary}"
            lines.append(line)
        lines.append("")
    else:
        lines.append("## 위키")
        lines.append("_아직 생성된 위키 아티클이 없습니다._")
        lines.append("")

    lines.append("## 팀 정보")
    lines.append(f"- 멤버: {len(member_emails)}명")
    if member_emails:
        lines.append("  " + ", ".join(member_emails))
    last_built = team.get("last_wiki_built_at")
    if last_built:
        lines.append(f"- 마지막 위키 빌드: {last_built}")
    lines.append(f"- 묶음 생성: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")

    lines.append("## 더 채우려면")
    lines.append("이 묶음은 매일 새벽 다시 빌드됩니다. 내용을 더 늘리려면 다음 중 하나:")
    lines.append("")
    lines.append("1. **공용 문서 업로드** — 팀 멤버라면 piLoci 웹 또는 MCP `doc` 툴로")
    lines.append(f"   `team_id`(`{team_id}`)와 `path`를 함께 보내면 `docs/`에 그대로 들어갑니다.")
    lines.append("   ```")
    lines.append(f'   doc(team_id="{team_id}", path="docs/주제/이름.md", content="...")')
    lines.append("   ```")
    lines.append("2. **팀 메모리 추가** — 짧은 결정·메모는 `memory` 툴로.")
    lines.append("   ```")
    lines.append(f'   memory(team_id="{team_id}", content="결정 내용", tags=["plan"])')
    lines.append("   ```")
    lines.append('3. **위키 즉시 재생성** — 웹에서 "지금 생성" 버튼, 또는 owner가')
    lines.append(f"   `POST /api/teams/{team_id}/wiki/build` 호출. 새벽까지 안 기다려도 됨.")
    lines.append("")
    lines.append("위키 아티클 본문 안에 `[[다른 토픽]]` 표기가 있으면, 같은 묶음 안의")
    lines.append("아티클로 자동 연결됩니다. 새 토픽이 필요하면 위 1~2번으로 자료부터")
    lines.append("쌓아두면 다음 빌드에서 위키가 그 토픽을 만듭니다.")
    lines.append("")
    lines.append("---")
    lines.append("_이 묶음은 piLoci에서 자동 생성됐습니다. 최신 데이터는 웹에서 확인하세요._")
    lines.append("")
    return "\n".join(lines)


def build_wiki_article_md(article: dict[str, Any]) -> str:
    """Wiki article as a stand-alone markdown file with frontmatter."""
    fm = ["---"]
    for key in ("title", "slug", "category", "revision", "generated_by", "updated_at"):
        value = article.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            safe = value.replace('"', "'")
            fm.append(f'{key}: "{safe}"')
        else:
            fm.append(f"{key}: {value}")
    fm.append("source: piloci-wiki")
    fm.append("---")
    body_parts = ["\n".join(fm), ""]

    title = article.get("title") or article.get("slug") or "Article"
    body_parts.append(f"# {title}")
    body_parts.append("")
    if article.get("summary"):
        body_parts.append(article["summary"])
        body_parts.append("")
    body_parts.append(article.get("content") or "_빈 본문_")

    sources = article.get("sources") or []
    if sources:
        body_parts.append("")
        body_parts.append("---")
        body_parts.append("## 근거 자료")
        for src in sources:
            kind = src.get("kind") or "?"
            sid = src.get("id") or "?"
            title = src.get("title") or sid
            body_parts.append(f"- `[{kind}]` {title}")
        body_parts.append("")

    return "\n".join(body_parts)


# ---------------------------------------------------------------------------
# ZIP packing
# ---------------------------------------------------------------------------


def pack_team_zip(
    team: dict[str, Any],
    documents: Iterable[dict[str, Any]],
    articles: list[dict[str, Any]],
    member_emails: list[str],
) -> tuple[str, bytes]:
    """Build the ZIP in memory; return ``(filename, bytes)``.

    Pi 5 RAM is fine for typical team sizes (single-digit MB). If a team
    ever crosses ~50MB worth of docs we can swap to a streamed writer; for
    now keeping it simple wins.
    """
    docs = list(documents)
    team_slug = _slugify_team_name(team.get("name") or team.get("id", "team"))
    root = team_slug

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Single entry-point file at root — index.md doubles as the agent
        # briefing and the table of contents.
        zf.writestr(
            f"{root}/index.md",
            build_index_md(team, docs, articles, member_emails),
        )

        for doc in docs:
            path = _safe_path(doc.get("path") or "")
            if not path:
                continue
            content = doc.get("content") or ""
            zf.writestr(f"{root}/docs/{path}", content)

        for art in articles:
            slug = _safe_path(art.get("slug") or "article")
            if not slug:
                continue
            zf.writestr(f"{root}/wiki/{slug}.md", build_wiki_article_md(art))

    filename = f"{team_slug}-bundle.zip"
    return filename, buf.getvalue()
