# piLoci

[![Website](https://img.shields.io/badge/website-piloci.jshsakura.com-blue)](https://piloci.jshsakura.com/) [![English](https://img.shields.io/badge/docs-English-blue)](./README.md)

**팀이 함께 쓰는 자체 호스팅 LLM 메모리 서비스** — Raspberry Pi 5에서 구동.

piLoci는 Python MCP 서버, 웹 대시보드, SQLite 인증, LanceDB 벡터 저장소, Obsidian 스타일 워크스페이스를 결합하여, 팀이 자체 하드웨어에서 프로젝트 단위 메모리를 운영할 수 있게 합니다.

> **현재 상태**: 알파, 패키지 버전 `0.3.29`
>
> 핵심 기능 구현 완료: 로컬 인증, Redis 세션, 프로젝트 스코프 MCP 토큰, 4개 MCP 도구(`memory`, `recall`, `listProjects`, `whoAmI`), 웹 대시보드, 팀 작업공간 UI, Google OAuth, 2FA, 감사 로그, 트랜스크립트 수집 파이프라인, 볼트 워크스페이스 MVP.

## 개요

piLoci (파이로싸이) — **Raspberry Pi** + **Loci법**(고대 기억술, 기억의 궁전)에서 유래 — 는 Raspberry Pi 5에서 구동되는 상시 가동 멀티유저 LLM 메모리 서비스입니다. 모든 데이터를 온디바이스에 보관하고, 여러 프로젝트를 엄격하게 격리하며, MCP 기반 인터페이스로 프로그래밍 방식의 메모리 저장/검색을 제공합니다. 임베디드 벡터 저장소, 경량 API, Obsidian 스타일 워크스페이스를 통해 지식 큐레이션을 쉽게 할 수 있습니다.

**팀을 위해 설계됨**: 여러 사용자가 하나의 piLoci 인스턴스를 공유합니다. 각 사용자는 자신의 계정(2FA 옵션)을 가지며, 프로젝트는 엄격한 메모리 격리를 적용합니다 — 팀원들이 같은 하드웨어에서 함께 작업하면서도 프로젝트 간 컨텍스트가 섞이지 않습니다. 프로젝트 팀을 위한 공유 상시 구동 브레인이라고 생각하세요.

현재 알파 버전(v0.3.x)이며, 핵심 구성요소는 작동하고 신뢰성·보안·UX 강화를 계속 진행 중입니다.

## 영감: llm-wiki

piLoci는 [llm-wiki](https://github.com/Pratiyush/llm-wiki)(Andrés Caparros) 프로젝트에서 디자인 영감을 얻었습니다. llm-wiki는 LLM용 위키 스타일 지식 계층으로, 분류 체계(sources / entities / concepts / syntheses / comparisons / questions), 항목 라이프사이클(draft → reviewed → verified → stale → archived), 듀얼 출력(HTML, Markdown, JSON), Auto Dream 연동 워커를 포함합니다.

구조화된 큐레이터 주도 지식이 모듈형 내보내기와 그래프 관계를 통해 장기 기억을 어떻게 지원하는지 보여줍니다. piLoci는 이 개념을 런타임 서버로 차용하며 다음 차별점을 강조합니다:

- **상시 가동** — 배치 파이프라인이 아닌, 팀이 실시간으로 접속하는 라이브 서비스
- **MCP 네이티브** — LLM 클라이언트가 Model Context Protocol을 통해 상호작용
- **멀티유저 / 프로젝트 격리** — 하나의 인스턴스를 팀이 공유, 프로젝트는 엄격 분리
- **LanceDB 시멘틱 검색** — 외부 프로세스 없이 작동하는 임베디드 벡터 저장소

## 아키텍처 한눈에 보기

```
Internet → Cloudflare Tunnel → piloci:8314 ← redis:6379
                                   └── SQLite + LanceDB (/data volume)
```

| 구성요소 | 역할 |
|---|---|
| **piloci** | Starlette 기반 API 서버 (REST/MCP, 인증, 정적 프론트엔드) |
| **Redis** | 세션 저장, 속도 제한, 임시 카운터 |
| **SQLite** | 사용자, 프로젝트, 토큰, 감사 로그 |
| **LanceDB** | 임베디드 벡터 저장소 — 별도 DB 프로세스 불필요 |
| **워크스페이스** | Obsidian 스타일 볼트: 노트, 태그, 위키링크, 그래프 |
| **프론트엔드** | Next.js(styleseed 기반) 웹 UI |
| **터널** | 외부 접속용 Cloudflare Tunnel (선택) |
| **배포** | 로컬 우선 Docker — 모든 데이터 온디바이스, Pi 5 최적화 |

## Obsidian 연동

piLoci는 이미 Obsidian 친화적 워크스페이스를 제공합니다. YAML frontmatter가 포함된 마크다운 노트를 생성하고, 태그와 위키링크를 보존하며, 노트와 그래프 데이터를 반환하는 워크스페이스 API를 노출합니다. 작은 외부 스크립트로 생성된 노트를 실제 Obsidian 볼트에 기록할 수 있습니다. 완전한 양방향 동기화는 향후 마일스톤에서 계획 중입니다.

### 현재 지원

- 워크스페이스 API에서 노트와 그래프 데이터 반환
- 마크다운 노트를 받아 작은 스크립트로 Obsidian 볼트에 기록
- 메모리가 큐레이션되어 Obsidian 스타일 노트로 노출

### 향후 계획

- piLoci 메모리와 Obsidian 볼트 간 완전한 양방향 동기화
- 충돌 처리 및 원활한 편집 반영
- 전용 Obsidian 플러그인

### 실질적인 연동 방식

현재 가장 현실적인 워크플로우:

1. piLoci 내부에서 메모리를 저장하고 큐레이션 (MCP 도구 또는 웹 UI)
2. `GET /api/projects/slug/{slug}/workspace` 호출
3. 각 `workspace.notes[].markdown`을 해당 `workspace.notes[].path`에 기록
4. 해당 디렉토리를 Obsidian 볼트로 열거나 기존 볼트에 동기화

## 사용 시나리오

### 시나리오 A — 팀 프로젝트 메모리 허브

소규모 팀이 하나의 Pi 5에 piLoci를 설치합니다. 각 팀원이 계정을 만들고 공유 프로젝트에 참여하여 MCP 도구로 메모리를 저장합니다. 모든 팀원이 동일한 지식 베이스의 혜택을 누리면서, 프로젝트 격리로 관련 없는 작업이 섞이지 않습니다.

### 시나리오 B — 멀티 프로젝트 워크스페이스

개발자나 연구자가 하나의 piLoci에서 여러 프로젝트(예: "논문 연구", "사이드 프로젝트", "클라이언트 작업")를 운영합니다. 각 프로젝트의 메모리는 격리되고, 워크스페이스 뷰어에서 프로젝트별 노트와 관계를 확인할 수 있습니다.

### 시나리오 C — Obsidian 내보내기

워크스페이스 노트를 생성하고 간단한 파일 쓰기로 Obsidian 볼트에 내보냅니다 — 팀이 piLoci에서 수집한 지식을 Obsidian에서 큐레이션하고 싶을 때 유용합니다.

```bash
curl -sS http://localhost:8314/api/projects/slug/my-project/workspace
```

## 기술 스택

piLoci는 MCP가 활성화된 Python 기반 API 서버와 가벼운 프론트엔드를 결합합니다. 아이덴티티 데이터는 **SQLite**, 임베딩 벡터 저장은 **LanceDB**, 세션은 **Redis**, 임베딩 연산은 **ONNX 기반** [fastembed](https://github.com/qdrant/fastembed)로 온디바이스에서 빠르게 수행됩니다. 프론트엔드는 **Next.js**(styleseed 기반)로 구성되며, **Docker**를 통해 로컬 우선 배포 모델을 제공합니다.

> **왜 LanceDB인가?** Qdrant의 jemalloc 의존성은 Raspberry Pi 5의 16KB 페이지 크기를 처리하지 못합니다(SIGABRT). LanceDB는 임베디드, mmap 기반, pip 설치만으로 가능 — 외부 프로세스가 필요 없습니다.

## 시작하기

piLoci 설치는 두 갈래로 나뉘고, 둘이 이어집니다.

1. **서버 측** — 이미지 풀 + Docker Compose 배포 ([Docker로 배포](#docker로-배포) 섹션). Raspberry Pi 5에서 로컬 구동, Cloudflare Tunnel로 공개 가능.
2. **클라이언트 측** — Claude Code / OpenCode가 깔린 머신에서 한 줄 페어링 ([AI 클라이언트 연결](#ai-클라이언트-연결) 섹션). 토큰 글자 노출 0.

"연결"이 실제로 하는 일:

- `~/.config/piloci/config.json`에 토큰 + ingest/analyze URL 기록 (양쪽 클라이언트 공유).
- **Claude Code**: `~/.claude.json` 에 MCP 서버 등록 (`memory` / `recall` / `recommend` 도구) **+** `~/.claude/settings.json` 에 자동 캡처 훅 (SessionStart는 과거 transcript 일괄 회수, Stop은 매 턴 라이브 푸시).
- **OpenCode**: `~/.config/opencode/opencode.json` 에 MCP 서버 등록. OpenCode는 훅 메커니즘이 없어 라이브 캡처 N/A — 그래도 LLM이 메모리 도구는 그대로 사용 가능.

단계별 계획과 현재 상태는 [PLAN.md](./PLAN.md)를 참조하세요.

## 빠른 링크

- **[piloci.jshsakura.com](https://piloci.jshsakura.com/)** — 라이브 제품 사이트
- **컨테이너 이미지** — [GHCR: `ghcr.io/jshsakura/oc-piloci`](https://github.com/jshsakura/oc-piloci/pkgs/container/oc-piloci) (권장, pull rate limit 없음) / [Docker Hub: `jshsakura/piloci`](https://hub.docker.com/r/jshsakura/piloci)
- [README.md](./README.md) — English documentation
- [PLAN.md](./PLAN.md) — 아키텍처 및 구현 단계의 단일 소스
- [docs/](./docs/) — 추가 문서
- [SECURITY.md](./SECURITY.md) — 보안 정책
- PyPI 패키지: `oc-piloci`

## 현재 상태

### 구현 완료

- Python 백엔드 + MCP 서버
- SQLite 사용자/프로젝트 데이터
- LanceDB 메모리 저장소
- fastembed 기반 임베딩
- Redis 세션 및 속도 제한
- 세션 쿠키 mutation용 double-submit CSRF 보호
- 저장된 토큰 상태 기반 Bearer token revocation 확인
- 웹 UI (로그인, 대시보드, 프로젝트 상세, 설정, 팀)
- 프로젝트 스코프 메모리 격리
- Google OAuth 및 TOTP 2FA 옵션
- 감사 로그 및 프로덕션 Docker 배포
- 트랜스크립트 수집 엔드포인트 + `piloci-ingest` CLI
- 볼트 워크스페이스 API (메모리 → 마크다운 노트, 태그, 링크, 그래프)
- 브라우저 내 프로젝트 워크스페이스 뷰어
- `/teams` 팀 작업공간 UI (팀 생성, 초대, 멤버, 공유 문서)
- MCP Streamable HTTP 세션도 SSE와 동일한 요약 알림 경로 사용

### 미구현

- 실제 공개 호스트명용 Cloudflare Tunnel 프로덕션 설정
- Obsidian 편집 → piLoci 메모리로의 양방향 동기화

## 핵심 기능

- **프로젝트 스코프 메모리 격리**: 모든 메모리 연산은 사용자와 프로젝트로 스코프되어 다른 프로젝트로 컨텍스트가 누출되지 않습니다.
- **MCP 네이티브 메모리 인터페이스**: `memory`, `recall`, `listProjects`, `whoAmI`를 노출하여 호환 클라이언트가 장기 컨텍스트를 직접 저장/검색할 수 있습니다.
- **트랜스크립트 수집 파이프라인**: `piloci-ingest`가 Claude Code, OpenCode, Codex 스타일 히스토리에서 세션 트랜스크립트를 수집하여 `/api/ingest`로 전송합니다.
- **Obsidian 스타일 워크스페이스 생성**: 저장된 메모리에서 YAML frontmatter, 태그, 위키링크, 그래프 관계가 포함된 마크다운 노트를 생성합니다.
- **워크스페이스 API + 브라우저 UI**: `GET /api/projects/slug/{slug}/workspace`가 노트와 그래프 데이터를 반환하며, 별도 내보내기 없이 웹앱에서 바로 탐색할 수 있습니다.
- **팀 작업공간 UI**: `/teams`에서 팀 생성, 이메일 초대, 멤버 확인, 공유 문서 편집을 한 화면에서 처리합니다.
- **로컬 우선 배포 모델**: SQLite, LanceDB, Redis가 모두 사용자 제어 하에 있으며, 호스팅된 메모리 백엔드가 필요 없습니다.

## 페이즈 로드맵

### v0.1 — 알파 제품 베이스라인

엔드투엔드 제품 골격 구현: 인증, 프로젝트, MCP 도구, REST API, 프론트엔드, 설정, 보안 미들웨어, 감사 로그, 배포 패키징, CI/CD.

### v0.2 — Qdrant 제거 및 LanceDB 도입

완료. Raspberry Pi 5 배포 안정성이 이론적 확장성보다 중요하여 저장소 백엔드를 Qdrant에서 LanceDB로 전환했습니다.

완료:

- 저장소 프로토콜 추출
- LanceDB 어댑터 통합
- Qdrant 코드 및 컨테이너 제거
- LanceDB 통합 테스트
- `LANCEDB_PATH` 및 인덱스 설정을 위한 구성 업데이트
- README 갱신
- ADR-14: LanceDB 백엔드 결정 기록
- ADR-1 Qdrant 용어 → LanceDB 용어 업데이트

### v0.3 — 자동 큐레이션 파이프라인

대부분 구현 중/완료된 단계: "메모리 저장소"에서 "살아있는 프로젝트 지식 베이스"로 전환.

- 자동 캡처 및 회상 흐름 재설계
- 로컬 Gemma를 활용한 백그라운드 큐레이션
- 마크다운/위키 스타일 볼트 출력
- 더 풍부한 Obsidian 호환 지식 뷰

## 보안 메모

- 세션 쿠키가 있는 unsafe 요청은 브라우저에서 읽을 수 있는 `piloci_csrf` 쿠키와 `X-CSRF-Token` 헤더가 일치해야 합니다.
- Bearer 기반 MCP/API 요청은 CSRF를 건너뛰지만, JWT에 `jti`가 있으면 저장된 토큰 상태와 대조해 폐기 여부를 확인합니다.
- 사용자 지정 외부 LLM provider는 기본적으로 private, loopback, link-local, multicast, reserved, 미해결 호스트를 거부합니다. 신뢰된 단일 사용자/로컬 배포에서만 `ALLOW_PRIVATE_LLM_PROVIDER_URLS=true`를 사용하세요.

## Docker로 배포

### 사전 요구사항

- Raspberry Pi 5 또는 arm64/amd64 Linux 호스트
- Docker Engine + Docker Compose v2

### 첫 배포

이미지는 GHCR과 Docker Hub 둘 다 발행됩니다. **GHCR을 권장** — Docker Hub는 6시간당 100/200회 pull rate limit이 있어 신규 설치 도중 막히는 경우가 잦습니다.

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

이미지 레지스트리:
- GHCR (권장): `ghcr.io/jshsakura/oc-piloci:latest`
- Docker Hub (`PILOCI_IMAGE` 미지정 시 기본): `jshsakura/piloci:latest`

### 저장소 클론 기반 배포

소스 트리까지 함께 받아서 운영하려면, 저장소를 클론한 뒤 같은 compose 흐름으로 진행하면 됩니다.

```bash
git clone https://github.com/jshsakura/oc-piloci.git
cd oc-piloci

./deploy/setup.sh
nano .env  # 옵션: PILOCI_IMAGE=ghcr.io/jshsakura/oc-piloci:latest
docker compose pull
docker compose up -d
docker compose logs -f piloci
```

`deploy/setup.sh`는 `.env.example`을 `.env`로 복사한 뒤 `JWT_SECRET`과
`SESSION_SECRET` 값을 자동 생성해 넣습니다.

기본 `.env` 형태는 최대한 단순하게 유지합니다:

```env
JWT_SECRET=32바이트-16진수-값으로-교체
SESSION_SECRET=32바이트-16진수-값으로-교체

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

# 선택 OAuth 공급자
# KAKAO_CLIENT_ID=
# KAKAO_CLIENT_SECRET=
# NAVER_CLIENT_ID=
# NAVER_CLIENT_SECRET=
# GOOGLE_CLIENT_ID=
# GOOGLE_CLIENT_SECRET=
# GITHUB_CLIENT_ID=
# GITHUB_CLIENT_SECRET=
```

`docker-compose.yml`은 앱을 `${PILOCI_BIND_HOST}:${PILOCI_HOST_PORT}`로 publish합니다.
기본값은 `127.0.0.1:8314`이며, 같은 Pi에서 nginx, Caddy, 터널을 함께 돌릴 때 가장 안전합니다.
리버스 프록시 없이 LAN에서 직접 접근하려면 `PILOCI_BIND_HOST=0.0.0.0`으로 바꾸세요.

앱은 첫 시작 시 SQLite와 LanceDB를 자동 초기화하므로 별도의 데이터베이스 부트스트랩 단계가 없습니다.

## AI 클라이언트 연결

서버가 뜬 후, Claude Code 또는 OpenCode를 쓰는 머신마다 한 줄로 페어링합니다. 토큰은 셸 히스토리·브라우저 URL 어디에도 안 남고, 10분짜리 단발 코드만 노출됩니다.

### 권장: device-flow CLI (크로스 플랫폼)

```bash
pip install -U oc-piloci && python -m piloci setup --server https://piloci.example.com
```

CLI가 `ABCD-1234` 코드를 출력하고 브라우저로 `/device` 페이지를 엽니다 — 거기서 로그인 + 승인하면, CLI가 폴링해서 토큰을 받고 감지된 모든 클라이언트를 자동 설정합니다. `piloci login` + `piloci install` 합친 명령.

### 대안: bash 한 줄

웹 UI **설정 → 토큰** 에서 토큰을 발급하고 같이 표시되는 install 명령을 복사:

```bash
curl -sSL https://piloci.example.com/install/<install_code> | bash
```

install code는 10분 단발성. CLI 버전과 기능 동일 — 환경에 맞는 거 선택 (CLI는 Windows에서도 작동, bash는 안 됨).

### 디스크에 떨어지는 것들

```
~/.config/piloci/
├── config.json     # 토큰 + ingest/analyze URL (mode 0600)
├── hook.py         # SessionStart catch-up (Claude 전용)
└── stop-hook.sh    # Stop 라이브 푸시 (Claude 전용)

~/.claude.json              # MCP 서버 엔트리 — Claude 전용
~/.claude/settings.json     # SessionStart + Stop 훅 — Claude 전용
~/.config/opencode/opencode.json  # MCP 서버 엔트리 — OpenCode 전용
```

머지하는 모든 파일은 **기존 엔트리 보존**, 처음 건드릴 때 `*.piloci-bak` 1회 백업.

### 토큰 회전

웹에서 토큰을 폐기/재발급하면 `piloci setup`을 다시 한 번 실행 (또는 `piloci login`만으로 `config.json` 갱신). 훅 스크립트와 MCP 엔트리는 토큰을 `config.json`에서 런타임에 읽기 때문에 재설치 불필요.

### 필수 런타임 구성

- `DATABASE_URL` — 기본값: `/data` 하위 SQLite
- `REDIS_URL` — 기본값: 번들 Redis
- `LANCEDB_PATH` — 기본값: `/data/lancedb`
- `JWT_SECRET` / `SESSION_SECRET` — Docker Compose를 포함한 모든 배포 경로에서 필수

선택 기능:

- `BASE_URL` — OAuth 콜백과 절대 리다이렉트 생성에 사용할 외부 HTTPS 주소
- `SMTP_*` — 이메일 인증 및 비밀번호 재설정
- `KAKAO_CLIENT_ID`, `KAKAO_CLIENT_SECRET` — Kakao OAuth 로그인
- `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` — Naver OAuth 로그인
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` — Google OAuth 로그인
- `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` — GitHub OAuth 로그인
- `WORKERS`, `LOG_LEVEL`, `LOG_FORMAT` — 런타임 튜닝

보존 / 저사양 운영 설정:

- `LOW_SPEC_MODE=true` — Pi 급 하드웨어에 맞게 런타임 기본값 조정
- `RAW_SESSION_RETENTION_DAYS` — 처리 완료된 오래된 원본 트랜스크립트 자동 삭제
- `AUDIT_LOG_RETENTION_DAYS` — 오래된 감사 로그 자동 삭제
- `MAINTENANCE_INTERVAL_SEC` — 백그라운드 정리 주기
- `SQLITE_BUSY_TIMEOUT_MS`, `SQLITE_SYNCHRONOUS` — SQLite 잠금/내구성 튜닝

### 스토리지 가드레일

- SQLite는 `WAL` 모드, `foreign_keys=ON`, 구성된 `busy_timeout`, `synchronous` 제어, `temp_store=MEMORY`로 시작합니다.
- LanceDB는 `LANCEDB_PATH` 하위에 임베디드로 유지됩니다. SQLite 데이터베이스와 같은 유지보수 기간에 함께 백업하세요.
- 백그라운드 유지보수는 보존 기간이 지난 **처리 완료된** 원본 세션만 삭제합니다. 대기 중/미처리 행은 큐레이터 복구가 재큐할 수 있도록 그대로 유지됩니다.
- 권장 백업 단위: SQLite 데이터베이스 파일 + LanceDB 디렉토리 전체.
- 저사양 디바이스에서는 `LOW_SPEC_MODE=true`를 선호하고, 프로파일링으로 여유가 확인되기 전까지 `WORKERS=1`을 유지하세요.

### 기존 배포 업데이트

```bash
docker compose pull
docker compose up -d
```

`docker compose pull`이 `.env`의 `PILOCI_IMAGE` 값을 따릅니다 (GHCR이든 Docker Hub이든). 별도로 `docker pull`을 부를 필요 없습니다.

### 리버스 프록시 뒤에서 OAuth 콜백 설정하기

nginx, Caddy, Cloudflare Tunnel 같은 리버스 프록시 뒤에서 piLoci를 공개한다면,
`.env`에 외부 HTTPS 도메인을 `BASE_URL`로 꼭 고정해야 합니다.

예시:

```env
BASE_URL=https://piloci.opencourse.kr
```

Google OAuth 리디렉션 URI는 한 글자까지 정확히 일치해야 하므로,
Google Cloud Console에는 아래 콜백을 등록해야 합니다.

```text
https://piloci.opencourse.kr/auth/google/callback
```

`BASE_URL`이 없으면 백엔드가 로컬/내부 요청 호스트를 기준으로 콜백 주소를 만들 수 있고,
클라이언트 ID/시크릿이 맞아도 `redirect_uri_mismatch`가 발생할 수 있습니다.

### 리버스 프록시 / 터널

포트 `8314`는 사용 중인 리버스 프록시 또는 터널에서 노출하세요. Cloudflare Tunnel,
Caddy, nginx 같은 엣지 구성은 `docker-compose.yml` 밖에서 관리합니다.
기본 설정에서는 Pi 호스트의 `http://127.0.0.1:8314`를 대상으로 프록시하면 됩니다.

## 개발

### 백엔드 + 로컬 스택

```bash
docker compose -f docker-compose.dev.yml up
```

### Python 설정

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### 트랜스크립트 수집 CLI

```bash
piloci-ingest --client opencode --dry-run
piloci-ingest --client codex --history-file ~/.codex/history.jsonl --project-id <project-id>
```

지원 클라이언트 어댑터:

- `claude-code`
- `opencode`
- `codex`
- `gemini` (플레이스홀더 / 베스트에포트 스텁)

### 웹 빌드

```bash
cd web
pnpm install --frozen-lockfile
pnpm build
```

## 릴리스 프로세스

```bash
# 1. pyproject.toml 버전 업데이트 (+0.0.1 단위, 명시 승인 없이는 major/minor bump 금지)
# 2. 검증
pytest tests/ -v
uv build

# 3. 태그 및 푸시
git tag v0.0.1
git push origin main v0.0.1
```

`.github/workflows/publish.yml`이 버전 태그에서 실행되어: 태그/버전 일치 확인 → 테스트 → 웹앱 빌드 → multi-arch Docker 이미지 게시 → GitHub Release 생성 → PyPI에 `oc-piloci` 게시.

`piloci.__version__`은 패키지 메타데이터/`pyproject.toml`에서 파생됩니다. 별도 하드코딩 버전을 수정하지 마세요.

## 개발 재개

각 구현 세션은 `PLAN.md`에서 시작하고, `## 현재 상태`에서 다음 미완료 항목을 확인하세요.
