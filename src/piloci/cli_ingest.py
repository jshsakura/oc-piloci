from __future__ import annotations

"""piloci-ingest CLI: normalize session transcripts from each MCP client
and POST them to /api/ingest. Designed to run inside each client's
session-end hook. Zero client-LLM tokens (runs in shell, not LLM).

Supported clients:
  claude-code  — stdin JSON with transcript_path
  opencode     — reads ~/.local/share/opencode/storage (SQLite)
  codex        — reads ~/.codex/history.jsonl
  gemini       — uses GEMINI_SESSION_ID env var (best-effort; stub)
"""

import argparse
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

import httpx
import orjson


def _read_config() -> dict[str, Any]:
    """Load endpoint + token from ~/.piloci/config.toml, with env fallback."""
    cfg = {
        "endpoint": os.environ.get("PILOCI_ENDPOINT", "http://localhost:8314"),
        "token": os.environ.get("PILOCI_TOKEN"),
        "project_id": os.environ.get("PILOCI_PROJECT_ID"),
    }
    config_path = Path.home() / ".piloci" / "config.toml"
    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
            cfg["endpoint"] = data.get("endpoint", cfg["endpoint"])
            cfg["token"] = data.get("token", cfg["token"])
            cfg["project_id"] = data.get("project_id", cfg["project_id"])
        except Exception as e:
            print(f"[piloci-ingest] config read failed: {e}", file=sys.stderr)
    return cfg


# ---------------------------------------------------------------------------
# Per-client adapters — each returns (session_id, transcript_list)
# ---------------------------------------------------------------------------


def _load_claude_code(stdin_data: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    transcript_path = stdin_data.get("transcript_path")
    session_id = stdin_data.get("session_id")
    if not transcript_path or not Path(transcript_path).exists():
        return session_id, []
    transcript = []
    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                transcript.append(orjson.loads(line))
            except (orjson.JSONDecodeError, ValueError):
                continue
    return session_id, transcript


def _load_opencode(session_id: str | None) -> tuple[str | None, list[dict[str, Any]]]:
    """Read the most recent session from OpenCode's SQLite storage.

    Storage dir: ~/.local/share/opencode/storage
    """
    storage_dir = Path.home() / ".local/share/opencode/storage"
    if not storage_dir.exists():
        return session_id, []
    # Find the most recent session JSON/db — OpenCode writes JSON per-session
    candidates = sorted(storage_dir.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return session_id, []
    latest = candidates[0]
    try:
        with open(latest, "rb") as f:
            data = orjson.loads(f.read())
        transcript = data.get("messages") or data.get("transcript") or []
        sid = data.get("id") or data.get("sessionId") or session_id
        return sid, transcript if isinstance(transcript, list) else []
    except Exception:
        return session_id, []


def _load_codex(history_file: str | None) -> tuple[str | None, list[dict[str, Any]]]:
    path = Path(history_file) if history_file else Path.home() / ".codex" / "history.jsonl"
    if not path.exists():
        return None, []
    transcript = []
    session_id = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = orjson.loads(line)
                transcript.append(entry)
                if session_id is None:
                    session_id = entry.get("session_id") or entry.get("sessionId")
            except (orjson.JSONDecodeError, ValueError):
                continue
    # Only send most recent session (last ~50 entries to stay bounded)
    return session_id, transcript[-200:]


def _load_gemini(session_id: str | None) -> tuple[str | None, list[dict[str, Any]]]:
    """Gemini CLI currently stubs transcript_path. Best-effort placeholder."""
    if not session_id:
        session_id = os.environ.get("GEMINI_SESSION_ID")
    # TODO: parse Gemini's actual session format once #14715 resolves
    return session_id, []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(prog="piloci-ingest")
    parser.add_argument(
        "--client",
        required=True,
        choices=["claude-code", "opencode", "codex", "gemini"],
    )
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--history-file", default=None)
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = _read_config()
    endpoint = args.endpoint or cfg["endpoint"]
    token = args.token or cfg["token"]
    project_id = args.project_id or cfg["project_id"]

    # Claude Code: hook sends JSON on stdin
    if args.client == "claude-code":
        try:
            stdin_data = orjson.loads(sys.stdin.read() or "{}")
        except (orjson.JSONDecodeError, ValueError):
            stdin_data = {}
        session_id, transcript = _load_claude_code(stdin_data)
    elif args.client == "opencode":
        session_id, transcript = _load_opencode(args.session_id)
    elif args.client == "codex":
        session_id, transcript = _load_codex(args.history_file)
    elif args.client == "gemini":
        session_id, transcript = _load_gemini(args.session_id)
    else:
        print(f"Unknown client: {args.client}", file=sys.stderr)
        return 2

    if not transcript:
        print(f"[piloci-ingest] no transcript for {args.client}", file=sys.stderr)
        return 0

    payload = {
        "client": args.client,
        "session_id": session_id,
        "transcript": transcript,
    }
    if project_id:
        payload["project_id"] = project_id

    if args.dry_run:
        print(
            orjson.dumps(
                {
                    "endpoint": endpoint,
                    "payload_preview": {
                        "client": payload["client"],
                        "session_id": payload["session_id"],
                        "transcript_length": len(transcript),
                        "project_id": payload.get("project_id"),
                    },
                },
                option=orjson.OPT_INDENT_2,
            ).decode()
        )
        return 0

    if not token:
        print("[piloci-ingest] missing PILOCI_TOKEN", file=sys.stderr)
        return 1

    try:
        resp = httpx.post(
            f"{endpoint.rstrip('/')}/api/ingest",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            content=orjson.dumps(payload),
            timeout=10.0,
        )
        if resp.status_code >= 400:
            print(f"[piloci-ingest] {resp.status_code} {resp.text}", file=sys.stderr)
            return 1
    except httpx.HTTPError as e:
        print(f"[piloci-ingest] request failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
