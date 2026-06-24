"""Templates for the bash installer and Stop hook served to client machines.

The installer is delivered in response to a one-time ``install_code``. It
lays down ``~/.config/piloci/{hook.py,stop-hook.py,config.json}`` and
merges the two hook commands into ``~/.claude/settings.json`` while
preserving any pre-existing user hooks. The token is inlined into the
script body — the network response is the only place it appears.

Token rotation
--------------
The hook scripts themselves contain no secrets — they read
``~/.config/piloci/config.json`` at runtime. Rotating the API token is a
matter of regenerating ``config.json``; nothing else changes on the
client.
"""

from __future__ import annotations

# Placeholders are simple ASCII tokens; we use ``str.replace`` instead of
# ``str.format``/f-strings so we don't have to escape every JSON brace in
# the embedded Python heredocs.
_BASE_PLACEHOLDER = "__PILOCI_BASE__"
_TOKEN_PLACEHOLDER = "__PILOCI_TOKEN__"


_INSTALL_TEMPLATE = """#!/usr/bin/env bash
# piloci installer (generated per install code, single-use).
#
# 클라이언트별 설치 위치:
#   * Claude Code  → ~/.claude/settings.json(훅) + ~/.claude.json(MCP) 직접 머지
#                    훅 스크립트는 ~/.config/piloci/{hook.py,stop-hook.py}
#   * OpenCode     → ~/.config/opencode/plugins/piloci.ts
# 공유: ~/.config/piloci/config.json (토큰 + URL — 훅 스크립트 런타임 참조)
#
# 설정 파일 머지는 기존 비-piloci 항목을 보존하며, piloci 항목은 idempotent
# (재실행 시 중복되지 않음). 구버전(자동 활성화 안 되던 플러그인 폴더) 흔적도
# 함께 자동 정리합니다.
set -euo pipefail

PILOCI_BASE="__PILOCI_BASE__"
PILOCI_TOKEN="__PILOCI_TOKEN__"

CFG_DIR="$HOME/.config/piloci"
CLAUDE_DIR="$HOME/.claude"
CLAUDE_SETTINGS="$CLAUDE_DIR/settings.json"
CLAUDE_MCP="$HOME/.claude.json"
CLAUDE_PLUGIN_DIR="$CLAUDE_DIR/plugins/piloci"
OPENCODE_DIR="$HOME/.config/opencode"
OPENCODE_CONFIG="$OPENCODE_DIR/opencode.json"
OPENCODE_PLUGINS_DIR="$OPENCODE_DIR/plugins"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[piloci] python3 가 필요합니다 (JSON 머지/검증에 사용)." >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "[piloci] curl 이 필요합니다." >&2
    exit 1
fi

HAS_CLAUDE=0
HAS_OPENCODE=0
[ -d "$CLAUDE_DIR" ] && HAS_CLAUDE=1
{ [ -d "$OPENCODE_DIR" ] || command -v opencode >/dev/null 2>&1; } && HAS_OPENCODE=1

if [ "$HAS_CLAUDE" -eq 0 ] && [ "$HAS_OPENCODE" -eq 0 ]; then
    echo "[piloci] 감지된 클라이언트가 없습니다." >&2
    echo "         Claude Code(~/.claude) 또는 OpenCode(~/.config/opencode 또는 'opencode' CLI)를 설치한 뒤 다시 실행해 주세요." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 1) 구버전 흔적 자동 정리 — 신/구 훅이 동시 실행되면 세션이 두 번 ingest 됩니다.
# ---------------------------------------------------------------------------
echo "[piloci] 구버전 흔적 정리…"
python3 - "$CLAUDE_SETTINGS" "$CLAUDE_MCP" "$OPENCODE_CONFIG" "$CFG_DIR" <<'PYEOF'
import json
import sys
from pathlib import Path

settings_path, claude_mcp, opencode_cfg, cfg_dir = (Path(p) for p in sys.argv[1:5])
PILOCI_PATH_TAG = "~/.config/piloci/"


def _strip_piloci_hooks(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
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
        data.pop("hooks", None)
    if changed:
        path.write_text(json.dumps(data, indent=2))
    return changed


def _strip_dict_key(path: Path, *parents: str, key: str = "piloci") -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    target = data
    for p in parents:
        nxt = target.get(p)
        if not isinstance(nxt, dict):
            return False
        target = nxt
    if key not in target:
        return False
    target.pop(key)
    if not target and parents:
        # parent dict empty → drop it
        data_walk = data
        for p in parents[:-1]:
            data_walk = data_walk[p]
        data_walk.pop(parents[-1])
    path.write_text(json.dumps(data, indent=2))
    return True


_strip_piloci_hooks(settings_path)
_strip_dict_key(claude_mcp, "mcpServers")
_strip_dict_key(opencode_cfg, "mcp")

for name in ("hook.py", "stop-hook.py", "stop-hook.sh"):
    p = cfg_dir / name
    if p.exists():
        p.unlink()
PYEOF

# ---------------------------------------------------------------------------
# 2) 공유 config.json (토큰 + URL) — 훅 스크립트가 런타임에 읽음
# ---------------------------------------------------------------------------
mkdir -p "$CFG_DIR"
chmod 700 "$CFG_DIR"

echo "[piloci] config.json 작성…"
PILOCI_BASE="$PILOCI_BASE" PILOCI_TOKEN="$PILOCI_TOKEN" python3 - <<'PYEOF'
import json
import os
from pathlib import Path

cfg = Path.home() / ".config" / "piloci" / "config.json"
base = os.environ["PILOCI_BASE"].rstrip("/")
data = {
    "token": os.environ["PILOCI_TOKEN"],
    "ingest_url": base + "/api/sessions/ingest",
    "analyze_url": base + "/api/sessions/analyze",
}
cfg.write_text(json.dumps(data, indent=2))
cfg.chmod(0o600)
PYEOF

# ---------------------------------------------------------------------------
# 3) Claude Code — config.json 기반 직접 훅 + MCP 주입
#    플러그인 폴더만 떨구는 방식은 Claude Code 가 자동 활성화하지 않아 훅이
#    한 번도 안 떴다(토큰 last_used=None). settings.json/.claude.json 에
#    직접 머지하는 검증된 방식으로 복귀한다. 기존 사용자 설정은 보존.
# ---------------------------------------------------------------------------
INSTALLED_KINDS=()

if [ "$HAS_CLAUDE" -eq 1 ]; then
    echo "[piloci] Claude Code 훅/MCP 설정…"

    # 훅 스크립트를 공유 config 디렉터리에 내려받음 (settings.json 이 이 경로를 참조)
    curl -sfL -H "Authorization: Bearer $PILOCI_TOKEN" \\
        "$PILOCI_BASE/api/hook/script" -o "$CFG_DIR/hook.py.tmp"
    mv "$CFG_DIR/hook.py.tmp" "$CFG_DIR/hook.py"
    chmod 755 "$CFG_DIR/hook.py"

    curl -sfL -H "Authorization: Bearer $PILOCI_TOKEN" \\
        "$PILOCI_BASE/api/hook/stop-script" -o "$CFG_DIR/stop-hook.py.tmp"
    mv "$CFG_DIR/stop-hook.py.tmp" "$CFG_DIR/stop-hook.py"
    chmod 755 "$CFG_DIR/stop-hook.py"

    # 자동 활성화가 안 돼 훅이 안 뜨던 구버전 플러그인 폴더 제거.
    rm -rf "$CLAUDE_PLUGIN_DIR"

    # settings.json 에 훅 직접 머지 — 기존 사용자 훅 보존, piloci 항목만 idempotent.
    python3 - "$CLAUDE_SETTINGS" <<'PYEOF'
import json
import os
import sys
from pathlib import Path

p = Path(sys.argv[1])
try:
    data = json.loads(p.read_text()) if p.exists() else {}
except (json.JSONDecodeError, OSError):
    data = {}
if not isinstance(data, dict):
    data = {}

hooks = data.get("hooks")
if not isinstance(hooks, dict):
    hooks = {}

TAG = "~/.config/piloci/"

def upsert(event, command):
    arr = hooks.get(event)
    if not isinstance(arr, list):
        arr = []
    arr = [h for h in arr if TAG not in json.dumps(h)]
    arr.append({"matcher": "*", "hooks": [{"type": "command", "command": command}]})
    hooks[event] = arr

upsert("SessionStart", "python3 ~/.config/piloci/hook.py 2>/dev/null || true")
upsert("Stop", "python3 ~/.config/piloci/stop-hook.py 2>/dev/null || true")
data["hooks"] = hooks

p.parent.mkdir(parents=True, exist_ok=True)
tmp = p.with_name(p.name + ".piloci-tmp")
tmp.write_text(json.dumps(data, indent=2))
os.replace(tmp, p)
PYEOF

    # MCP 서버를 ~/.claude.json 에 머지 — 기존 mcpServers/설정 보존.
    PILOCI_BASE="$PILOCI_BASE" PILOCI_TOKEN="$PILOCI_TOKEN" python3 - "$CLAUDE_MCP" <<'PYEOF'
import json
import os
import sys
from pathlib import Path

p = Path(sys.argv[1])
try:
    data = json.loads(p.read_text()) if p.exists() else {}
except (json.JSONDecodeError, OSError):
    data = {}
if not isinstance(data, dict):
    data = {}

servers = data.get("mcpServers")
if not isinstance(servers, dict):
    servers = {}
servers["piloci"] = {
    "type": "http",
    "url": os.environ["PILOCI_BASE"].rstrip("/") + "/mcp/http",
    "headers": {"Authorization": "Bearer " + os.environ["PILOCI_TOKEN"]},
}
data["mcpServers"] = servers

p.parent.mkdir(parents=True, exist_ok=True)
tmp = p.with_name(p.name + ".piloci-tmp")
tmp.write_text(json.dumps(data, indent=2))
os.replace(tmp, p)
PYEOF

    INSTALLED_KINDS+=("claude")
fi

# ---------------------------------------------------------------------------
# 4) OpenCode 플러그인 파일 드롭
# ---------------------------------------------------------------------------
if [ "$HAS_OPENCODE" -eq 1 ]; then
    echo "[piloci] OpenCode 플러그인 파일 드롭…"
    mkdir -p "$OPENCODE_PLUGINS_DIR"
    curl -sfL -H "Authorization: Bearer $PILOCI_TOKEN" \\
        "$PILOCI_BASE/api/hook/opencode-plugin" -o "$OPENCODE_PLUGINS_DIR/piloci.ts.tmp"
    mv "$OPENCODE_PLUGINS_DIR/piloci.ts.tmp" "$OPENCODE_PLUGINS_DIR/piloci.ts"
    chmod 644 "$OPENCODE_PLUGINS_DIR/piloci.ts"

    INSTALLED_KINDS+=("opencode")
fi

# ---------------------------------------------------------------------------
# 5) 설치 시그널 — 대시보드에 installed_at/client_kinds/hostname 기록
# ---------------------------------------------------------------------------
if [ ${#INSTALLED_KINDS[@]} -gt 0 ]; then
    KINDS_JSON=$(printf '"%s",' "${INSTALLED_KINDS[@]}" | sed 's/,$//')
    HOSTNAME_VAL=$(hostname 2>/dev/null | tr -d '\\n' | cut -c1-64)
    curl -sf -H "Authorization: Bearer $PILOCI_TOKEN" \\
        -H "Content-Type: application/json" \\
        --max-time 5 \\
        -d "{\\"client_kinds\\":[${KINDS_JSON}],\\"hostname\\":\\"${HOSTNAME_VAL}\\"}" \\
        "$PILOCI_BASE/api/install/heartbeat" >/dev/null 2>&1 || true
fi

# ---------------------------------------------------------------------------
# 6) 연결 확인 (선택)
# ---------------------------------------------------------------------------
echo "[piloci] 연결 확인…"
if curl -sf -H "Authorization: Bearer $PILOCI_TOKEN" \\
        "$PILOCI_BASE/healthz" >/dev/null 2>&1; then
    echo "[piloci] ✓ 연결 OK"
else
    echo "[piloci] ⚠ $PILOCI_BASE 에 닿지 못했지만 설정은 끝났습니다."
    echo "         서버가 살아있을 때 자동으로 동작합니다."
fi

echo ""
echo "✓ piloci 설치 완료"
[ "$HAS_CLAUDE" -eq 1 ] && echo "  • Claude Code: $CLAUDE_PLUGIN_DIR (다음 세션 시작 시 자동 발견)"
[ "$HAS_OPENCODE" -eq 1 ] && echo "  • OpenCode: $OPENCODE_PLUGINS_DIR/piloci.ts"
echo "  토큰 회전 시 ~/.config/piloci/config.json 만 갱신하세요."
"""


STOP_HOOK_SCRIPT = '''\
#!/usr/bin/env python3
"""piLoci Stop hook (Claude Code / Codex) — Mac, Linux, Windows.

Pushes the current session's transcript at end of turn. Reads token +
URL from ~/.config/piloci/config.json at runtime (no secrets in this
file). Receives the host's stop payload via stdin; extracts the
transcript path and POSTs to piLoci. Failures are silent so a Stop hook
crash never blocks the user's next turn.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

_CONFIG = Path.home() / ".config" / "piloci" / "config.json"
_MIN_ROLE_LINES = 4


def _project_root(cwd):
    """Collapse cwd to its git project root before reporting it to the server.

    Keeps a repo from fragmenting into one project per subdirectory and folds
    Claude Code subagent worktrees (.../.claude/worktrees/agent-XXXX) back into
    the real repo. Mirror of piloci.tools.memory_tools.resolve_project_root.
    """
    def _git(*args):
        try:
            r = subprocess.run(
                ["git", "-C", cwd, "rev-parse", *args],
                capture_output=True, text=True, timeout=3,
            )
        except Exception:
            return None
        out = r.stdout.strip()
        return out if r.returncode == 0 and out else None

    common = _git("--path-format=absolute", "--git-common-dir")
    if common:
        norm = common.replace("\\\\", "/").rstrip("/")
        if norm.endswith("/.git"):
            return norm[: -len("/.git")]
    top = _git("--show-toplevel")
    if top:
        return top
    marker = "/.claude/worktrees/"
    norm = cwd.replace("\\\\", "/")
    idx = norm.find(marker)
    if idx != -1:
        return norm[:idx]
    return cwd


def _read_stdin_payload():
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read()
    except OSError:
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def main():
    try:
        cfg = json.loads(_CONFIG.read_text())
    except Exception:
        return

    token = cfg.get("token")
    url = cfg.get("analyze_url")
    if not token or not url:
        return

    payload = _read_stdin_payload()
    transcript_path_str = payload.get("transcript_path")
    if not transcript_path_str:
        return

    path = Path(transcript_path_str)
    try:
        transcript = path.read_bytes().decode("utf-8", "ignore")
    except OSError:
        return

    # Skip turns that are too small to be worth shipping.
    if transcript.count(\'"role"\') < _MIN_ROLE_LINES:
        return

    cwd = _project_root(payload.get("cwd") or os.getcwd())
    body = {"transcript": transcript, "cwd": cwd}

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "piloci-stop-hook",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=30)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        pass


main()
'''

# Cross-platform Stop hook for Codex CLI (Mac / Linux / Windows).
# Reads Codex stop payload from stdin and ships the transcript to piLoci.
CODEX_STOP_HOOK_SCRIPT = '''\
#!/usr/bin/env python3
"""piLoci Stop hook for Codex CLI — Mac, Linux, Windows.

Reads token + URL from ~/.config/piloci/config.json at runtime.
Receives Codex stop payload via stdin; extracts transcript_path and POSTs to piLoci.
"""
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

_CONFIG = Path.home() / ".config" / "piloci" / "config.json"
_MIN_ROLE_LINES = 4


def _project_root(cwd):
    """Collapse cwd to its git project root (mirror of resolve_project_root)."""
    def _git(*args):
        try:
            r = subprocess.run(
                ["git", "-C", cwd, "rev-parse", *args],
                capture_output=True, text=True, timeout=3,
            )
        except Exception:
            return None
        out = r.stdout.strip()
        return out if r.returncode == 0 and out else None

    common = _git("--path-format=absolute", "--git-common-dir")
    if common:
        norm = common.replace("\\\\", "/").rstrip("/")
        if norm.endswith("/.git"):
            return norm[: -len("/.git")]
    top = _git("--show-toplevel")
    if top:
        return top
    marker = "/.claude/worktrees/"
    norm = cwd.replace("\\\\", "/")
    idx = norm.find(marker)
    if idx != -1:
        return norm[:idx]
    return cwd


def main():
    try:
        cfg = json.loads(_CONFIG.read_text())
    except Exception:
        return

    token = cfg.get("token")
    url = cfg.get("analyze_url")
    if not token or not url:
        return

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw and raw.strip() else {}
    except Exception:
        return

    transcript_path_str = payload.get("transcript_path")
    cwd = payload.get("cwd", "")
    if cwd:
        cwd = _project_root(cwd)
    if not transcript_path_str:
        return

    path = Path(transcript_path_str)
    try:
        transcript = path.read_bytes().decode("utf-8", "ignore")
    except OSError:
        return

    if transcript.count(\'"role"\') < _MIN_ROLE_LINES:
        return

    body: dict = {"transcript": transcript}
    if cwd:
        body["cwd"] = cwd

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "piloci-codex-stop-hook",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=30)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        pass


main()
'''


def build_install_script(*, token: str, base_url: str) -> str:
    """Return the bash installer with token + base URL inlined.

    The token shows up in only two places: the response body of
    ``GET /install/<code>`` and the file the user pipes to bash. After the
    code is consumed the server can no longer reproduce the script.
    """
    base = base_url.rstrip("/")
    return _INSTALL_TEMPLATE.replace(_BASE_PLACEHOLDER, base).replace(_TOKEN_PLACEHOLDER, token)


# ---------------------------------------------------------------------------
# Windows PowerShell installer — same end state as the bash variant
# ---------------------------------------------------------------------------

_POWERSHELL_INSTALL_TEMPLATE = r"""#Requires -Version 5.1
# piloci Windows installer (PowerShell 5.1+ / 7.x).
# 한 줄 실행:
#   iwr -useb https://your.piloci.example/install/<code>.ps1 | iex
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$PILOCI_BASE  = '__PILOCI_BASE__'
$PILOCI_TOKEN = '__PILOCI_TOKEN__'

function Find-PythonCommand {
    # `py` launcher (Python.org official) is the canonical Windows entry point;
    # fall back to plain `python` for chocolatey / winget / Microsoft Store builds
    # that skip it. Return the literal command name so we can embed it in hook
    # configs the host AI client will shell out to later.
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { return 'py' }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return 'python' }
    return $null
}

$pythonCmd = Find-PythonCommand
if (-not $pythonCmd) {
    Write-Error '[piloci] Python 3.10+ 가 필요합니다. https://www.python.org/downloads/ 에서 설치하세요.'
    exit 1
}
Write-Host "[piloci] Python: $pythonCmd"

# Auth header reused for every download.
$headers = @{ Authorization = "Bearer $PILOCI_TOKEN"; 'User-Agent' = 'piloci-installer' }

# 1) Shared config dir under ~/.config/piloci — same layout as POSIX so a user
#    moving a config between machines doesn't need to relocate it.
$cfgDir = Join-Path $env:USERPROFILE '.config\piloci'
if (-not (Test-Path $cfgDir)) {
    New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
}

Write-Host '[piloci] config.json 작성…'
$config = [ordered]@{
    token       = $PILOCI_TOKEN
    ingest_url  = "$PILOCI_BASE/api/sessions/ingest"
    analyze_url = "$PILOCI_BASE/api/sessions/analyze"
}
$cfgPath = Join-Path $cfgDir 'config.json'
($config | ConvertTo-Json -Depth 5) | Set-Content -Path $cfgPath -Encoding UTF8

# Drop the cross-platform hook scripts into the shared config dir. The
# Claude Code settings written below point at these paths at runtime.
Write-Host '[piloci] hook 스크립트 다운로드…'
Invoke-WebRequest -Uri "$PILOCI_BASE/api/hook/script" -Headers $headers `
    -OutFile (Join-Path $cfgDir 'hook.py') -UseBasicParsing
Invoke-WebRequest -Uri "$PILOCI_BASE/api/hook/stop-script" -Headers $headers `
    -OutFile (Join-Path $cfgDir 'stop-hook.py') -UseBasicParsing
# Remove legacy bash file from older installs so the dir stops shipping two.
$legacyShPath = Join-Path $cfgDir 'stop-hook.sh'
if (Test-Path $legacyShPath) { Remove-Item -Force $legacyShPath }

# 2) Claude Code — settings.json(훅) + .claude.json(MCP) 직접 머지.
#    플러그인 폴더만 떨구면 Claude Code 가 자동 활성화하지 않아 훅이 안 떴다.
#    기존 사용자 설정은 보존하고 piloci 항목만 idempotent 하게 기록한다.
$claudeDir = Join-Path $env:USERPROFILE '.claude'
if (Test-Path $claudeDir) {
    Write-Host '[piloci] Claude Code 훅/MCP 설정…'
    $settingsPath  = Join-Path $claudeDir 'settings.json'
    $claudeMcpPath = Join-Path $env:USERPROFILE '.claude.json'

    # 자동 활성화가 안 되던 구버전 플러그인 폴더 제거.
    $legacyPluginDir = Join-Path $claudeDir 'plugins\piloci'
    if (Test-Path $legacyPluginDir) { Remove-Item -Recurse -Force $legacyPluginDir }

    $hookPyPath = (Join-Path $cfgDir 'hook.py')
    $stopPyPath = (Join-Path $cfgDir 'stop-hook.py')
    $env:PILOCI_BASE     = $PILOCI_BASE
    $env:PILOCI_TOKEN    = $PILOCI_TOKEN
    $env:PILOCI_HOOK_CMD = "$pythonCmd `"$hookPyPath`" 2>NUL"
    $env:PILOCI_STOP_CMD = "$pythonCmd `"$stopPyPath`" 2>NUL"

    $mergePy = @'
import json, os, sys
from pathlib import Path

mode, target = sys.argv[1], Path(sys.argv[2])
try:
    data = json.loads(target.read_text()) if target.exists() else {}
except Exception:
    data = {}
if not isinstance(data, dict):
    data = {}


def is_piloci(h):
    s = json.dumps(h)
    return "piloci" in s and "hook.py" in s


if mode == "hooks":
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}

    def upsert(event, command):
        arr = hooks.get(event)
        if not isinstance(arr, list):
            arr = []
        arr = [h for h in arr if not is_piloci(h)]
        arr.append({"matcher": "*", "hooks": [{"type": "command", "command": command}]})
        hooks[event] = arr

    upsert("SessionStart", os.environ["PILOCI_HOOK_CMD"])
    upsert("Stop", os.environ["PILOCI_STOP_CMD"])
    data["hooks"] = hooks
else:
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers["piloci"] = {
        "type": "http",
        "url": os.environ["PILOCI_BASE"].rstrip("/") + "/mcp/http",
        "headers": {"Authorization": "Bearer " + os.environ["PILOCI_TOKEN"]},
    }
    data["mcpServers"] = servers

target.parent.mkdir(parents=True, exist_ok=True)
tmp = target.with_name(target.name + ".piloci-tmp")
tmp.write_text(json.dumps(data, indent=2))
os.replace(str(tmp), str(target))
'@
    $mergeScript = Join-Path $cfgDir '_merge.py'
    Set-Content -Path $mergeScript -Value $mergePy -Encoding UTF8
    & $pythonCmd $mergeScript hooks $settingsPath
    & $pythonCmd $mergeScript mcp $claudeMcpPath
    Remove-Item -Force $mergeScript
}

Write-Host ''
Write-Host '[piloci] 설치 완료.'
Write-Host "  토큰 회전 시 $cfgPath 만 갱신하세요."
"""


def build_powershell_install_script(*, token: str, base_url: str) -> str:
    """Return the PowerShell installer with token + base URL inlined.

    Mirrors ``build_install_script`` for Windows clients — same end state in
    ``%USERPROFILE%\\.config\\piloci`` and the optional Claude Code plugin
    folder. PowerShell 5.1 compatible (the default shell shipped with
    Windows 10/11) so users don't need to install PowerShell 7 first.
    """
    base = base_url.rstrip("/")
    return _POWERSHELL_INSTALL_TEMPLATE.replace(_BASE_PLACEHOLDER, base).replace(
        _TOKEN_PLACEHOLDER, token
    )
