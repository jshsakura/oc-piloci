# piLoci

Self-hosted multi-user LLM memory service for Raspberry Pi 5.
MCP-compatible. Inspired by Method of Loci.

> **Status**: Active development. See [PLAN.md](./PLAN.md) for the full design document.

## Quick Links

- [PLAN.md](./PLAN.md) — Full architecture and implementation plan
- [SECURITY.md](./SECURITY.md) — Security policy
- PyPI: `oc-piloci`

## Deploy with Docker

### Prerequisites

- Raspberry Pi 5 (or any arm64/amd64 Linux host)
- [Docker](https://docs.docker.com/engine/install/) + Docker Compose v2

### First Deploy

```bash
git clone https://github.com/<your-org-or-user>/piloci.git
cd piloci

# Generate secrets, create .env
./deploy/setup.sh

# Review and customize .env (SMTP, OAuth, etc.)
nano .env

# Optional: set the published image name if not using the default placeholder
export PILOCI_IMAGE=ghcr.io/<your-org-or-user>/piloci:latest

# Pull and start
docker compose pull
docker compose up -d

# Check logs
docker compose logs -f piloci
```

The app auto-initializes SQLite + LanceDB on first startup — no manual DB setup needed.

### Update

```bash
docker compose pull
docker compose up -d
```

### Architecture

```
Internet → Cloudflare Tunnel → piloci:8314 ← redis:6379
                                  └── SQLite + LanceDB (/data volume)
```

- **piloci** — Backend + static frontend (single container)
- **redis** — Session cache, rate limiting
- **cloudflared** — Optional; remove if using your own reverse proxy

### Without Cloudflare Tunnel

Remove the `cloudflared` service from `docker-compose.yml` and add a port mapping:

```yaml
piloci:
  ports:
    - "8314:8314"
```

### Development

```bash
# Backend with hot-reload + nginx proxy + Redis
docker compose -f docker-compose.dev.yml up
```

## Release Process

`piLoci`는 `mfa-servicenow-mcp`처럼 **버전 태그 푸시 기반**으로 배포합니다.

### Release checklist

1. `pyproject.toml`의 `version`을 올립니다.
2. 로컬 검증을 실행합니다.

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest tests/ -v
uv build
```

웹 변경이 있으면 추가로 실행합니다.

```bash
cd web
pnpm install --no-frozen-lockfile
pnpm build
```

3. 릴리스 커밋을 만듭니다.
4. 버전 태그를 만들고 푸시합니다.

```bash
git tag v0.1.0
git push origin main v0.1.0
```

### What the publish workflow does

`.github/workflows/publish.yml`는 tag push가 들어오면 자동으로:

- `pyproject.toml` 버전과 태그 일치 여부 확인
- Python 테스트 실행
- Next.js 정적 웹 빌드 생성
- multi-arch Docker 이미지 (`linux/arm64`, `linux/amd64`)를 GHCR에 푸시
- GitHub Release 생성
- PyPI 패키지 `oc-piloci` 배포

즉, **릴리스 트리거는 일반 커밋 푸시가 아니라 버전 태그 푸시**입니다.

## Resume Development

Open this directory in a new Claude Code session and read `PLAN.md` first.
The `## 현재 상태` section tracks what's done and what's next.
