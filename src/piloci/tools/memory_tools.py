from __future__ import annotations

"""piloci v0.3 MCP tools — 5 tools: memory, recall, listProjects, whoAmI, init.

All queries enforce (user_id, project_id) isolation. Recall uses 3-phase
token-saving strategy: preview → fetch → to_file.
"""

import json
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
    "Save/forget memories. team_id sets team scope (shared); else personal+project. "
    "When in doubt, SAVE."
)

RECALL_DESC = (
    "Search memories. team_id sets team scope; else personal+project. "
    "Returns preview; use fetch_ids for full content."
)

DOC_DESC = (
    "Save a verbatim document/note. team_id+path uploads to team docs (folder structure "
    "preserved). team_id only = team raw note. None = personal."
)

LIST_PROJECTS_DESC = (
    "List projects + teams the user belongs to. Use the team id with memory/recall/doc "
    "for team scope."
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
    team_id: Annotated[
        str | None,
        Field(
            description="If set, save/forget in this team's shared memory.",
            max_length=64,
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
    include_feedback: Annotated[
        bool,
        Field(
            description=(
                "Include private 'feedback' memories (frustration/praise quotes). "
                "Off by default — UI/digest callers set true."
            ),
        ),
    ] = False
    team_id: Annotated[
        str | None,
        Field(
            description="If set, search this team's shared memory instead of personal.",
            max_length=64,
        ),
    ] = None


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


def _hook_python_cmd() -> str:
    """Pick the Python launcher to embed in hook command strings.

    Mirrors installer._python_cmd — kept as a local copy so this module stays
    importable without circulating through ``piloci.installer`` (the installer
    imports tools, not the other way around).
    """
    import os as _os
    import shutil as _shutil

    if _os.name == "nt":
        return "py" if _shutil.which("py") else "python"
    return "python3"


# Generic script — no token. Reads ~/.config/piloci/config.json at runtime.
# Install once, update config.json when token rotates.
HOOK_SCRIPT = '''\
#!/usr/bin/env python3
"""piLoci SessionStart hook — works with Claude Code and Codex CLI.

Install once. Update ~/.config/piloci/config.json when the token rotates.
Tracks ingested sessions in ~/.config/piloci/state.json.
Never blocks startup; failures are silent.

Codex CLI passes transcript_path via stdin JSON; Claude Code is served by
scanning ~/.claude/projects/ on disk.
"""
import json
import os
import sys
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


def _read_stdin():
    """Non-blocking stdin read: returns parsed JSON or {} if nothing is ready.

    Cross-platform: select.select on stdin works on POSIX file descriptors but
    not on Windows pipes. We test isatty first — interactive shells never have
    JSON piped in — then drain stdin if data is actually there (Codex CLI path)
    or skip silently (Claude Code SessionStart, which provides no stdin).
    """
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        if os.name == "nt":
            # Windows: select can't poll a pipe FD. Read whatever is buffered.
            raw = sys.stdin.read()
        else:
            import select as _select

            r, _, _ = _select.select([sys.stdin], [], [], 0)
            if not r:
                return {}
            raw = sys.stdin.read()
        return json.loads(raw) if raw and raw.strip() else {}
    except Exception:
        return {}


def _post(url, token, payload_bytes):
    req = urllib.request.Request(
        url,
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "piloci-hook",
        },
        method="POST",
    )
    urllib.request.urlopen(req, timeout=60)


def main():
    cfg = _read(_CONFIG)
    token = cfg.get("token")
    url = cfg.get("ingest_url")
    if not token or not url:
        return

    state = _read(_STATE)
    if not isinstance(state, dict):
        state = {}

    # Codex CLI path: transcript_path provided via stdin JSON
    stdin = _read_stdin()
    transcript_path_str = stdin.get("transcript_path")
    cwd = stdin.get("cwd") or os.getcwd()

    if transcript_path_str:
        path = Path(transcript_path_str)
        try:
            st = path.stat()
        except OSError:
            return
        if not (200 < st.st_size < MAX_FILE_BYTES):
            return
        sid = path.stem
        sent = state.get(cwd, {})
        if not isinstance(sent, dict):
            sent = {}
        fp = f"{st.st_size}:{st.st_mtime}"
        if sent.get(sid) == fp:
            return
        try:
            transcript = path.read_bytes().decode("utf-8", "ignore")
        except OSError:
            return
        payload = json.dumps({"cwd": cwd, "sessions": [{"session_id": sid, "transcript": transcript}]}).encode()
        try:
            _post(url, token, payload)
            sent[sid] = fp
            state[cwd] = sent
            state.pop("_auth_invalid", None)
            _write(_STATE, state)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                state["_auth_invalid"] = {"at": time.time(), "url": url}
                _write(_STATE, state)
        except (urllib.error.URLError, OSError):
            pass
        return

    # Claude Code path: scan ~/.claude/projects/ for session JSONL files.
    # Project directories use the cwd with every path separator replaced by '-'
    # — strip both '/' and '\\' so Windows paths (C:\\Users\\x\\app) map to
    # the same '-C-Users-x-app' shape as Linux's '/home/x/app' → '-home-x-app'.
    project_dir = Path.home() / ".claude" / "projects" / cwd.replace("\\\\", "-").replace("/", "-")
    if not project_dir.is_dir():
        return

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
    try:
        _post(url, token, payload)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            state["_auth_invalid"] = {"at": time.time(), "url": url}
            _write(_STATE, state)
        return
    except (urllib.error.URLError, OSError):
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
                            "command": f"{_hook_python_cmd()} {_HOOK_SCRIPT_PATH} 2>/dev/null || true",
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


_DEDUP_THRESHOLD = 0.95  # cosine similarity above which we update instead of insert


async def _ensure_team_member(team_id: str, user_id: str) -> dict[str, Any] | None:
    """Returns None if user is a member of team; else an error dict.

    Single SQLite RTT per MCP call — store calls below this point assume
    the access check already passed.
    """
    from piloci.api.team_routes import _get_team_member
    from piloci.db.session import async_session

    async with async_session() as db:
        member = await _get_team_member(db, team_id, user_id)
        if not member:
            return {"success": False, "error": "Not a member of this team"}
        return None


async def _handle_team_memory(
    args: MemoryInput,
    user_id: str,
    team_id: str,
    store,
    embed_fn,
) -> dict[str, Any]:
    deny = await _ensure_team_member(team_id, user_id)
    if deny:
        return deny

    if args.action == "forget":
        if not args.memory_id:
            return {
                "success": False,
                "error": "forget requires memory_id. Use recall first to find it.",
            }
        # Determine if requester is the team owner (allowed to delete any row).
        is_owner = False
        try:
            from sqlalchemy import select

            from piloci.db.models import Team
            from piloci.db.session import async_session

            async with async_session() as db:
                row = await db.execute(select(Team.owner_id).where(Team.id == team_id))
                owner_id = row.scalar_one_or_none()
            is_owner = owner_id == user_id
        except Exception:
            is_owner = False

        deleted = await store.team_delete(
            team_id=team_id,
            memory_id=args.memory_id,
            requester_id=user_id,
            allow_owner=is_owner,
        )
        if not deleted:
            return {
                "success": False,
                "action": "forget",
                "error": (
                    f"memory_id '{args.memory_id}' not found, or you are not " "the author/owner."
                ),
            }
        return {
            "success": True,
            "action": "forget",
            "memory_id": args.memory_id,
            "team_id": team_id,
        }

    vector = await embed_fn(args.content)

    memory_id = await store.team_save(
        team_id=team_id,
        author_id=user_id,
        content=args.content,
        vector=vector,
        tags=args.tags,
        metadata={"source": "manual"},
    )
    await _invalidate_team_vault_silently(team_id)
    return {
        "success": True,
        "action": "save",
        "memory_id": memory_id,
        "team_id": team_id,
        "scope": "team",
    }


async def _invalidate_team_vault_silently(team_id: str) -> None:
    """Drop the cached team workspace on memory writes so the wiki page sees
    fresh data on next load. Cache miss is harmless — fail-open."""
    try:
        from piloci.config import get_settings
        from piloci.curator.team_vault import invalidate_team_vault_cache

        await invalidate_team_vault_cache(get_settings().vault_dir, team_id)
    except Exception:
        pass


async def handle_memory(
    args: MemoryInput,
    user_id: str,
    project_id: str | None,
    store,
    embed_fn,
) -> dict[str, Any]:
    if args.team_id:
        return await _handle_team_memory(args, user_id, args.team_id, store, embed_fn)

    if not project_id:
        return {
            "success": False,
            "error": "Personal memory requires a project-scoped token (or set team_id).",
        }

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

    # Deduplication: if a near-identical memory exists, refresh it instead of duplicating
    similar = await store.search(
        user_id=user_id,
        project_id=project_id,
        query_vector=vector,
        top_k=1,
        min_score=_DEDUP_THRESHOLD,
    )
    if similar:
        existing = similar[0]
        await store.update(
            user_id=user_id,
            project_id=project_id,
            memory_id=existing["id"],
            content=args.content,
            new_vector=vector,
            tags=args.tags if args.tags is not None else existing.get("tags"),
        )
        return {
            "success": True,
            "action": "updated",
            "memory_id": existing["id"],
            "project_id": project_id,
            "was_duplicate": True,
        }

    memory_id = await store.save(
        user_id=user_id,
        project_id=project_id,
        content=args.content,
        vector=vector,
        tags=args.tags,
        metadata={"source": "manual"},
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


# Total characters of excerpt text returned across a single team recall. Keeps
# the MCP tool response token-bounded ("응답 안 터지게") so a broad query against
# a big team vault degrades into a truncated, narrow-your-query hint rather
# than a wall of text.
_RECALL_CHAR_CAP = 6000
_DOC_EXCERPT_LEN = 240


def _result_metadata(row: dict[str, Any]) -> dict[str, Any]:
    """Parse a row's metadata blob (str or already-dict) into a dict."""
    meta = row.get("metadata")
    if isinstance(meta, dict):
        return meta
    if isinstance(meta, str | bytes | bytearray) and meta:
        try:
            parsed = json.loads(meta)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _doc_preview(row: dict[str, Any], meta: dict[str, Any], excerpt_len: int) -> dict[str, Any]:
    content = row.get("content", "")
    excerpt = content[:excerpt_len]
    if len(content) > excerpt_len:
        excerpt += "..."
    return {
        "kind": "doc",
        "path": meta.get("path", ""),
        "line_start": meta.get("line_start"),
        "line_end": meta.get("line_end"),
        "score": row.get("score", 0.0),
        "excerpt": excerpt,
    }


def _build_team_previews(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Build token-bounded recall previews, tagging doc chunks vs memories.

    Walks results in (already ranked) order, accumulating excerpt characters
    against ``_RECALL_CHAR_CAP``. Once the cap is hit we stop emitting further
    previews and flag ``truncated`` so the agent knows to narrow the query.
    """
    previews: list[dict[str, Any]] = []
    used = 0
    truncated = False
    for row in results:
        meta = _result_metadata(row)
        if meta.get("kind") == "doc_chunk":
            item = _doc_preview(row, meta, _DOC_EXCERPT_LEN)
        else:
            item = {"kind": "memory", **_preview(row)}
        excerpt_len = len(item.get("excerpt", ""))
        if used + excerpt_len > _RECALL_CHAR_CAP and previews:
            # Cap reached — drop the rest rather than overflow the response.
            truncated = True
            break
        previews.append(item)
        used += excerpt_len
    return previews, truncated


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


def _filter_feedback_out(rows: list[Any]) -> list[Any]:
    """Drop private 'feedback' memories. Used when include_feedback=False.

    Memory ``category`` is persisted inside the JSON ``metadata`` blob so we
    parse it lazily — bad/missing JSON falls through as "not feedback" rather
    than raising, since filter logic should never hide a coding memory because
    its metadata is malformed.
    """
    from piloci.storage.privacy import PRIVATE_MEMORY_CATEGORIES

    kept = []
    for r in rows:
        meta_raw = r.get("metadata") if isinstance(r, dict) else None
        category: str | None = None
        if isinstance(meta_raw, str) and meta_raw:
            try:
                parsed = json.loads(meta_raw)
                if isinstance(parsed, dict):
                    cat = parsed.get("category")
                    if isinstance(cat, str):
                        category = cat
            except (ValueError, TypeError):
                pass
        elif isinstance(meta_raw, dict):
            cat = meta_raw.get("category")
            if isinstance(cat, str):
                category = cat
        if category not in PRIVATE_MEMORY_CATEGORIES:
            kept.append(r)
    return kept


async def _handle_team_recall(
    args: RecallInput,
    user_id: str,
    team_id: str,
    store,
    embed_fn,
    export_dir: Path | None = None,
) -> dict[str, Any]:
    deny = await _ensure_team_member(team_id, user_id)
    if deny:
        return deny

    if args.fetch_ids:
        fetched = []
        for mid in args.fetch_ids:
            row = await store.team_get(team_id, mid)
            if row:
                fetched.append(row)
        if not args.include_feedback:
            fetched = _filter_feedback_out(fetched)
        return {
            "memories": fetched,
            "mode": "full",
            "fetched": len(fetched),
            "team_id": team_id,
        }

    if args.query is None:
        return {"memories": [], "mode": "preview", "total": 0, "error": "query required"}

    vector = await embed_fn(args.query)
    results = await store.team_hybrid_search(
        team_id=team_id,
        query_text=args.query,
        query_vector=vector,
        top_k=args.limit,
        tags=args.tags,
    )
    if not args.include_feedback:
        results = _filter_feedback_out(results)

    if args.to_file and export_dir is not None:
        md_content = _format_recall_markdown(results, None)
        out_dir = export_dir / f"team_{team_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = out_dir / f"recall_{ts}.md"
        file_path.write_text(md_content, encoding="utf-8")
        return {
            "file": str(file_path),
            "count": len(results),
            "total_chars": len(md_content),
            "mode": "file",
            "team_id": team_id,
            "previews": [_preview(r) for r in results],
        }

    previews, truncated = _build_team_previews(results)
    return {
        "memories": previews,
        "mode": "preview",
        "total": len(results),
        "truncated": truncated,
        "team_id": team_id,
    }


async def handle_recall(
    args: RecallInput,
    user_id: str,
    project_id: str | None,
    store,
    embed_fn,
    profile_fn=None,
    export_dir: Path | None = None,
) -> dict[str, Any]:
    if args.team_id:
        return await _handle_team_recall(args, user_id, args.team_id, store, embed_fn, export_dir)

    if not project_id:
        return {
            "memories": [],
            "mode": "preview",
            "total": 0,
            "error": "Personal recall requires a project-scoped token (or set team_id).",
        }

    if args.fetch_ids:
        fetched = []
        for mid in args.fetch_ids:
            row = await store.get(user_id, project_id, mid)
            if row:
                fetched.append(row)
        if not args.include_feedback:
            fetched = _filter_feedback_out(fetched)
        response: dict[str, Any] = {"memories": fetched, "mode": "full", "fetched": len(fetched)}
        if args.include_profile:
            profile = await _get_profile(profile_fn, user_id, project_id)
            if profile:
                response["profile"] = profile
        return response

    if args.query is None:
        return {"memories": [], "mode": "preview", "total": 0, "error": "query required"}

    vector = await embed_fn(args.query)
    use_hybrid = hasattr(store, "hybrid_search")
    if use_hybrid:
        results = await store.hybrid_search(
            user_id=user_id,
            project_id=project_id,
            query_text=args.query,
            query_vector=vector,
            top_k=args.limit,
            tags=args.tags,
        )
    else:
        results = await store.search(
            user_id=user_id,
            project_id=project_id,
            query_vector=vector,
            top_k=args.limit,
            tags=args.tags,
        )

    if not args.include_feedback:
        results = _filter_feedback_out(results)

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
    teams = await _list_user_teams(user_id)
    return {"projects": projects, "teams": teams}


async def _list_user_teams(user_id: str) -> list[dict[str, Any]]:
    """Return teams the user belongs to. Empty list on error or no DB."""
    try:
        from sqlalchemy import select

        from piloci.db.models import Team, TeamMember
        from piloci.db.session import async_session

        async with async_session() as db:
            result = await db.execute(
                select(Team.id, Team.name, TeamMember.role)
                .join(TeamMember, Team.id == TeamMember.team_id)
                .where(TeamMember.user_id == user_id)
                .order_by(Team.created_at)
            )
            rows = result.all()
        return [{"id": r.id, "name": r.name, "role": r.role} for r in rows]
    except Exception as e:
        logger.debug("list_user_teams skipped: %s", e)
        return []


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

    # If no project-scoped token, resolve or create a project — preferring an
    # exact cwd match so two folders that slugify the same don't merge.
    if not project_id:
        projects: list[dict[str, Any]] = []
        if projects_fn:
            try:
                projects = await projects_fn(user_id, False)
            except Exception:
                pass

        matched: dict[str, Any] | None = None
        if args.cwd:
            matched = next((p for p in projects if p.get("cwd") == args.cwd), None)
        if matched is None:
            # Legacy fallback: slug match where existing row has no cwd yet.
            matched = next(
                (p for p in projects if p.get("slug") == slug and not p.get("cwd")), None
            )

        if matched:
            project_id = matched.get("id")
            if not args.project_name:
                display_name = matched.get("name") or display_name
            slug = matched.get("slug") or slug
        else:
            # No match — create. create_project_fn handles slug-collision
            # disambiguation when another project already owns this slug.
            if create_project_fn:
                try:
                    try:
                        new_proj = await create_project_fn(
                            user_id, display_name or slug, slug, cwd=args.cwd
                        )
                    except TypeError:
                        # Older mocks/impls that don't accept cwd kwarg.
                        new_proj = await create_project_fn(user_id, display_name or slug, slug)
                    project_id = new_proj.get("id") or new_proj.get("project_id")
                    slug = new_proj.get("slug") or slug
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


# ---------------------------------------------------------------------------
# doc tool — verbatim document storage. Three modes:
#   team_id + path  →  team_documents SQL row (folder-structured, downloadable)
#   team_id only    →  team-scoped LanceDB memory (raw, searchable)
#   neither         →  personal LanceDB memory (raw, searchable)
# ---------------------------------------------------------------------------

_DOC_EMBED_LIMIT = 2_000  # chars used for embedding; full content stored verbatim
_DOC_TAG = "doc"


class DocInput(BaseModel):
    title: Annotated[
        str,
        Field(description="Short title (used as filename when path omitted).", max_length=200),
    ]
    content: Annotated[
        str,
        Field(
            description="Full document or markdown content to store verbatim.", max_length=2_000_000
        ),
    ]
    tags: Annotated[
        list[str] | None,
        Field(description="Optional extra tags. 'doc' is always added.", max_length=5),
    ] = None
    save_to_file: Annotated[
        bool,
        Field(description="Also write to disk as a .md file in the export dir."),
    ] = False
    team_id: Annotated[
        str | None,
        Field(description="If set, save to this team's shared scope.", max_length=64),
    ] = None
    path: Annotated[
        str | None,
        Field(
            description="Doc path incl. folders (team_id only). e.g. docs/api/auth.md",
            max_length=500,
        ),
    ] = None


async def _save_team_document(
    team_id: str, user_id: str, path: str, content: str
) -> dict[str, Any]:
    """Persist a verbatim file to team_documents. Returns response payload.

    Uses the same upsert semantics the REST routes already exercise: if a row
    with the same path exists, bump the version; else insert a new row.
    """
    import hashlib
    import uuid
    from datetime import datetime, timezone

    from sqlalchemy import select

    from piloci.db.models import TeamDocument
    from piloci.db.session import async_session

    content_hash = hashlib.sha256(content.encode()).hexdigest()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    async with async_session() as db:
        existing = await db.execute(
            select(TeamDocument).where(
                TeamDocument.team_id == team_id,
                TeamDocument.path == path,
                TeamDocument.is_deleted == False,  # noqa: E712
            )
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            row.content = content
            row.content_hash = content_hash
            row.version = (row.version or 1) + 1
            row.updated_at = now
            row.author_id = user_id
            doc_id = row.id
            version = row.version
        else:
            doc_id = str(uuid.uuid4())
            db.add(
                TeamDocument(
                    id=doc_id,
                    team_id=team_id,
                    author_id=user_id,
                    path=path,
                    content=content,
                    content_hash=content_hash,
                    version=1,
                    parent_hash=None,
                    updated_at=now,
                    created_at=now,
                    is_deleted=False,
                )
            )
            version = 1

    return {
        "success": True,
        "doc_id": doc_id,
        "team_id": team_id,
        "path": path,
        "version": version,
        "content_hash": content_hash,
        "bytes": len(content.encode()),
        "download_url": f"/api/teams/{team_id}/documents/{doc_id}/raw",
        "scope": "team-doc",
    }


async def handle_doc(
    args: DocInput,
    user_id: str,
    project_id: str | None,
    store,
    embed_fn,
    export_dir: Path | None = None,
) -> dict[str, Any]:
    import re

    # Mode A: team_id + path → team_documents (file/folder model)
    if args.team_id and args.path:
        deny = await _ensure_team_member(args.team_id, user_id)
        if deny:
            return deny
        return await _save_team_document(args.team_id, user_id, args.path, args.content)

    embed_text = f"{args.title}\n\n{args.content[:_DOC_EMBED_LIMIT]}"
    vector = await embed_fn(embed_text)
    tags = [_DOC_TAG] + [t for t in (args.tags or []) if t != _DOC_TAG]
    full_content = f"# {args.title}\n\n{args.content}"

    # Mode B: team_id only → team-scoped raw memory
    if args.team_id:
        deny = await _ensure_team_member(args.team_id, user_id)
        if deny:
            return deny
        memory_id = await store.team_save(
            team_id=args.team_id,
            author_id=user_id,
            content=full_content,
            vector=vector,
            tags=tags,
            metadata={"source": "manual", "doc_title": args.title},
        )
        return {
            "success": True,
            "memory_id": memory_id,
            "team_id": args.team_id,
            "title": args.title,
            "bytes": len(full_content.encode()),
            "scope": "team",
        }

    # Mode C: personal raw memory (legacy path, unchanged)
    if not project_id:
        return {
            "success": False,
            "error": "Personal doc requires a project-scoped token (or set team_id).",
        }

    memory_id = await store.save(
        user_id=user_id,
        project_id=project_id,
        content=full_content,
        vector=vector,
        tags=tags,
        metadata={"source": "manual", "doc_title": args.title},
    )

    result: dict[str, Any] = {
        "success": True,
        "memory_id": memory_id,
        "project_id": project_id,
        "title": args.title,
        "bytes": len(full_content.encode()),
    }

    if args.save_to_file:
        slug = re.sub(r"[^\w\-]", "_", args.title.lower())[:60]
        out_dir = (export_dir or Path.home() / ".piloci" / "docs") / user_id / project_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{slug}.md"
        out_path.write_text(full_content, encoding="utf-8")
        result["file"] = str(out_path)

    return result


# Backwards-compatibility aliases — older tests import MemoInput/handle_memo.
MemoInput = DocInput
handle_memo = handle_doc
MEMO_DESC = DOC_DESC
