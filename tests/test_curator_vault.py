from __future__ import annotations

from piloci.curator.team_vault import build_team_vault
from piloci.curator.vault import build_project_vault


def test_build_project_vault_creates_obsidian_ready_notes_and_graph() -> None:
    project = {"id": "p1", "slug": "alpha-lab", "name": "Alpha Lab"}
    memories = [
        {
            "id": "mem-12345678",
            "content": "Use [[Vector Search]] for semantic recall.",
            "tags": ["search", "rag"],
            "metadata": {"title": "Semantic Recall"},
            "created_at": 1710000000,
            "updated_at": 1710000100,
        }
    ]

    vault = build_project_vault(project, memories)

    assert vault["root"] == "vaults/alpha-lab"
    assert vault["stats"]["notes"] == 1
    assert vault["stats"]["edges"] == 4

    note = vault["notes"][0]
    assert note["title"] == "Semantic Recall"
    assert note["path"] == "memories/semantic-recall-mem-1234.md"
    assert "[[search]]" in note["markdown"]
    assert "[[Vector Search]]" in note["markdown"]

    node_kinds = {node["kind"] for node in vault["graph"]["nodes"]}
    assert node_kinds == {"project", "note", "tag", "topic"}


def test_build_project_vault_deduplicates_repeated_links() -> None:
    project = {"id": "p1", "slug": "beta", "name": "Beta"}
    memories = [
        {
            "id": "mem-abcdefgh",
            "content": "Repeat [[Python]] and [[Python]] again.",
            "tags": ["python"],
            "metadata": {},
            "created_at": 1,
            "updated_at": 2,
        }
    ]

    vault = build_project_vault(project, memories)
    link_edges = [edge for edge in vault["graph"]["edges"] if edge["kind"] == "links"]

    assert len(link_edges) == 1
    assert vault["notes"][0]["links"] == ["Python"]


def _team() -> dict:
    return {"id": "t1", "name": "Team One"}


def test_build_team_vault_without_articles_is_unchanged() -> None:
    documents = [{"id": "d1", "path": "docs/auth.md", "content": "auth notes"}]
    base = build_team_vault(_team(), [], documents)
    none_explicit = build_team_vault(_team(), [], documents, articles=None)
    empty = build_team_vault(_team(), [], documents, articles=[])

    # No article nodes regardless of how the absent arg is spelled.
    for vault in (base, none_explicit, empty):
        kinds = {n["kind"] for n in vault["graph"]["nodes"]}
        assert "article" not in kinds

    # Graph shape is identical to the legacy 3-arg call.
    assert base["graph"]["nodes"] == empty["graph"]["nodes"]
    assert base["graph"]["edges"] == empty["graph"]["edges"]


def test_build_team_vault_adds_article_node_and_source_edge() -> None:
    documents = [{"id": "d1", "path": "docs/auth.md", "content": "auth notes"}]
    memories = [{"id": "m1", "content": "session handling", "metadata": {"title": "Sessions"}}]
    articles = [
        {
            "slug": "auth-guide",
            "title": "Auth Guide",
            "category": "security",
            "summary": "How auth works",
            "content": "See the docs.",
            "sources": [
                {"kind": "doc", "id": "d1"},
                {"kind": "memory", "id": "m1"},
                # Dangling source — node does not exist, so no edge.
                {"kind": "doc", "id": "ghost"},
            ],
        }
    ]

    vault = build_team_vault(_team(), memories, documents, articles=articles)
    nodes = {n["id"]: n for n in vault["graph"]["nodes"]}

    assert "article:auth-guide" in nodes
    article_node = nodes["article:auth-guide"]
    assert article_node["kind"] == "article"
    assert article_node["label"] == "Auth Guide"
    assert article_node["slug"] == "auth-guide"
    assert article_node["category"] == "security"
    assert article_node["summary"] == "How auth works"

    source_edges = {
        (e["source"], e["target"]) for e in vault["graph"]["edges"] if e["kind"] == "source"
    }
    assert ("article:auth-guide", "doc:d1") in source_edges
    assert ("article:auth-guide", "memory:m1") in source_edges
    # Dangling source produced no edge.
    assert all("ghost" not in tgt for _, tgt in source_edges)


def test_build_team_vault_links_articles_via_wikilinks() -> None:
    articles = [
        {
            "slug": "auth-guide",
            "title": "Auth Guide",
            "category": "security",
            "summary": "",
            "content": "Pairs with [[Session Model]] for the full picture.",
            "sources": [],
        },
        {
            "slug": "session-model",
            "title": "Session Model",
            "category": "security",
            "summary": "",
            "content": "Standalone.",
            "sources": [],
        },
    ]

    vault = build_team_vault(_team(), [], [], articles=articles)
    wikilink_edges = {
        (e["source"], e["target"]) for e in vault["graph"]["edges"] if e["kind"] == "wikilink"
    }

    # Title match (case-insensitive) resolves to the other article's slug.
    assert ("article:auth-guide", "article:session-model") in wikilink_edges
    # No self-link, no edge for the article with no matching wikilink.
    assert ("article:session-model", "article:session-model") not in wikilink_edges
