"""Templates for the bash installer and Stop hook served to client machines.

The installer is delivered in response to a one-time ``install_code``. It
lays down ``~/.config/piloci/{hook.py,stop-hook.sh,config.json}`` and
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
# 신스타일 단일 폴더 드롭 — 사용자 설정 파일을 건드리지 않습니다:
#   * Claude Code  → ~/.claude/plugins/piloci/  (Claude Code가 자동 발견)
#   * OpenCode     → ~/.config/opencode/plugins/piloci.ts
# 공유: ~/.config/piloci/config.json (토큰 + URL — 훅 스크립트 런타임 참조)
#
# 실행 시 구버전(설정 파일 직접 수정) 흔적도 함께 자동 정리합니다.
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

for name in ("hook.py", "stop-hook.sh"):
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
# 3) Claude Code 플러그인 폴더 드롭
# ---------------------------------------------------------------------------
INSTALLED_KINDS=()

if [ "$HAS_CLAUDE" -eq 1 ]; then
    echo "[piloci] Claude Code 플러그인 폴더 드롭…"
    mkdir -p "$CLAUDE_PLUGIN_DIR/.claude-plugin" "$CLAUDE_PLUGIN_DIR/hooks"

    PILOCI_BASE="$PILOCI_BASE" PILOCI_TOKEN="$PILOCI_TOKEN" \\
        PILOCI_PLUGIN_DIR="$CLAUDE_PLUGIN_DIR" python3 - <<'PYEOF'
import json
import os
from pathlib import Path

base = os.environ["PILOCI_BASE"].rstrip("/")
token = os.environ["PILOCI_TOKEN"]
plugin = Path(os.environ["PILOCI_PLUGIN_DIR"])

(plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({
    "name": "piloci",
    "version": "0.0.0",
    "description": (
        "piLoci memory — auto-capture sessions and expose "
        "memory/recall/recommend MCP tools"
    ),
    "author": {"name": "piLoci"},
    "homepage": "https://github.com/jshsakura/oc-piloci",
    "license": "MIT",
}, indent=2))

(plugin / "hooks" / "hooks.json").write_text(json.dumps({
    "description": "piLoci auto-capture (SessionStart catch-up + Stop live push)",
    "hooks": {
        "SessionStart": [{"hooks": [{
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/hook.py 2>/dev/null || true",
        }]}],
        "Stop": [{"hooks": [{
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/stop-hook.sh 2>/dev/null || true",
        }]}],
    },
}, indent=2))

mcp_path = plugin / ".mcp.json"
mcp_path.write_text(json.dumps({
    "piloci": {
        "type": "http",
        "url": base + "/mcp/http",
        "headers": {"Authorization": "Bearer " + token},
    }
}, indent=2))
mcp_path.chmod(0o600)
PYEOF

    curl -sfL -H "Authorization: Bearer $PILOCI_TOKEN" \\
        "$PILOCI_BASE/api/hook/script" -o "$CLAUDE_PLUGIN_DIR/hooks/hook.py.tmp"
    mv "$CLAUDE_PLUGIN_DIR/hooks/hook.py.tmp" "$CLAUDE_PLUGIN_DIR/hooks/hook.py"
    chmod 755 "$CLAUDE_PLUGIN_DIR/hooks/hook.py"

    curl -sfL -H "Authorization: Bearer $PILOCI_TOKEN" \\
        "$PILOCI_BASE/api/hook/stop-script" -o "$CLAUDE_PLUGIN_DIR/hooks/stop-hook.sh.tmp"
    mv "$CLAUDE_PLUGIN_DIR/hooks/stop-hook.sh.tmp" "$CLAUDE_PLUGIN_DIR/hooks/stop-hook.sh"
    chmod 755 "$CLAUDE_PLUGIN_DIR/hooks/stop-hook.sh"

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


STOP_HOOK_SCRIPT = """#!/usr/bin/env bash
# piloci Stop hook — pushes the current session's transcript at end of turn.
# Reads token + URL from ~/.config/piloci/config.json (no secrets in this file).
set -euo pipefail

CFG="$HOME/.config/piloci/config.json"
[ -f "$CFG" ] || exit 0

CFG_OUT=$(python3 - "$CFG" <<'PYEOF' 2>/dev/null || true
import json
import sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get("token", ""))
    print(d.get("analyze_url", ""))
except Exception:
    pass
PYEOF
)
PILOCI_TOKEN=$(printf '%s\\n' "$CFG_OUT" | sed -n '1p')
PILOCI_URL=$(printf '%s\\n' "$CFG_OUT" | sed -n '2p')
[ -n "$PILOCI_TOKEN" ] || exit 0
[ -n "$PILOCI_URL" ] || exit 0

STDIN_DATA=$(cat 2>/dev/null || true)
TRANSCRIPT_FILE=""
if [ -n "$STDIN_DATA" ]; then
    TRANSCRIPT_FILE=$(printf '%s' "$STDIN_DATA" | python3 -c \\
        "import sys, json; d=json.load(sys.stdin); print(d.get('transcript_path',''))" \\
        2>/dev/null || true)
fi
[ -n "$TRANSCRIPT_FILE" ] || exit 0
[ -f "$TRANSCRIPT_FILE" ] || exit 0

# Skip turns with too little content.
MSG_COUNT=$(grep -c '"role"' "$TRANSCRIPT_FILE" 2>/dev/null || echo "0")
if [ "$MSG_COUNT" -lt 4 ]; then
    exit 0
fi

# Pull cwd off STDIN payload so the server can resolve user-scoped tokens
# to a project via slug — without it the analyze route 400s with
# "project scope required".
PILOCI_CWD=$(printf '%s' "$STDIN_DATA" | python3 -c \\
    "import sys, json, os; d=json.load(sys.stdin); print(d.get('cwd', '') or os.getcwd())" \\
    2>/dev/null || pwd)

PILOCI_TOKEN="$PILOCI_TOKEN" PILOCI_URL="$PILOCI_URL" \\
    PILOCI_TRANSCRIPT="$TRANSCRIPT_FILE" PILOCI_CWD="$PILOCI_CWD" python3 - <<'PYEOF'
import json
import os
import urllib.error
import urllib.request

url = os.environ["PILOCI_URL"]
token = os.environ["PILOCI_TOKEN"]
fn = os.environ["PILOCI_TRANSCRIPT"]
cwd = os.environ.get("PILOCI_CWD", "")
try:
    transcript = open(fn, "rb").read().decode("utf-8", "ignore")
except OSError:
    raise SystemExit(0)
body = {"transcript": transcript}
if cwd:
    body["cwd"] = cwd
payload = json.dumps(body).encode()
req = urllib.request.Request(
    url,
    data=payload,
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
PYEOF
exit 0
"""

# Cross-platform Stop hook for Codex CLI (Mac / Linux / Windows).
# Reads Codex stop payload from stdin and ships the transcript to piLoci.
CODEX_STOP_HOOK_SCRIPT = '''\
#!/usr/bin/env python3
"""piLoci Stop hook for Codex CLI — Mac, Linux, Windows.

Reads token + URL from ~/.config/piloci/config.json at runtime.
Receives Codex stop payload via stdin; extracts transcript_path and POSTs to piLoci.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

_CONFIG = Path.home() / ".config" / "piloci" / "config.json"
_MIN_ROLE_LINES = 4


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
