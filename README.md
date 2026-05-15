# piLoci

[![Website](https://img.shields.io/badge/website-piloci.jshsakura.com-blue)](https://piloci.jshsakura.com/) [![한국어](https://img.shields.io/badge/문서-한국어-green)](./README.ko.md)

Self-hosted, multi-user LLM memory service for teams — on Raspberry Pi 5.

piLoci combines a Python MCP server, web dashboard, SQLite auth data, LanceDB vector storage, and an Obsidian-style workspace layer so your team can run project-scoped memory on your own hardware.

> **Current status**: alpha, package version `0.3.30`
>
> Core product is working: local auth, Redis-backed sessions, project-scoped MCP tokens, 4 MCP tools (`memory`, `recall`, `listProjects`, `whoAmI`), web dashboard, team workspace UI, Google OAuth option, 2FA option, audit logs, transcript ingest pipeline, cached vault workspace/export flow, low-token recall flow, batched curator embeddings, and thresholded Telegram session alerts are implemented.

## Overview

piLoci (파이로싸이) — from **Raspberry Pi** + **Method of Loci** (the ancient memory palace technique) — is a live, self-hosted multi-user LLM memory service designed to run on Raspberry Pi 5. It stays on-device, supports multiple projects with strict memory isolation, and exposes an MCP-based surface for programmatic memory storage and retrieval. The stack emphasizes a local-first approach with embedded vector storage, a lightweight API, and an Obsidian-style workspace for easy knowledge curation.

**Built for teams**: Multiple users share a single piLoci instance. Each user gets their own account (with optional 2FA), and projects enforce strict memory isolation — so your team works together on the same hardware without leaking context between projects. Think of it as a shared, always-on brain for your project team.

The project is in alpha (v0.3.x). Core components are functional, and ongoing development continues to harden reliability, security, and UX.

## Inspiration: llm-wiki

piLoci draws design inspiration from [llm-wiki](https://github.com/Pratiyush/llm-wiki) (Andrés Caparros). llm-wiki implements a wiki-like knowledge layer for LLMs with a categorized wiki structure (sources / entities / concepts / syntheses / comparisons / questions), a lifecycle for wiki entries (draft → reviewed → verified → stale → archived), dual outputs (HTML, Markdown, and JSON), and an Auto Dream integration worker.

It demonstrates how structured, curator-driven knowledge can support long-term memory with modular exports and graph relationships. piLoci borrows this concept into a runtime server with key differentiators:

- **Always-on** — not a batch pipeline but a live service your team connects to in real time
- **MCP-native** — LLM clients interact through the Model Context Protocol, not CLI scripts
- **Multi-user / project-isolated** — teams share one instance, projects stay strictly separated
- **LanceDB semantic search** — embedded vector store with no external process to manage

## Architecture at a glance

```
Internet → Cloudflare Tunnel → piloci:8314 ← redis:6379
                                   └── SQLite + LanceDB (/data volume)
```

| Component | Role |
|---|---|
| **piloci** | Starlette-based API server handling REST/MCP, auth, and static frontend |
| **Redis** | Session storage, rate limiting, transient counters |
| **SQLite** | Users, projects, tokens, audit logs |
| **LanceDB** | Embedded vector store — no separate DB process required |
| **Workspace** | Obsidian-style vault: notes, tags, wikilinks, and graph data |
| **Frontend** | Next.js (styleseed-based) with a rich web UI |
| **Tunnel** | Optional Cloudflare Tunnel for external access |
| **Deploy** | Local-first Docker — all data stays on-device, tuned for Pi 5 |

## Obsidian integration

piLoci already exposes an Obsidian-friendly workspace today. It can generate markdown notes with YAML frontmatter, preserve tags and wikilinks, and expose a workspace API that returns notes and graph data. A small external script can write generated notes into a real Obsidian vault. Full two-way sync with Obsidian is planned for a future milestone.

### What works now

- Workspace API returns notes and graph data
- Vault JSON is cached on disk and can be exported as an Obsidian-style zip
- Fetch markdown notes and write them into an Obsidian vault via a small script
- Memories are curated and surfaced as Obsidian-like notes

### What is planned

- Full two-way synchronization between piLoci memories and Obsidian vaults
- Conflict handling and seamless edit propagation
- A dedicated Obsidian plugin

### Practical integration pattern

The most realistic near-term workflow:

1. Store and curate memories inside piLoci (via MCP tools or the web UI)
2. Call `GET /api/projects/slug/{slug}/workspace`
3. Write each `workspace.notes[].markdown` into its `workspace.notes[].path`
4. Open that directory as an Obsidian vault — or sync it into an existing one

If you want a ready-made archive instead of scripting the file writes yourself, use:

```bash
curl -OJ http://localhost:8314/api/vault/my-project/export
```

## Usage scenarios

### Scenario A — Team project memory hub

A small team sets up one piLoci on a shared Pi 5. Each member creates an account, joins shared projects, and stores memories via MCP tools. Everyone benefits from the same knowledge base while project isolation keeps unrelated work separate.

### Scenario B — Multi-project workspace

A solo developer or researcher runs several projects (e.g., "thesis research", "side project", "client work") on one piLoci. Each project's memories stay isolated, and the workspace viewer shows notes and relationships per project.

### Scenario C — Obsidian export

Generate workspace notes and export to an Obsidian vault via simple file write — useful for teams who want to curate knowledge in Obsidian after it's been collected in piLoci.

```bash
curl -sS http://localhost:8314/api/projects/slug/my-project/workspace
```

## Tech stack

piLoci combines a Python-based MCP-enabled API server with a lightweight frontend. It uses **SQLite** for identity data, **LanceDB** for embedded vector storage, **Redis** for sessions, and **ONNX-based embeddings** ([fastembed](https://github.com/qdrant/fastembed)) for fast, on-device inference. The frontend is built with **Next.js** (styleseed-driven) for a polished UI, while **Docker** provides a straightforward, local-first deployment model.

> **Why LanceDB?** Qdrant's jemalloc dependency cannot handle Raspberry Pi 5's 16 KB page size (SIGABRT). LanceDB is embedded, mmap-based, and pip-installable — no external process needed.

## Getting started

piLoci has two install paths that hand off to each other:

1. **Server side** — pull the image and deploy via Docker Compose ([Deploy with Docker](#deploy-with-docker)). Runs locally on Raspberry Pi 5; optional public exposure via Cloudflare Tunnel.
2. **Client side** — on the machine where Claude Code / OpenCode lives, pair with a single command ([Connect your AI client](#connect-your-ai-client)). No copy-paste of tokens.

What "connect" actually does:

- Drops `~/.config/piloci/config.json` (token + ingest/analyze URLs) — shared by both clients.
- **Claude Code**: registers the MCP server in `~/.claude.json` (`memory` / `recall` / `recommend` tools) **and** installs auto-capture hooks in `~/.claude/settings.json` (SessionStart catches up on past transcripts, Stop pushes each turn live).
- **OpenCode**: registers the MCP server in `~/.config/opencode/opencode.json`. OpenCode has no hook events, so live capture is not applicable — the LLM still gets the memory tools.

See [PLAN.md](./PLAN.md) for the phased plan and current status.

## Quick Links

- **[piloci.jshsakura.com](https://piloci.jshsakura.com/)** — live product site
- **Container images** — [GHCR: `ghcr.io/jshsakura/oc-piloci`](https://github.com/jshsakura/oc-piloci/pkgs/container/oc-piloci) (recommended, no pull rate limit) / [Docker Hub: `jshsakura/piloci`](https://hub.docker.com/r/jshsakura/piloci)
- [README.ko.md](./README.ko.md) — 한국어 문서
- [PLAN.md](./PLAN.md) — source of truth for architecture and implementation phases
- [docs/](./docs/) — additional documentation
- [SECURITY.md](./SECURITY.md) — security policy
- PyPI package: `oc-piloci`

## Status Snapshot

### What is done

- Python backend + MCP server
- SQLite user/project data
- LanceDB memory storage
- fastembed-based embeddings
- Redis sessions and rate limiting
- Double-submit CSRF protection for cookie-authenticated mutations
- Bearer token revocation checks against persisted token state
- Web UI for login, dashboard, project detail, settings, and teams
- Project-scoped memory isolation
- Google OAuth and TOTP 2FA options
- Audit logs and production Docker deployment
- Transcript ingest endpoint + `piloci-ingest` CLI for client session capture
- Vault workspace API that turns memories into markdown notes, tags, links, and graph data
- In-browser project workspace viewer for generated notes and relationships
- Team workspace UI at `/teams` for team creation, invites, members, and shared documents
- Persistent vault JSON cache plus downloadable Obsidian-style zip export
- Low-token recall flow: preview by default, full fetch by ID, large-result markdown export
- Batched curator embeddings on ingest to reduce repeated executor hops
- Thresholded Telegram session summaries with zero extra LLM cost
- Real 5-minute MCP `listProjects` cache to avoid repeated SQLite hits
- Streamable HTTP MCP sessions now share the same summary notification path as SSE

### What is still open

- Cloudflare Tunnel production setup for a real public hostname (`PLAN.md` marks this as manual)
- Two-way sync from Obsidian edits back into piLoci memories

## Functional Highlights

- **Project-scoped memory isolation**: every memory operation is scoped by user and project so different projects do not leak context into each other.
- **MCP-native memory surface**: piLoci exposes `memory`, `recall`, `listProjects`, and `whoAmI` so compatible clients can save and retrieve long-term context directly.
- **Low-token recall by default**: `recall` now returns previews first, supports `fetch_ids` for selective full loads, and can export large results to markdown files instead of dumping long payloads back into the model context.
- **Cheaper curator ingest path**: extracted memories are now embedded with one `embed_texts(...)` batch per ingest job instead of one embedding call per memory item, while keeping dedup/search/save semantics unchanged.
- **Zero-token session alerts**: MCP session summaries can be pushed to Telegram from backend-only metadata when a session is long enough or memory activity is meaningful.
- **Cheap project discovery**: MCP `listProjects` now uses a real 5-minute per-user cache, with `refresh=true` available when the caller explicitly wants a fresh DB read.
- **Transcript ingest pipeline**: `piloci-ingest` can collect session transcripts from Claude Code, OpenCode, and Codex-style histories and send them to `/api/ingest` for queued processing.
- **Obsidian-style workspace generation**: piLoci can derive markdown notes with YAML frontmatter, tags, wikilinks, and graph relationships from stored memories.
- **Workspace API + browser UI**: `GET /api/projects/slug/{slug}/workspace` returns notes and graph data, and the web app already lets you browse the generated workspace without a separate export step.
- **Team workspace UI**: `/teams` gives team creation, email invites, member visibility, and shared document editing a visible home in the app shell.
- **Cached vault + export path**: generated workspace data now persists under `/data/vaults/{slug}/vault.json`, and `GET /api/vault/{slug}/export` returns an Obsidian-style zip with markdown notes plus the vault JSON snapshot.
- **Local-first deployment model**: SQLite, LanceDB, and Redis stay under your control, with no required hosted memory backend.

## Recent optimization wins

- **Recall no longer dumps full search payloads by default** — preview-first responses keep model context small, and large recall results can be written to markdown under `export_dir`.
- **Dead MCP schema noise removed** — the unused `container_tag` parameter was removed from memory/recall schemas to cut misleading tokens.
- **Meaningful sessions only** — Telegram notifications are gated by duration or memory activity thresholds, so trivial sessions stay silent.
- **Project listing is finally as cheap as documented** — `listProjects` now really is cached for 5 minutes unless the caller opts into refresh.
- **Vault work is no longer rebuilt from scratch every read** — workspace JSON is cached on disk and reusable for both the web UI and Obsidian-style exports.
- **Curator ingest now batches embeddings** — the worker collapses one job's extracted memories into a single embedding batch before per-item duplicate checks and saves.

## Phase Roadmap

### v0.1 — alpha product baseline

Delivered the end-to-end product skeleton: auth, projects, MCP tools, REST API, frontend, settings, security middleware, audit logs, deployment packaging, and CI/CD.

### v0.2 — Qdrant removal and LanceDB adoption

Completed. The storage backend was switched from Qdrant to LanceDB because Raspberry Pi 5 deployment reliability matters more than theoretical scale.

Done in this phase:

- Storage protocol extraction
- LanceDB adapter integration
- Qdrant code and container removal
- LanceDB integration tests
- Config updates for `LANCEDB_PATH` and index settings
- README refresh to match the new architecture
- ADR-14: LanceDB backend decision record
- ADR-1 update from Qdrant terminology to LanceDB terminology

### v0.3 — automatic curation pipeline

In progress and mostly implemented: piLoci is moving from “memory storage” toward a “living project knowledge base.”

The current implementation includes:

- automatic capture and recall flow redesign
- background curation with local Gemma
- markdown/wiki-style vault outputs
- richer Obsidian-compatible knowledge views

## Security Notes

- Cookie-authenticated unsafe requests require a browser-readable `piloci_csrf` cookie and matching `X-CSRF-Token` header.
- Bearer-authenticated MCP/API requests skip CSRF but are checked against persisted token state when the JWT has a `jti`.
- Custom external LLM providers reject private, loopback, link-local, multicast, reserved, and unresolved hosts by default. Set `ALLOW_PRIVATE_LLM_PROVIDER_URLS=true` only for trusted single-user/local deployments.

## Deploy with Docker

### Prerequisites

- Raspberry Pi 5 or any arm64/amd64 Linux host
- Docker Engine + Docker Compose v2

### First deploy

The image is published to both GHCR and Docker Hub. **GHCR is recommended** because Docker Hub's anonymous/free-tier pull rate limit (100/200 per 6h) often blocks fresh installs.

```bash
mkdir -p ~/app/piloci
cd ~/app/piloci

curl -fsSLo docker-compose.yml https://raw.githubusercontent.com/jshsakura/oc-piloci/main/docker-compose.yml
curl -fsSLo .env.example https://raw.githubusercontent.com/jshsakura/oc-piloci/main/.env.example
mkdir -p deploy
curl -fsSLo deploy/setup.sh https://raw.githubusercontent.com/jshsakura/oc-piloci/main/deploy/setup.sh
chmod +x deploy/setup.sh

./deploy/setup.sh
nano .env  # 설정 채우기. GHCR을 쓰려면 다음 한 줄 추가:
           #   PILOCI_IMAGE=ghcr.io/jshsakura/oc-piloci:latest

docker compose pull
docker compose up -d
docker compose logs -f piloci
```

Image registries:
- GHCR (recommended): `ghcr.io/jshsakura/oc-piloci:latest`
- Docker Hub (default if `PILOCI_IMAGE` is unset): `jshsakura/piloci:latest`

### Repo-based deploy

If you want the full source tree locally, clone the repo and use the same compose flow:

```bash
git clone https://github.com/jshsakura/oc-piloci.git
cd oc-piloci

./deploy/setup.sh
nano .env  # 옵션: PILOCI_IMAGE=ghcr.io/jshsakura/oc-piloci:latest
docker compose pull
docker compose up -d
docker compose logs -f piloci
```

`deploy/setup.sh` copies `.env.example` to `.env` and replaces `JWT_SECRET` and
`SESSION_SECRET` with generated values.

The default `.env` shape is intentionally simple:

```env
JWT_SECRET=replace-with-32-byte-hex
SESSION_SECRET=replace-with-32-byte-hex

DATABASE_URL=sqlite+aiosqlite:////data/piloci.db
LANCEDB_PATH=/data/lancedb
REDIS_URL=redis://redis:6379/0

HOST=0.0.0.0
PORT=8314
PILOCI_BIND_HOST=127.0.0.1
PILOCI_HOST_PORT=8314
# BASE_URL=https://piloci.opencourse.kr
LOG_LEVEL=INFO
LOG_FORMAT=json

# Optional OAuth providers
# KAKAO_CLIENT_ID=
# KAKAO_CLIENT_SECRET=
# NAVER_CLIENT_ID=
# NAVER_CLIENT_SECRET=
# GOOGLE_CLIENT_ID=
# GOOGLE_CLIENT_SECRET=
# GITHUB_CLIENT_ID=
# GITHUB_CLIENT_SECRET=
```

`docker-compose.yml` publishes the app to `${PILOCI_BIND_HOST}:${PILOCI_HOST_PORT}`.
The default is `127.0.0.1:8314`, which is ideal when nginx, Caddy, or a tunnel runs on the same Pi.
If you want direct LAN access without a reverse proxy, set `PILOCI_BIND_HOST=0.0.0.0`.

The app auto-initializes SQLite and LanceDB on first startup, so there is no separate database bootstrap step.

## Connect your AI client

After the server is up, every machine that runs Claude Code or OpenCode pairs with one command. The token never appears in your shell history or browser URL bar — only a 10-minute single-use code does.

### Recommended: device-flow CLI (cross-platform)

```bash
pip install -U oc-piloci && python -m piloci setup --server https://piloci.example.com
```

The CLI prints an `ABCD-1234` code, opens your browser to `/device`, polls for approval, and configures every detected client. Equivalent to running `piloci login` followed by `piloci install`.

### Alternative: bash one-liner

Issue an API token from **Settings → Tokens** in the web UI and copy the install command shown:

```bash
curl -sSL https://piloci.example.com/install/<install_code> | bash
```

The install code expires in 10 minutes and is single-use. The bash variant matches the CLI feature-by-feature; pick whichever fits your environment (the CLI works on Windows, bash does not).

### What lands on disk

```
~/.config/piloci/
├── config.json     # token + ingest/analyze URLs (mode 0600)
├── hook.py         # SessionStart catch-up (Claude only)
└── stop-hook.sh    # Stop live push (Claude only)

~/.claude.json              # MCP server entry — Claude only
~/.claude/settings.json     # SessionStart + Stop hooks — Claude only
~/.config/opencode/opencode.json  # MCP server entry — OpenCode only
```

Existing entries in any of those files are preserved; piLoci writes a one-time `*.piloci-bak` next to anything it modifies.

### Token rotation

If you revoke a token from the web UI, just regenerate it and run `piloci setup` again (or `piloci login` to refresh `config.json` only). The hook scripts and MCP entries do not need to be reinstalled — they read the token from `config.json` at runtime.

### Required runtime configuration

- `DATABASE_URL` — defaults to SQLite under `/data`
- `REDIS_URL` — defaults to bundled Redis
- `LANCEDB_PATH` — defaults to `/data/lancedb`
- `JWT_SECRET` / `SESSION_SECRET` — required for every deployment path, including Docker Compose

Optional features:

- `BASE_URL` — public HTTPS origin used for OAuth callbacks and absolute redirects
- `SMTP_*` — email verification and password reset
- `KAKAO_CLIENT_ID`, `KAKAO_CLIENT_SECRET` — Kakao OAuth login
- `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` — Naver OAuth login
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` — Google OAuth login
- `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` — GitHub OAuth login
- `WORKERS`, `LOG_LEVEL`, `LOG_FORMAT` — runtime tuning
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — optional MCP session summary alerts
- `TELEGRAM_MIN_DURATION_SEC`, `TELEGRAM_MIN_MEMORY_OPS`, `TELEGRAM_TIMEOUT_SEC` — alert thresholds and timeout

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

`docker compose pull` honours `PILOCI_IMAGE` from `.env` (GHCR or Docker Hub). No need to call `docker pull` separately.

### OAuth callback URLs behind a reverse proxy

If piLoci is published through nginx, Caddy, Cloudflare Tunnel, or any other reverse proxy,
set `BASE_URL` in `.env` to the exact external HTTPS origin.

Example:

```env
BASE_URL=https://piloci.opencourse.kr
```

Google OAuth redirect URIs must match exactly, so the callback registered in Google Cloud Console
should be:

```text
https://piloci.opencourse.kr/auth/google/callback
```

Without `BASE_URL`, the backend may derive the callback from a local/internal request host,
which can trigger `redirect_uri_mismatch` even when the Google client ID and secret are correct.

### Reverse proxy / tunnel

Expose port `8314` through your own reverse proxy or tunnel. Cloudflare Tunnel,
Caddy, nginx, and similar edge services are managed outside `docker-compose.yml`.
With the default settings they should proxy to `http://127.0.0.1:8314` on the Pi host.

## Connecting MCP clients

piLoci exposes a Streamable HTTP MCP endpoint at `/mcp/http`. The connection format differs by client.

### 1. Issue a token

Open the web UI → Settings → 토큰 tab → issue a new token. Choose **user scope** for cross-project access or **project scope** to lock the token to one project.

### 2. Client-specific configuration

#### Claude Desktop / Claude Code / Cursor

All three use `"type": "http"` in their MCP config files.

**Claude Desktop** — `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

```json
{
  "mcpServers": {
    "piloci": {
      "type": "http",
      "url": "https://piloci.example.com/mcp/http",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}
```

**Claude Code** — `.mcp.json` in project root, or `~/.claude.json` for global scope

```json
{
  "mcpServers": {
    "piloci": {
      "type": "http",
      "url": "https://piloci.example.com/mcp/http",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}
```

**Cursor** — `~/.cursor/mcp.json`

Same format as Claude Code above.

#### OpenCode

OpenCode uses `"type": "remote"` (not `"http"`) for all remote MCP servers.

**`opencode.json`** (project root or `~/.config/opencode/opencode.json`)

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "piloci": {
      "type": "remote",
      "url": "https://piloci.example.com/mcp/http",
      "enabled": true,
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}
```

> **Key difference**: Claude-family clients use `mcpServers` + `type: "http"`. OpenCode uses `mcp` + `type: "remote"`. The endpoint URL (`/mcp/http`) is the same for both.

### 3. Auto-memory with Stop hook (Claude Code)

To have memories saved automatically at the end of each Claude Code session, add the Stop hook from the token setup dialog to `~/.claude/settings.json`. The hook calls `/api/sessions/analyze` when the session ends.

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

### Transcript ingest CLI

piLoci ships with a helper CLI for sending captured client transcripts into the ingest queue:

```bash
piloci-ingest --client opencode --dry-run
piloci-ingest --client codex --history-file ~/.codex/history.jsonl --project-id <project-id>
```

Supported client adapters in the current implementation:

- `claude-code`
- `opencode`
- `codex`
- `gemini` (placeholder / best-effort stub)

Configuration can come from `~/.piloci/config.toml` or environment variables such as:

- `PILOCI_ENDPOINT`
- `PILOCI_TOKEN`
- `PILOCI_PROJECT_ID`

### Web build

```bash
cd web
pnpm install --frozen-lockfile
pnpm build
```

## Release Process

piLoci uses a tag-driven release flow.

### Release checklist

1. Bump `pyproject.toml` version by exactly `+0.0.1` unless a larger release is explicitly approved.
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

3. Create the release commit. `piloci.__version__` is derived from package metadata/`pyproject.toml`; do not edit a second hardcoded version.
4. Tag and push the matching version.

```bash
git tag v0.0.1
git push origin main v0.0.1
```

### What the publish workflow does

`.github/workflows/publish.yml` runs on version tags and:

- checks tag/version consistency
- runs Python tests
- builds the static web app
- publishes multi-arch Docker images to Docker Hub and GHCR
- creates a GitHub Release
- publishes `oc-piloci` to PyPI

## Resume Development

Start each implementation session from `PLAN.md`, then check `## 현재 상태` (Current Status) for the next incomplete item.
