#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# piLoci — First Deploy Setup Script
#
# Creates `.env` and fills in runtime secrets for production deployment.
#
# Usage:
#   chmod +x deploy/setup.sh
#   ./deploy/setup.sh
#
# Safe to re-run — keeps an existing `.env` untouched.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Colors ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── 1. .env file ─────────────────────────────────────────────
info "Setting up .env..."

ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"

if [ -f "$ENV_FILE" ]; then
    ok ".env already exists — skipping"
else
    if [ ! -f "$ENV_EXAMPLE" ]; then
        error ".env.example not found — cannot create .env"
    fi
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    JWT_SECRET_VALUE="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    SESSION_SECRET_VALUE="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    REDIS_PASSWORD_VALUE="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
    python3 - "$ENV_FILE" "$JWT_SECRET_VALUE" "$SESSION_SECRET_VALUE" "$REDIS_PASSWORD_VALUE" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
jwt_secret = sys.argv[2]
session_secret = sys.argv[3]
redis_password = sys.argv[4]
content = env_path.read_text(encoding="utf-8")
content = content.replace(
    "JWT_SECRET=change-me-generate-with-secrets-token-hex-32",
    f"JWT_SECRET={jwt_secret}",
    1,
)
content = content.replace(
    "SESSION_SECRET=change-me-generate-with-secrets-token-hex-32",
    f"SESSION_SECRET={session_secret}",
    1,
)
content = content.replace(
    "REDIS_PASSWORD=changeme",
    f"REDIS_PASSWORD={redis_password}",
    1,
)
env_path.write_text(content, encoding="utf-8")
PY
    ok "Created .env from .env.example"
    ok "Generated JWT_SECRET, SESSION_SECRET, REDIS_PASSWORD in .env"
    warn "Edit .env to configure SMTP, OAuth, reverse proxy, etc. as needed"
    warn "Default host binding is 127.0.0.1:${PILOCI_HOST_PORT:-8314} for reverse proxy / tunnel use"
fi

# ── 2. Data directories (Docker volumes are auto-created,
#       but bind-mount dirs need manual creation) ──────────────
info "Checking data directories..."

# Named volumes in docker-compose.yml are auto-created by Docker.
# If you switch to bind mounts, uncomment and customize:
# mkdir -p "$PROJECT_ROOT/data"

ok "Using Docker named volumes (auto-created by compose)"

# ── 3. Verify requirements ───────────────────────────────────
info "Verifying requirements..."

command -v docker >/dev/null 2>&1 || error "docker not found — install Docker first"
command -v docker compose >/dev/null 2>&1 || error "docker compose not found — install Docker Compose v2"

ok "Docker & Docker Compose found"

# ── 4. Summary ───────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Setup complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  Env file: $ENV_FILE"
echo -e "  Published app URL: http://127.0.0.1:8314"
echo ""
echo -e "  ${CYAN}Next steps:${NC}"
echo -e "    1. Review and customize .env"
echo -e "    2. docker compose pull"
echo -e "    3. docker compose up -d"
echo -e "    4. Check logs: docker compose logs -f piloci"
echo ""
