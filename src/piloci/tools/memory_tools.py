from __future__ import annotations

"""piloci v0.3 MCP tools — 5 tools: memory, recall, listProjects, whoAmI, init.

All queries enforce (user_id, project_id) isolation. Recall uses 3-phase
token-saving strategy: preview → fetch → to_file.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool descriptions (concise — every char costs tokens)
# ---------------------------------------------------------------------------

MEMORY_DESC = (
    "Save or forget memories. action='save' to store facts/decisions/patterns. "
    "action='forget' with memory_id to remove. When in doubt, SAVE."
)

RECALL_DESC = (
    "Search memories. Returns preview (excerpt+tags+score). "
    "Use fetch_ids to get full content. Set to_file=true to save as file."
)

LIST_PROJECTS_DESC = (
    "List available projects for organizing memories. Cached 5min unless " "refresh=true."
)

WHOAMI_DESC = (
    "Get the current logged-in user's information. Returns userId, email, "
    "name, client info, session id."
)

INIT_DESC = (
    "One-time project setup. Pass cwd=$PWD. Returns CLAUDE.md and AGENTS.md "
    "content to write to project root. Refused in home/root dirs."
)


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------

_EXCERPT_LEN = 80


class MemoryInput(BaseModel):
    content: Annotated[
        str,
        Field(
            description="The memory content to save. Ignored for forget action.",
            max_length=200_000,
        ),
    ]
    action: Annotated[
        Literal["save", "forget"],
        Field(
            description="'save' to add a memory, 'forget' to remove by id",
        ),
    ] = "save"
    tags: Annotated[
        list[str] | None,
        Field(
            description="Optional tags (save action only). 1-3 normalized tags.",
        ),
    ] = None
    memory_id: Annotated[
        str | None,
        Field(
            description="Required for forget action. Get id from recall first.",
        ),
    ] = None


class RecallInput(BaseModel):
    query: Annotated[
        str | None,
        Field(
            description="Search query. Required unless fetch_ids provided.",
            max_length=1_000,
        ),
    ] = None
    fetch_ids: Annotated[
        list[str] | None,
        Field(
            description="Get full content for these memory IDs. Skip search.",
            max_length=20,
        ),
    ] = None
    to_file: Annotated[
        bool,
        Field(
            description="Save results as markdown file. Returns file path only.",
        ),
    ] = False
    include_profile: Annotated[
        bool,
        Field(
            description="Include profile summary in results.",
        ),
    ] = True
    tags: Annotated[list[str] | None, Field(description="Filter by tags")] = None
    limit: Annotated[int, Field(description="Max results (preview mode)", ge=1, le=50)] = 5


class ListProjectsInput(BaseModel):
    refresh: Annotated[
        bool,
        Field(
            description="Force re-fetch from DB instead of 5-min cache",
        ),
    ] = False


class WhoAmIInput(BaseModel):
    pass


class InitInput(BaseModel):
    cwd: Annotated[
        str | None,
        Field(description="Current working directory path. Pass $PWD value."),
    ] = None
    project_name: Annotated[
        str | None,
        Field(description="Project name. Defaults to the current directory name."),
    ] = None


# ---------------------------------------------------------------------------
# Shared snippet builder
# ---------------------------------------------------------------------------

_HOME_PATTERNS = (
    r"^/$",
    r"^/root$",
    r"^/home/[^/]+$",
    r"^/Users/[^/]+$",
    r"^[A-Za-z]:[/\\]Users[/\\][^/\\]+$",
    r"^~$",
)


def _is_home_or_root(cwd: str) -> bool:
    import re

    normalized = cwd.replace("\\", "/").rstrip("/")
    return any(re.match(p, normalized) for p in _HOME_PATTERNS)


def _dir_name(cwd: str) -> str:
    """Extract the last path component as a project name."""
    normalized = cwd.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] or "project"


def build_setup_snippets(
    project_name: str | None = None, project_slug: str | None = None
) -> dict[str, str]:
    """Return CLAUDE.md and AGENTS.md content for project-root setup."""
    header = "## piLoci Memory"
    project_line = ""
    if project_name:
        slug_hint = f" (piLoci: {project_slug})" if project_slug else ""
        project_line = f"\n**Project**: {project_name}{slug_hint}\n"

    content = (
        f"{header}{project_line}\n"
        "Use piLoci MCP tools to maintain context across sessions:\n\n"
        "1. **Session start**: Call `recall` with a query about the current task "
        "to load relevant memories from past sessions\n"
        "2. **Save actively**: Use `memory` throughout the conversation to save facts, "
        "decisions, preferences, code patterns, and insights. When in doubt, SAVE.\n"
        '3. **Tags**: Add 1-3 tags when saving (e.g. `["architecture", "bugfix", "preference"]`)\n'
    )
    return {"claude_md": content, "agents_md": content}


# ---------------------------------------------------------------------------
# Handlers (called from mcp/server.py)
# ---------------------------------------------------------------------------


async def handle_memory(
    args: MemoryInput,
    user_id: str,
    project_id: str,
    store,
    embed_fn,
) -> dict[str, Any]:
    if args.action == "forget":
        if not args.memory_id:
            return {
                "success": False,
                "error": "forget requires memory_id. Use recall first to find it.",
            }
        deleted = await store.delete(
            user_id=user_id,
            project_id=project_id,
            memory_id=args.memory_id,
        )
        if not deleted:
            return {
                "success": False,
                "action": "forget",
                "error": f"memory_id '{args.memory_id}' not found in this project",
            }
        return {"success": True, "action": "forget", "memory_id": args.memory_id}

    vector = await embed_fn(args.content)
    memory_id = await store.save(
        user_id=user_id,
        project_id=project_id,
        content=args.content,
        vector=vector,
        tags=args.tags,
    )
    return {
        "success": True,
        "action": "save",
        "memory_id": memory_id,
        "project_id": project_id,
    }


def _preview(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", "")
    excerpt = content[:_EXCERPT_LEN]
    if len(content) > _EXCERPT_LEN:
        excerpt += "..."
    return {
        "id": row.get("memory_id", ""),
        "score": row.get("score", 0.0),
        "tags": row.get("tags", []),
        "excerpt": excerpt,
        "length": len(content),
        "created_at": row.get("created_at"),
    }


def _format_recall_markdown(
    results: list[dict[str, Any]], profile: dict[str, Any] | None = None
) -> str:
    parts: list[str] = []
    if profile:
        parts.append("# Profile\n")
        for item in profile.get("static", []):
            parts.append(f"- {item}")
        for item in profile.get("dynamic", []):
            parts.append(f"- {item}")
        parts.append("")
    parts.append(f"# Memories ({len(results)} results)\n")
    for i, r in enumerate(results, 1):
        score = r.get("score", 0)
        tags = ", ".join(r.get("tags", []))
        header = f"## {i}. [{score:.2f}]"
        if tags:
            header += f" {tags}"
        parts.append(header)
        parts.append("")
        parts.append(r.get("content", ""))
        parts.append(f"\n_ID: {r.get('memory_id', '')}_\n")
    return "\n".join(parts)


async def _get_profile(profile_fn: Any, user_id: str, project_id: str) -> dict[str, Any] | None:
    if profile_fn is None:
        return None
    try:
        return await profile_fn(user_id, project_id)
    except Exception as e:
        logger.warning("profile_fn failed: %s", e)
        return None


async def handle_recall(
    args: RecallInput,
    user_id: str,
    project_id: str,
    store,
    embed_fn,
    profile_fn=None,
    export_dir: Path | None = None,
) -> dict[str, Any]:
    if args.fetch_ids:
        fetched = []
        for mid in args.fetch_ids:
            row = await store.get(user_id, project_id, mid)
            if row:
                fetched.append(row)
        response: dict[str, Any] = {"memories": fetched, "mode": "full", "fetched": len(fetched)}
        if args.include_profile:
            profile = await _get_profile(profile_fn, user_id, project_id)
            if profile:
                response["profile"] = profile
        return response

    if args.query is None:
        return {"memories": [], "mode": "preview", "total": 0, "error": "query required"}

    vector = await embed_fn(args.query)
    results = await store.search(
        user_id=user_id,
        project_id=project_id,
        query_vector=vector,
        top_k=args.limit,
        tags=args.tags,
    )

    if args.to_file and export_dir is not None:
        profile = (
            await _get_profile(profile_fn, user_id, project_id) if args.include_profile else None
        )
        md_content = _format_recall_markdown(results, profile)
        out_dir = export_dir / project_id
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = out_dir / f"recall_{ts}.md"
        file_path.write_text(md_content, encoding="utf-8")
        return {
            "file": str(file_path),
            "count": len(results),
            "total_chars": len(md_content),
            "mode": "file",
            "previews": [_preview(r) for r in results],
        }

    response = {
        "memories": [_preview(r) for r in results],
        "mode": "preview",
        "total": len(results),
    }
    if args.include_profile:
        profile = await _get_profile(profile_fn, user_id, project_id)
        if profile:
            response["profile"] = profile
    return response


async def handle_list_projects(
    args: ListProjectsInput,
    user_id: str,
    projects_fn,  # async callable: (user_id, refresh) -> list[dict]
) -> dict[str, Any]:
    projects = await projects_fn(user_id, args.refresh)
    return {"projects": projects}


async def handle_whoami(
    args: WhoAmIInput,
    user_id: str,
    project_id: str | None,
    auth_payload: dict[str, Any] | None,
    session_id: str | None,
    client_info: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "userId": user_id,
        "projectId": project_id,
        "email": (auth_payload or {}).get("email"),
        "scope": (auth_payload or {}).get("scope"),
        "sessionId": session_id,
        "client": client_info,
    }


async def handle_init(
    args: InitInput,
    user_id: str,
    project_id: str | None,
    projects_fn,  # async callable: (user_id, refresh) -> list[dict]
    create_project_fn,  # async callable: (user_id, name, slug) -> dict
) -> dict[str, Any]:
    """One-time project setup: returns CLAUDE.md + AGENTS.md content to write."""
    # Guard: refuse to init in home or root directories
    if args.cwd and _is_home_or_root(args.cwd):
        return {
            "success": False,
            "error": (
                f"init refused: '{args.cwd}' looks like a home or root directory. "
                "Navigate to your project directory first, then run init again."
            ),
        }

    # Resolve a friendly project name from cwd or explicit arg
    resolved_name = args.project_name or (_dir_name(args.cwd) if args.cwd else None)

    # If no project-scoped token, resolve or create a project automatically
    if not project_id:
        projects: list[dict[str, Any]] = []
        if projects_fn:
            try:
                projects = await projects_fn(user_id, False)
            except Exception:
                pass

        if not projects:
            # No projects at all — auto-create using resolved name (init is intentional)
            slug = (resolved_name or "default").lower().replace(" ", "-")[:40]
            name = resolved_name or "default"
            if create_project_fn:
                try:
                    new_proj = await create_project_fn(user_id, name, slug)
                    project_id = new_proj.get("id") or new_proj.get("project_id")
                except Exception as e:
                    return {"success": False, "error": f"Failed to create project: {e}"}
        elif len(projects) == 1:
            # Exactly one project — use it automatically
            project_id = projects[0].get("id")
        else:
            # Multiple projects, user-scoped token — ask the user to pick one
            return {
                "action_required": True,
                "message": (
                    f"You have {len(projects)} projects. "
                    "Please re-issue a project-scoped token for the project you want to use, "
                    "then run init again. Which project would you like to set up?"
                ),
                "projects": [
                    {"id": p.get("id"), "name": p.get("name"), "slug": p.get("slug")}
                    for p in projects
                ],
            }

    # Resolve project slug for the snippet header
    project_slug: str | None = None
    if projects_fn and project_id:
        try:
            all_projects = await projects_fn(user_id, False)
            matched = next((p for p in all_projects if p.get("id") == project_id), None)
            if matched:
                project_slug = matched.get("slug")
                if not resolved_name:
                    resolved_name = matched.get("name")
        except Exception:
            pass

    snippets = build_setup_snippets(project_name=resolved_name, project_slug=project_slug)
    anchor = "## piLoci Memory"
    return {
        "success": True,
        "project_id": project_id,
        "project_name": resolved_name,
        "anchor": anchor,
        "files": {
            "CLAUDE.md": snippets["claude_md"],
            "AGENTS.md": snippets["agents_md"],
        },
        "instructions": (
            f"For each file (CLAUDE.md, AGENTS.md) in the project root:\n"
            f"1. If the file already contains '{anchor}' → SKIP (already configured).\n"
            f"2. If the file exists but lacks '{anchor}' → APPEND the content at the end.\n"
            f"3. If the file does not exist → CREATE it with the content.\n"
            f"After writing, piLoci will automatically recall memories at session start."
        ),
    }
