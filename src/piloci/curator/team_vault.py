from __future__ import annotations

"""Team workspace builder — graph + folder tree from team memories and docs.

Mirrors the per-project ``vault.py`` shape so the same frontend renderer can
draw both. Two extras specific to teams:

1. ``team_documents`` rows carry a ``path`` so we build folder nodes that the
   client can render as a tree. e.g. ``docs/api/auth.md`` becomes
   folder:docs → folder:docs/api → doc:<id>.
2. A ``wiki_articles`` slot is reserved on the workspace dict. The
   ``team_wiki_worker`` (GLM-backed) fills it on demand; until then it stays
   an empty list so the UI shows "위키 생성하기" CTA.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import orjson

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str, fallback: str = "node") -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or fallback


def _coerce_tags(item: dict[str, Any]) -> list[str]:
    tags = item.get("tags") or []
    return [str(tag).strip() for tag in tags if str(tag).strip()]


def _extract_links(content: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for match in _WIKILINK_RE.findall(content or ""):
        label = match.strip()
        if label and label not in seen:
            seen.add(label)
            out.append(label)
    return out


def _title_from_memory(memory: dict[str, Any]) -> str:
    metadata = memory.get("metadata") or {}
    for key in ("doc_title", "title", "name", "topic", "summary"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    content = (memory.get("content") or "").strip()
    return (content.splitlines()[0].strip() if content else "Untitled")[:80] or "Untitled"


def _folder_chain(path: str) -> list[str]:
    """`docs/api/auth.md` → [`docs`, `docs/api`]. File component dropped."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return []
    folders: list[str] = []
    for i in range(1, len(parts)):
        folders.append("/".join(parts[:i]))
    return folders


def build_team_vault(
    team: dict[str, Any],
    memories: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble graph + notes + folder tree for a team workspace."""

    generated_at = datetime.now(timezone.utc).isoformat()
    notes: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    edge_keys: set[tuple[str, str, str]] = set()

    def add_node(node_id: str, label: str, kind: str, **extra: Any) -> None:
        if node_id in node_ids:
            return
        node_ids.add(node_id)
        node = {"id": node_id, "label": label, "kind": kind}
        node.update(extra)
        nodes.append(node)

    def add_edge(source: str, target: str, kind: str) -> None:
        key = (source, target, kind)
        if key in edge_keys:
            return
        edge_keys.add(key)
        edges.append({"source": source, "target": target, "kind": kind})

    team_id = team["id"]
    team_node_id = f"team:{team_id}"
    add_node(team_node_id, team.get("name") or team_id, "team", team_id=team_id)

    # ---- Team documents (path-structured) --------------------------------
    sorted_docs = sorted(documents, key=lambda d: d.get("path") or "")
    for doc in sorted_docs:
        path = doc.get("path") or ""
        if not path:
            continue
        doc_id = str(doc.get("id") or "")
        if not doc_id:
            continue

        # Build folder chain so the graph mirrors the filesystem.
        prev = team_node_id
        for folder_path in _folder_chain(path):
            folder_node_id = f"folder:{folder_path}"
            label = folder_path.rsplit("/", 1)[-1] or folder_path
            add_node(folder_node_id, label, "folder", path=folder_path)
            add_edge(prev, folder_node_id, "contains")
            prev = folder_node_id

        is_binary = bool(doc.get("is_binary"))
        doc_node_id = f"doc:{doc_id}"
        filename = path.rsplit("/", 1)[-1] or path
        # Binary uploads (PDF/img/zip) have no inline text — render them as
        # ``file`` nodes (downloadable, no body) and skip wiki-link parsing so
        # an empty body never spawns phantom topic edges.
        if is_binary:
            add_node(
                doc_node_id,
                filename,
                "file",
                path=path,
                doc_id=doc_id,
                version=doc.get("version"),
                mime=doc.get("mime"),
                size=doc.get("size"),
                download_url=f"/api/teams/{team_id}/documents/{doc_id}/raw",
            )
            add_edge(prev, doc_node_id, "contains")
            notes.append(
                {
                    "kind": "file",
                    "doc_id": doc_id,
                    "title": filename,
                    "path": path,
                    "version": doc.get("version"),
                    "mime": doc.get("mime"),
                    "size": doc.get("size"),
                    "author_email": doc.get("author_email"),
                    "updated_at": (
                        doc["updated_at"].isoformat()
                        if hasattr(doc.get("updated_at"), "isoformat")
                        else str(doc.get("updated_at") or "")
                    ),
                    "download_url": f"/api/teams/{team_id}/documents/{doc_id}/raw",
                }
            )
            continue

        add_node(
            doc_node_id,
            filename,
            "doc",
            path=path,
            doc_id=doc_id,
            version=doc.get("version"),
            download_url=f"/api/teams/{team_id}/documents/{doc_id}/raw",
        )
        add_edge(prev, doc_node_id, "contains")

        # Wiki-link backrefs inside content also become topic nodes — the
        # team-wiki worker can later turn the topic into a full article.
        for link in _extract_links(doc.get("content") or ""):
            topic_node_id = f"topic:{_slugify(link, fallback='topic')}"
            add_node(topic_node_id, link, "topic")
            add_edge(doc_node_id, topic_node_id, "links")

        notes.append(
            {
                "kind": "doc",
                "doc_id": doc_id,
                "title": filename,
                "path": path,
                "version": doc.get("version"),
                "author_email": doc.get("author_email"),
                "updated_at": (
                    doc["updated_at"].isoformat()
                    if hasattr(doc.get("updated_at"), "isoformat")
                    else str(doc.get("updated_at") or "")
                ),
                "excerpt": (doc.get("content") or "")[:180],
                "download_url": f"/api/teams/{team_id}/documents/{doc_id}/raw",
            }
        )

    # ---- Team semantic memories (raw + saved with doc tool team scope) ---
    sorted_memories = sorted(memories, key=lambda m: m.get("updated_at", 0), reverse=True)
    for memory in sorted_memories:
        memory_id = str(memory.get("id") or memory.get("memory_id") or "")
        if not memory_id:
            continue
        title = _title_from_memory(memory)
        tags = _coerce_tags(memory)
        content = (memory.get("content") or "").strip()
        links = _extract_links(content)

        note_node_id = f"memory:{memory_id}"
        add_node(note_node_id, title, "note", memory_id=memory_id)
        add_edge(team_node_id, note_node_id, "contains")

        for tag in tags:
            tag_node_id = f"tag:{_slugify(tag, fallback='tag')}"
            add_node(tag_node_id, tag, "tag")
            add_edge(note_node_id, tag_node_id, "tagged")

        for link in links:
            topic_node_id = f"topic:{_slugify(link, fallback='topic')}"
            add_node(topic_node_id, link, "topic")
            add_edge(note_node_id, topic_node_id, "links")

        notes.append(
            {
                "kind": "memory",
                "memory_id": memory_id,
                "title": title,
                "tags": tags,
                "links": links,
                "excerpt": content[:180],
                "author_id": (memory.get("metadata") or {}).get("author_id"),
                "created_at": memory.get("created_at"),
                "updated_at": memory.get("updated_at"),
            }
        )

    return {
        "root": f"teams/{team_id}",
        "team": {
            "id": team_id,
            "name": team.get("name"),
            "auto_wiki_enabled": bool(team.get("auto_wiki_enabled")),
            "last_wiki_built_at": team.get("last_wiki_built_at"),
        },
        "generated_at": generated_at,
        "stats": {
            "documents": sum(1 for n in notes if n["kind"] in ("doc", "file")),
            "memories": sum(1 for n in notes if n["kind"] == "memory"),
            "nodes": len(nodes),
            "edges": len(edges),
        },
        "notes": notes,
        "graph": {"nodes": nodes, "edges": edges},
        # Filled by team_wiki_worker. Empty list means "not yet generated";
        # UI shows the 'AI 위키 생성하기' CTA in that case.
        "wiki_articles": [],
    }


# ---------------------------------------------------------------------------
# Cache (mirrors vault.py shape)
# ---------------------------------------------------------------------------


def _team_vault_dir(vault_dir: Path, team_id: str) -> Path:
    return vault_dir / f"team_{team_id}"


def _team_vault_path(vault_dir: Path, team_id: str) -> Path:
    return _team_vault_dir(vault_dir, team_id) / "vault.json"


def load_cached_team_vault(vault_dir: Path, team_id: str) -> dict[str, Any] | None:
    path = _team_vault_path(vault_dir, team_id)
    if not path.is_file():
        return None
    try:
        return orjson.loads(path.read_bytes())
    except (orjson.JSONDecodeError, ValueError):
        return None


def save_team_vault(vault_dir: Path, team_id: str, workspace: dict[str, Any]) -> None:
    team_dir = _team_vault_dir(vault_dir, team_id)
    team_dir.mkdir(parents=True, exist_ok=True)
    _team_vault_path(vault_dir, team_id).write_bytes(orjson.dumps(workspace))


def merge_wiki_articles(
    vault_dir: Path, team_id: str, articles: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Patch ``wiki_articles`` into the cached vault without rebuilding the
    graph. Returns the merged dict or None if the cache is missing."""
    cached = load_cached_team_vault(vault_dir, team_id)
    if cached is None:
        return None
    cached["wiki_articles"] = articles
    cached["wiki_built_at"] = datetime.now(timezone.utc).isoformat()
    save_team_vault(vault_dir, team_id, cached)
    return cached


async def invalidate_team_vault_cache(vault_dir: Path, team_id: str) -> None:
    """Drop the cached file so the next workspace GET rebuilds. Called by
    handlers that mutate team memories or documents."""
    try:
        path = _team_vault_path(vault_dir, team_id)
        if path.is_file():
            path.unlink()
    except OSError:
        pass
