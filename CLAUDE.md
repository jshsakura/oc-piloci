# piLoci — Development Rules

## Session Protocol

**구현 세션 시작 시:**
1. `PLAN.md` 읽기 → `## 현재 상태` 체크박스 확인
2. 다음 미완료 항목부터 시작
3. 작업 완료 시 체크박스 업데이트 + `MEMORY.md` 갱신

## Tool Description Rules (LLM Context Budget)

- Tool `description`: max 120 chars
- Parameter `description`: max 80 chars
- Schema compaction은 `src/piloci/tools/_schema.py`의 `compact_schema()`가 자동 처리

## Security Non-Negotiables

- 모든 LanceDB 조회/검색에 `(user_id, project_id)` 필터 **반드시** 적용 (누락 시 데이터 유출)
- 비밀번호: argon2id만 사용 (bcrypt 금지)
- JWT secret, session secret은 환경 변수/Docker secrets로만 — 코드 하드코딩 금지
- raw SQL 금지, SQLAlchemy ORM만 사용
- 사용자 입력은 Pydantic 스키마로 검증 후에만 사용

## Adding New MCP Tools

1. `src/piloci/tools/` 에 구현
2. `src/piloci/mcp/tools.py` 에 등록
3. description ≤ 120자, 파라미터 description ≤ 80자
4. `compact_schema()` 통과 확인
5. `tests/test_tools_*.py` 에 테스트 추가

## Code Style

- formatter: black (line-length=100)
- linter: ruff
- import sort: isort (profile=black)
- pre-commit 실행 후 커밋

## Version Bumps & Release

- 버전은 `pyproject.toml`의 `[project].version` 단일 소스 기준으로 관리
- 버전 업데이트는 기본적으로 `+0.0.1` patch 단위만 허용 (major/minor bump는 명시 승인 필요)
- 릴리스는 **태그 푸시 기반**: `git tag v{version} && git push origin main v{version}`
- 태그는 반드시 `pyproject.toml` 버전과 일치해야 함 (`v0.2.0` ↔ `0.2.0`)
- 릴리스 전 최소 확인:
  - `pytest tests/ -v`
  - `uv build`
  - 웹 변경이 있으면 `pnpm build` (in `web/`)
- GitHub Actions `publish.yml`가 다음을 담당:
  - version guard
  - test gate
  - web build artifact
  - multi-arch Docker publish
  - GitHub Release
  - PyPI publish (`oc-piloci`)
- 버전 bump 커밋은 태그 없이 푸시하지 말 것. 릴리스 커밋과 태그를 같은 흐름으로 처리

## Performance (Pi 5 원칙)

- 임베딩은 항상 `run_in_executor` (블로킹 금지)
- 임베딩 LRU 캐시 활용 (`storage/cache.py`)
- 배치 처리 가능한 경우 단건 반복 금지
- `orjson` 사용 (표준 json 금지)
