# piLoci

[![Website](https://img.shields.io/badge/website-piloci.jshsakura.com-blue)](https://piloci.jshsakura.com/) [![한국어](https://img.shields.io/badge/문서-한국어-green)](./README.ko.md)

Self-hosted, multi-user LLM memory service for teams — on Raspberry Pi 5.

piLoci combines a Python MCP server, web dashboard, SQLite auth data, LanceDB vector storage, and an Obsidian-style workspace layer so your team can run project-scoped memory on your own hardware.

> **Current status**: alpha, package version `0.1.0`
>
> Core product is working: local auth, Redis-backed sessions, project-scoped MCP tokens, 4 MCP tools (`memory`, `recall`, `listProjects`, `whoAmI`), web dashboard, Google OAuth option, 2FA option, audit logs, transcript ingest pipeline, cached vault workspace/export flow, low-token recall flow, batched curator embeddings, and thresholded Telegram session alerts are implemented.

## Overview

piLoci (파이로싸이) — from **Raspberry Pi** + **Method of Loci** (the ancient memory palace technique) — is a live, self-hosted multi-user LLM memory service designed to run on Raspberry Pi 5. It stays on-device, supports multiple projects with strict memory isolation, and exposes an MCP-based surface for programmatic memory storage and retrieval. The stack emphasizes a local-first approach with embedded vector storage, a lightweight API, and an Obsidian-style workspace for easy knowledge curation.

**Built for teams**: Multiple users share a single piLoci instance. Each user gets their own account (with optional 2FA), and projects enforce strict memory isolation — so your team works together on the same hardware without leaking context between projects. Think of it as a shared, always-on brain for your project team.

The project is in alpha (v0.1.0). While many core components are functional, ongoing development continues to harden reliability, security, and UX.

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

Clone the repo, run the setup, then deploy with Docker Compose as described in the [Deploy with Docker](#deploy-with-docker) section below. It runs locally on Raspberry Pi 5 with optional public exposure via Cloudflare Tunnel. See [PLAN.md](./PLAN.md) for the phased plan and current status.

## Quick Links

- **[piloci.jshsakura.com](https://piloci.jshsakura.com/)** — live product site
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
- Web UI for login, dashboard, project detail, settings
- Project-scoped memory isolation
- Google OAuth and TOTP 2FA options
- Audit logs and production Docker deployment
- Transcript ingest endpoint + `piloci-ingest` CLI for client session capture
- Vault workspace API that turns memories into markdown notes, tags, links, and graph data
- In-browser project workspace viewer for generated notes and relationships
- Persistent vault JSON cache plus downloadable Obsidian-style zip export
- Low-token recall flow: preview by default, full fetch by ID, large-result markdown export
- Batched curator embeddings on ingest to reduce repeated executor hops
- Thresholded Telegram session summaries with zero extra LLM cost
- Real 5-minute MCP `listProjects` cache to avoid repeated SQLite hits

### What is still open

- Cloudflare Tunnel production setup for a real public hostname (`PLAN.md` marks this as manual)
- ADR refresh for the LanceDB transition
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

Start each implementation session from `PLAN.md`, then check `## 현재 상태` (Current Status) for the next incomplete item.
