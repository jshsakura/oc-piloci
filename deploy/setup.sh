#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# piLoci — First Deploy Setup Script
#
# Creates secrets, .env, and data directories for production
# deployment via docker-compose.
#
# Usage:
#   chmod +x deploy/setup.sh
#   ./deploy/setup.sh
#
# Safe to re-run — skips existing secrets, only creates missing ones.
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

# ── 1. Secrets ────────────────────────────────────────────────
info "Setting up Docker secrets..."

SECRETS_DIR="$PROJECT_ROOT/secrets"
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

generate_secret() {
    local path="$SECRETS_DIR/$1"
    if [ -f "$path" ] && [ -s "$path" ]; then
        warn "Secret $1 already exists — skipping (delete to regenerate)"
        return 0
    fi
    python3 -c "import secrets; print(secrets.token_hex(32))" > "$path"
    chmod 600 "$path"
    ok "Generated $1"
}

generate_secret jwt_secret
generate_secret session_secret

# Cloudflare tunnel token — requires manual input
if [ ! -f "$SECRETS_DIR/tunnel_token" ] || [ ! -s "$SECRETS_DIR/tunnel_token" ]; then
    echo ""
    warn "tunnel_token not set."
    echo -e "  If using Cloudflare Tunnel, paste your token below."
    echo -e "  Press Enter to skip (tunnel won't start)."
    echo -ne "  ${CYAN}Tunnel token:${NC} "
    read -r token
    if [ -n "$token" ]; then
        echo "$token" > "$SECRETS_DIR/tunnel_token"
        chmod 600 "$SECRETS_DIR/tunnel_token"
        ok "Saved tunnel_token"
    else
        warn "Skipped tunnel_token — cloudflared won't start"
    fi
else
    ok "tunnel_token already exists — skipping"
fi

# ── 2. .env file ─────────────────────────────────────────────
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
    sed -i '/^JWT_SECRET=/d' "$ENV_FILE"
    sed -i '/^SESSION_SECRET=/d' "$ENV_FILE"
    ok "Created .env from .env.example (review and customize)"
    warn "Edit .env to configure SMTP, OAuth, etc. as needed"
fi

# ── 3. Data directories (Docker volumes are auto-created,
#       but bind-mount dirs need manual creation) ──────────────
info "Checking data directories..."

# Named volumes in docker-compose.yml are auto-created by Docker.
# If you switch to bind mounts, uncomment and customize:
# mkdir -p "$PROJECT_ROOT/data"

ok "Using Docker named volumes (auto-created by compose)"

# ── 4. Verify requirements ───────────────────────────────────
info "Verifying requirements..."

command -v docker >/dev/null 2>&1 || error "docker not found — install Docker first"
command -v docker compose >/dev/null 2>&1 || error "docker compose not found — install Docker Compose v2"

ok "Docker & Docker Compose found"

# ── 5. Summary ───────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Setup complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  Secrets:  $SECRETS_DIR/"
ls -la "$SECRETS_DIR" | tail -n +2 | while read -r line; do
    echo -e "            $(echo "$line" | awk '{print $NF}') $(echo "$line" | awk '{print $1}')"
done
echo ""
echo -e "  Env file: $ENV_FILE"
echo ""
echo -e "  ${CYAN}Next steps:${NC}"
echo -e "    1. Review and customize .env"
echo -e "    2. docker compose pull"
echo -e "    3. docker compose up -d"
echo -e "    4. Check logs: docker compose logs -f piloci"
echo ""
