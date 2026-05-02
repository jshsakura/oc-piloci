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
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

PILOCI_DIR_NAME = ".config/piloci"
CLAUDE_DIR_NAME = ".claude"
OPENCODE_DIR_NAME = ".config/opencode"
PILOCI_PATH_TAG = "~/.config/piloci/"


@dataclass
class InstallReport:
    """Summary returned to the caller; the CLI prints it for the user."""

    config_path: Path
    claude_configured: bool = False
    opencode_configured: bool = False
    notes: list[str] = field(default_factory=list)


def detect_clients(home: Path | None = None) -> tuple[bool, bool]:
    """Return (has_claude, has_opencode) for the given HOME (defaults to real)."""
    h = home or Path.home()
    has_claude = (h / CLAUDE_DIR_NAME).is_dir()
    has_opencode = (h / OPENCODE_DIR_NAME).is_dir() or shutil.which("opencode") is not None
    return has_claude, has_opencode


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

    # 3. MCP server config — Claude Code plugin spec uses server-name keys at
    # the top level of ``.mcp.json`` (NOT wrapped in ``mcpServers``).
    mcp_path = plugin_dir / ".mcp.json"
    mcp_path.write_text(
        json.dumps(
            {
                "piloci": {
                    "type": "http",
                    "url": base + "/mcp/http",
                    "headers": {"Authorization": "Bearer " + token},
                }
            },
            indent=2,
        )
    )
    try:
        mcp_path.chmod(0o600)
    except PermissionError:
        pass

    return plugin_dir


def _merge_claude_settings(settings_path: Path) -> None:
    """Add piloci's SessionStart + Stop hooks while preserving anything else."""
    existing: dict = {}
    if settings_path.exists():
        raw = settings_path.read_text()
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                existing = loaded
        except json.JSONDecodeError:
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
    """Drop the piloci OpenCode plugin at ``~/.config/opencode/plugins/piloci.ts``.

    OpenCode auto-discovers ``{plugin,plugins}/*.{ts,js}`` files in its config
    directory. The plugin runs inside OpenCode's bun runtime: it subscribes to
    the local ``/event`` SSE feed in-process (no daemon, no system service) and
    pushes finished sessions to piloci. Token + URLs are read from
    ``~/.config/piloci/config.json`` at runtime so this file is identical for
    every user and survives token rotation.
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
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                existing = loaded
        except json.JSONDecodeError:
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


def run_install(token: str, base_url: str, *, home: Path | None = None) -> InstallReport:
    """Detect clients and run the appropriate installers. Pure orchestration."""
    h = home or Path.home()
    has_claude, has_opencode = detect_clients(home=h)
    if not has_claude and not has_opencode:
        raise RuntimeError(
            "Claude Code(~/.claude) 또는 OpenCode(~/.config/opencode 또는 'opencode' CLI)를 "
            "먼저 설치해 주세요."
        )

    cfg = write_config_json(token, base_url, home=h)
    report = InstallReport(config_path=cfg)

    if has_claude:
        try:
            plugin_dir = install_claude_plugin(base_url, token, home=h)
            report.claude_configured = True
            report.notes.append(
                f"Claude Code 플러그인 설치: {plugin_dir} "
                "(hooks + MCP 자동 발견; 설정 파일 안 건드림)"
            )
        except (urllib.error.URLError, OSError) as e:
            report.notes.append(f"Claude 플러그인 설치 실패: {e}")

    if has_opencode:
        try:
            plugin_path = install_opencode_plugin(base_url, token, home=h)
            report.opencode_configured = True
            report.notes.append(
                f"OpenCode 플러그인 설치: {plugin_path} " "(자동 캡처 + MCP; 설정 파일 안 건드림)"
            )
        except (urllib.error.URLError, OSError) as e:
            report.notes.append(f"OpenCode 플러그인 설치 실패: {e}")

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
