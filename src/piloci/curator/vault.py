from __future__ import annotations

import io
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import orjson

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str, fallback: str = "note") -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or fallback


def _title_from_memory(memory: dict[str, Any]) -> str:
    metadata = memory.get("metadata") or {}
    for key in ("title", "name", "topic", "summary"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]

    content = (memory.get("content") or "").strip()
    first_line = content.splitlines()[0].strip() if content else "Untitled memory"
    return first_line[:80] or "Untitled memory"


def _extract_links(content: str) -> list[str]:
    seen: set[str] = set()
    links: list[str] = []
    for match in _WIKILINK_RE.findall(content):
        label = match.strip()
        if label and label not in seen:
            seen.add(label)
            links.append(label)
    return links


def _coerce_tags(memory: dict[str, Any]) -> list[str]:
    tags = memory.get("tags") or []
    return [str(tag).strip() for tag in tags if str(tag).strip()]


def _frontmatter(
    title: str, memory_id: str, created_at: str, updated_at: str, tags: list[str]
) -> str:
    lines = [
        "---",
        f'title: "{title.replace(chr(34), chr(39))}"',
        f'memory_id: "{memory_id}"',
        f'created_at: "{created_at}"',
        f'updated_at: "{updated_at}"',
        "tags:",
    ]
    if tags:
        lines.extend([f"  - {tag}" for tag in tags])
    else:
        lines.append("  - inbox")
    lines.extend(
        [
            "source: piloci",
            "---",
        ]
    )
    return "\n".join(lines)


def build_project_vault(project: dict[str, Any], memories: list[dict[str, Any]]) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    notes: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    edge_keys: set[tuple[str, str, str]] = set()
    _tag_count: int = 0

    def add_node(node_id: str, label: str, kind: str, **extra: Any) -> None:
        nonlocal _tag_count
        if node_id in node_ids:
            return
        node_ids.add(node_id)
        node = {"id": node_id, "label": label, "kind": kind}
        node.update(extra)
        nodes.append(node)
        if kind == "tag":
            _tag_count += 1

    def add_edge(source: str, target: str, kind: str) -> None:
        key = (source, target, kind)
        if key in edge_keys:
            return
        edge_keys.add(key)
        edges.append({"source": source, "target": target, "kind": kind})

    project_node_id = f'project:{project["slug"]}'
    add_node(project_node_id, project["name"], "project", slug=project["slug"])

    sorted_memories = sorted(memories, key=lambda item: item.get("updated_at", 0), reverse=True)
    for memory in sorted_memories:
        memory_id = str(memory.get("id") or memory.get("memory_id") or "")
        if not memory_id:
            continue

        title = _title_from_memory(memory)
        tags = _coerce_tags(memory)
        content = (memory.get("content") or "").strip()
        links = _extract_links(content)
        file_slug = _slugify(title, fallback=memory_id[:8])
        created_at = str(memory.get("created_at") or "")
        updated_at = str(memory.get("updated_at") or "")
        path = f"memories/{file_slug}-{memory_id[:8]}.md"

        related_links = [f"[[{tag}]]" for tag in tags]
        related_links.extend([f"[[{link}]]" for link in links if link not in tags])
        related_block = ""
        if related_links:
            related_block = "\n\n## Related\n" + "\n".join(f"- {link}" for link in related_links)

        note = {
            "memory_id": memory_id,
            "title": title,
            "path": path,
            "created_at": created_at,
            "updated_at": updated_at,
            "tags": tags,
            "links": links,
            "excerpt": content[:180],
            "markdown": (
                f"{_frontmatter(title, memory_id, created_at, updated_at, tags)}\n\n"
                f"{content or '_No content yet._'}{related_block}\n"
            ),
        }
        notes.append(note)

        note_node_id = f"note:{memory_id}"
        add_node(note_node_id, title, "note", path=path)
        add_edge(project_node_id, note_node_id, "contains")

        for tag in tags:
            tag_node_id = f"tag:{_slugify(tag, fallback='tag')}"
            add_node(tag_node_id, tag, "tag")
            add_edge(note_node_id, tag_node_id, "tagged")

        for link in links:
            topic_node_id = f"topic:{_slugify(link, fallback='topic')}"
            add_node(topic_node_id, link, "topic")
            add_edge(note_node_id, topic_node_id, "links")

    return {
        "root": f"vaults/{project['slug']}",
        "generated_at": generated_at,
        "stats": {
            "notes": len(notes),
            "nodes": len(nodes),
            "edges": len(edges),
            "tags": _tag_count,
        },
        "notes": notes,
        "graph": {
            "nodes": nodes,
            "edges": edges,
        },
    }


def _vault_project_dir(vault_dir: Path, project_slug: str) -> Path:
    return vault_dir / project_slug


def _vault_json_path(vault_dir: Path, project_slug: str) -> Path:
    return _vault_project_dir(vault_dir, project_slug) / "vault.json"


def load_cached_project_vault(vault_dir: Path, project_slug: str) -> dict[str, Any] | None:
    path = _vault_json_path(vault_dir, project_slug)
    if not path.is_file():
        return None
    return orjson.loads(path.read_bytes())


def build_and_cache_project_vault(
    project: dict[str, Any], memories: list[dict[str, Any]], vault_dir: Path
) -> dict[str, Any]:
    workspace = build_project_vault(project, memories)
    project_dir = _vault_project_dir(vault_dir, project["slug"])
    project_dir.mkdir(parents=True, exist_ok=True)
    _vault_json_path(vault_dir, project["slug"]).write_bytes(orjson.dumps(workspace))
    return workspace


def ensure_project_vault(
    project: dict[str, Any],
    memories: list[dict[str, Any]],
    vault_dir: Path,
    force: bool = False,
) -> dict[str, Any]:
    if not force:
        cached = load_cached_project_vault(vault_dir, project["slug"])
        if cached is not None:
            return cached
    return build_and_cache_project_vault(project, memories, vault_dir)


def build_project_vault_preview(workspace: dict[str, Any], note_limit: int = 5) -> dict[str, Any]:
    notes = workspace.get("notes") or []
    preview_notes: list[dict[str, Any]] = []
    for note in notes[:note_limit]:
        preview_notes.append(
            {
                "memory_id": note.get("memory_id"),
                "title": note.get("title"),
                "path": note.get("path"),
                "created_at": note.get("created_at"),
                "updated_at": note.get("updated_at"),
                "tags": note.get("tags") or [],
                "links": note.get("links") or [],
                "excerpt": note.get("excerpt") or "",
            }
        )

    return {
        "root": workspace.get("root"),
        "generated_at": workspace.get("generated_at"),
        "stats": workspace.get("stats"),
        "notes": preview_notes,
        "graph": workspace.get("graph") or {"nodes": [], "edges": []},
        "preview": True,
        "note_limit": note_limit,
    }


async def invalidate_project_vault_cache(
    vault_dir: Path,
    user_id: str,
    project_id: str,
    project_slug: str | None = None,
) -> None:
    slug = project_slug
    if not slug:
        from sqlalchemy import select

        from piloci.db.models import Project
        from piloci.db.session import async_session

        async with async_session() as db:
            result = await db.execute(
                select(Project.slug).where(Project.id == project_id, Project.user_id == user_id)
            )
            slug = result.scalar_one_or_none()
    if not slug:
        return
    shutil.rmtree(_vault_project_dir(vault_dir, slug), ignore_errors=True)


def export_project_vault_zip(project: dict[str, Any], workspace: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    root = workspace.get("root") or f"vaults/{project['slug']}"
    notes = workspace.get("notes") or []
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{root}/vault.json", orjson.dumps(workspace, option=orjson.OPT_INDENT_2))
        for note in notes:
            note_path = note.get("path")
            markdown = note.get("markdown")
            if not note_path or not isinstance(markdown, str):
                continue
            archive.writestr(f"{root}/{note_path}", markdown)
    return buffer.getvalue()
