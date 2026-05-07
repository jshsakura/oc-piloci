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

    # rstrip("/") would turn "/" into "" — preserve lone slash so the ^/$ pattern matches.
    normalized = cwd.replace("\\", "/").rstrip("/") or "/"
    return any(re.match(p, normalized) for p in _HOME_PATTERNS)


def _dir_name(cwd: str) -> str:
    """Extract the last path component as a project name."""
    normalized = cwd.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] or "project"


def _slugify(text: str) -> str:
    """ASCII-safe slug: strip non-ASCII, lowercase, replace spaces/special with dash."""
    import re

    ascii_only = text.encode("ascii", errors="ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug[:40] or "project"


def cwd_to_slug(cwd: str) -> str:
    """Derive the canonical project slug from a working directory path.

    Single source of truth for cwd→slug — used by both `init` and
    `/api/sessions/ingest` so the hook always lands in the right project.
    """
    return _slugify(_dir_name(cwd))


_HOOK_SCRIPT_PATH = "~/.config/piloci/hook.py"

# Generic script — no token. Reads ~/.config/piloci/config.json at runtime.
# Install once, update config.json when token rotates.
HOOK_SCRIPT = '''\
#!/usr/bin/env python3
"""piLoci SessionStart hook.

Install once. Update ~/.config/piloci/config.json when the token rotates.
Tracks ingested sessions in ~/.config/piloci/state.json.
Never blocks Claude startup; failures are silent.

On 401 (token revoked or expired) the script records ``_auth_invalid`` in
state.json so the surface that surveys hook health can flag it. The
script does not retry until config.json is updated.
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

_CONFIG = Path.home() / ".config" / "piloci" / "config.json"
_STATE = Path.home() / ".config" / "piloci" / "state.json"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_AGE_SEC = 30 * 86400
MAX_SESSIONS = 10


def _read(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return {}


def _write(p, data):
    try:
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(json.dumps(data))
    except Exception:
        pass


def main():
    cfg = _read(_CONFIG)
    token = cfg.get("token")
    url = cfg.get("ingest_url")
    if not token or not url:
        return

    cwd = os.getcwd()
    project_dir = Path.home() / ".claude" / "projects" / cwd.replace("/", "-")
    if not project_dir.is_dir():
        return

    state = _read(_STATE)
    if not isinstance(state, dict):
        state = {}
    sent = state.get(cwd, {})
    if not isinstance(sent, dict):
        sent = {}
    cutoff = time.time() - MAX_AGE_SEC
    sessions, updated = [], dict(sent)

    for path in sorted(project_dir.glob("*.jsonl")):
        try:
            st = path.stat()
        except OSError:
            continue
        if not (200 < st.st_size < MAX_FILE_BYTES) or st.st_mtime < cutoff:
            continue
        sid = path.stem
        fp = f"{st.st_size}:{st.st_mtime}"
        if sent.get(sid) == fp:
            continue
        try:
            sessions.append({"session_id": sid, "transcript": path.read_bytes().decode("utf-8", "ignore")})
            updated[sid] = fp
        except OSError:
            continue
        if len(sessions) >= MAX_SESSIONS:
            break

    if not sessions:
        return

    payload = json.dumps({"cwd": cwd, "sessions": sessions}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            # Cloudflare in front of piloci flags Python-urllib's default UA as
            # bot traffic and returns 1010. A stable explicit UA passes.
            "User-Agent": "piloci-hook",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            state["_auth_invalid"] = {"at": time.time(), "url": url}
            _write(_STATE, state)
        # On any HTTP error: do not advance sent fingerprints — we will retry next session.
        return
    except (urllib.error.URLError, OSError):
        # Transient network problem; retry naturally on next session.
        return

    state[cwd] = updated
    state.pop("_auth_invalid", None)
    _write(_STATE, state)


if __name__ == "__main__":
    main()
'''


def build_hook_config_json(token: str, base_url: str) -> dict[str, str]:
    """Return the config.json content to write to ~/.config/piloci/config.json.

    Includes both ingest (SessionStart catch-up) and analyze (Stop live push) URLs
    so a single config file feeds both hook scripts.
    """
    base = base_url.rstrip("/")
    return {
        "token": token,
        "ingest_url": f"{base}/api/sessions/ingest",
        "analyze_url": f"{base}/api/sessions/analyze",
    }


def _build_session_start_hook() -> dict[str, Any]:
    """Return hook_config dict for ~/.claude/settings.json — calls generic script."""
    return {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {_HOOK_SCRIPT_PATH} 2>/dev/null || true",
                        }
                    ],
                }
            ]
        }
    }


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
    projects_fn,
    create_project_fn,
) -> dict[str, Any]:
    """One-time project setup: returns CLAUDE.md and AGENTS.md for the project root."""
    # Guard: refuse in home/root directories
    if args.cwd and _is_home_or_root(args.cwd):
        return {
            "success": False,
            "error": (
                f"init refused: '{args.cwd}' looks like a home or root directory. "
                "Navigate to your project directory first, then run init again."
            ),
        }

    # Display name (Korean OK) from explicit arg or cwd folder
    # Slug is always ASCII-safe, derived from cwd folder name
    cwd_folder = _dir_name(args.cwd) if args.cwd else None
    display_name = args.project_name or cwd_folder
    slug = cwd_to_slug(args.cwd) if args.cwd else _slugify(display_name or "project")

    # If no project-scoped token, resolve or create a project by cwd slug
    if not project_id:
        projects: list[dict[str, Any]] = []
        if projects_fn:
            try:
                projects = await projects_fn(user_id, False)
            except Exception:
                pass

        matched_by_slug = next((p for p in projects if p.get("slug") == slug), None)

        if matched_by_slug:
            project_id = matched_by_slug.get("id")
            if not args.project_name:
                display_name = matched_by_slug.get("name") or display_name
        else:
            # No slug match — always create for this exact directory
            if create_project_fn:
                try:
                    new_proj = await create_project_fn(user_id, display_name or slug, slug)
                    project_id = new_proj.get("id") or new_proj.get("project_id")
                except Exception as e:
                    return {"success": False, "error": f"Failed to create project: {e}"}

    # Enrich display_name / slug from the resolved project record
    if projects_fn and project_id:
        try:
            all_projects = await projects_fn(user_id, False)
            matched = next((p for p in all_projects if p.get("id") == project_id), None)
            if matched:
                if not args.project_name:
                    display_name = matched.get("name") or display_name
                slug = matched.get("slug") or slug
        except Exception:
            pass

    snippets = build_setup_snippets(project_name=display_name, project_slug=slug)
    anchor = "## piLoci Memory"

    return {
        "success": True,
        "project_id": project_id,
        "project_name": display_name,
        "anchor": anchor,
        "files": {
            "CLAUDE.md": snippets["claude_md"],
            "AGENTS.md": snippets["agents_md"],
        },
        "instructions": (
            f"For each file (CLAUDE.md, AGENTS.md) in the project root:\n"
            f"1. Already contains '{anchor}' → SKIP.\n"
            f"2. File exists but no anchor → APPEND at end.\n"
            f"3. Missing → CREATE with content."
        ),
    }
