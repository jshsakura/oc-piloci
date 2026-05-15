# piLoci — 개발 계획서

> 이 문서는 계획 세션(Opus 4.7)과 구현 세션(Sonnet 4.6) 사이의 인수인계 문서입니다.
> 새 세션을 시작하면 이 문서부터 읽고 `## 현재 상태` 섹션을 확인하세요.

---

## 프로젝트 개요

**이름**: piLoci (파이로싸이)
**어원**: Raspberry Pi + Method of Loci (기억술의 "장소법")
**한 줄 설명**: 라즈베리파이5에서 상시 구동하는 셀프호스티드 멀티유저 LLM 메모리 서비스 (MCP 호환, 프로젝트 격리 지원)

**목표**: SuperMemory 같은 유료 LLM 메모리 서비스를 본인 라즈베리파이에서 운영. Docker 기반 상시 구동, 외부 공개 URL로 접속, 이메일/비밀번호 로컬 인증 우선 + OAuth(Google) 옵션. 유저는 여러 프로젝트를 만들어 메모리를 완전 격리 운영 가능. **보안을 최우선**으로 설계.

---

## 현재 상태

- [x] 프로젝트 폴더 생성
- [x] PLAN.md 작성
- [x] pyproject.toml 스캐폴드
- [x] 디렉토리 구조 생성 (Python 백엔드 + Next.js 프론트)
- [x] Dockerfile + docker-compose.yml (piloci + Redis + cloudflared, LanceDB 내장)
- [x] Python 의존성 설치 (uv)
- [x] MCP 서버 스켈레톤
- [x] LanceDB 연동
- [x] fastembed 연동
- [x] **로컬 인증 (email + argon2 비밀번호)**
- [x] 세션 관리 (Redis)
- [x] 프로젝트 스코프 토큰 발급
- [x] MCP 툴 7종 구현 (프로젝트 격리 적용)
- [x] 보안 미들웨어 (Rate limit, CSRF, Security Headers)
- [x] REST API 완성 (프론트 연동용)
- [x] Next.js 프론트 스캐폴드 (styleseed 기반)
- [x] 랜딩/로그인/회원가입 페이지
- [x] 대시보드 (프로젝트 목록)
- [x] 프로젝트 상세 (메모리 관리)
- [x] 팀 작업공간 UI (`/teams`: 팀 생성, 초대, 멤버, 공유 문서)
- [x] 설정 페이지 (토큰/2FA/비밀번호)
- [x] Google OAuth (선택 로그인 옵션으로)
- [x] 2FA (TOTP) 옵션
- [x] 프로젝트 상세 vault workspace MVP (Obsidian형 markdown + graph 관계 브라우저 뷰)
- [x] Cloudflare Tunnel 설정 (`piloci.example.com` — 사용자/운영자 직접 설정, 저장소 구현 범위 밖)
- [x] 보안 감사 로그
- [x] PyPI 배포 (oc-piloci)
- [x] GitHub Actions CI/CD (버전 태그 v* 시에만 Docker 빌드+배포)

### v0.2 완료

- [x] Storage Protocol 추출 (`src/piloci/storage/base.py`)
- [x] LanceDB 어댑터 (`src/piloci/storage/lancedb_store.py`)
- [x] Qdrant 코드/테스트/의존성 통째 제거 (`storage/qdrant.py`, `tests/test_storage_qdrant.py`, `qdrant-client` from pyproject)
- [x] `run.py` Qdrant 오케스트레이션 제거, `docker-compose.yml`에서 qdrant 서비스 삭제
- [x] LanceDB 통합 테스트 (`tests/test_storage_lancedb.py`) — 21개 통과
- [x] config: `lancedb_path`, `lancedb_index_type`, `lancedb_index_threshold` 추가
- [x] README 갱신
- [x] ADR-14 신규 (`docs/ADR-014-lancedb-backend.md`)
- [x] ADR-1 갱신 (`docs/ADR-001-storage-isolation.md`)

> 상세는 아래 **`v0.2: Qdrant 제거 + LanceDB 도입`** 섹션 참조.
> ⚠️ 운영 데이터 없음 → "마이그레이션"이 아니라 "백엔드 교체". 데이터 이전 스크립트 불필요.

### v0.2.x 백엔드 개선 예정

- [x] 백엔드 런타임 프로파일링 기준선 수집 (API p50/p95, embed latency, LanceDB query latency, RSS 메모리)
- [x] 임베딩 전용 executor/동시성 상한 도입 (`run_in_executor` 남용 방지, 저사양 CPU 보호)
- [x] ingest queue backpressure 추가 (bounded queue + 429/재시도 정책)
- [x] curator worker 저사양 모드 추가 (동시성/배치/주기 설정 분리)
- [x] readiness/health 세분화 (Redis 포함, degraded 원인 명시)
- [x] SQLite/LanceDB 운영 가드레일 문서화 (WAL, 디스크 여유, 백업, compaction/cleanup)
- [x] 저사양 기본값 재조정 (worker 수, cache 크기, queue 크기)

---

## 메타 정보

| 항목 | 값 |
|---|---|
| 경로 | `/home/pi/app/jupyterLab/notebooks/piloci` |
| PyPI 패키지명 | `oc-piloci` |
| Python import명 | `piloci` |
| GitHub 레포 | `piloci` (owner: `<your-org-or-user>`) |
| Python 버전 | 3.11+ |
| 라이선스 | MIT |
| 저자 | piLoci contributors |

---

## 참고 프로젝트

- **mfa-servicenow-mcp** (`/home/pi/app/jupyterLab/notebooks/mfa-servicenow-mcp`)
  - 가져올 것: Docker 멀티스테이지 빌드, CLAUDE.md 툴 최적화 규칙, Schema compaction, pre-commit 설정, CI/CD 워크플로우, SSE 서버 패턴
  - 버릴 것: 구조 자체는 모놀리식 도메인 툴 모음이라 메모리 MCP에는 과함

- **MemPalace** (https://github.com/MemPalace/mempalace)
  - 참고할 것: 29개 MCP 툴 아이디어, LongMemEval 벤치마크 방법론, Wing/Room/Drawer 계층 개념
  - 차별점: ChromaDB → Qdrant, 단일 유저 → 멀티 유저, 로컬 → 공개 URL

- **styleseed** (`/home/pi/app/jupyterLab/notebooks/styleseed`) — **프론트엔드 베이스**
  - 활용: Next.js + styleseed engine + 선택 skin으로 웹 UI 구축
  - 69개 디자인 규칙 + 48개 컴포넌트 + 7개 브랜드 스킨 (toss/linear/notion 등)
  - `data-skin` 속성 하나로 테마 전환 가능
  - AI로 개발해도 프로급 UI 품질 확보 — piLoci 전체 개발 속도와 품질에 결정적

- **llm-wiki** (https://github.com/Pratiyush/llm-wiki) — **v0.3 큐레이션/위키 레이어 레퍼런스**
  - 카파시 LLM Wiki 패턴을 정적 사이트 제너레이터로 구현한 오픈소스
  - 차용: 위키 분류체계(`sources/entities/concepts/syntheses/comparisons/questions`), 라이프사이클 상태(draft→reviewed→verified→stale→archived), 듀얼 출력 포맷(HTML + .md + .json), `llms.txt`, JSON-LD 그래프, Obsidian 볼트 통합 패턴, "Auto Dream" 통합 워커
  - 차별점: piloci는 정적 사이트가 아니라 **상시 서버 + 라이브 큐레이션**, MCP로 능동 호출, 멀티유저+프로젝트 격리, LanceDB 의미 검색 추가
  - 가져올 것: 위키 폴더 구조, 린트 규칙(11개 중 구조 규칙 8개 우선), MEMORY.md 자동 통합 패턴

---

## 아키텍처

```
                         인터넷
                            │
                ┌───────────┴────────────┐
                │   Cloudflare Tunnel    │
│ (piloci.example.com)     │
                └───────────┬────────────┘
                            │ HTTPS
                ┌───────────┴────────────┐
                │     라즈베리파이 5      │
                │                        │
                │  ┌──────────────────┐  │
                │  │  piLoci Server   │  │
                │  │  (uvicorn 8314)  │  │
                │  │                  │  │
                │  │ ┌──────────────┐ │  │
                │  │ │ Static Files │ │  │ ← /, /login, /dashboard
                │  │ │ (Next.js SSG)│ │  │   (styleseed 기반)
                │  │ └──────────────┘ │  │
                │  │ ┌──────────────┐ │  │
                │  │ │ REST API     │ │  │ ← /api/*
                │  │ │ (Starlette)  │ │  │   (프론트가 호출)
                │  │ └──────────────┘ │  │
                │  │ ┌──────────────┐ │  │
                │  │ │ Auth Routes  │ │  │ ← /auth/*
                │  │ └──────────────┘ │  │
                │  │ ┌──────────────┐ │  │
                │  │ │ MCP Endpoint │ │  │ ← /mcp/http, /mcp
                │  │ │ (SSE + JWT)  │ │  │
                │  │ └──────────────┘ │  │
                │  └─┬────────────┬───┘  │
                │    │            │      │
                │ ┌──┴────┐  ┌────┴────┐ │
                │ │SQLite │  │ LanceDB │ │ ← NVMe
                │ │users  │  │ vectors │ │
                │ └───────┘  └─────────┘ │
                │                        │
                │  ┌──────────────────┐  │
                │  │ fastembed (ONNX) │  │ ← ARM NEON SIMD
                │  └──────────────────┘  │
                └────────────────────────┘
                            │
                ┌───────────┼───────────┐
             유저 A      유저 B      유저 C
           (JWT 토큰) (JWT 토큰) (JWT 토큰)
```

---

## 기술 스택

### 백엔드

| 레이어 | 선택 | 이유 |
|---|---|---|
| 언어 | Python 3.11+ | servicenow-mcp와 일관성, asyncio 성숙 |
| 웹 프레임워크 | Starlette | MCP SSE 공식 패턴, 가볍고 빠름 |
| ASGI 서버 | uvicorn | 사실상 표준 |
| MCP SDK | `mcp[cli]>=1.8.0` | 공식 SDK |
| 벡터 DB | LanceDB | 임베디드, mmap 기반, Pi 5 배포 단순, 별도 프로세스 불필요 |
| 임베딩 | fastembed | ONNX 양자화, 서버리스, ARM NEON |
| 임베딩 모델 | BAAI/bge-small-en-v1.5 | 25MB, 384차원, Pi 5에서 빠름 |
| 유저 DB | SQLite + SQLAlchemy | 가볍고 NVMe에서 충분히 빠름 |
| 비밀번호 해싱 | argon2-cffi | bcrypt보다 현대적, OWASP 권장 |
| OAuth (옵션) | authlib | 멀티 provider 지원 용이 |
| JWT | python-jose[cryptography] | 표준 |
| 세션/캐시 저장소 | **Redis** (Docker 컨테이너) | 인메모리 <1ms, TTL 네이티브, Rate limit에 최적 |
| 2FA | pyotp | TOTP 표준 (Google Authenticator 호환) |
| Rate limit | slowapi + Redis backend | 원자적 카운터, 정확한 슬라이딩 윈도우 |
| CSRF | Double-submit cookie middleware | 세션 쿠키 요청 방어, Bearer API는 제외 |
| 의존성 관리 | uv | servicenow-mcp와 동일 |

### 프론트엔드 (styleseed 기반)

| 레이어 | 선택 | 이유 |
|---|---|---|
| 프레임워크 | Next.js 15+ (App Router) | styleseed 호환, 정적 export 지원 |
| 언어 | TypeScript | 타입 안전성 |
| 디자인 시스템 | **styleseed engine** (로컬 참조) | 69개 규칙 + 48개 컴포넌트 |
| 기본 스킨 | **linear** (개발자 친화적, 다크모드 기본) | 변경 가능 옵션 제공 |
| 스타일링 | Tailwind CSS + styleseed tokens | styleseed 기본 스택 |
| 상태 관리 | Zustand | 가볍고 간단 |
| 데이터 fetching | TanStack Query | 캐싱/리페칭 |
| 폼 | React Hook Form + zod | 검증 강력 |
| 빌드 모드 | `output: 'export'` (정적) | Python 백엔드가 서빙 |
| 패키지 매니저 | pnpm | 빠르고 디스크 효율 |

**styleseed 참조 방식:**
- **엔진 파일 복사** (심볼릭 링크 아님) — `web/engine/`, `web/skins/linear/`에 실제 파일 배치
- 이유: Docker 빌드 컨텍스트 안에 있어야 하고, styleseed 버전 고정이 재현성에 좋음
- 업데이트 절차: styleseed 릴리즈 시 `scripts/sync-styleseed.sh`로 복사 갱신
- 향후 styleseed가 npm 배포되면 `package.json` 의존성으로 전환

### 인프라 (Docker 우선)

| 항목 | 선택 |
|---|---|
| 기본 배포 | **Docker Compose** (piloci + redis + cloudflared) |
| 컨테이너 러너 | Docker (Pi OS 64bit) |
| 공개 URL | Cloudflare Tunnel (cloudflared 컨테이너) |
| HTTPS | Cloudflare이 종단 처리 (내부는 http) |
| 프로세스 관리 | Docker restart policy (`unless-stopped`) |
| 백업 | LanceDB 디렉토리 스냅샷 + SQLite dump 스케줄러 |
| 모니터링 | Docker logs + 구조화 로그 (JSON) |
| 대안 | systemd 네이티브 실행 옵션도 제공 (문서만) |

---

## Pi 5 성능 최적화 전략

### 1. 임베딩 레이어
- **fastembed + ONNX 양자화 모델** — PyTorch 대비 3-5배 빠름, ARM NEON SIMD 자동 활용
- **임베딩 캐시** — 같은 텍스트 재임베딩 방지 (LRU cache, 1000개)
- **배치 처리** — 다중 문서 저장 시 배치 임베딩

### 2. 벡터 DB 레이어
- **LanceDB mmap 기반 읽기** — NVMe와 궁합 최상, 별도 서버 프로세스 없이 RAM 사용량 절감
- **인덱스 임계치 기반 생성** — 작은 데이터셋은 brute force, 커지면 IVF_PQ로 전환
- **스칼라 인덱싱** — `user_id`, `project_id`, `tags` 인덱스로 격리 필터와 태그 필터 가속
- **결과 후처리 최소화** — top_k/score threshold 기본값을 보수적으로 유지해 Pi 5 CPU 점유 억제

### 3. 서버 레이어
- **uvicorn 멀티워커** — 기본은 1~2 workers, Pi 5에서도 메모리/캐시 중복 비용을 먼저 본 뒤 확장
- **asyncio 전면화** — 블로킹 호출 금지, 임베딩도 `run_in_executor`
- **orjson** — 표준 json 대비 3배 빠름 (servicenow-mcp에서도 사용)

### 4. 스토리지 레이어
- **LanceDB 데이터 디렉토리를 NVMe에 배치** — `~/app/piloci/lancedb` 또는 `/data/lancedb`
- **SQLite WAL 모드** — 동시 읽기/쓰기 성능 개선
- **주기적 정리/백업** — LanceDB 테이블 재작성(compaction)과 SQLite dump를 운영 루틴으로 관리

### 5. MCP 프로토콜 최적화 (servicenow-mcp에서 가져올 것)
- **Schema compaction** — 툴 설명 120자 제한, 파라미터 80자 제한
- **anyOf 평탄화** — nullable union 단순화
- **title 필드 제거** — description과 중복

---

## 데이터 스키마

### SQLite (유저 관리)

```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,              -- UUID v7
    email TEXT UNIQUE NOT NULL,
    email_verified BOOLEAN DEFAULT 0,
    name TEXT,
    password_hash TEXT,               -- argon2, 로컬 인증 유저만 NOT NULL
    oauth_provider TEXT,              -- 'google' 등, OAuth 유저만 (NULLABLE)
    oauth_sub TEXT,                   -- provider의 고유 ID
    totp_secret TEXT,                 -- 2FA 활성화 유저만
    totp_enabled BOOLEAN DEFAULT 0,
    failed_login_count INTEGER DEFAULT 0,
    locked_until TIMESTAMP,           -- 계정 잠금 (brute-force 방어)
    created_at TIMESTAMP NOT NULL,
    last_login_at TIMESTAMP,
    last_login_ip TEXT,
    is_active BOOLEAN DEFAULT 1,
    is_admin BOOLEAN DEFAULT 0,
    quota_bytes INTEGER DEFAULT 1073741824,  -- 기본 1GB
    UNIQUE(oauth_provider, oauth_sub)
);

-- 세션은 Redis에 저장 (SQLite 아님):
--   session:{session_id} → {user_id, created_at, ip, user_agent, ...}  TTL=14d
--   user_sessions:{user_id} → SET of session_ids  (동시 세션 추적)
--
-- Rate limit도 Redis:
--   ratelimit:login:{ip} → INCR + EXPIRE
--   ratelimit:signup:{ip}, ratelimit:mcp:{token_jti}
--
-- 로그인 실패 카운터도 Redis:
--   login_fail:{email} → INCR, 5회 도달 시 locked_until 설정

CREATE TABLE password_reset_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT 0,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,             -- 'login', 'login_failed', 'token_created', etc.
    ip_address TEXT,
    user_agent TEXT,
    metadata TEXT,                    -- JSON
    created_at TIMESTAMP NOT NULL
);

CREATE INDEX idx_audit_user ON audit_logs(user_id);
CREATE INDEX idx_audit_action ON audit_logs(action);
CREATE INDEX idx_audit_created ON audit_logs(created_at);

CREATE TABLE projects (
    id TEXT PRIMARY KEY,              -- UUID v7
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,               -- URL-friendly name: "webapp-dev"
    name TEXT NOT NULL,               -- 표시명: "Webapp Dev"
    description TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    memory_count INTEGER DEFAULT 0,   -- 캐시 (주기적 동기화)
    bytes_used INTEGER DEFAULT 0,     -- 캐시
    UNIQUE(user_id, slug)
);

CREATE INDEX idx_projects_user ON projects(user_id);

CREATE TABLE api_tokens (
    token_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,  -- NULL = 전체 접근
    name TEXT NOT NULL,               -- "Claude Code 노트북 / webapp"
    token_hash TEXT NOT NULL,         -- bcrypt
    scope TEXT NOT NULL DEFAULT 'project',  -- 'project' | 'user'
    created_at TIMESTAMP NOT NULL,
    last_used_at TIMESTAMP,
    expires_at TIMESTAMP,
    revoked BOOLEAN DEFAULT 0
);

CREATE INDEX idx_api_tokens_user ON api_tokens(user_id) WHERE revoked = 0;
CREATE INDEX idx_api_tokens_project ON api_tokens(project_id) WHERE revoked = 0;
```

### LanceDB (벡터 스토어)

**테이블 전략**: 단일 memories 테이블 + `(user_id, project_id)` SQL WHERE 필터링
**이유**: 별도 벡터 DB 프로세스 없이 Pi 5에서 안정적으로 운영 가능. 테이블 분리보다 단일 테이블 + 필수 스코프 필터가 단순하고 백업도 쉽다.

```python
table_name = "memories"
vector_size = 384  # bge-small-en-v1.5

# Row schema
{
    "memory_id": "uuid",
    "user_id": "uuid",        # 필수 스코프
    "project_id": "uuid",     # 필수 스코프
    "vector": [0.1, 0.2, ...],  # 384 floats
    "content": "원문 텍스트",
    "metadata": {...},
    "tags": ["tag1", "tag2"],
    "created_at": 1234567890,
    "updated_at": 1234567890,
}

# 모든 쿼리에 자동 적용되는 필수 필터
where = "user_id = '{user_id}' AND project_id = '{project_id}'"
```

### JWT 페이로드

```json
{
  "sub": "user-uuid",
  "email": "user@example.com",
  "project_id": "project-uuid",   // 프로젝트 토큰인 경우, user 토큰은 null
  "project_slug": "webapp-dev",   // 편의용
  "scope": "project",              // "project" | "user"
  "iat": 1234567890,
  "exp": 1234567890,
  "jti": "token-id"
}
```

**토큰 스코프 동작:**
- `scope=project`: 해당 project_id에만 read/write. 다른 프로젝트 접근 시도는 403
- `scope=user`: 유저의 모든 프로젝트 접근 가능. 툴 호출 시 `project` 파라미터 필수

---

## MCP 툴 스펙

표준 메모리 MCP 인터페이스 (서비스나우 MCP의 CLAUDE.md 규칙 적용: description 120자, 파라미터 80자).

**프로젝트 스코프 동작:**
- project 토큰 사용 시: `project` 파라미터 생략 가능, 토큰의 project_id로 자동 바인딩
- user 토큰 사용 시: 모든 툴에 `project` 파라미터 필수 (slug or id)

| 툴 | 설명 | 파라미터 |
|---|---|---|
| `save_memory` | 텍스트를 벡터화해서 저장. tags로 카테고리 분류 | `content`, `tags?`, `metadata?`, `project?` |
| `search_memory` | 시맨틱 검색. 쿼리와 유사한 메모리 top_k개 반환 | `query`, `top_k?=5`, `tags?`, `min_score?`, `project?` |
| `get_memory` | ID로 단건 조회. search_memory로 ID 먼저 찾기 | `memory_id`, `project?` |
| `list_memories` | 메모리 목록. 태그/날짜 필터 지원 | `tags?`, `limit?=20`, `offset?=0`, `project?` |
| `update_memory` | 기존 메모리 수정. 내용/태그/메타데이터 변경 | `memory_id`, `content?`, `tags?`, `metadata?`, `project?` |
| `delete_memory` | 메모리 영구 삭제. 복구 불가 | `memory_id`, `project?` |
| `clear_memories` | 프로젝트의 모든 메모리 삭제. 확인 필수 | `confirm: true`, `project?` |

**프로젝트 관리 툴 (user 토큰 전용):**

| 툴 | 설명 | 파라미터 |
|---|---|---|
| `list_projects` | 내 프로젝트 목록 조회 | 없음 |
| `create_project` | 새 프로젝트 생성. slug로 식별 | `slug`, `name`, `description?` |
| `delete_project` | 프로젝트 삭제. 모든 메모리 영구 삭제 | `project`, `confirm: true` |

**향후 추가 고려:**
- `export_memories` — JSON 덤프
- `import_memories` — 다른 프로젝트/백업 복원
- `get_stats` — 메모리 개수, 용량, 태그 분포 (프로젝트별/전체)
- `move_memory` — 프로젝트 간 이동

---

## REST API 스펙

### Public

| Method | Path | 설명 |
|---|---|---|
| GET | `/` | 랜딩 페이지 |
| GET | `/login` | 로그인 페이지 |
| POST | `/auth/login` | 로컬 로그인 (email + password) |
| GET | `/signup` | 회원가입 페이지 |
| POST | `/auth/signup` | 로컬 회원가입 |
| GET | `/auth/verify-email` | 이메일 인증 토큰 확인 |
| GET | `/auth/forgot` | 비밀번호 재설정 요청 페이지 |
| POST | `/auth/forgot` | 재설정 이메일 발송 |
| GET | `/auth/reset` | 재설정 페이지 (토큰 검증) |
| POST | `/auth/reset` | 새 비밀번호 설정 |
| GET | `/auth/google` | Google OAuth 시작 (옵션) |
| GET | `/auth/google/callback` | OAuth 콜백 |
| POST | `/auth/logout` | 로그아웃 |
| GET | `/healthz` | 헬스체크 (liveness) |
| GET | `/readyz` | 준비 상태 (DB/Redis/LanceDB/worker 상태 확인) |

### Authenticated (세션 쿠키 + CSRF 토큰)

| Method | Path | 설명 |
|---|---|---|
| GET | `/dashboard` | 대시보드 (프로젝트 목록) |
| GET | `/projects/{slug}` | 프로젝트 상세 (메모리 목록) |
| GET | `/settings` | 계정 설정 |
| POST | `/api/account/password` | 비밀번호 변경 (기존 비번 확인) |
| POST | `/api/account/2fa/enable` | 2FA 활성화 (QR 코드 반환) |
| POST | `/api/account/2fa/confirm` | OTP 확인 후 활성화 |
| POST | `/api/account/2fa/disable` | 2FA 비활성화 (비번 + OTP 필요) |
| GET | `/api/projects` | 프로젝트 목록 |
| POST | `/api/projects` | 프로젝트 생성 |
| PATCH | `/api/projects/{id}` | 프로젝트 수정 |
| DELETE | `/api/projects/{id}` | 프로젝트 삭제 (confirm 필요) |
| POST | `/api/tokens` | API 토큰 발급 (project_id, scope 지정) |
| DELETE | `/api/tokens/{id}` | 토큰 폐기 |
| GET | `/api/tokens` | 내 토큰 목록 |
| GET | `/api/audit` | 내 감사 로그 조회 |
| GET | `/api/sessions` | 활성 세션 목록 |
| DELETE | `/api/sessions/{id}` | 세션 강제 로그아웃 |

### MCP (Bearer JWT)

| Method | Path | 설명 |
|---|---|---|
| ANY | `/mcp/http` | MCP Streamable HTTP 연결 |
| GET | `/mcp` | MCP SSE 호환 연결 |

---

## 보안 모델 (최우선 설계)

### 위협 모델

공개 인터넷에 노출되는 서비스로서 아래 위협을 가정:
1. **무차별 대입 공격** (Brute-force) — 로그인 엔드포인트
2. **자격 증명 탈취** — 비밀번호 DB 유출, 토큰 탈취
3. **세션 하이재킹** — XSS, CSRF, 쿠키 탈취
4. **권한 상승** — 다른 유저/프로젝트 데이터 접근
5. **DoS** — Rate limit 우회, 대용량 업로드
6. **자동화된 남용** — Bot 회원가입, 스팸
7. **공급망 공격** — 의존성 취약점

### 기본 인증 (로컬, M2 구현)

```
1. 회원가입: 이메일 + 비밀번호
   - 비밀번호 정책: 최소 12자, 대소문자/숫자/특수 조합
   - 이메일 형식 검증 + DNS MX 확인 (옵션)
   - 이메일 인증 토큰 발송 (SMTP 설정 시)
   - argon2로 해싱 저장 (parallelism=1, memory=64MB, time=3)
2. 로그인: 이메일 + 비밀번호
   - 실패 5회 → 15분 계정 잠금
   - IP당 Rate limit: 10회/분
   - 성공 시 세션 ID 발급 (32바이트 random)
   - 세션 쿠키: HttpOnly, Secure, SameSite=Lax, Path=/
3. 2FA (옵션): TOTP
   - 활성화 시 로그인 후 OTP 입력 필요
   - 백업 코드 10개 발급 (해싱 저장)
4. 비밀번호 재설정: 이메일로 일회용 토큰 (1시간 유효)
```

### OAuth 인증 (옵션, M4 구현)

```
1. /auth/google 클릭 → Google 로그인
2. 콜백에서 이메일 기준 users 테이블 upsert
3. 기존 로컬 유저면 계정 연결 (이메일 일치 시)
4. 세션 발급 (로컬과 동일)
```

### API 토큰 발급 (MCP 연결용)

```
1. 로그인 + 대시보드 진입
2. 프로젝트 선택 → "API 토큰 생성"
3. 토큰 이름 입력 (예: "노트북 Claude Code")
4. JWT 발급 (project_id, scope 포함)
   - 만료: 기본 90일 (1일~365일 선택)
   - 서명: HS256 (서버 전용 비밀키)
5. api_tokens 테이블에 해시(sha256)만 저장
6. 토큰을 페이지에 1회 표시 (복사 후 새로고침 시 사라짐)
7. 사용자는 .mcp.json에 Bearer로 저장
8. 매 요청마다 서버가 JWT 검증 → token_hash DB 조회 → revoked 확인
```

### 방어 계층

**네트워크 레이어:**
- Cloudflare Tunnel로만 외부 노출 (포트포워딩 금지)
- Cloudflare DDoS 보호 자동 적용
- 내부 Docker 네트워크는 격리

**애플리케이션 레이어:**
- **Rate limiting** (slowapi):
  - `/auth/login`: 10/min per IP
  - `/auth/signup`: 3/min per IP
  - `/auth/*/password-reset`: 3/hour per IP
  - device auth: 20/min
  - ingest: 30/min
  - chat: 30/min
  - mutation/admin/team endpoints: 경로별 제한
- **CSRF 보호**: 세션 쿠키가 있는 모든 unsafe 요청에 double-submit CSRF 토큰 필수
- **Content Security Policy**: API/health 응답에 `default-src 'self'; script-src 'self'` 적용
- **보안 헤더**:
  ```
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: geolocation=(), microphone=(), camera=()
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  ```
- **입력 검증**: Pydantic 스키마로 모든 요청 본문 검증
- **SQL 인젝션**: SQLAlchemy ORM 전용, raw SQL 금지
- **XSS**: Jinja2 autoescape=true, 사용자 입력 HTML 렌더링 금지

**인증/세션 레이어:**
- 비밀번호: argon2id (OWASP 2024 권장 파라미터)
- 세션: 32바이트 random ID, **Redis 저장** (쿠키에 ID만)
- 세션 만료: Redis TTL 14일, 활성화 시 TTL 갱신
- 동시 세션: 유저당 최대 10개 (Redis SET으로 추적, 초과 시 LRU 제거)
- JWT 시크릿: 최소 256비트 random, `.env`로 주입, 로테이션 가능
- 로그인 실패 카운터: Redis (`login_fail:{email}`, TTL 15분)
- 로그인 실패 로그: audit_logs 기록 (영구)

**데이터 격리:**
- 모든 메모리 쿼리에 `(user_id, project_id)` 필터 **자동 적용** (미들웨어 레벨)
- 서비스 레이어에서 필터 누락 불가능하게 강제 (타입 시스템 활용)
- 프로젝트 toekn은 자기 project만 접근 가능, 다른 project 명시 시 403

**시크릿 관리:**
- `.env` 파일은 `.gitignore`
- Docker secrets 또는 환경 변수로 주입
- 시크릿: `JWT_SECRET`, `SESSION_SECRET`, `OAUTH_CLIENT_SECRET`, `SMTP_PASSWORD`
- 컨테이너 내부에서만 읽을 수 있게 권한 설정 (600)

**감사/관찰성:**
- audit_logs 테이블에 핵심 이벤트 기록:
  - 로그인 성공/실패, 비밀번호 변경, 2FA 활성화, 토큰 발급/폐기, 프로젝트 삭제
  - 각 로그에 IP, User-Agent 포함
- 구조화 로그 (JSON) → stdout → Docker logs → 외부 수집 가능
- 실패 로그인 급증 감지 → 이메일 알림 (옵션)

**컨테이너 보안:**
- Non-root 유저로 실행 (UID 1000)
- Read-only rootfs (`/tmp`, `/data`만 쓰기 가능)
- Capabilities 최소화 (CAP_NET_BIND_SERVICE만)
- 이미지는 `python:3.11-slim-bookworm` 기반 (CVE 적음)
- 정기 `docker scan` / Trivy 스캔
- Dependabot + pip-audit CI 통합

**백업 & 복구:**
- LanceDB 디렉토리 스냅샷: 일 1회 자동 (cron)
- SQLite dump: 시간당 1회 WAL 체크포인트 + 일 1회 전체 덤프
- 백업 위치: 로컬 + (선택) S3/rclone 오프사이트
- 복구 스크립트 포함 (`scripts/restore.sh`)

### 프로젝트별 Claude Code 설정 예

```jsonc
// 프로젝트 A: ~/projects/webapp/.mcp.json
{
  "mcpServers": {
    "piloci": {
      "type": "http",
        "url": "https://piloci.example.com/mcp/http",
      "headers": {
        "Authorization": "Bearer eyJ...webapp-token..."
      }
    }
  }
}

// 프로젝트 B: ~/projects/research/.mcp.json
{
  "mcpServers": {
    "piloci": {
      "type": "http",
        "url": "https://piloci.example.com/mcp/http",
      "headers": {
        "Authorization": "Bearer eyJ...research-token..."
      }
    }
  }
}
```
각 디렉토리에서 작업할 때 **자동으로 해당 프로젝트 메모리만 접근**.

### 방어 계층

- **CSRF**: 세션 쿠키는 SameSite=Lax + double-submit CSRF, OAuth state 파라미터
- **Rate limiting**: slowapi로 경로별 제한, Redis URL 설정 시 Redis backend 사용
- **Quota**: 유저별 총 바이트 수 제한 (기본 1GB)
- **Token rotation**: JWT 만료 90일, 수동 폐기 가능
- **비밀키 관리**: `.env` 파일, 절대 커밋 금지

---

## 배포 전략 (Docker 우선)

### 개발 환경

```bash
cd /home/pi/app/jupyterLab/notebooks/piloci
cp .env.example .env
# .env 편집: JWT_SECRET, SESSION_SECRET 등 생성
docker compose -f docker-compose.dev.yml up --build
# piloci는 코드 변경 시 자동 리로드 (볼륨 마운트)
```

### 프로덕션 (기본: Docker Compose)

```yaml
# docker-compose.yml
services:
  piloci:
    image: ghcr.io/<your-org-or-user>/piloci:latest
    restart: unless-stopped
    read_only: true
    user: "1000:1000"
    cap_drop: [ALL]
    cap_add: [NET_BIND_SERVICE]
    security_opt: [no-new-privileges:true]
    tmpfs:
      - /tmp
    environment:
      - QDRANT_URL=http://qdrant:6333
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=sqlite:////data/piloci.db
      - JWT_SECRET=${JWT_SECRET}
      - SESSION_SECRET=${SESSION_SECRET}
      - LOG_LEVEL=INFO
      - LOG_FORMAT=json
    volumes:
      - piloci_data:/data
    depends_on:
      qdrant: { condition: service_healthy }
      redis: { condition: service_healthy }
    networks: [piloci_internal]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8314/readyz"]
      interval: 30s
      timeout: 10s
      retries: 3

  qdrant:
    image: qdrant/qdrant:latest
    restart: unless-stopped
    volumes:
      - /mnt/nvme/qdrant:/qdrant/storage
    networks: [piloci_internal]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/readyz"]

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: >
      redis-server
      --save 60 1
      --appendonly yes
      --maxmemory 256mb
      --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    networks: [piloci_internal]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

volumes:
  piloci_data:
  redis_data:

networks:
  piloci_internal:
    driver: bridge
```

### 핵심 보안 포인트

- **외부로 포트 노출 안 함** — 모든 트래픽은 Cloudflare Tunnel 경유
- **read_only rootfs + tmpfs** — 컨테이너 침투 시 수정 불가
- **non-root user** — UID 1000
- **capabilities drop ALL** — 필수만 추가
- **no-new-privileges** — privilege escalation 차단
- **런타임 시크릿은 `.env`로 주입** — 저장소 커밋 금지, 배포 시 교체 필수
- **내부 네트워크 격리** — piloci ↔ qdrant는 내부망에서만

### Cloudflare Tunnel 설정

```bash
# 초기 1회
cloudflared tunnel login
cloudflared tunnel create piloci
cloudflared tunnel route dns piloci piloci.example.com

# 이후는 운영 환경(systemd, 별도 컨테이너, 호스트 서비스 등)에서 터널을 따로 실행
```

### 대안: 네이티브 systemd (문서만 제공)

Docker를 쓰고 싶지 않은 유저를 위해 `docs/DEPLOYMENT_NATIVE.md`에 systemd 유닛 예시 제공. 공식 지원은 Docker.

---

## 디렉토리 구조

```
piloci/
├── PLAN.md                      ← 이 문서
├── CLAUDE.md                    ← 개발 규칙 (servicenow-mcp에서 이식)
├── SECURITY.md                  ← 보안 정책, 취약점 신고
├── README.md                    ← 프로젝트 소개
├── README.ko.md                 ← 한글 README
├── LICENSE                      ← MIT
├── pyproject.toml               ← Python 백엔드
├── .gitignore
├── .dockerignore
├── .env.example
├── .pre-commit-config.yaml
├── Dockerfile                   ← Python 백엔드 (웹 빌드 결과물 포함)
├── Dockerfile.web               ← Next.js 빌드 스테이지 (멀티 스테이지)
├── docker-compose.yml           ← 프로덕션
├── docker-compose.dev.yml       ← 개발 (볼륨 마운트, 자동 리로드)
├── .github/
│   └── workflows/
│       ├── ci.yml               ← 테스트 + lint + 보안 스캔
│       ├── publish.yml          ← PyPI 자동 배포
│       └── docker.yml           ← GHCR 이미지 빌드
├── deploy/
│   ├── systemd/                 ← 네이티브 실행 옵션 (문서용)
│   │   ├── piloci.service
│   │   └── cloudflared.service
│   └── cloudflared-config.yml
├── scripts/
│   ├── init-db.py               ← DB 마이그레이션
│   ├── create-admin.py          ← 초기 관리자 생성
│   ├── backup.sh                ← 백업 스크립트
│   ├── restore.sh               ← 복구 스크립트
│   └── sync-styleseed.sh        ← styleseed engine/skin 갱신 복사
├── src/
│   └── piloci/
│       ├── __init__.py
│       ├── version.py
│       ├── cli.py
│       ├── main.py              ← 앱 진입점 (Starlette + uvicorn)
│       ├── config.py            ← Pydantic Settings
│       ├── mcp/
│       │   ├── __init__.py
│       │   ├── server.py        ← MCP 코어
│       │   ├── sse.py           ← SSE 트랜스포트
│       │   └── tools.py         ← MCP 툴 등록
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── local.py         ← 로컬 인증 (이메일/비밀번호)
│       │   ├── oauth.py         ← Google OAuth (옵션)
│       │   ├── totp.py          ← 2FA TOTP
│       │   ├── password.py      ← argon2 해싱
│       │   ├── jwt_utils.py
│       │   ├── session.py       ← 세션 관리
│       │   └── middleware.py    ← Bearer + 세션 미들웨어
│       ├── db/
│       │   ├── __init__.py
│       │   ├── models.py        ← SQLAlchemy 모델
│       │   ├── session.py
│       │   └── migrations/      ← Alembic
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── lancedb_store.py ← LanceDB 래퍼 + 자동 필터 강제
│       │   ├── embed.py         ← fastembed 래퍼
│       │   └── cache.py         ← 임베딩 LRU 캐시
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── memory_tools.py  ← 7개 MCP 툴
│       │   ├── project_tools.py ← 프로젝트 관리 툴
│       │   └── _schema.py       ← Schema compaction
│       ├── api/
│       │   ├── __init__.py
│       │   ├── routes.py        ← REST API 라우트 (/api/*)
│       │   ├── static.py        ← Next.js 빌드 결과물 서빙
│       │   ├── security.py      ← CSRF, 보안 헤더, CSP
│       │   ├── ratelimit.py     ← slowapi 설정
│       │   └── audit.py         ← 감사 로그 헬퍼
│       └── utils/
│           ├── __init__.py
│           ├── schema_compact.py ← servicenow-mcp에서 이식
│           └── logging.py        ← 구조화 로그
├── web/                         ← Next.js 프론트엔드 (styleseed 기반)
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── next.config.ts           ← output: 'export' 정적 빌드
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── postcss.config.mjs
│   ├── engine/                  ← styleseed 엔진 (파일 복사 스냅샷)
│   ├── skins/
│   │   └── linear/              ← 선택한 스킨 (파일 복사 스냅샷)
│   ├── app/                     ← Next.js App Router
│   │   ├── layout.tsx           ← data-skin 속성 적용
│   │   ├── page.tsx             ← 랜딩
│   │   ├── login/page.tsx
│   │   ├── signup/page.tsx
│   │   ├── dashboard/page.tsx
│   │   ├── projects/[slug]/page.tsx
│   │   └── settings/page.tsx
│   ├── components/              ← piLoci 전용 컴포넌트
│   │   ├── MemoryCard.tsx
│   │   ├── ProjectList.tsx
│   │   ├── TokenManager.tsx
│   │   └── SearchBar.tsx
│   ├── lib/
│   │   ├── api.ts               ← API 클라이언트
│   │   ├── auth.ts              ← 세션 관리
│   │   └── types.ts             ← 공유 타입
│   └── public/
│       └── piloci-logo.svg
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_auth_local.py
│   ├── test_auth_oauth.py
│   ├── test_tools_memory.py
│   ├── test_tools_project.py
│   ├── test_storage.py
│   ├── test_security.py         ← 보안 테스트 (CSRF, Rate limit, 격리)
│   └── test_e2e.py              ← 전체 플로우
└── docs/
    ├── CLIENT_SETUP.md          ← Claude Code 연결 가이드
    ├── DEPLOYMENT.md            ← Docker 배포 (기본)
    ├── DEPLOYMENT_NATIVE.md     ← systemd 대안
    ├── SECURITY.md              ← 보안 모범 사례
    ├── API.md                   ← REST API 스펙
    └── THREAT_MODEL.md          ← 위협 모델 문서
```

---

## 마일스톤

### M1: Docker 기반 MCP 서버 (단일 유저, stdio/http)
- pyproject.toml + 기본 구조
- Dockerfile + docker-compose.dev.yml (piloci + Redis)
- LanceDB + fastembed 연동
- 7개 MCP 툴 구현 (유저/프로젝트 격리 없이)
- stdio + HTTP 두 방식 동작
- 로컬 Claude Code에서 연결 테스트

### M2: 로컬 인증 + 프로젝트 (API만)
- SQLite 스키마 (users, projects, sessions, api_tokens, audit_logs)
- argon2 비밀번호 해싱
- REST API: 회원가입/로그인/로그아웃 (이메일 + 비밀번호)
- 세션 쿠키 (HttpOnly, Secure, SameSite)
- CSRF 보호
- Rate limiting
- 보안 헤더 미들웨어
- 프로젝트 CRUD API
- 프로젝트 스코프 JWT 발급 API
- (user_id, project_id) payload 필터링 자동 강제
- OpenAPI 스펙 자동 생성 (프론트 타입 생성용)

### M2.5: Next.js 프론트엔드 (styleseed 기반)
- Next.js 15 + App Router 초기화
- styleseed engine + linear skin 복사/연결
- 랜딩 페이지
- 로그인/회원가입
- 대시보드 (프로젝트 목록)
- 프로젝트 상세 (메모리 목록 + 검색)
- 팀 작업공간 (`/teams`: 생성/초대/문서 협업)
- 설정 (토큰 관리)
- API 클라이언트 (타입 안전, 자동 재시도)
- `next build && next export` → Python에서 서빙

### M3: 프로덕션 Docker + Cloudflare Tunnel
- docker-compose.yml (read-only, non-root, secrets)
- Cloudflare Tunnel 컨테이너 통합
- 실제 공개 URL로 외부 접속 검증
- 백업 스크립트
- 헬스체크 + 모니터링

### M4: 고급 보안 & OAuth
- 2FA (TOTP)
- 이메일 인증 (SMTP)
- 비밀번호 재설정
- Google OAuth 추가 (선택 로그인 옵션)
- 계정 잠금 (brute-force 방어)
- 감사 로그 UI

### M5: 성능 최적화 & 관찰성
- 임베딩 캐시 튜닝
- LanceDB compaction/index tuning
- 구조화 로그 → JSON
- 프로메테우스 메트릭 (옵션)
- 부하 테스트 (locust)

### M6: 배포
- GitHub 레포 공개
- PyPI 배포 (`oc-piloci`)
- GHCR 도커 이미지 배포
- 보안 감사 (의존성 스캔, Trivy)
- 문서 정리
- 데모 인스턴스 (선택)

### M7 (후속): 프론트 고도화
- 다크/라이트 테마 토글 (styleseed `data-skin`)
- 스킨 선택 옵션 (toss/notion/raycast 등)
- 메모리 그래프 시각화
- 태그 관리 UI
- 사용량 차트
- 관리자 대시보드
- 실시간 업데이트 (SSE로 메모리 변경 push)

---

## v0.2: Qdrant 제거 + LanceDB 도입

> 결정일: 2026-04-23 (Opus 4.7 계획 세션)
> 구현 세션 (Sonnet 4.6) 인수인계용 상세 계획
> **운영 데이터 없음** → "마이그레이션" 아님. Qdrant 코드 통째 삭제 + LanceDB 신규 도입.

### 배경 및 결정

**문제**:
- Qdrant 공식 도커 이미지가 Pi 5에서 부팅 불가 — 번들된 jemalloc이 Pi 5의 16KB 메모리 페이지를 인식 못해 SIGABRT (확인됨: `<jemalloc>: Unsupported system page size` → `Aborted (core dumped)`)
- Qdrant 네이티브 빌드는 538개 crate, ~1시간, 6GB+ RAM 피크 → 일반 사용자한테 강요 불가
- "누구든 쉽게 설치해서 쓰는" 프로젝트 비전과 정면 충돌

**결정**: SQLite (기존 aiosqlite 유지) + **LanceDB** (벡터 신규)
- 둘 다 임베디드 라이브러리 → 별도 프로세스 0, IPC 0
- 베이스라인 RAM ~80~150MB (Postgres+pgvector 대비 1/5)
- LanceDB는 IVF_PQ + mmap 기반, Pi 5 페이지 사이즈 이슈 없음, aarch64 사전빌드 wheel 제공
- `pip install lancedb` 한 줄로 완료

**기각된 대안**:
| 옵션 | 기각 사유 |
|---|---|
| sqlite-vec (vec 확장으로 통합) | 운영 SQLite 파일과 벡터 데이터를 한 파일에 두면 손상 시 블라스트 반경 동시 폭발. 사용자가 SQLite 손상 경험 있어 거부 |
| Postgres + pgvector | 단일 사용자 MCP 시나리오에 RAM 300~700MB 베이스라인은 과함. Pi 5에서 gemma + 컨테이너들과 메모리 경합 |
| Qdrant 네이티브 유지 | 빌드 1시간 + 6GB RAM 요구는 "쉬운 설치" 목표 불충족 |
| Qdrant 도커 + jemalloc 우회 빌드 | 커스텀 이미지 유지보수 부담 |

### 작업 순서 (Sonnet 인수인계)

**Phase 1: Storage Protocol 추출 (미래 확장 여지용)**
- 신규 `src/piloci/storage/base.py` — `MemoryStore` Protocol/ABC
- 메서드 시그니처는 현재 `src/piloci/storage/qdrant.py`의 클래스에서 추출 (참고 후 qdrant.py 자체는 Phase 6에서 삭제):
  - `async ensure_collection() -> None`
  - `async save(memory: MemoryRecord) -> str`
  - `async get(memory_id, user_id, project_id) -> Optional[MemoryRecord]`
  - `async update(memory_id, user_id, project_id, **fields) -> None`
  - `async delete(memory_id, user_id, project_id) -> None`
  - `async clear_project(user_id, project_id) -> int`
  - `async search(query_vector, user_id, project_id, tags=None, limit=10, score_threshold=None) -> list[SearchResult]`
  - `async list(user_id, project_id, tags=None, limit=100, offset=0) -> list[MemoryRecord]`
  - `async close() -> None`
- `MemoryRecord`, `SearchResult` 데이터클래스를 base.py로 이동
- **단일 백엔드 시작**이지만 Protocol을 두는 이유: 추후 chroma/pgvector 등 추가 요청 시 쉽게 확장 (구현은 그때 PR 단위로)

**Phase 2: LanceDB 어댑터**
- 신규 `src/piloci/storage/lancedb.py` — `LanceDBMemoryStore(MemoryStore)`
- 비동기 클라이언트: `lancedb.connect_async(path)`
- pyarrow 스키마:
  ```python
  pa.schema([
      pa.field("memory_id", pa.string(), nullable=False),
      pa.field("user_id", pa.string(), nullable=False),
      pa.field("project_id", pa.string(), nullable=False),
      pa.field("content", pa.string()),
      pa.field("tags", pa.list_(pa.string())),
      pa.field("metadata", pa.string()),  # JSON 직렬화
      pa.field("created_at", pa.int64()),
      pa.field("updated_at", pa.int64()),
      pa.field("vector", pa.list_(pa.float32(), 384)),
  ])
  ```
- 인덱스:
  - 벡터: 데이터 <10k면 brute force, 이상이면 IVF_PQ (config로 결정)
  - 스칼라: `user_id`, `project_id`, `tags` 위에 BTREE
- 메서드 매핑:

| 작업 | Qdrant API | LanceDB 등가 |
|---|---|---|
| upsert | `client.upsert(points=[Point(id, vector, payload)])` | `table.merge_insert("memory_id").when_matched_update_all().when_not_matched_insert_all().execute([dict])` |
| search | `client.search(vector, query_filter, limit, score_threshold)` | `table.search(vector).where("user_id = ? AND project_id = ?").limit(N).to_list()` + 후처리로 score 필터 |
| scroll | `client.scroll(filter, limit, offset)` | `table.search().where(...).limit(N).offset(M).to_list()` |
| set_payload | `client.set_payload(payload, points=[id])` | `table.update(where=f"memory_id = '{id}'", values={...})` |
| delete | `client.delete(points_selector=Filter(must=[...]))` | `table.delete(where="user_id = ? AND project_id = ?")` |
| 인덱스 생성 | `client.create_payload_index(field, type)` | `table.create_scalar_index(field, index_type="BTREE")` |
| 컬렉션 보장 | `recreate_collection(...)` | `db.create_table(name, schema=..., exist_ok=True)` |

**Phase 3: Config 갱신**
- `src/piloci/config.py` 변경:
  - **제거**: `qdrant_url`, `qdrant_api_key`, `qdrant_collection`, qdrant HNSW 튜닝/quantization 플래그 등 Qdrant 관련 필드 전부
  - **추가**:
    - `lancedb_path: Path = Path("~/app/piloci/lancedb").expanduser()`
    - `lancedb_index_type: Literal["NONE", "IVF_PQ"] = "IVF_PQ"`
    - `lancedb_index_threshold: int = 10_000` (데이터 N 이상이면 인덱스 자동 빌드)
- `src/piloci/main.py`: 기존 직접 `MemoryStore` (qdrant) import 제거, `LanceDBMemoryStore`로 직접 교체 (백엔드 토글 불필요)
- `src/piloci/mcp/server.py` line 12 동일 처리

**Phase 4: 의존성**
- `pyproject.toml` 변경:
  - **제거**: `qdrant-client>=1.9.0`
  - **추가**: `lancedb>=0.x`, `pyarrow>=14`
- optional extras 불필요 (단일 백엔드)

**Phase 5: 테스트**
- **삭제**: `tests/test_storage_qdrant.py` (백엔드 자체가 사라지니 회귀 대상 없음)
- 신규 `tests/test_storage_lancedb.py`: 실제 LanceDB로 통합 테스트 (임시 디렉토리 fixture — 임베디드라 서비스 불필요)
- 신규 `tests/test_storage_protocol.py` (선택): Protocol 계약 단독 검증 (LanceDB 하나만으로도 가능, 추후 백엔드 추가 시 매트릭스 확장)
- `tests/conftest.py`: 기존 qdrant fixture 제거, `lancedb_store` fixture 추가 (`tmp_path` 활용)

**Phase 6: 코드/인프라 통째 청소**
- **삭제**:
  - `src/piloci/storage/qdrant.py`
  - `tests/test_storage_qdrant.py`
  - `run.py` line 24-70, 86, 117의 Qdrant 바이너리 오케스트레이션 (LanceDB는 외부 프로세스 없음)
- **수정**:
  - `docker-compose.yml`에서 qdrant 서비스 블록 제거
  - `docker-compose.dev.yml`의 native qdrant 안내 주석 제거
  - `Dockerfile`/`Dockerfile.web` 검토 — qdrant 관련 단계 있으면 제거
  - `src/piloci/api/routes.py` line 662-667 헬스체크: qdrant probe → lancedb 디렉토리/테이블 존재 확인으로 변경
- 검색해서 잡아낼 잔재: `git grep -i qdrant` — 주석/문서/import 모든 흔적 제거

**Phase 7: 문서**
- `README.md` 갱신:
  - 기본 설치: `pip install oc-piloci` 만으로 LanceDB 포함 → 외부 인프라 의존성 0
  - 데이터 위치: `~/app/piloci/lancedb/` 명시
  - 기존 Qdrant 안내 섹션이 있으면 모두 삭제
- 신규 ADR:
  - **ADR-14: LanceDB 단일 백엔드 + Protocol 추상화** — Qdrant 제거 사유(Pi 5 jemalloc 16KB 페이지, 설치 무게), LanceDB 채택 사유(임베디드, mmap, 사전빌드 wheel), Protocol을 두는 이유(미래 확장 여지)
- ADR-1 갱신: "Qdrant 단일 컬렉션 + payload 필터" → "LanceDB 단일 테이블 + SQL WHERE 필터". 개념·격리 모델 동일.

### 호환성 차이 (구현 시 주의)

1. **필터 표현법**: Qdrant `Filter(must=[FieldCondition(key="user_id", match=MatchValue(...))])` → LanceDB SQL WHERE. **반드시 파라미터 바인딩**으로 SQL injection 방지 (`table.search().where("user_id = $uid", parameters={"uid": user_id})`)
2. **태그 IN 필터**: Qdrant `MatchAny(any=tags)` → LanceDB `array_has_any(tags, ['a', 'b'])` 또는 `... AND list_contains(tags, $tag)` 다중 OR
3. **score_threshold**: Qdrant 직접 지원, LanceDB는 결과 후처리에서 `_distance` 필드 기준 필터
4. **트랜잭션**: LanceDB는 단일 op 원자성만, 다중 op 트랜잭션 X. 현재 코드는 단일 op만 쓰므로 문제 없음
5. **임베딩 차원 변경**: 둘 다 스키마 고정. 384 외 사용 시 새 테이블 필요 (현재 v0.x는 단일 차원으로 고정)
6. **CLAUDE.md의 보안 규칙** "모든 Qdrant 쿼리에 (user_id, project_id) 필터 필수" → **LanceDB에도 동일하게 적용**. Protocol 레벨 enforcement 권장 (예: `_must_filter()` 헬퍼 in base.py)

### Verification 체크리스트

- [ ] `pip install -e .` 시 lancedb 포함, qdrant-client 없음 (`pip list | grep -i qdrant` → 빈 결과)
- [ ] `git grep -i qdrant` → 코드/문서/주석 잔재 0
- [ ] `pytest` 전체 통과 (qdrant 테스트는 삭제됨)
- [ ] `pytest tests/test_storage_lancedb.py` 통과
- [ ] 모든 7개 MCP 툴 end-to-end smoke test (lancedb 백엔드)
- [ ] `/health` 엔드포인트가 LanceDB 디렉토리/테이블 상태 반환
- [x] `docker compose up` Qdrant 컨테이너 없이 백엔드 정상 부팅
- [ ] `~/app/piloci/lancedb/` 디렉토리 자동 생성 + 초기 테이블 생성 확인
- [ ] (user_id, project_id) 필터 누락 케이스 테스트 — 데이터 유출 없음
- [x] PyPI 0.2.0 dry-run 빌드 성공 (`uv build`)

## v0.2.x: 백엔드 속도·안정성·저사양 최적화

> 목표: **Pi 5뿐 아니라 더 낮은 사양에서도 "느려도 안 죽고, 천천히라도 계속 도는" 백엔드**로 정리.
> 초점은 새 기능 추가보다 **latency 상한, 메모리 상한, 장애 복구성, 운영 예측 가능성**이다.

### 왜 지금 이 단계가 필요한가

- 현재 백엔드는 이미 임베디드 스택(SQLite + LanceDB + Redis)이라 방향은 맞다.
- 하지만 실제 코드 기준으로는 **저사양 보호 장치**가 아직 약하다:
  - `src/piloci/storage/embed.py`: 기본 executor에 임베딩 작업을 그대로 태움 → CPU 경합 상한이 명시적이지 않음
  - `src/piloci/curator/queue.py`: ingest queue가 무한 큐 → burst 유입 시 메모리 상한이 없음
  - `src/piloci/curator/worker.py`: 장기 워커는 있으나 저사양 모드/배치 상한/재시도 정책이 아직 단순함
  - `src/piloci/api/routes.py`: `readyz`는 LanceDB + DB만 보며 Redis/queue 압력은 안 드러남
  - `src/piloci/auth/session.py`: Redis 세션은 안정적이지만 운영 기준치(메모리/세션 수/timeout) 문서화가 약함

### Phase 1 — 측정 먼저 (추정 금지)

- `/api/*`, `/auth/*`, `/sse`, `/api/ingest` 경로별 p50/p95 측정
- 임베딩 1건/10건/50건 latency 측정
- LanceDB search/list/save latency 측정
- idle / login burst / ingest burst 시 RSS 메모리 측정
- 결과를 기준으로 "Pi 5 권장값"과 "저사양 모드" 기본값 분리

### Phase 2 — request path 안정화

- `/healthz`는 liveness 전용, `/readyz`는 LanceDB + SQLite + Redis + queue backlog까지 포함
- degraded 응답에 어떤 의존성이 문제인지 명시
- startup/shutdown에서 worker 종료 timeout, 재시작 시 unfinished job 재큐잉 동작을 체크리스트화
- 로그는 성능 이벤트(느린 임베딩, 느린 LanceDB query, 큐 적체)를 구조화 필드로 남김

### Phase 3 — 저사양 보호 장치

- 임베딩 전용 executor를 분리하고 최대 동시 작업 수를 설정 가능하게 함
- `embed_lru_size`, `workers`, curator 관련 설정에 low-spec preset 제공
- ingest queue를 bounded queue로 바꾸고 꽉 차면 429 또는 지연 응답 정책 적용
- curator worker는 batch 크기, polling 주기, 동시성 1 고정 옵션을 제공
- Cloud/desktop이 아니라 Pi 운영 기준으로 "최대 처리량"보다 "응답성 보존"을 우선

### Phase 4 — 저장소/데이터 경량화

- SQLite WAL/pragma 운영 기준 확정
- LanceDB 인덱스 생성 시점과 재생성 정책 문서화
- 큰 transcript 처리 시 저장/증류/삭제 lifecycle 정의 (raw session 무한 적재 방지)
- 오래된 audit/raw session 정리 정책 추가

### Phase 5 — 실패 복구와 운영성

- Redis 불가 / Gemma 불가 / LanceDB 손상 시의 degraded mode 정의
- curator 비활성화 상태에서도 핵심 MCP/REST 기능은 계속 살아있게 보장
- 운영자가 바로 볼 수 있는 상태값: queue depth, last worker success, last embed latency, disk usage
- 백업/복구 절차를 SQLite + LanceDB 기준으로 문서화

### 구현 우선순위 (실행 순서)

1. ingest queue bounded + backpressure
2. readiness에 Redis/queue 상태 추가
3. 임베딩 executor 분리 + 동시성 상한
4. 저사양 preset 정리
5. raw session / audit log retention

### 완료 기준

- burst ingest 상황에서도 프로세스 RSS가 예측 가능한 상한 안에 머문다
- curator 장애가 API/로그인/MCP 핵심 경로를 막지 않는다
- readiness만 봐도 어떤 의존성이 병목인지 운영자가 바로 안다
- Pi 5와 저사양 장치용 기본 설정값이 문서와 코드에서 일치한다

### 노스스타 (제품 비전)

> **카파시(Karpathy)의 LLM 위키 수준의 개인 지식 베이스를 프로젝트별로 자동 누적하는 시스템.**
> 메모리 서버는 수단이고, 진짜 목표는 **"프로젝트별 작업 노하우/하네스/팁이 일하면서 저절로 정리된 위키로 쌓이는 것"**.
> 구체적 레퍼런스: [llm-wiki](https://github.com/Pratiyush/llm-wiki) 같은 위키 산출물을 **정적 빌드가 아니라 상시 라이브 갱신**으로 구현.

이 비전이 v0.3+ 설계의 모든 우선순위를 결정한다:
- 검색보다 **큐레이션 품질**이 1순위 (raw chunk가 아니라 lesson/recipe 단위)
- 단순 저장이 아니라 **자동 분류/요약/링크화** 파이프라인 필요
- 출력 포맷은 사람이 일상적으로 읽을 수 있는 형태 (마크다운 위키, [[wikilink]] 그래프)
- 프로젝트 격리는 단순 보안이 아니라 **각 프로젝트의 위키 자율성** 보장
- llm-wiki에서 차용: 위키 분류체계(sources/entities/concepts/syntheses/comparisons/questions), 라이프사이클(draft→reviewed→verified→stale→archived), 듀얼 출력(.md/.json/HTML), llms.txt, JSON-LD 그래프

### v0.3 후속 (별도 계획): Obsidian 자동 출력 파이프라인

위 노스스타의 첫 구현체. 방향성만 적어둠 — 구현은 별도 세션 설계.

**큐레이션 엔진 = 로컬 Gemma 4 E2B** (이미 Pi에서 상시 구동 중인 `llama-server.service`, port 9090)
- v0.1.x까지 옵션 취급이었지만 v0.3부터 **시스템 코어 컴포넌트**
- 역할: 백그라운드에서 천천히 메모리를 묶고 정리해서 위키로 끊임없이 갱신
- 운영 철학: "느리지만 가볍게, 24/7 계속" — latency는 신경 쓰지 않음, 처리량(eventually consistent)만 중요
- 리소스 예산: 이미 배치된 ~3GB RAM 그대로 사용 (추가 비용 0). systemd `--prio 2` + 스레드/배치 캡으로 다른 워크로드 안 방해
- Korean 출력 OK (Gemma 4 다국어 지원), function calling으로 구조화된 출력 안정적
- 백엔드는 OpenAI 호환 API(`http://localhost:9090/v1/chat/completions`)로 호출 — 모델 교체 자유로움

**핵심 자동화 흐름** (백엔드 단독으로 완결 가능):
1. **수집 (이미 v0.x)**: MCP 툴로 메모리 저장 → LanceDB
2. **트리거**: `MemoryStore.save/update/delete` 시 비동기 이벤트 발행 (asyncio.Queue 또는 background task)
3. **큐레이션 (v0.3 핵심)**: 신규 `src/piloci/curator/` 모듈
   - 백그라운드 워커가 큐에서 변경분을 꺼내 **Gemma에게 천천히 전달**
   - 그룹핑: project_id + 태그/주제별 클러스터링 (LanceDB 벡터 검색으로 유사 메모리 묶기)
   - 요약/추출: Gemma가 "이 묶음의 핵심 팁/하네스" 추출 (몇 초~몇십 초 걸려도 무방)
   - 마크다운 렌더링: front-matter + 본문 + 태그 [[wikilink]] + 출처 링크 (메모리 ID 역참조)
   - **rate limiting**: Gemma 호출은 직렬 또는 동시 1~2건만, 다른 사용자 요청 안 막도록
4. **출력**: `~/app/piloci/vaults/{user_id}/{project_id}/...md`
5. **웹 노출**: `/api/vault/{user_id}/{project_id}/...` → 마크다운 raw + 메타 반환, 프론트는 react-markdown 렌더 (위키 페이지 UI)
6. **Obsidian 호환**: 같은 .md 파일을 사용자가 Obsidian으로 직접 열면 양쪽 동시 열람 (단방향 sync)

**큐레이션 일관성 모델**: eventually consistent. 메모리 저장 시점과 vault 업데이트 시점이 분리됨. 사용자는 "방금 저장한 노트가 위키에 반영되는데 N분 걸린다"는 걸 UI로 인지할 수 있게 표시 (예: "정리 중... ⏳").

**방향성**: v0.3 단방향 (LanceDB → vault → 웹/Obsidian). 양방향 흡수(Obsidian 편집 → LanceDB)는 v0.4 이후 — 충돌 해소 설계 필요

---

## 핵심 설계 결정 (ADR)

### ADR-1: 테이블 분리 vs 스코프 필터
**결정**: 단일 LanceDB 테이블 + `user_id`/`project_id` 필수 WHERE 필터
**이유**: 컬렉션/테이블 생성 비용을 피하고, 임베디드 LanceDB 운영을 단순하게 유지하면서 저장소 어댑터가 격리 필터를 강제한다.
**문서**: `docs/ADR-001-storage-isolation.md`

### ADR-2: 임베딩 모델 선정
**결정**: `BAAI/bge-small-en-v1.5` (384d, 25MB)
**이유**: Pi 5에서 지연 <50ms, MTEB 영어 벤치 상위, 한국어는 별도 `multilingual` 버전 옵션
**대안 고려**: `jina-embeddings-v2-small` (한국어 지원 좋음) — v0.2에서 프로젝트별 모델 선택 옵션 추가 고려

### ADR-3: 세션 vs JWT
**결정**: 웹은 세션 쿠키, MCP는 JWT
**이유**: 웹 UX는 쿠키가 자연스럽고, MCP는 stateless Bearer가 표준

### ADR-4: stdio vs SSE 우선
**결정**: M1에서 stdio 먼저, M2에서 SSE 추가
**이유**: stdio가 디버깅 쉽고 MCP 툴 검증 빠름. SSE는 인증/네트워크 이슈 분리

### ADR-5: 프론트 프레임워크
**결정**: Next.js + styleseed 기반 SPA (정적 export) — 처음부터 적용
**이유**: styleseed라는 고품질 디자인 시스템이 이미 있어서 Jinja2로 임시 UI를 만들고 재작성하는 낭비 제거. styleseed로 한 번에 프로급 UI 확보. 백엔드는 순수 API 서버로 단순해지고, 빌드된 정적 파일만 Python이 서빙하므로 운영 복잡도 증가 없음.
**대안 고려**:
- Jinja2 서버사이드 → styleseed를 못 쓰거나 스타일만 추출해야 해서 가치 훼손
- 별도 웹 서버(Node.js 컨테이너) → 컨테이너 하나 더 늘어남, 세션 공유 복잡
- Vite + React → Next.js가 styleseed와 공식 호환

### ADR-6: 프로젝트 격리 방식
**결정**: 토큰에 project_id 바인딩 + payload 필터링
**이유**: Claude Code 설정 하나당 프로젝트 하나 매핑이 가장 자연스러움. 유저 레벨 전체 토큰도 옵션으로 제공하되 기본은 프로젝트 스코프. 컬렉션 분리 안 함(ADR-1과 동일 이유).
**대안 고려**:
- HTTP 헤더로 프로젝트 전달 → 토큰 재사용성은 좋으나 실수 여지 큼
- 툴 파라미터로만 전달 → LLM이 매번 판단해야 해서 불안정

### ADR-7: 라이선스
**결정**: MIT
**이유**: 제한 최소, 사용자/기여자 친화적. servicenow-mcp의 Apache-2.0보다 가벼움.

### ADR-8: 인증 우선순위
**결정**: 로컬 인증(이메일+비번) 우선, OAuth는 선택 옵션
**이유**: OAuth는 Google Cloud Console 등록 필요로 초기 진입 장벽 높음. 로컬 인증은 이메일만 있으면 되어 셀프호스팅 서비스에 자연스러움. OAuth는 편의성을 위해 M4에서 추가.

### ADR-9: Docker 기본 배포
**결정**: Docker Compose를 기본 배포 방식으로, systemd는 대안 문서로만
**이유**: 보안 격리(read-only, non-root, capabilities drop), 의존성 캡슐화, 업데이트 용이성. 라즈베리파이5에서 Docker 오버헤드는 무시 가능 수준.

### ADR-10: argon2 > bcrypt
**결정**: argon2id (OWASP 2024 권장)
**이유**: GPU/ASIC 공격 저항성. bcrypt는 여전히 안전하지만 argon2가 현재 베스트 프랙티스. Pi 5에서도 메모리 64MB/time=3 파라미터로 충분히 빠름.

### ADR-11: 세션 저장소
**결정**: **Redis (Docker 컨테이너)**
**이유**: Docker Compose 스택이라 Redis 컨테이너 추가가 거의 공짜. 인메모리 <1ms 응답, TTL 네이티브, 원자적 INCR로 Rate limit/실패 카운터에도 활용. AOF + maxmemory 정책으로 크래시 복원. 메모리 256MB 제한.
**대안 고려**:
- SQLite → 매 요청 디스크 쿼리, Rate limit 구현에 약함
- 메모리(Python dict) → 재시작 시 전체 로그아웃, 워커 확장 불가

### ADR-12: 외부 노출 방식
**결정**: Cloudflare Tunnel 전용, 포트포워딩 금지
**이유**: 가정용 IP 노출 방지, 자동 HTTPS, DDoS 방어, 설정 단순. 라우터 포트포워딩은 공격 표면 노출.

### ADR-13: styleseed 통합 방식
**결정**: **엔진/스킨 파일 복사 스냅샷** (심볼릭 링크 금지)
**이유**:
- Docker 빌드 컨텍스트 안에 있어야 함 (컨테이너가 외부 경로 접근 불가)
- 버전 고정 → 재현 가능한 빌드
- styleseed 변경이 즉시 piLoci에 영향 주지 않음 (의도적 동기화)
- `scripts/sync-styleseed.sh`로 명시적 업데이트
- 향후 npm 배포 시 `package.json`으로 전환
**적용 스킨**: linear (개발자 친화적, 다크모드 기본, 메모리 관리 UI와 어울림)
**대안**: toss (화려함), notion (문서 중심) — 유저 설정에서 전환 가능하게 향후 확장

---

## 참고 자료

- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- MCP 스펙: https://spec.modelcontextprotocol.io/
- Qdrant 튜닝: https://qdrant.tech/documentation/guides/optimize/
- fastembed: https://github.com/qdrant/fastembed
- authlib: https://docs.authlib.org/

---

## v0.3: 자동 캡처 + Gemma 증류 파이프라인

> 결정일: 2026-04-23 (Opus 4.7 설계 세션)
> 레퍼런스: [supermemoryai/supermemory/tree/main/apps/mcp](https://github.com/supermemoryai/supermemory/tree/main/apps/mcp) v4.0
> 핵심 모토: **"쓰레기 전부 수집해서 Pi에서 증류"**

### 배경 및 결정

**문제**: MCP로 연결된 LLM이 대화 내용을 자동으로 수집·저장하는 구조 필요. 현재 `save_memory` 등 7툴은 LLM이 명시적으로 호출해야만 작동 → 사실상 수집 안 됨.

**검토한 자동화 경로**:
1. Stop 훅 (Claude Code/OpenCode/Codex/Gemini) — 세션 종료 시 transcript 파일 경로 전달
2. MCP Resources/Prompts 자동 주입 — 세션 시작 시 클라이언트가 자동 로드
3. 공격적 tool description — SuperMemory 방식

**결정**: **SuperMemory v4.0 아키텍처 채택 + Gemma 로컬 증류 추가**
- Stop 훅은 모든 클라이언트에서 균일하게 작동하지 않음 (Gemini는 아직 미완성)
- 공격적 프롬프트 엔지니어링이 모든 MCP 클라이언트에 보편적으로 먹힘
- Gemma는 백그라운드 증류기로 raw 저장물 → wiki 품질 메모리로 승격
- Stop 훅은 지원 클라이언트에서 "보너스 무료 경로"로만 활용

### 툴 재설계: 7개 → 4개

**삭제되는 기존 MCP 툴** (웹 UI/REST로 이전):
- `get_memory`, `update_memory`, `delete_memory` (action 파라미터로 통합 or REST)
- `clear_memories` (REST + 이중 확인)
- `create_project`, `delete_project` (웹 UI 전용)

**새 MCP 툴 (4개, 공격적 description)**:

```python
# 1. memory - 저장/삭제 통합
memory(
    content: str,                       # 저장할 내용 (forget 시 무시)
    action: "save" | "forget" = "save",
    tags: list[str] | None = None,      # save 전용
    memory_id: str | None = None,       # forget 시 필수
    container_tag: str | None = None,   # 프로젝트 지정 (user 토큰 전용)
)
# description 시작: "CRITICAL: THIS IS THE ONLY MEMORY TOOL. DO NOT USE
#   ANY OTHER SAVE/STORE/REMEMBER/NOTE TOOL..."

# 2. recall - 검색 + 프로필 (SuperMemory 방식)
recall(
    query: str,
    include_profile: bool = True,       # 유저 프로필도 결과에 포함
    tags: list[str] | None = None,
    limit: int = 5,
    container_tag: str | None = None,
)
# description 시작: "CRITICAL: THIS IS THE ONLY RECALL TOOL..."

# 3. listProjects - 프로젝트 목록 (캐시)
listProjects(refresh: bool = False)
# 캐시 TTL 5분, refresh=true로 강제 갱신

# 4. whoAmI - 현재 유저 정보
whoAmI()  # {userId, email, name, client, sessionId}
```

### MCP Resources (3개)

```
piloci://profile   # Gemma가 주기적 생성한 유저 프로필
  → { stable: [...], dynamic: [...] }
  → 세션 시작 시 클라이언트가 자동 로드

piloci://projects  # 사용 가능한 프로젝트 목록
  → { projects: [...] }

piloci://recent    # 최근 N개 메모리 (list_memories 대체)
  → { memories: [...] }
```

### MCP Prompt (1개) — 자동성의 핵심 엔진 ⭐

SuperMemory의 `context` prompt 구조 그대로 차용. 클라이언트가 세션 시작 시 system context에 자동 주입하면 LLM이 세션 내내 memory 툴을 적극 호출하게 됨.

```python
@server.registerPrompt("context")
async def context_prompt(include_recent: bool = True) -> Prompt:
    parts = [
        "**Important:** Whenever the user shares informative facts, "
        "preferences, personal details, code patterns, decisions, or any "
        "memory-worthy information, use the `memory` tool to save it to "
        "piloci. When in doubt, SAVE. This helps maintain context across "
        "conversations.",
        "",
    ]

    profile = await get_profile(user_id, project_id)
    if profile.static:
        parts.append("## User Context")
        parts.append("**Stable Preferences:**")
        parts.extend(f"- {f}" for f in profile.static)
    if include_recent and profile.dynamic:
        parts.append("\n**Recent Activity:**")
        parts.extend(f"- {f}" for f in profile.dynamic)

    return Prompt(messages=[{"role": "user", "content": "\n".join(parts)}])
```

### REST API 확장 (MCP 아님, 웹 UI 전용)

```
PATCH  /api/memories/{id}          # content/tags/metadata 수정
DELETE /api/memories/{id}          # 단건 삭제 (id 지정)
POST   /api/memories/clear         # 프로젝트 전체 삭제 (이중 확인)
GET    /api/memories/{id}          # 단건 조회
POST   /api/ingest                 # Stop 훅 수신 (신규)
```

### `/api/ingest` — Stop 훅 수신 경로

```python
POST /api/ingest
Authorization: Bearer {jwt}
X-Sm-Project: {project_id}  # optional (container_tag 역할)
Content-Type: application/json

Body: {
  "client": "claude-code" | "opencode" | "codex" | "gemini",
  "session_id": "...",
  "transcript": [
    {"role": "user"|"assistant"|"system"|"tool", "content": "...", ...}
  ]
}

Response 202 Accepted (즉시 반환, 큐에 push만):
{"queued": true, "ingest_id": "..."}
```

내부 동작:
1. JWT 검증 + rate limit (세션당 1회, 전체 10/분)
2. 원본 transcript → SQLite `raw_sessions` 테이블 저장
3. `asyncio.Queue`에 `(user_id, project_id, ingest_id)` push
4. 즉시 202 응답
5. 백그라운드 Gemma 워커가 큐 소비

### Gemma 증류기 (핵심 신규 컴포넌트)

**파일**: `src/piloci/curator/worker.py`

**역할**: raw transcript → 구조화된 메모리 + wiki 페이지

**프롬프트 구조** (Gemma 4 E2B에 맞춤):
```text
System: You extract durable memories from AI coding session transcripts.
Output JSON only. Extract facts, decisions, preferences, code patterns,
errors encountered, solutions found. Skip chitchat, commands, tool traces.

User: <transcript excerpt>

Output schema:
{
  "memories": [
    {
      "content": "...",      # 1-2 sentences, self-contained
      "tags": ["..."],        # 1-3 normalized tags
      "category": "fact"|"decision"|"preference"|"pattern"|"error"|"solution"
    }
  ]
}
```

**처리 흐름**:
1. 큐에서 (user_id, project_id, ingest_id) 수신
2. `raw_sessions` 테이블에서 transcript 로드
3. 너무 길면 슬라이딩 윈도우로 청크 분할 (Gemma context 한계)
4. 각 청크 → Gemma 호출 (`http://localhost:9090/v1/chat/completions`)
5. 추출된 memories 목록 파싱
6. 각 메모리:
   - 임베딩 생성 (fastembed)
   - 기존 메모리와 유사도 계산 → 0.95 이상 시 **병합 (중복 제거)**
   - 아니면 `MemoryStore.save()` 호출
7. `raw_sessions` 해당 레코드 `processed_at` 업데이트

**Rate limiting**: Gemma 호출은 세마포어로 동시 1건만 (Pi 5 리소스 보호)

**실패 내성**: Gemma 응답 파싱 실패 시 3회 재시도 → 최종 실패 시 `raw_sessions.error` 필드에 기록하고 건너뜀 (큐 진행 멈추지 않음)

### 프로필 요약 워커

**파일**: `src/piloci/curator/profile.py`

**역할**: 모든 메모리 → 압축된 유저 프로필 생성 (Resource로 노출)

**실행 주기**: 새 메모리 저장 후 N분 뒤 (debounced), 최대 시간당 1회

**Gemma 프롬프트**:
```text
Summarize the following memories into a user profile.

Output JSON:
{
  "static": [
    "user prefers TypeScript over JavaScript",
    "main projects: piloci, styleseed",
    ...
  ],  # 지속적 선호/사실, 최대 20개
  "dynamic": [
    "recently working on LanceDB migration",
    ...
  ]   # 최근 활동, 최대 10개
}
```

결과는 `user_profiles` 테이블에 저장 (JSON 컬럼), Resource 요청 시 즉시 반환.

### Stop 훅 어댑터 CLI

**파일**: `src/piloci/cli_ingest.py` → `piloci-ingest` 커맨드

**클라이언트별 포맷 흡수**:

```python
# Claude Code: stdin JSON (session_id, transcript_path, cwd, ...)
piloci-ingest --client=claude-code < stdin

# OpenCode: ~/.local/share/opencode/storage (SQLite Drizzle)
piloci-ingest --client=opencode --session-id=$SESSION_ID

# Codex CLI: ~/.codex/history.jsonl
piloci-ingest --client=codex --history-file=~/.codex/history.jsonl

# Gemini CLI: GEMINI_SESSION_ID 환경변수 (transcript_path 미완성)
piloci-ingest --client=gemini --session-id=$GEMINI_SESSION_ID  # stub
```

설정:
- `~/.piloci/config.toml`에 endpoint + token 저장
- 없으면 환경변수 `PILOCI_ENDPOINT`, `PILOCI_TOKEN` fallback

### 새 SQLite 테이블

```sql
CREATE TABLE raw_sessions (
    ingest_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    project_id TEXT REFERENCES projects(id),
    client TEXT NOT NULL,              -- claude-code | opencode | ...
    session_id TEXT,
    transcript_json TEXT NOT NULL,     -- 원본 JSON 통째
    created_at TIMESTAMP NOT NULL,
    processed_at TIMESTAMP,            -- Gemma 처리 완료 시각
    error TEXT,                        -- 실패 시 에러 메시지
    memories_extracted INTEGER DEFAULT 0
);

CREATE INDEX idx_raw_unprocessed ON raw_sessions(processed_at)
  WHERE processed_at IS NULL;

CREATE TABLE user_profiles (
    user_id TEXT NOT NULL REFERENCES users(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    profile_json TEXT NOT NULL,        -- {static: [...], dynamic: [...]}
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (user_id, project_id)
);
```

### 작업 순서 (Sonnet 인수인계)

**Phase 1: MCP 툴 4개로 재설계**
- [ ] `src/piloci/tools/memory_tools.py` 재작성 (memory + recall + listProjects + whoAmI)
- [ ] 공격적 description 적용
- [ ] `src/piloci/mcp/server.py` 툴 등록 목록 업데이트
- [ ] 기존 7툴 핸들러/테스트 삭제

**Phase 2: Resources + Prompts 추가**
- [ ] MCP Resource 핸들러 3개 (`piloci://profile`, `piloci://projects`, `piloci://recent`)
- [ ] MCP Prompt 핸들러 1개 (`context`)
- [ ] SSE 레이어에서 Resource/Prompt 요청 처리

**Phase 3: Gemma 큐레이터 인프라**
- [ ] `src/piloci/curator/__init__.py`, `worker.py`, `profile.py`
- [ ] `httpx`로 Gemma OpenAI-호환 API 호출 래퍼
- [ ] asyncio.Queue 전역 인스턴스 (startup에서 생성)
- [ ] 백그라운드 태스크로 워커 시작 (lifespan hook)

**Phase 4: /api/ingest 엔드포인트**
- [ ] `raw_sessions` 테이블 마이그레이션
- [ ] `POST /api/ingest` 라우트
- [ ] JWT 인증 + rate limit
- [ ] transcript 저장 + 큐 push

**Phase 5: REST 관리 API**
- [ ] `PATCH /api/memories/{id}`, `DELETE /api/memories/{id}`
- [ ] `POST /api/memories/clear` (이중 확인)
- [ ] `GET /api/memories/{id}`

**Phase 6: 프로필 요약 워커**
- [ ] `user_profiles` 테이블 마이그레이션
- [ ] debounced 프로필 갱신 워커
- [ ] Resource 핸들러에서 `user_profiles` 조회

**Phase 7: Stop 훅 CLI**
- [ ] `src/piloci/cli_ingest.py` — 4개 클라이언트 어댑터
- [ ] `pyproject.toml`에 `piloci-ingest` 스크립트 등록
- [ ] `docs/CLIENT_SETUP.md`에 각 클라이언트 훅 설정 예시

**Phase 8: 테스트**
- [ ] `tests/test_tools_memory_v2.py` (memory + recall + listProjects + whoAmI)
- [ ] `tests/test_curator_worker.py` (mock Gemma 응답)
- [ ] `tests/test_curator_profile.py`
- [ ] `tests/test_ingest_api.py` (큐 push 검증)
- [ ] `tests/test_cli_ingest.py` (각 클라이언트 포맷 파싱)

**Phase 9: 문서**
- [ ] README 갱신 (2툴 구조 설명, Resources/Prompts 역할)
- [ ] `docs/CLIENT_SETUP.md` 전체 재작성
- [ ] ADR-15 신규: "자동 캡처 아키텍처 = 공격적 프롬프트 + Gemma 증류"

### 토큰 비용 목표

- 세션 시작 오버헤드: ~1,800 토큰 (툴 정의 4개 + 프로필 Resource + context Prompt)
- 저장 호출당: ~200-500 토큰
- 리콜 호출당: ~500-1,500 토큰 (profile 포함)
- 월간 실효 비용 (하루 10세션, 주 5일): **Claude Sonnet $5-10**
- Gemma 증류 = 로컬, API 비용 0

### Verification 체크리스트

- [ ] 4개 MCP 툴만 노출 (`tools/list` 응답 확인)
- [ ] 3개 Resources 노출, 각각 JSON 반환
- [ ] `context` prompt 가져가면 "use the `memory` tool" 문구 포함
- [ ] `memory(action=forget)` 호출 시 `memory_id` 없으면 거절
- [ ] `/api/ingest`에 4개 클라이언트 포맷 모두 POST 성공
- [ ] Gemma 워커가 transcript → memories 저장까지 end-to-end 동작
- [ ] 유사도 0.95+ 메모리는 중복 저장 안 됨
- [ ] 프로필 요약 워커가 `user_profiles` 테이블 갱신
- [ ] Claude Code Stop 훅 → piloci-ingest → 실제 메모리 저장 검증 (수동)
- [ ] OpenCode session_completed 훅 → 저장 검증 (수동)
- [ ] 토큰 소비 측정: 1세션에 <2,000 토큰 (캐시 히트 시)

### v0.3 설계 정제 (2026-04-24)

> 이 세션에서 위 v0.3 원본 계획을 코드 기반으로 검증·정제한 결과.
> 원본 계획과 충돌 시 이 섹션이 우선.

#### 1. SSE 세션 자동 캡처: 툴콜 훅 방식

**문제**: SSE 핸들러(`sse.py`)는 투명 파이프. `read_stream`/`write_stream`이 MCP SDK로 직행하며 대화 버퍼링 없음. MCP 프로토콜에 실리는 것은 툴콜+결과뿐, LLM-사용자 대화는 백엔드가 볼 수 없음.

**결정**: 전체 대화 캡처 시도 안 함. 대신 툴콜 단위 훅:
- `handle_sse()` finally 블록에 세션 종료 훅 추가 (이미 `mcp_auth_ctx.reset()` 있음)
- 수집: "이 세션에서 recall N번, memory M번, forget K번 호출됨" (메타데이터만)
- 결과를 RawSession에 기록 (transcript 없이 메타데이터 전용)
- 전체 대화는 클라이언트가 `POST /api/ingest`로 전송 (기존 엔드포인트, 변경 없음)

**구현 위치**: `src/piloci/mcp/sse.py` finally 블록 + `src/piloci/mcp/server.py` `_call_tool()` 래퍼

#### 2. 단일 진실 공급원: LanceDB만, 새 저장소 없음

**문제**: 원본 계획에 "KnowledgeVault SQLite 테이블" 제안 있었으나, 불필요한 복잡도 증가.

**결정**: SQLite 테이블 추가 없음. LanceDB가 단일 진실 공급원.
- 모든 메모리는 LanceDB에 저장 (변경 없음)
- Vault(`build_project_vault()` 출력)는 LanceDB에서 파생된 뷰
- Vault 결과를 파일시스템에 캐시 (`/data/vaults/{slug}/vault.json`)
- 캐시 무효화: memory save/forget 시 해당 프로젝트 캐시 무효화 → debounce 후 재구축
- Obsidian 내보내기: 캐시된 Vault → 마크다운 파일 생성
- Web UI 그래프: 캐시된 Vault의 `graph.nodes/edges` 직접 사용

**삭제**: `tools/project_tools.py`는 사용되지 않는 레거시 모듈 (MCP 서버에 import 안 됨). 정리 대상.

#### 3. Gemma 호출 추가 없음

**문제**: Pi 5 (8GB RAM + 16GB swap)에서 `Semaphore(1)`이 이미 모든 Gemma 호출을 직렬화. Ingest 추출 + Profile 리프레시가 하나의 레인 공유. 추가 호출 여력 없음.

**결정**: 새 Gemma 호출 추가 안 함.
- SSE 세션 훅 → RawSession 기록 (메타데이터) → 기존 IngestJob 큐 → 기존 큐레이터 → 기존 Gemma
- 큐레이터 파이프라인에 데이터를 더 공급만 하고, 추출 로직은 변경 없음
- 성능 개선은 Semaphore 분리(ingest vs profile) 등 기존 경로 최적화에 집중

#### 4. 사용자 데이터 이식 (Export/Import)

**요구사항**: 사용자가 자기 데이터를 다른 piLoci 인스턴스로 들고 갈 수 있어야 함. 관리자 마이그레이션이 아니라 사용자 단위.

**설계**:
```
Export: GET /api/data/export → 파일 다운로드
├── manifest.json    ← piLoci 버전, embed 모델, 체크섬, 타임스탬프
├── projects.json    ← 프로젝트 메타
├── memories.parquet ← LanceDB 메모리 (벡터 포함)
└── profile.json     ← 사용자 프로필

Import: POST /api/data/import (multipart) → 현재 계정으로 병합
├── 로그인된 사용자의 ID로 자동 매핑
├── 프로젝트 slug 충돌 시 자동 이름 변경
├── embed 모델 버전 비교 → 다르면 재임베드
└── 프로필 재생성 트리거
```

**핵심 원칙**: 사용자는 이미 대상 서버에 계정이 있음. 파일 업로드 → "불러오기" → 현재 계정으로 쏙 들어감. 사용자 생성/ID 재매핑 불필요.

**포맷**: Parquet (벡터 컬럼 그대로 담을 수 있고 LanceDB와 호환)

#### 5. 성능 최적화 우선순위

기존 코드 기반 분석 결과, 다음 항목들을 v0.3 구현 시 함께 처리:

| 항목 | 현재 상태 | 개선 |
|---|---|---|
| Batch embedding | `embed_one()` 1건씩 executor hop | 호출부에서 리스트 단위 배치 |
| `EmbeddingCache.get()` | `list.remove()` O(n) | `OrderedDict` 또는 `dict`+순서 추적 |
| Gemma Semaphore | 글로벌 `Semaphore(1)` | ingest/profile 분리 (2개 세마포어) |
| Workspace cache | 매 GET마다 전체 재구축 | 파일시스템 캐시 + 이벤트 무효화 |
| `listProjects` 캐시 | MCP desc는 "5분 캐시"라 했지만 DB 조회 | 실제 캐시 구현 |
| `container_tag` | 스키마에 노출되나 핸들러에서 무시 | 스키마에서 제거 또는 구현 |
| Bulk save | LanceDB에 1건씩 save | 배치 save API 추가 |

#### 6. v0.3 작업 순서 (정제됨)

Phase 1-8은 원본 계획 유지. 다음 Phase 추가:

**Phase 10: 사용자 데이터 이식**
- [x] `GET /api/data/export` — LanceDB 필터링 + Parquet 직렬화 + manifest 생성
- [x] `POST /api/data/import` — 업로드 수신 → 파싱 → 현재 사용자 ID로 병합
- [x] embed 모델 버전 비교 → 불일치 시 재임베드 옵션
- [x] `tests/test_data_portability.py`
- [x] `tests/test_api_data_portability.py` (라우트 레벨 회귀)
- [x] `/api/data/import` rate limit
- [x] 설정 페이지 export/import UI

**Phase 11: Vault 캐시 + Obsidian 내보내기**
- [x] `build_project_vault()` 결과를 `/data/vaults/{slug}/vault.json`에 캐시
- [x] memory save/forget 시 캐시 무효화 이벤트 (debounce 없는 즉시 무효화)
- [x] `GET /api/vault/{slug}/export` — 캐시에서 Obsidian 마크다운 .zip 생성
- [x] Web UI graph 엔드포인트, 캐시된 vault JSON 직접 반환
- [x] `tests/test_vault_cache.py`

**Phase 11 진행 메모 (2026-04-25)**
- `src/piloci/curator/vault.py`에 vault JSON 캐시/로드/무효화/zip export helper 추가
- `GET /api/projects/slug/{slug}/workspace`는 기본적으로 `/data/vaults/{slug}/vault.json`을 우선 사용하고, `refresh=true`일 때만 재빌드함
- `GET /api/vault/{slug}/export`는 캐시된 vault를 Obsidian형 markdown + `vault.json`이 들어있는 zip으로 내려줌
- vault 캐시는 REST 메모리 수정/삭제/clear, MCP memory save/forget, curator ingest 저장 시 무효화됨
- 관련 회귀 검증: `uv run pytest tests/test_curator_vault.py tests/test_vault_cache.py tests/test_tools_memory.py tests/test_main_projects_cache.py tests/test_notify_telegram.py -v --no-cov` → `32 passed`

**Phase 12: 성능 개선**
- [x] Batch embedding API
- [ ] EmbeddingCache O(1) 갱신
- [ ] Gemma 세마포어 분리 (ingest / profile)
- [x] listProjects 캐시 구현
- [ ] LanceDB bulk save
- [x] `container_tag` 스키마 정리

**Phase 12 진행 메모 (2026-04-25)**
- MCP `listProjects`는 실제 5분 사용자별 인메모리 캐시로 구현됨 (`src/piloci/main.py::_ProjectsCache`)
- `refresh=true`면 캐시를 우회하고 DB에서 다시 읽음
- 죽은 MCP 스키마 필드였던 `container_tag`는 `MemoryInput`/`RecallInput`에서 제거되어 툴 스키마 토큰을 줄임
- curator ingest 경로는 `src/piloci/curator/worker.py`에서 `embed_one()` 루프 대신 `embed_texts()` 1회 배치 호출을 사용하도록 변경됨
- 중복 검사와 `store.save()`는 그대로 개별 처리해 동작 리스크는 낮추고, executor hop/임베딩 호출 수만 줄였음
- `tests/test_curator_worker.py`에 다건 배치 임베딩 + duplicate skip + vault invalidation 회귀가 추가됨
- 관련 회귀 검증: `uv run pytest tests/test_curator_worker.py tests/test_curator_vault.py tests/test_vault_cache.py tests/test_tools_memory.py tests/test_main_projects_cache.py tests/test_notify_telegram.py -q --no-cov` → `43 passed`

**Phase 13: 레거시 정리**
- [ ] `src/piloci/tools/project_tools.py` 제거 (사용되지 않음)
- [ ] 사용하지 않는 import/참조 정리

#### 7. MCP 세션 Telegram 요약 알림 (구현됨)

**구현 완료**:
- `src/piloci/mcp/session_state.py` 추가: MCP 세션 단위 카운터/태그 집계용 `McpSessionTracker`, `mcp_auth_ctx`, `mcp_session_ctx`
- `src/piloci/mcp/server.py` `_call_tool()`에서 성공한 툴 호출만 집계
- `src/piloci/mcp/sse.py` `finally`에서 세션 종료 시점 알림 전송 시도
- `src/piloci/notify/telegram.py` 추가: Telegram Bot API `sendMessage` 직접 호출, plain-text, timeout, 429 retry, 4096자 truncation
- `src/piloci/config.py`에 Telegram 설정 추가:
  - `telegram_bot_token`
  - `telegram_chat_id`
  - `telegram_min_duration_sec`
  - `telegram_min_memory_ops`
  - `telegram_timeout_sec`

**알림 조건**:
- 봇 토큰/채팅 ID가 모두 설정되어 있어야 함
- 세션에서 실제 MCP tool call이 1회 이상 있어야 함
- 아래 둘 중 하나 충족 시만 전송:
  - 세션 지속시간 ≥ `telegram_min_duration_sec`
  - memory save/forget 합계 ≥ `telegram_min_memory_ops`

**의도**:
- LLM 추가 호출 없이 세션 메타데이터만으로 “작업이 있었던 세션”만 저비용 요약 알림
- 시시한 짧은 세션/조회 거의 없는 세션은 자동 무시

**현재 범위**:
- Telegram 알림은 구현 완료
- RawSession 메타데이터 영구 저장은 아직 미구현 (설계 항목으로만 유지)

---

## 세션 인수인계 규칙

**구현 세션 시작 시:**
1. 이 파일(`PLAN.md`)부터 읽기
2. `## 현재 상태` 체크박스 확인
3. 다음 미완료 항목부터 시작
4. 작업 완료하면 체크박스 업데이트
5. 주요 설계 변경 시 `## 핵심 설계 결정` 에 ADR 추가

**Opus로 계획 세션 전환 시점:**
- 새로운 마일스톤 시작 전
- 설계 변경이 필요한 막힘 발생 시
- 성능 최적화 전략 재검토 필요 시

**Sonnet으로 구현 세션 전환 시점:**
- 위 계획 세션에서 결정 사항이 명확해진 직후
- 단순 코드 작성/수정/테스트 작업
