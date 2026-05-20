"""Unit tests for the team workspace builder.

The builder is pure (no I/O outside the cache helpers) so these tests stay
fast and don't need an event loop or database. They cover three things:

1. graph shape — that team → folder → doc edges form a real tree
2. memory branch — tags become nodes, [[wikilinks]] become topic edges
3. cache round-trip — save/load/merge_wiki_articles keep the JSON intact
"""

from __future__ import annotations

from pathlib import Path

import pytest

from piloci.curator.team_vault import (
    _folder_chain,
    _slugify,
    build_team_vault,
    invalidate_team_vault_cache,
    load_cached_team_vault,
    merge_wiki_articles,
    save_team_vault,
)


def test_folder_chain_drops_filename_component() -> None:
    assert _folder_chain("docs/api/auth.md") == ["docs", "docs/api"]
    assert _folder_chain("notes.md") == []
    assert _folder_chain("") == []
    # Leading slash should be ignored, not crash.
    assert _folder_chain("/a/b/c.md") == ["a", "a/b"]


def test_slugify_collapses_non_alpha_and_falls_back_for_empty() -> None:
    # Graph-node slugs are ASCII-only here (Hangul is the wiki-article
    # slugify's job in team_wiki_worker, not this one).
    assert _slugify("api! design$$ notes") == "api-design-notes"
    assert _slugify("") == "node"  # fallback default


def _doc(doc_id: str, path: str, content: str = "") -> dict:
    return {
        "id": doc_id,
        "path": path,
        "content": content,
        "version": 1,
        "updated_at": "2026-05-19T00:00:00",
    }


def _memory(memory_id: str, content: str, tags: list[str]) -> dict:
    return {
        "id": memory_id,
        "content": content,
        "tags": tags,
        "metadata": {"author_id": "alice"},
        "created_at": 1,
        "updated_at": 2,
    }


def test_build_team_vault_assembles_folder_tree_and_doc_nodes() -> None:
    team = {"id": "team-1", "name": "YKO"}
    workspace = build_team_vault(
        team,
        memories=[],
        documents=[_doc("d1", "docs/api/auth.md", "auth")],
    )

    node_ids = {n["id"] for n in workspace["graph"]["nodes"]}
    assert "team:team-1" in node_ids
    assert "folder:docs" in node_ids
    assert "folder:docs/api" in node_ids
    assert "doc:d1" in node_ids

    edges = {(e["source"], e["target"]) for e in workspace["graph"]["edges"]}
    assert ("team:team-1", "folder:docs") in edges
    assert ("folder:docs", "folder:docs/api") in edges
    assert ("folder:docs/api", "doc:d1") in edges

    # Note list surfaces the doc with a download_url pointing at the raw route.
    doc_note = next(n for n in workspace["notes"] if n["kind"] == "doc")
    assert doc_note["title"] == "auth.md"
    assert doc_note["download_url"].endswith("/documents/d1/raw")


def test_build_team_vault_renders_binary_doc_as_file_node() -> None:
    """A binary doc becomes a ``file`` node (downloadable, with mime/size) and
    its empty body never spawns topic edges or an excerpt note."""
    team = {"id": "team-bin", "name": "YKO"}
    workspace = build_team_vault(
        team,
        memories=[],
        documents=[
            {
                "id": "b1",
                "path": "assets/logo.png",
                "content": "",
                "version": 1,
                "updated_at": "2026-05-19T00:00:00",
                "is_binary": True,
                "mime": "image/png",
                "size": 4096,
            }
        ],
    )

    nodes = {n["id"]: n for n in workspace["graph"]["nodes"]}
    assert "doc:b1" in nodes
    assert nodes["doc:b1"]["kind"] == "file"
    assert nodes["doc:b1"]["mime"] == "image/png"
    assert nodes["doc:b1"]["size"] == 4096
    assert nodes["doc:b1"]["download_url"].endswith("/documents/b1/raw")

    # No topic nodes/edges from an empty body.
    assert not any(nid.startswith("topic:") for nid in nodes)

    file_note = next(n for n in workspace["notes"] if n["kind"] == "file")
    assert file_note["path"] == "assets/logo.png"
    assert "excerpt" not in file_note
    # Binary still counts toward the document tally.
    assert workspace["stats"]["documents"] == 1


def test_build_team_vault_binary_doc_does_not_crash_without_mime() -> None:
    """Missing mime/size on a binary doc is tolerated — no KeyError."""
    workspace = build_team_vault(
        {"id": "t", "name": "T"},
        memories=[],
        documents=[{"id": "b", "path": "x.bin", "is_binary": True}],
    )
    note = next(n for n in workspace["notes"] if n["kind"] == "file")
    assert note["mime"] is None


def test_build_team_vault_emits_tag_and_wikilink_edges_for_memories() -> None:
    team = {"id": "team-2", "name": "Team"}
    workspace = build_team_vault(
        team,
        memories=[_memory("m1", "see [[Onboarding]] for details", ["docs", "guide"])],
        documents=[],
    )

    node_ids = {n["id"] for n in workspace["graph"]["nodes"]}
    assert "memory:m1" in node_ids
    assert "tag:docs" in node_ids
    assert "tag:guide" in node_ids
    # [[Onboarding]] turns into a topic node, slugified.
    assert any(nid.startswith("topic:onboarding") for nid in node_ids)

    edge_kinds = {(e["source"], e["kind"]) for e in workspace["graph"]["edges"]}
    assert ("memory:m1", "tagged") in edge_kinds
    assert ("memory:m1", "links") in edge_kinds


def test_build_team_vault_reserves_empty_wiki_articles_slot() -> None:
    workspace = build_team_vault({"id": "team-3"}, [], [])
    assert workspace["wiki_articles"] == []
    assert workspace["stats"]["nodes"] >= 1  # team node always present


def test_save_load_round_trip(tmp_path: Path) -> None:
    workspace = build_team_vault({"id": "team-cache"}, [], [_doc("d", "a.md")])
    save_team_vault(tmp_path, "team-cache", workspace)

    loaded = load_cached_team_vault(tmp_path, "team-cache")
    assert loaded is not None
    assert loaded["root"] == workspace["root"]
    assert loaded["graph"]["nodes"][0]["id"] == workspace["graph"]["nodes"][0]["id"]


def test_load_returns_none_when_cache_missing(tmp_path: Path) -> None:
    assert load_cached_team_vault(tmp_path, "absent") is None


def test_merge_wiki_articles_patches_existing_cache(tmp_path: Path) -> None:
    workspace = build_team_vault({"id": "team-patch"}, [], [])
    save_team_vault(tmp_path, "team-patch", workspace)

    articles = [{"slug": "intro", "title": "Intro", "revision": 1}]
    merged = merge_wiki_articles(tmp_path, "team-patch", articles)

    assert merged is not None
    assert merged["wiki_articles"] == articles
    assert "wiki_built_at" in merged

    # Re-read from disk to confirm the patch persisted.
    again = load_cached_team_vault(tmp_path, "team-patch")
    assert again is not None
    assert again["wiki_articles"] == articles


def test_merge_wiki_articles_returns_none_when_cache_absent(tmp_path: Path) -> None:
    assert merge_wiki_articles(tmp_path, "missing", []) is None


@pytest.mark.asyncio
async def test_invalidate_team_vault_cache_removes_file(tmp_path: Path) -> None:
    workspace = build_team_vault({"id": "team-x"}, [], [])
    save_team_vault(tmp_path, "team-x", workspace)
    assert load_cached_team_vault(tmp_path, "team-x") is not None

    await invalidate_team_vault_cache(tmp_path, "team-x")
    assert load_cached_team_vault(tmp_path, "team-x") is None


@pytest.mark.asyncio
async def test_invalidate_team_vault_cache_is_fail_open(tmp_path: Path) -> None:
    # Should not raise even if no cached file exists for this team.
    await invalidate_team_vault_cache(tmp_path, "never-saved")
