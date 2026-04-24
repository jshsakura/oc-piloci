# piLoci

Self-hosted multi-user LLM memory service for Raspberry Pi 5.

piLoci combines a Python MCP server, web dashboard, SQLite auth data, and LanceDB vector storage so you can run project-scoped memory on your own hardware.

> **Current status**: alpha, package version `0.1.0`
>  
> Core product is working: local auth, Redis-backed sessions, project-scoped MCP tokens, 4 MCP tools (`memory`, `recall`, `listProjects`, `whoAmI`), web dashboard, Google OAuth option, 2FA option, audit logs, and vault workspace MVP are implemented.

## Quick Links

- [PLAN.md](./PLAN.md) — source of truth for architecture and implementation phases
- [SECURITY.md](./SECURITY.md) — security policy
- PyPI package: `oc-piloci`

## Status Snapshot

### What is done

- Python backend + MCP server
- SQLite user/project data
- LanceDB memory storage
- fastembed-based embeddings
- Redis sessions and rate limiting
- Web UI for login, dashboard, project detail, settings
- Project-scoped memory isolation
- Google OAuth and TOTP 2FA options
- Audit logs and production Docker deployment

### What is still open

- Cloudflare Tunnel production setup for a real public hostname (`PLAN.md` marks this as manual)
- ADR refresh for the LanceDB transition

## Phase Roadmap

### v0.1 — alpha product baseline

Delivered the end-to-end product skeleton: auth, projects, MCP tools, REST API, frontend, settings, security middleware, audit logs, deployment packaging, and CI/CD.

### v0.2 — Qdrant removal and LanceDB adoption

This is the current documentation phase. The storage backend has already been switched from Qdrant to LanceDB because Raspberry Pi 5 deployment reliability matters more than theoretical scale.

Done in this phase:

- Storage protocol extraction
- LanceDB adapter integration
- Qdrant code and container removal
- LanceDB integration tests
- Config updates for `LANCEDB_PATH` and index settings
- README refresh to match the new architecture

Still pending in this phase:

- ADR-14: LanceDB backend decision record
- ADR-1 update from Qdrant terminology to LanceDB terminology

### v0.3 — automatic curation pipeline

Planned next step: move from “memory storage” toward “living project knowledge base.”

The current plan in `PLAN.md` points toward:

- automatic capture and recall flow redesign
- background curation with local Gemma
- markdown/wiki-style vault outputs
- richer Obsidian-compatible knowledge views

## Architecture

```text
Internet → Cloudflare Tunnel → piloci:8314 ← redis:6379
                                  └── SQLite + LanceDB (/data volume)
```

- **piloci** — Starlette app serving API, auth, MCP, and static frontend
- **redis** — sessions, rate limiting, transient counters
- **SQLite** — users, projects, tokens, audit logs
- **LanceDB** — embedded vector store, no separate DB process required

## Deploy with Docker

### Prerequisites

- Raspberry Pi 5 or any arm64/amd64 Linux host
- Docker Engine + Docker Compose v2

### First deploy

```bash
git clone https://github.com/jshsakura/piloci.git
cd piloci

./deploy/setup.sh
nano .env
docker compose pull
docker compose up -d
docker compose logs -f piloci
```

`deploy/setup.sh` creates the local secret files used by Compose:

- `secrets/jwt_secret`
- `secrets/session_secret`
- optionally `secrets/tunnel_token`

The app auto-initializes SQLite and LanceDB on first startup, so there is no separate database bootstrap step.

### Required runtime configuration

- `DATABASE_URL` — defaults to SQLite under `/data`
- `REDIS_URL` — defaults to bundled Redis
- `LANCEDB_PATH` — defaults to `/data/lancedb`
- `JWT_SECRET` / `SESSION_SECRET` — only for native or local non-Docker runs
- `JWT_SECRET_FILE` / `SESSION_SECRET_FILE` — used by Docker Compose production

Optional features:

- `SMTP_*` — email verification and password reset
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` — Google OAuth login
- `WORKERS`, `LOG_LEVEL`, `LOG_FORMAT` — runtime tuning

Retention / low-spec ops knobs:

- `LOW_SPEC_MODE=true` — clamps runtime defaults for Pi-class hardware
- `RAW_SESSION_RETENTION_DAYS` — deletes old processed raw transcripts automatically
- `AUDIT_LOG_RETENTION_DAYS` — deletes old audit rows automatically
- `MAINTENANCE_INTERVAL_SEC` — background cleanup cadence
- `SQLITE_BUSY_TIMEOUT_MS`, `SQLITE_SYNCHRONOUS` — SQLite lock/durability tuning

### Storage guardrails

- SQLite starts in `WAL` mode with `foreign_keys=ON`, configured `busy_timeout`, `synchronous` control, and `temp_store=MEMORY`.
- LanceDB stays embedded under `LANCEDB_PATH`; back it up together with the SQLite database from the same maintenance window.
- Background maintenance deletes only **processed** raw sessions older than retention. Pending/unprocessed rows stay intact so curator recovery can still requeue them.
- Recommended backup unit: the SQLite database file plus the full LanceDB directory.
- On low-spec devices, prefer `LOW_SPEC_MODE=true` and keep `WORKERS=1` unless profiling proves more headroom.

### Updating an existing deployment

```bash
docker compose pull
docker compose up -d
```

### Without Cloudflare Tunnel

If you do not want Cloudflare Tunnel, remove the `cloudflared` service from `docker-compose.yml` and expose port `8314` through your own reverse proxy.

## Development

### Backend + local stack

```bash
docker compose -f docker-compose.dev.yml up
```

### Idle profiling baseline

When the deployment is still empty, you can still collect a repeatable baseline from the public operational endpoints.

Set env defaults first, then use flags only for one-off overrides:

```bash
export PILOCI_PROFILE_BASELINE_ENDPOINT="http://localhost:8314"
export PILOCI_PROFILE_BASELINE_SAMPLES=5
export PILOCI_PROFILE_BASELINE_TIMEOUT=5
export PILOCI_PROFILE_BASELINE_PATHS="/healthz,/readyz,/profilez"
```

```bash
uv run piloci profile-baseline
```

This collector samples `GET /healthz`, `GET /readyz`, and `GET /profilez` and prints JSON with client-side latency summaries plus the final response payload seen for each path.

Resolution order is env-first and operator-friendly:

- `PILOCI_PROFILE_BASELINE_*` wins for baseline-specific defaults
- shared `PILOCI_ENDPOINT` / `PILOCI_TOKEN` are used as fallback
- explicit CLI flags override both

You can extend it later once authenticated read paths become meaningful:

```bash
export PILOCI_TOKEN="$TOKEN"

uv run piloci profile-baseline \
  --samples 10 \
  --path /healthz \
  --path /readyz \
  --path /profilez
```

For a one-off target, pass flags explicitly:

```bash
uv run piloci profile-baseline --endpoint http://staging:8314 --samples 3
```

Use this as an idle baseline first, then compare later runs after real data and authenticated traffic exist.

### Python setup

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Web build

```bash
cd web
pnpm install --frozen-lockfile
pnpm build
```

## Release Process

piLoci uses a tag-driven release flow.

### Release checklist

1. Bump `pyproject.toml` version.
2. Run local verification.

```bash
uv pip install -e ".[dev]"
pytest tests/ -v
uv build
```

If the web app changed, also run:

```bash
cd web
pnpm install --frozen-lockfile
pnpm build
```

3. Create the release commit.
4. Tag and push the matching version.

```bash
git tag v0.1.0
git push origin main v0.1.0
```

### What the publish workflow does

`.github/workflows/publish.yml` runs on version tags and:

- checks tag/version consistency
- runs Python tests
- builds the static web app
- publishes multi-arch Docker images
- creates a GitHub Release
- publishes `oc-piloci` to PyPI

## Resume Development

Start each implementation session from `PLAN.md`, then check `## 현재 상태` for the next incomplete item.
