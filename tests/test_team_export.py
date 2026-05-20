"""Unit tests for the team bundle exporter.

Covers the pure functions (`_safe_path`, `_slugify_team_name`,
`build_index_md`, `build_wiki_article_md`) and the ZIP packer with a real
in-memory ZipFile so we exercise the actual archive shape.
"""

from __future__ import annotations

import io
import zipfile

from piloci.curator.team_export import (
    _safe_path,
    _slugify_team_name,
    build_index_md,
    build_wiki_article_md,
    pack_team_zip,
)


def test_safe_path_strips_leading_slash_and_parent_segments() -> None:
    assert _safe_path("/docs/a.md") == "docs/a.md"
    # `..` segments are stripped to prevent zip-slip when extracting.
    assert _safe_path("../etc/passwd") == "etc/passwd"
    # Repeated slashes and empty segments collapse.
    assert _safe_path("docs//api/auth.md") == "docs/api/auth.md"


def test_safe_path_keeps_hangul_and_collapses_unsafe() -> None:
    # Hangul is allowed so ZIPs remain readable in Korean.
    assert _safe_path("문서/회의록.md") == "문서/회의록.md"
    # Spaces and weird punctuation become underscores.
    assert _safe_path("a b/c!.md").endswith("c_.md")


def test_slugify_team_name_falls_back_when_empty() -> None:
    assert _slugify_team_name("YKO") == "YKO"
    assert _slugify_team_name("") == "team"
    assert _slugify_team_name("My Team!! 회의") == "My-Team-회의"


def test_build_index_md_lists_docs_and_articles_with_guide() -> None:
    team = {"id": "tid", "name": "YKO", "last_wiki_built_at": "2026-05-19T00:00:00"}
    documents = [
        {"path": "docs/a.md", "updated_at": "2026-05-19T01:00:00", "version": 3},
        {"path": "notes/m.md", "updated_at": "2026-05-19T02:00:00", "version": 1},
    ]
    articles = [
        {"slug": "intro", "title": "Intro", "summary": "한 줄 요약"},
        {"slug": "design", "title": "API Design", "summary": None},
    ]
    md = build_index_md(team, documents, articles, member_emails=["a@x.com", "b@x.com"])

    # Doc index links use relative paths so the README renders in any viewer.
    assert "[`docs/docs/a.md`]" in md
    assert "[`docs/notes/m.md`]" in md
    # Wiki index links + the article title.
    assert "[`wiki/intro.md`]" in md
    assert "**API Design**" in md
    # Guide block tells the agent how to extend the bundle.
    assert "## 더 채우려면" in md
    assert 'doc(team_id="tid"' in md
    assert 'memory(team_id="tid"' in md


def test_build_index_md_renders_empty_state() -> None:
    md = build_index_md({"id": "t", "name": "Empty"}, [], [], member_emails=[])
    assert "아직 공유된 문서가 없습니다" in md
    assert "아직 생성된 위키 아티클이 없습니다" in md


def test_build_wiki_article_md_includes_frontmatter_and_sources() -> None:
    article = {
        "title": "API 인증",
        "slug": "api-auth",
        "category": "folder/docs",
        "revision": 2,
        "generated_by": "glm",
        "summary": "JWT 흐름",
        "content": "본문…",
        "sources": [
            {"kind": "doc", "id": "d1", "title": "docs/api/auth.md"},
            {"kind": "memory", "id": "m1"},
        ],
    }
    md = build_wiki_article_md(article)
    assert md.startswith("---")
    assert 'slug: "api-auth"' in md
    assert "# API 인증" in md
    assert "JWT 흐름" in md
    # Sources surfaced as a "근거 자료" footer.
    assert "## 근거 자료" in md
    assert "docs/api/auth.md" in md
    assert "m1" in md


def test_pack_team_zip_layout() -> None:
    """The packed ZIP must include exactly the structure the agent expects:
    team-root/{index.md, docs/<original-paths>, wiki/<slug>.md}."""
    team = {"id": "tid", "name": "YKO"}
    documents = [
        {"path": "docs/api/auth.md", "content": "# auth body"},
        {"path": "notes.md", "content": "raw note"},
    ]
    articles = [
        {
            "slug": "intro",
            "title": "Intro",
            "summary": "s",
            "content": "body",
            "category": "folder/docs",
            "revision": 1,
            "generated_by": "glm",
            "sources": [],
        }
    ]
    filename, payload = pack_team_zip(team, documents, articles, ["a@x.com"])
    assert filename.endswith(".zip")
    assert filename.startswith("YKO")

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())
        assert "YKO/index.md" in names
        assert "YKO/docs/docs/api/auth.md" in names
        assert "YKO/docs/notes.md" in names
        assert "YKO/wiki/intro.md" in names
        # No AGENTS.md — index.md is the single entry point.
        assert "YKO/AGENTS.md" not in names

        # The agent's first read should mention how to add content.
        index_body = zf.read("YKO/index.md").decode("utf-8")
        assert "더 채우려면" in index_body
        assert zf.read("YKO/docs/docs/api/auth.md").decode("utf-8") == "# auth body"


def test_pack_team_zip_writes_binary_bytes_at_path(tmp_path) -> None:
    """A binary doc's real bytes (read from the blob store via storage_key)
    land at its path inside the ZIP — not its empty inline content."""
    from piloci.storage.team_files import save_blob

    team = {"id": "tid", "name": "YKO"}
    blob = b"\x89PNG\r\n\x1a\n binary payload \x00\xff"
    _sha, storage_key, _size = save_blob(tmp_path, "tid", blob)

    documents = [
        {"path": "docs/text.md", "content": "# text body"},
        {
            "path": "assets/logo.png",
            "content": "",
            "is_binary": True,
            "storage_key": storage_key,
        },
    ]
    _, payload = pack_team_zip(team, documents, [], [], team_files_dir=tmp_path)

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())
        assert "YKO/docs/docs/text.md" in names
        assert "YKO/docs/assets/logo.png" in names
        # Real bytes, not the empty inline content.
        assert zf.read("YKO/docs/assets/logo.png") == blob


def test_pack_team_zip_skips_missing_blob(tmp_path) -> None:
    """A binary doc whose blob is gone (deleted/never written) is silently
    skipped — the bundle still builds with the remaining files."""
    team = {"id": "tid", "name": "YKO"}
    documents = [
        {"path": "kept.md", "content": "ok"},
        {
            "path": "gone.bin",
            "content": "",
            "is_binary": True,
            # Valid-shaped key, but no blob on disk → FileNotFoundError → skip.
            "storage_key": "tid/" + ("a" * 64),
        },
    ]
    _, payload = pack_team_zip(team, documents, [], [], team_files_dir=tmp_path)

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())
        assert "YKO/docs/kept.md" in names
        assert "YKO/docs/gone.bin" not in names


def test_pack_team_zip_skips_blank_paths_and_slugs() -> None:
    """Empty path or slug rows shouldn't blow up the packer — they're just
    silently dropped, since the alternative is a zip entry with no name."""
    team = {"id": "t", "name": "X"}
    docs = [
        {"path": "", "content": "ignored"},
        {"path": "kept.md", "content": "ok"},
    ]
    arts = [
        {"slug": "", "title": "Bad", "content": "x"},
        {"slug": "good", "title": "Good", "content": "y"},
    ]
    _, payload = pack_team_zip(team, docs, arts, [])
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
        assert "X/docs/kept.md" in names
        assert "X/wiki/good.md" in names
        assert all(not n.endswith("/docs/") for n in names)
        assert all(not n.endswith("/wiki/.md") for n in names)
