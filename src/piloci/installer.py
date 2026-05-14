"""Python-native client installer.

Functional twin of the bash installer in ``piloci.tools.install_script`` —
detects which AI coding client(s) live on this machine, drops the shared
``~/.config/piloci/config.json`` (token + endpoints), and patches each
detected client's own configuration:

  * Claude Code  → ``~/.claude/settings.json``  (SessionStart + Stop hooks)
                 + ``~/.config/piloci/{hook.py, stop-hook.sh}``
  * OpenCode     → ``~/.config/opencode/opencode.json``  (mcp.piloci entry)

The CLI imports ``run_install`` from here. Tests can also call individual
functions to validate merge behaviour.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# JSONC (JSON with comments) parser — needed for Zed settings.json
# ---------------------------------------------------------------------------

_JSONC_TOKEN_RE = re.compile(
    r'"(?:[^"\\]|\\.)*"'  # string literal — must match first to skip its content
    r"|//[^\n]*"  # line comment
    r"|/\*.*?\*/",  # block comment
    re.DOTALL,
)


def _parse_jsonc(text: str) -> object:
    """Parse JSONC: strip // / /* */ comments and trailing commas, then json.loads."""

    def _replace(m: re.Match) -> str:
        s = m.group(0)
        if s.startswith('"'):
            return s  # preserve string literals unchanged
        return re.sub(r"[^\n]", " ", s)  # keep newlines for correct line numbers

    stripped = _JSONC_TOKEN_RE.sub(_replace, text)
    stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)  # trailing commas
    return json.loads(stripped)


# ---------------------------------------------------------------------------

PILOCI_DIR_NAME = ".config/piloci"
CLAUDE_DIR_NAME = ".claude"
OPENCODE_DIR_NAME = ".config/opencode"
CURSOR_DIR_NAME = ".cursor"
GEMINI_DIR_NAME = ".gemini"
WINDSURF_DIR_NAME = ".codeium/windsurf"
ANTIGRAVITY_DIR_NAME = ".antigravity"
ZED_DIR_NAME = ".config/zed"
CODEX_DIR_NAME = ".codex"
PILOCI_PATH_TAG = "~/.config/piloci/"

# Display label per kind — used in InstallReport notes and surfaced in the CLI.
CLIENT_LABELS: dict[str, str] = {
    "claude": "Claude Code",
    "opencode": "OpenCode",
    "cursor": "Cursor",
    "gemini": "Gemini CLI",
    "windsurf": "Windsurf",
    "antigravity": "AntiGravity",
    "zed": "Zed",
    "codex": "Codex CLI",
}


@dataclass
class InstallReport:
    """Summary returned to the caller; the CLI prints it for the user."""

    config_path: Path
    claude_configured: bool = False
    opencode_configured: bool = False
    # Per-kind status: "ok" on success, "failed: <reason>" otherwise. Populated
    # for every client run_install actually attempted (whether or not it was
    # auto-detected). Older booleans above are mirrors for legacy callers/tests.
    clients: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def detect_clients(home: Path | None = None) -> tuple[bool, bool]:
    """Return (has_claude, has_opencode) for the given HOME (defaults to real)."""
    h = home or Path.home()
    has_claude = (h / CLAUDE_DIR_NAME).is_dir()
    has_opencode = (h / OPENCODE_DIR_NAME).is_dir() or shutil.which("opencode") is not None
    return has_claude, has_opencode


def detect_all_targets(home: Path | None = None) -> dict[str, bool]:
    """Return ``{kind: detected}`` for every client piloci can install into.

    Detection is best-effort — presence of the config dir or the CLI binary
    counts as "detected". The /device approve page uses this to preselect
    checkboxes; ``run_install`` falls back to it when no explicit ``targets``
    list is supplied.
    """
    h = home or Path.home()
    has_claude, has_opencode = detect_clients(home=h)
    return {
        "claude": has_claude,
        "opencode": has_opencode,
        "cursor": (h / CURSOR_DIR_NAME).is_dir() or shutil.which("cursor") is not None,
        "gemini": (h / GEMINI_DIR_NAME).is_dir() or shutil.which("gemini") is not None,
        "windsurf": (h / WINDSURF_DIR_NAME).is_dir() or shutil.which("windsurf") is not None,
        "antigravity": (h / ANTIGRAVITY_DIR_NAME).is_dir()
        or shutil.which("antigravity") is not None,
        "zed": (h / ZED_DIR_NAME).is_dir() or shutil.which("zed") is not None,
        "codex": (h / CODEX_DIR_NAME).is_dir() or shutil.which("codex") is not None,
    }


def write_config_json(token: str, base_url: str, *, home: Path | None = None) -> Path:
    """Write the shared ``config.json`` (token + endpoints) atomically."""
    h = home or Path.home()
    cfg_dir = h / PILOCI_DIR_NAME
    cfg_dir.mkdir(parents=True, exist_ok=True)
    try:
        cfg_dir.chmod(0o700)
    except PermissionError:
        pass
    base = base_url.rstrip("/")
    cfg = cfg_dir / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "token": token,
                "ingest_url": base + "/api/sessions/ingest",
                "analyze_url": base + "/api/sessions/analyze",
            },
            indent=2,
        )
    )
    try:
        cfg.chmod(0o600)
    except PermissionError:
        pass
    return cfg


def _http_download(url: str, *, token: str | None = None, timeout: int = 30) -> bytes:
    headers = {"User-Agent": "piloci-cli"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


CLAUDE_PLUGIN_DIR_NAME = ".claude/plugins/piloci"
OPENCODE_PLUGIN_DIR_NAME = ".config/opencode/plugins"


def install_claude_plugin(
    base_url: str,
    token: str,
    *,
    version: str = "0.0.0",
    home: Path | None = None,
) -> Path:
    """Lay out the piloci Claude Code plugin under ``~/.claude/plugins/piloci/``.

    The plugin folder is auto-discovered by Claude Code on next session start —
    no patching of ``~/.claude/settings.json`` or ``~/.claude.json``. Uninstall
    is a single ``rm -rf`` of this directory.

    Layout::

        piloci/
        ├── .claude-plugin/plugin.json
        ├── hooks/hooks.json    ← SessionStart + Stop wired to scripts below
        ├── hooks/hook.py       ← downloaded from /api/hook/script
        ├── hooks/stop-hook.sh  ← downloaded from /api/hook/stop-script
        └── .mcp.json           ← memory/recall/recommend MCP server
    """
    h = home or Path.home()
    plugin_dir = h / CLAUDE_PLUGIN_DIR_NAME
    plugin_dir.mkdir(parents=True, exist_ok=True)

    base = base_url.rstrip("/")

    # 1. Manifest
    (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "piloci",
                "version": version,
                "description": (
                    "piLoci memory — auto-capture sessions and expose "
                    "memory/recall/recommend MCP tools"
                ),
                "author": {"name": "piLoci"},
                "homepage": "https://github.com/jshsakura/oc-piloci",
                "license": "MIT",
            },
            indent=2,
        )
    )

    # 2. Hook config + scripts. Scripts live IN the plugin (use
    # ${CLAUDE_PLUGIN_ROOT} so Claude Code resolves the path) but read the
    # token + URLs from ``~/.config/piloci/config.json`` at runtime so token
    # rotation doesn't require touching the plugin folder.
    hooks_dir = plugin_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "hooks.json").write_text(
        json.dumps(
            {
                "description": "piLoci auto-capture (SessionStart catch-up + Stop live push)",
                "hooks": {
                    # SessionStart / Stop are non-tool events — no ``matcher`` field,
                    # matching the official Claude Code plugin examples.
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/hook.py "
                                        "2>/dev/null || true"
                                    ),
                                }
                            ],
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "bash ${CLAUDE_PLUGIN_ROOT}/hooks/stop-hook.sh "
                                        "2>/dev/null || true"
                                    ),
                                }
                            ],
                        }
                    ],
                },
            },
            indent=2,
        )
    )

    hook_py = hooks_dir / "hook.py"
    hook_py.write_bytes(_http_download(base + "/api/hook/script", token=token))
    try:
        hook_py.chmod(0o755)
    except PermissionError:
        pass

    stop_sh = hooks_dir / "stop-hook.sh"
    stop_sh.write_bytes(_http_download(base + "/api/hook/stop-script", token=token))
    try:
        stop_sh.chmod(0o755)
    except PermissionError:
        pass

    # 3. MCP server config — same mcpServers wrapper as project .mcp.json.
    mcp_path = plugin_dir / ".mcp.json"
    mcp_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "piloci": {
                        "type": "http",
                        "url": base + "/mcp/http",
                        "headers": {"Authorization": "Bearer " + token},
                    }
                }
            },
            indent=2,
        )
    )
    try:
        mcp_path.chmod(0o600)
    except PermissionError:
        pass

    # 4. Register MCP server in ~/.claude.json (User MCPs) so it shows globally.
    _merge_json_mcp(
        h / ".claude.json",
        parent_key="mcpServers",
        server_name="piloci",
        server_entry={
            "type": "http",
            "url": base + "/mcp/http",
            "headers": {"Authorization": "Bearer " + token},
        },
    )

    return plugin_dir


def _merge_claude_settings(settings_path: Path) -> None:
    """Add piloci's SessionStart + Stop hooks while preserving anything else."""
    existing: dict = {}
    if settings_path.exists():
        raw = settings_path.read_text()
        try:
            loaded = _parse_jsonc(raw)
            if isinstance(loaded, dict):
                existing = loaded
        except (json.JSONDecodeError, ValueError):
            # Don't blow away a corrupt file — back it up and start fresh.
            settings_path.with_suffix(".json.piloci-corrupt-bak").write_text(raw)
            existing = {}

    backup = settings_path.with_suffix(".json.piloci-bak")
    if not backup.exists() and settings_path.exists():
        backup.write_text(settings_path.read_text())

    hooks = existing.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        existing["hooks"] = hooks

    def _install_hook(event: str, command: str) -> None:
        arr = hooks.setdefault(event, [])
        if not isinstance(arr, list):
            arr = []
            hooks[event] = arr
        # Drop any prior piloci entry so re-running doesn't duplicate.
        arr[:] = [h for h in arr if PILOCI_PATH_TAG not in json.dumps(h)]
        arr.append(
            {
                "matcher": "*",
                "hooks": [{"type": "command", "command": command}],
            }
        )

    _install_hook(
        "SessionStart",
        "python3 ~/.config/piloci/hook.py 2>/dev/null || true",
    )
    _install_hook(
        "Stop",
        "bash ~/.config/piloci/stop-hook.sh 2>/dev/null || true",
    )

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(existing, indent=2))


def install_opencode_plugin(base_url: str, token: str, *, home: Path | None = None) -> Path:
    """Drop the piloci OpenCode plugin and register the MCP server in opencode.json.

    Writes the TypeScript plugin for auto-capture to
    ``~/.config/opencode/plugins/piloci.ts`` AND merges the remote MCP entry
    into ``~/.config/opencode/opencode.json`` so that recall/memory tools are
    accessible from within OpenCode sessions.
    """
    h = home or Path.home()
    plugins_dir = h / OPENCODE_PLUGIN_DIR_NAME
    plugins_dir.mkdir(parents=True, exist_ok=True)

    plugin_path = plugins_dir / "piloci.ts"
    base = base_url.rstrip("/")
    plugin_path.write_bytes(_http_download(base + "/api/hook/opencode-plugin", token=token))
    try:
        plugin_path.chmod(0o644)
    except PermissionError:
        pass

    # Also register the MCP server so recall/memory tools work inside OpenCode.
    cfg_path = h / OPENCODE_DIR_NAME / "opencode.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if cfg_path.exists():
        raw = cfg_path.read_text()
        try:
            loaded = _parse_jsonc(raw)
            if isinstance(loaded, dict):
                existing = loaded
        except (json.JSONDecodeError, ValueError):
            cfg_path.with_suffix(".json.piloci-corrupt-bak").write_text(raw)
    backup = cfg_path.with_suffix(".json.piloci-bak")
    if not backup.exists() and cfg_path.exists():
        backup.write_text(cfg_path.read_text())
    existing.setdefault("$schema", "https://opencode.ai/config.json")
    mcp = existing.setdefault("mcp", {})
    if not isinstance(mcp, dict):
        mcp = {}
        existing["mcp"] = mcp
    mcp["piloci"] = {
        "type": "remote",
        "url": base + "/mcp/http",
        "enabled": True,
        "headers": {"Authorization": "Bearer " + token},
    }
    cfg_path.write_text(json.dumps(existing, indent=2))
    try:
        cfg_path.chmod(0o600)
    except PermissionError:
        pass

    return plugin_path


# Legacy helper kept for tests that still target the older opencode.json merge
# path. Production install flow uses ``install_opencode_plugin``.
def install_opencode_mcp(base_url: str, token: str, *, home: Path | None = None) -> Path:
    """Legacy ``opencode.json`` merge — kept for tests/back-compat only."""
    h = home or Path.home()
    cfg_path = h / OPENCODE_DIR_NAME / "opencode.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if cfg_path.exists():
        raw = cfg_path.read_text()
        try:
            loaded = _parse_jsonc(raw)
            if isinstance(loaded, dict):
                existing = loaded
        except (json.JSONDecodeError, ValueError):
            cfg_path.with_suffix(".json.piloci-corrupt-bak").write_text(raw)
            existing = {}

    backup = cfg_path.with_suffix(".json.piloci-bak")
    if not backup.exists() and cfg_path.exists():
        backup.write_text(cfg_path.read_text())

    existing.setdefault("$schema", "https://opencode.ai/config.json")
    mcp = existing.setdefault("mcp", {})
    if not isinstance(mcp, dict):
        mcp = {}
        existing["mcp"] = mcp

    base = base_url.rstrip("/")
    mcp["piloci"] = {
        "type": "remote",
        "url": base + "/mcp/http",
        "enabled": True,
        "headers": {"Authorization": "Bearer " + token},
    }

    cfg_path.write_text(json.dumps(existing, indent=2))
    try:
        cfg_path.chmod(0o600)
    except PermissionError:
        pass
    return cfg_path


# ---------------------------------------------------------------------------
# Generic per-client MCP merge (Cursor, Gemini, Windsurf, AntiGravity, Zed)
# ---------------------------------------------------------------------------


def _merge_json_mcp(
    cfg_path: Path,
    *,
    parent_key: str,
    server_name: str,
    server_entry: dict,
) -> Path:
    """Merge ``server_entry`` into ``cfg_path`` under ``parent_key.server_name``.

    Idempotent — re-running replaces the prior piloci entry without touching
    sibling servers. Backs the original up to ``<file>.piloci-bak`` once so a
    user can revert by hand. A corrupt JSON file is moved aside to
    ``<file>.piloci-corrupt-bak`` and the merge starts from a clean slate.
    """
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if cfg_path.exists():
        raw = cfg_path.read_text()
        try:
            loaded = _parse_jsonc(raw)
            if isinstance(loaded, dict):
                existing = loaded
        except (json.JSONDecodeError, ValueError):
            cfg_path.with_suffix(cfg_path.suffix + ".piloci-corrupt-bak").write_text(raw)
            existing = {}

    backup = cfg_path.with_suffix(cfg_path.suffix + ".piloci-bak")
    if not backup.exists() and cfg_path.exists():
        backup.write_text(cfg_path.read_text())

    bucket = existing.setdefault(parent_key, {})
    if not isinstance(bucket, dict):
        bucket = {}
        existing[parent_key] = bucket
    bucket[server_name] = server_entry

    cfg_path.write_text(json.dumps(existing, indent=2))
    try:
        cfg_path.chmod(0o600)
    except PermissionError:
        pass
    return cfg_path


def _remove_json_mcp_entry(cfg_path: Path, *, parent_key: str, server_name: str) -> bool:
    """Drop ``parent_key.server_name`` from ``cfg_path``. Returns True if changed."""
    if not cfg_path.exists():
        return False
    try:
        loaded = _parse_jsonc(cfg_path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(loaded, dict):
        return False
    bucket = loaded.get(parent_key)
    if not isinstance(bucket, dict) or server_name not in bucket:
        return False
    bucket.pop(server_name)
    if not bucket:
        loaded.pop(parent_key, None)
    cfg_path.write_text(json.dumps(loaded, indent=2))
    return True


def install_cursor_mcp(base_url: str, token: str, *, home: Path | None = None) -> Path:
    """Merge piloci into Cursor's global ``~/.cursor/mcp.json`` (HTTP transport)."""
    h = home or Path.home()
    base = base_url.rstrip("/")
    return _merge_json_mcp(
        h / CURSOR_DIR_NAME / "mcp.json",
        parent_key="mcpServers",
        server_name="piloci",
        server_entry={
            "url": base + "/mcp/http",
            "headers": {"Authorization": "Bearer " + token},
        },
    )


def install_gemini_mcp(base_url: str, token: str, *, home: Path | None = None) -> Path:
    """Merge piloci into Gemini CLI's ``~/.gemini/settings.json``."""
    h = home or Path.home()
    base = base_url.rstrip("/")
    return _merge_json_mcp(
        h / GEMINI_DIR_NAME / "settings.json",
        parent_key="mcpServers",
        server_name="piloci",
        server_entry={
            "httpUrl": base + "/mcp/http",
            "headers": {"Authorization": "Bearer " + token},
        },
    )


def install_windsurf_mcp(base_url: str, token: str, *, home: Path | None = None) -> Path:
    """Merge piloci into Windsurf's ``~/.codeium/windsurf/mcp_config.json``."""
    h = home or Path.home()
    base = base_url.rstrip("/")
    return _merge_json_mcp(
        h / WINDSURF_DIR_NAME / "mcp_config.json",
        parent_key="mcpServers",
        server_name="piloci",
        server_entry={
            "serverUrl": base + "/mcp/http",
            "headers": {"Authorization": "Bearer " + token},
        },
    )


def install_antigravity_mcp(base_url: str, token: str, *, home: Path | None = None) -> Path:
    """Merge piloci into AntiGravity's ``~/.antigravity/mcp.json``."""
    h = home or Path.home()
    base = base_url.rstrip("/")
    return _merge_json_mcp(
        h / ANTIGRAVITY_DIR_NAME / "mcp.json",
        parent_key="mcpServers",
        server_name="piloci",
        server_entry={
            "url": base + "/mcp/http",
            "headers": {"Authorization": "Bearer " + token},
        },
    )


def install_zed_mcp(base_url: str, token: str, *, home: Path | None = None) -> Path:
    """Merge piloci into Zed's ``~/.config/zed/settings.json`` (context_servers)."""
    h = home or Path.home()
    base = base_url.rstrip("/")
    return _merge_json_mcp(
        h / ZED_DIR_NAME / "settings.json",
        parent_key="context_servers",
        server_name="piloci",
        server_entry={
            "url": base + "/mcp/http",
            "headers": {"Authorization": "Bearer " + token},
        },
    )


# ---------------------------------------------------------------------------
# Codex CLI — TOML config. Maintained as a fenced block so we can rewrite the
# piloci section without parsing/reformatting the user's hand-edited TOML.
# ---------------------------------------------------------------------------

_CODEX_BLOCK_BEGIN = "# >>> piloci managed >>>"
_CODEX_BLOCK_END = "# <<< piloci managed <<<"
_CODEX_BLOCK_RE = re.compile(
    r"\n*" + re.escape(_CODEX_BLOCK_BEGIN) + r".*?" + re.escape(_CODEX_BLOCK_END) + r"\n?",
    re.DOTALL,
)


def install_codex_mcp(base_url: str, token: str, *, home: Path | None = None) -> Path:
    """Append piloci's MCP server to Codex CLI's ``~/.codex/config.toml``."""
    h = home or Path.home()
    cfg = h / CODEX_DIR_NAME / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    base = base_url.rstrip("/")

    raw = cfg.read_text() if cfg.exists() else ""
    backup = cfg.with_suffix(".toml.piloci-bak")
    if not backup.exists() and cfg.exists():
        backup.write_text(raw)

    block = (
        f"\n{_CODEX_BLOCK_BEGIN}\n"
        "[mcp_servers.piloci]\n"
        f'url = "{base}/mcp/http"\n'
        "[mcp_servers.piloci.headers]\n"
        f'Authorization = "Bearer {token}"\n'
        f"{_CODEX_BLOCK_END}\n"
    )
    stripped = _CODEX_BLOCK_RE.sub("\n", raw).rstrip()
    cfg.write_text((stripped + block) if stripped else block.lstrip("\n"))
    try:
        cfg.chmod(0o600)
    except PermissionError:
        pass
    return cfg


def cleanup_legacy_install(*, home: Path | None = None, remove_plugins: bool = False) -> list[str]:
    """Remove pre-plugin-folder install artifacts so they don't fire alongside the
    new plugin (which would double-ingest each session).

    Always cleans:
      * piloci hook entries in ``~/.claude/settings.json`` (legacy ``_merge_claude_settings``)
      * ``~/.config/piloci/{hook.py, stop-hook.sh}`` (moved into the plugin folder)
      * piloci ``mcp`` entry in ``~/.config/opencode/opencode.json`` (legacy)

    With ``remove_plugins=True``, also wipes the plugin folders so the next
    install re-downloads ``hook.py`` / ``piloci.ts`` from the server:
      * ``~/.claude/plugins/piloci/``
      * ``~/.config/opencode/plugins/piloci.ts``

    Returns a list of removed paths/keys for the install report.
    """
    h = home or Path.home()
    removed: list[str] = []

    settings_path = h / CLAUDE_DIR_NAME / "settings.json"
    if settings_path.exists():
        try:
            loaded = _parse_jsonc(settings_path.read_text())
        except (json.JSONDecodeError, ValueError):
            loaded = None
        if isinstance(loaded, dict):
            hooks = loaded.get("hooks")
            if isinstance(hooks, dict):
                changed = False
                for event, arr in list(hooks.items()):
                    if not isinstance(arr, list):
                        continue
                    kept = [h for h in arr if PILOCI_PATH_TAG not in json.dumps(h)]
                    if len(kept) != len(arr):
                        changed = True
                        if kept:
                            hooks[event] = kept
                        else:
                            hooks.pop(event)
                if not hooks:
                    loaded.pop("hooks", None)
                if changed:
                    settings_path.write_text(json.dumps(loaded, indent=2))
                    removed.append(f"{settings_path} (piloci hook 엔트리)")

    legacy_dir = h / PILOCI_DIR_NAME
    for name in ("hook.py", "stop-hook.sh"):
        p = legacy_dir / name
        if p.exists():
            p.unlink()
            removed.append(str(p))

    opencode_cfg = h / OPENCODE_DIR_NAME / "opencode.json"
    if opencode_cfg.exists():
        try:
            loaded = _parse_jsonc(opencode_cfg.read_text())
        except (json.JSONDecodeError, ValueError):
            loaded = None
        if isinstance(loaded, dict):
            mcp = loaded.get("mcp")
            if isinstance(mcp, dict) and "piloci" in mcp:
                mcp.pop("piloci")
                if not mcp:
                    loaded.pop("mcp", None)
                opencode_cfg.write_text(json.dumps(loaded, indent=2))
                removed.append(f"{opencode_cfg} (mcp.piloci)")

    if remove_plugins:
        claude_plugin = h / CLAUDE_PLUGIN_DIR_NAME
        if claude_plugin.exists():
            shutil.rmtree(claude_plugin)
            removed.append(str(claude_plugin))
        opencode_plugin = h / OPENCODE_PLUGIN_DIR_NAME / "piloci.ts"
        if opencode_plugin.exists():
            opencode_plugin.unlink()
            removed.append(str(opencode_plugin))

    return removed


# All config files that may have a .piloci-bak snapshot taken at install time.


def _backup_targets(home: Path) -> list[Path]:
    """Return every config path that may have a .piloci-bak beside it."""
    h = home
    return [
        h / CLAUDE_DIR_NAME / "settings.json",
        h / OPENCODE_DIR_NAME / "opencode.json",
        h / CURSOR_DIR_NAME / "mcp.json",
        h / GEMINI_DIR_NAME / "settings.json",
        h / WINDSURF_DIR_NAME / "mcp_config.json",
        h / ANTIGRAVITY_DIR_NAME / "mcp.json",
        h / ZED_DIR_NAME / "settings.json",
        h / CODEX_DIR_NAME / "config.toml",
    ]


def _bak_path(cfg: Path) -> Path:
    """Return the .piloci-bak path for a given config file."""
    return cfg.with_suffix(cfg.suffix + ".piloci-bak")


def list_backups(*, home: Path | None = None) -> list[tuple[Path, Path]]:
    """Return [(original_path, backup_path), ...] for every existing backup."""
    h = home or Path.home()
    return [(cfg, _bak_path(cfg)) for cfg in _backup_targets(h) if _bak_path(cfg).exists()]


def restore_backups(*, home: Path | None = None) -> list[str]:
    """Restore every .piloci-bak file to its original location.

    Copies backup → original, then removes the backup. Returns the list of
    restored file paths. Files without a backup are left untouched.
    """
    restored: list[str] = []
    for cfg, bak in list_backups(home=home):
        shutil.copy2(bak, cfg)
        bak.unlink()
        restored.append(str(cfg))
    return restored


def run_uninstall(*, home: Path | None = None, restore: bool = True) -> list[str]:
    """Remove every piloci artifact from the host.

    With ``restore=True`` (default): config files that have a ``.piloci-bak``
    snapshot are restored to their pre-install state before piloci entries are
    removed. Files without a backup get surgical removal of only the piloci
    entry. With ``restore=False``, only surgical removal is performed (useful
    when you want to keep post-install changes to other settings).

    Returns the list of removed/restored paths for the CLI to print.
    """
    h = home or Path.home()
    report: list[str] = []

    # Step 1: restore originals where we have a snapshot.
    if restore:
        for path in restore_backups(home=h):
            report.append(f"{path} (원본 복구)")

    # Step 2: remove plugin folders, legacy hook scripts, and surgically clean
    # any config files that were NOT covered by a backup (backup was already
    # restored to the pre-piloci state, so surgical removal would be a no-op
    # for those — cleanup_legacy_install handles both gracefully).
    report.extend(cleanup_legacy_install(home=h, remove_plugins=True))

    # Step 3: remove piloci MCP entries from secondary clients not yet cleaned.
    json_targets: list[tuple[Path, str]] = [
        (h / ".claude.json", "mcpServers"),
        (h / CURSOR_DIR_NAME / "mcp.json", "mcpServers"),
        (h / GEMINI_DIR_NAME / "settings.json", "mcpServers"),
        (h / WINDSURF_DIR_NAME / "mcp_config.json", "mcpServers"),
        (h / ANTIGRAVITY_DIR_NAME / "mcp.json", "mcpServers"),
        (h / ZED_DIR_NAME / "settings.json", "context_servers"),
    ]
    for cfg_path, parent_key in json_targets:
        if _remove_json_mcp_entry(cfg_path, parent_key=parent_key, server_name="piloci"):
            report.append(f"{cfg_path} ({parent_key}.piloci 제거)")

    codex_cfg = h / CODEX_DIR_NAME / "config.toml"
    if codex_cfg.exists():
        raw = codex_cfg.read_text()
        stripped = _CODEX_BLOCK_RE.sub("\n", raw).rstrip()
        if stripped != raw.rstrip():
            codex_cfg.write_text(stripped + ("\n" if stripped else ""))
            report.append(f"{codex_cfg} (mcp_servers.piloci 제거)")

    # Step 4: wipe the shared piloci config directory (token, endpoints, scripts).
    cfg_dir = h / PILOCI_DIR_NAME
    if cfg_dir.exists():
        shutil.rmtree(cfg_dir)
        report.append(str(cfg_dir))

    return report


def post_install_heartbeat(
    base_url: str,
    token: str,
    *,
    client_kinds: list[str],
    hostname: str | None = None,
    timeout: int = 5,
) -> bool:
    """Fire-and-forget POST to ``/api/install/heartbeat`` to record this device.

    Failures (network, 4xx, 5xx) are swallowed — the install itself is already
    complete and the dashboard will simply omit the install timestamp. Returns
    True on 2xx, False otherwise so callers/tests can distinguish.
    """
    payload = {
        "client_kinds": client_kinds,
        "hostname": hostname,
        "cli_version": _cli_version(),
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/install/heartbeat",
        method="POST",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "piloci-cli",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError):
        return False


def _cli_version() -> str:
    try:
        from piloci.version import __version__

        return str(__version__)
    except Exception:
        return "unknown"


def run_install(
    token: str,
    base_url: str,
    *,
    home: Path | None = None,
    force: bool = False,
    targets: list[str] | None = None,
) -> InstallReport:
    """Detect clients and run the appropriate installers. Pure orchestration.

    Always sweeps legacy install artifacts (hook entries in settings.json, the
    old ``~/.config/piloci/hook.py``, OpenCode mcp entry) before laying down the
    plugin folder — otherwise the legacy hooks fire alongside the plugin's own
    hooks and each session gets ingested twice.

    ``force=True`` additionally wipes the plugin folders so this run re-downloads
    them fresh.

    ``targets`` is the explicit list selected by the user on the /device approve
    page (``["claude", "cursor", ...]``). When omitted the orchestrator falls
    back to auto-detection so ``piloci install`` keeps working from a plain CLI
    invocation.
    """
    h = home or Path.home()
    detected = detect_all_targets(home=h)

    if targets is not None:
        chosen = [k for k in targets if k in CLIENT_LABELS]
    else:
        chosen = [k for k, v in detected.items() if v]

    if not chosen:
        raise RuntimeError(
            "지원하는 클라이언트가 감지되지 않았습니다. Claude Code, OpenCode, Cursor, "
            "Gemini CLI, Windsurf, Codex CLI, AntiGravity, Zed 중 하나 이상을 먼저 설치하거나 "
            "/device 화면에서 설치 대상을 선택하세요."
        )

    swept = cleanup_legacy_install(home=h, remove_plugins=force)

    cfg = write_config_json(token, base_url, home=h)
    report = InstallReport(config_path=cfg)
    for item in swept:
        report.notes.append(f"정리: {item}")

    install_table: dict[str, Callable[[], Path]] = {
        "claude": lambda: install_claude_plugin(base_url, token, home=h),
        "opencode": lambda: install_opencode_plugin(base_url, token, home=h),
        "cursor": lambda: install_cursor_mcp(base_url, token, home=h),
        "gemini": lambda: install_gemini_mcp(base_url, token, home=h),
        "windsurf": lambda: install_windsurf_mcp(base_url, token, home=h),
        "antigravity": lambda: install_antigravity_mcp(base_url, token, home=h),
        "zed": lambda: install_zed_mcp(base_url, token, home=h),
        "codex": lambda: install_codex_mcp(base_url, token, home=h),
    }

    for kind in chosen:
        label = CLIENT_LABELS[kind]
        try:
            path = install_table[kind]()
            report.clients[kind] = "ok"
            if kind == "claude":
                report.claude_configured = True
                report.notes.append(
                    f"Claude Code 플러그인 설치: {path} " "(hooks + ~/.claude.json mcpServers 등록)"
                )
            elif kind == "opencode":
                report.opencode_configured = True
                report.notes.append(
                    f"OpenCode 플러그인 설치: {path} " "(자동 캡처 + opencode.json MCP 등록)"
                )
            else:
                report.notes.append(f"{label} MCP 설정 머지: {path}")
        except (urllib.error.URLError, OSError) as e:
            report.clients[kind] = f"failed: {e}"
            report.notes.append(f"{label} 설치 실패: {e}")

    kinds = [k for k, v in report.clients.items() if v == "ok"]
    if kinds:
        import socket

        try:
            host = socket.gethostname()
        except OSError:
            host = None
        if post_install_heartbeat(base_url, token, client_kinds=kinds, hostname=host):
            report.notes.append(f"설치 시그널 전송: {','.join(kinds)} ({host or '-'})")

    return report


# ---------------------------------------------------------------------------
# Network helpers used by the CLI (kept here so the module is self-contained)
# ---------------------------------------------------------------------------


def fetch_install_payload(install_url: str, *, timeout: int = 15) -> dict[str, str]:
    """Resolve a one-time install URL → {token, base_url}.

    Calls the same ``/install/{code}`` endpoint with ``Accept: application/json``
    so the server returns the JSON variant instead of the bash one-liner.
    """
    req = urllib.request.Request(
        install_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "piloci-cli",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    data = json.loads(body)
    if not isinstance(data, dict) or "token" not in data or "base_url" not in data:
        raise ValueError(f"install endpoint returned unexpected payload: {data!r}")
    return {"token": str(data["token"]), "base_url": str(data["base_url"])}


def get_default_server() -> str | None:
    """Return PILOCI_SERVER env var, or the URL stashed in config.json (if any)."""
    env = os.environ.get("PILOCI_SERVER")
    if env:
        return env.rstrip("/")
    cfg = Path.home() / PILOCI_DIR_NAME / "config.json"
    if not cfg.exists():
        return None
    try:
        loaded = json.loads(cfg.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    ingest = loaded.get("ingest_url", "")
    if isinstance(ingest, str) and ingest.endswith("/api/sessions/ingest"):
        return ingest[: -len("/api/sessions/ingest")]
    return None
