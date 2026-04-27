#!/usr/bin/env bash
# piloci Stop hook — send Claude Code session to piLoci for instinct extraction.
#
# Setup (add to ~/.claude/settings.json):
#
#   "hooks": {
#     "Stop": [{
#       "matcher": "*",
#       "hooks": [{
#         "type": "command",
#         "command": "/path/to/piloci-stop-hook.sh"
#       }]
#     }]
#   }
#
# Required env vars (set in ~/.claude/settings.json or shell profile):
#   PILOCI_URL    — e.g. http://localhost:8314  (default: http://localhost:8314)
#   PILOCI_TOKEN  — project-scoped API token from piLoci Settings > Tokens

set -euo pipefail

PILOCI_URL="${PILOCI_URL:-http://localhost:8314}"
PILOCI_TOKEN="${PILOCI_TOKEN:-}"

if [ -z "$PILOCI_TOKEN" ]; then
    exit 0
fi

# Claude Code provides session transcript path via env or stdin JSON
TRANSCRIPT_FILE="${CLAUDE_SESSION_TRANSCRIPT:-}"

# Fall back to stdin (Claude Code Stop hook passes JSON to stdin)
if [ -z "$TRANSCRIPT_FILE" ]; then
    STDIN_DATA=$(cat 2>/dev/null || true)
    if [ -n "$STDIN_DATA" ]; then
        TRANSCRIPT_FILE=$(echo "$STDIN_DATA" | python3 -c \
            "import sys,json; d=json.load(sys.stdin); print(d.get('transcript_path',''))" 2>/dev/null || true)
    fi
fi

if [ -z "$TRANSCRIPT_FILE" ] || [ ! -f "$TRANSCRIPT_FILE" ]; then
    exit 0
fi

# Skip short sessions (< 10 exchanges)
MSG_COUNT=$(grep -c '"role"' "$TRANSCRIPT_FILE" 2>/dev/null || echo "0")
if [ "$MSG_COUNT" -lt 10 ]; then
    exit 0
fi

# Read transcript and send to piLoci
TRANSCRIPT=$(cat "$TRANSCRIPT_FILE")

python3 - <<'PYEOF'
import os, sys, json, urllib.request, urllib.error

url = os.environ["PILOCI_URL"].rstrip("/") + "/api/sessions/analyze"
token = os.environ["PILOCI_TOKEN"]
transcript = sys.stdin.read() if not sys.stdin.isatty() else os.environ.get("_TRANSCRIPT", "")

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
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
        extracted = result.get("extracted", 0)
        if extracted > 0:
            print(f"[piloci] extracted {extracted} instinct(s) from session", file=sys.stderr)
except urllib.error.URLError:
    pass  # piLoci not running — silently skip
PYEOF

exit 0
