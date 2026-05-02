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
# Auto-detects which client(s) are present and configures each:
#   * Claude Code  → ~/.claude/settings.json (SessionStart + Stop hooks)
#                    + ~/.config/piloci/{hook.py, stop-hook.sh}
#   * OpenCode     → ~/.config/opencode/opencode.json (mcp.piloci entry)
# Both clients share the same ~/.config/piloci/config.json (token + URLs).
set -euo pipefail

PILOCI_BASE="__PILOCI_BASE__"
PILOCI_TOKEN="__PILOCI_TOKEN__"

CFG_DIR="$HOME/.config/piloci"
CLAUDE_DIR="$HOME/.claude"
CLAUDE_SETTINGS="$CLAUDE_DIR/settings.json"
OPENCODE_DIR="$HOME/.config/opencode"
OPENCODE_CONFIG="$OPENCODE_DIR/opencode.json"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[piloci] python3 가 필요합니다 (JSON 머지에 사용)." >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "[piloci] curl 이 필요합니다." >&2
    exit 1
fi

# Detect which clients exist on this machine.
HAS_CLAUDE=0
HAS_OPENCODE=0
[ -d "$CLAUDE_DIR" ] && HAS_CLAUDE=1
{ [ -d "$OPENCODE_DIR" ] || command -v opencode >/dev/null 2>&1; } && HAS_OPENCODE=1

if [ "$HAS_CLAUDE" -eq 0 ] && [ "$HAS_OPENCODE" -eq 0 ]; then
    echo "[piloci] 감지된 클라이언트가 없습니다." >&2
    echo "         Claude Code(~/.claude) 또는 OpenCode(~/.config/opencode 또는 'opencode' CLI)를 설치한 뒤 다시 실행해 주세요." >&2
    exit 1
fi

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

CLAUDE_MCP="$HOME/.claude.json"

if [ "$HAS_CLAUDE" -eq 1 ]; then
    echo "[piloci] Claude Code 감지 — hook.py / stop-hook.sh 다운로드…"
    mkdir -p "$CLAUDE_DIR"
    curl -sfL -H "Authorization: Bearer $PILOCI_TOKEN" \\
        "$PILOCI_BASE/api/hook/script" -o "$CFG_DIR/hook.py.tmp"
    mv "$CFG_DIR/hook.py.tmp" "$CFG_DIR/hook.py"
    chmod 644 "$CFG_DIR/hook.py"

    curl -sfL -H "Authorization: Bearer $PILOCI_TOKEN" \\
        "$PILOCI_BASE/api/hook/stop-script" -o "$CFG_DIR/stop-hook.sh.tmp"
    mv "$CFG_DIR/stop-hook.sh.tmp" "$CFG_DIR/stop-hook.sh"
    chmod 755 "$CFG_DIR/stop-hook.sh"

    echo "[piloci] ~/.claude/settings.json 머지…"
    python3 - "$CLAUDE_SETTINGS" <<'PYEOF'
import json
import sys
from pathlib import Path

settings_path = Path(sys.argv[1])
existing = {}
if settings_path.exists():
    raw = settings_path.read_text()
    try:
        existing = json.loads(raw) or {}
    except json.JSONDecodeError:
        # Don't overwrite a corrupt file blindly; back it up and start fresh.
        settings_path.with_suffix(".json.piloci-corrupt-bak").write_text(raw)
        existing = {}

# Keep one pristine backup of whatever was there before piloci first touched it.
backup = settings_path.with_suffix(".json.piloci-bak")
if not backup.exists() and settings_path.exists():
    backup.write_text(settings_path.read_text())

PILOCI_PATH_TAG = "~/.config/piloci/"


def install_hook(hooks_section, event_name, command):
    arr = hooks_section.setdefault(event_name, [])
    arr[:] = [h for h in arr if PILOCI_PATH_TAG not in json.dumps(h)]
    arr.append({
        "matcher": "*",
        "hooks": [{"type": "command", "command": command}],
    })


if not isinstance(existing, dict):
    existing = {}
hooks = existing.setdefault("hooks", {})
if not isinstance(hooks, dict):
    hooks = {}
    existing["hooks"] = hooks

install_hook(
    hooks,
    "SessionStart",
    "python3 ~/.config/piloci/hook.py 2>/dev/null || true",
)
install_hook(
    hooks,
    "Stop",
    "bash ~/.config/piloci/stop-hook.sh 2>/dev/null || true",
)

settings_path.parent.mkdir(parents=True, exist_ok=True)
settings_path.write_text(json.dumps(existing, indent=2))
PYEOF

    echo "[piloci] ~/.claude.json (MCP 서버) 머지…"
    PILOCI_BASE="$PILOCI_BASE" PILOCI_TOKEN="$PILOCI_TOKEN" python3 - "$CLAUDE_MCP" <<'PYEOF'
import json
import os
import sys
from pathlib import Path

cfg_path = Path(sys.argv[1])
base = os.environ["PILOCI_BASE"].rstrip("/")
token = os.environ["PILOCI_TOKEN"]

existing = {}
if cfg_path.exists():
    raw = cfg_path.read_text()
    try:
        existing = json.loads(raw) or {}
    except json.JSONDecodeError:
        cfg_path.with_suffix(".json.piloci-corrupt-bak").write_text(raw)
        existing = {}

backup = cfg_path.with_suffix(".json.piloci-bak")
if not backup.exists() and cfg_path.exists():
    backup.write_text(cfg_path.read_text())

if not isinstance(existing, dict):
    existing = {}
servers = existing.setdefault("mcpServers", {})
if not isinstance(servers, dict):
    servers = {}
    existing["mcpServers"] = servers

servers["piloci"] = {
    "type": "http",
    "url": base + "/mcp/http",
    "headers": {"Authorization": "Bearer " + token},
}

cfg_path.write_text(json.dumps(existing, indent=2))
cfg_path.chmod(0o600)
PYEOF
fi

if [ "$HAS_OPENCODE" -eq 1 ]; then
    echo "[piloci] OpenCode 감지 — opencode.json 머지…"
    mkdir -p "$OPENCODE_DIR"
    PILOCI_BASE="$PILOCI_BASE" PILOCI_TOKEN="$PILOCI_TOKEN" python3 - "$OPENCODE_CONFIG" <<'PYEOF'
import json
import os
import sys
from pathlib import Path

cfg_path = Path(sys.argv[1])
base = os.environ["PILOCI_BASE"].rstrip("/")
token = os.environ["PILOCI_TOKEN"]

existing = {}
if cfg_path.exists():
    raw = cfg_path.read_text()
    try:
        existing = json.loads(raw) or {}
    except json.JSONDecodeError:
        cfg_path.with_suffix(".json.piloci-corrupt-bak").write_text(raw)
        existing = {}

backup = cfg_path.with_suffix(".json.piloci-bak")
if not backup.exists() and cfg_path.exists():
    backup.write_text(cfg_path.read_text())

if not isinstance(existing, dict):
    existing = {}
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

cfg_path.parent.mkdir(parents=True, exist_ok=True)
cfg_path.write_text(json.dumps(existing, indent=2))
cfg_path.chmod(0o600)
PYEOF
fi

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
[ "$HAS_CLAUDE" -eq 1 ] && echo "  • Claude Code: 새 세션 시작 시 자동 메모 적재"
[ "$HAS_OPENCODE" -eq 1 ] && echo "  • OpenCode: opencode.json 의 mcp.piloci 엔트리로 MCP 연결"
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

PILOCI_TOKEN="$PILOCI_TOKEN" PILOCI_URL="$PILOCI_URL" \\
    PILOCI_TRANSCRIPT="$TRANSCRIPT_FILE" python3 - <<'PYEOF'
import json
import os
import urllib.error
import urllib.request

url = os.environ["PILOCI_URL"]
token = os.environ["PILOCI_TOKEN"]
fn = os.environ["PILOCI_TRANSCRIPT"]
try:
    transcript = open(fn, "rb").read().decode("utf-8", "ignore")
except OSError:
    raise SystemExit(0)
payload = json.dumps({"transcript": transcript}).encode()
req = urllib.request.Request(
    url,
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
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


def build_install_script(*, token: str, base_url: str) -> str:
    """Return the bash installer with token + base URL inlined.

    The token shows up in only two places: the response body of
    ``GET /install/<code>`` and the file the user pipes to bash. After the
    code is consumed the server can no longer reproduce the script.
    """
    base = base_url.rstrip("/")
    return _INSTALL_TEMPLATE.replace(_BASE_PLACEHOLDER, base).replace(_TOKEN_PLACEHOLDER, token)
