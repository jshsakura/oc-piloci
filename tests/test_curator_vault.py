from __future__ import annotations

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
