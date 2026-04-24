# piLoci Documentation

> **Live site**: [piloci.jshsakura.com](https://piloci.jshsakura.com/)

## Repository docs

| Document | Description |
|---|---|
| [README.md](../README.md) | Project overview, architecture, setup (English) |
| [README.ko.md](../README.ko.md) | 프로젝트 개요, 아키텍처, 설정 (한국어) |
| [PLAN.md](../PLAN.md) | Architecture decisions, phased implementation plan, current status |
| [MEMORY.md](../MEMORY.md) | Development history and session notes |
| [SECURITY.md](../SECURITY.md) | Security policy and vulnerability reporting |
| [WEB_BUILD.md](./WEB_BUILD.md) | Web frontend build and development instructions |

## Key concepts

### MCP Tools

piLoci exposes four MCP tools that LLM clients can call directly:

| Tool | Purpose |
|---|---|
| `memory` | Store new information or project context permanently |
| `recall` | Semantic search for the most relevant past memories |
| `listProjects` | List available projects for the authenticated user |
| `whoAmI` | Return the identity of the current MCP session |

### Workspace API

```
GET /api/projects/slug/{slug}/workspace
```

Returns notes, graph data, and statistics for a project's Obsidian-style workspace:

- `workspace.notes[]` — markdown notes with YAML frontmatter
- `workspace.graph.nodes` / `workspace.graph.edges` — relationship graph
- `workspace.stats` — note, node, edge, and tag counts

### Architecture

```
Internet → Cloudflare Tunnel → piloci:8314 ← redis:6379
                                   └── SQLite + LanceDB (/data volume)
```

- **piloci** — Starlette API server (REST/MCP/auth/static frontend)
- **Redis** — sessions, rate limiting, transient counters
- **SQLite** — users, projects, tokens, audit logs
- **LanceDB** — embedded vector store, no separate process needed

### Why LanceDB?

Qdrant's jemalloc dependency crashes on Raspberry Pi 5 due to 16 KB page size (SIGABRT). LanceDB is embedded, mmap-based, and pip-installable — zero external dependencies.

### Security model

- Passwords: argon2id only (no bcrypt)
- Sessions: JWT + Redis-backed
- Multi-factor: optional Google OAuth and TOTP 2FA
- Isolation: all queries scoped by `(user_id, project_id)`
- Docker: non-root, read-only rootfs, secrets via files
- Audit: all sensitive operations logged

## Deployment

See the [Deploy with Docker](../README.md#deploy-with-docker) section in the main README.

Quick start:

```bash
git clone https://github.com/jshsakura/piloci.git
cd piloci
./deploy/setup.sh
nano .env
docker compose pull
docker compose up -d
```
