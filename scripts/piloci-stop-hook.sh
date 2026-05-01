#!/usr/bin/env bash
# piloci Stop hook — pushes the current session's transcript at end of turn.
# Reads token + URL from ~/.config/piloci/config.json (no secrets in this file).
#
# This script is the canonical Stop hook served by ``/api/hook/stop-script`` and
# laid down at ``~/.config/piloci/stop-hook.sh`` by the install flow. The copy
# kept in this repo exists for visibility — keep it in sync with the
# ``STOP_HOOK_SCRIPT`` constant in ``src/piloci/tools/install_script.py``.
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
PILOCI_TOKEN=$(printf '%s\n' "$CFG_OUT" | sed -n '1p')
PILOCI_URL=$(printf '%s\n' "$CFG_OUT" | sed -n '2p')
[ -n "$PILOCI_TOKEN" ] || exit 0
[ -n "$PILOCI_URL" ] || exit 0

STDIN_DATA=$(cat 2>/dev/null || true)
TRANSCRIPT_FILE=""
if [ -n "$STDIN_DATA" ]; then
    TRANSCRIPT_FILE=$(printf '%s' "$STDIN_DATA" | python3 -c \
        "import sys, json; d=json.load(sys.stdin); print(d.get('transcript_path',''))" \
        2>/dev/null || true)
fi
[ -n "$TRANSCRIPT_FILE" ] || exit 0
[ -f "$TRANSCRIPT_FILE" ] || exit 0

# Skip turns with too little content.
MSG_COUNT=$(grep -c '"role"' "$TRANSCRIPT_FILE" 2>/dev/null || echo "0")
if [ "$MSG_COUNT" -lt 4 ]; then
    exit 0
fi

PILOCI_TOKEN="$PILOCI_TOKEN" PILOCI_URL="$PILOCI_URL" \
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
