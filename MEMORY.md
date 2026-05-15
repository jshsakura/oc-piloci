# MEMORY

## 2026-05-15

- Closed the security/product hardening pass: added double-submit CSRF for cookie-authenticated unsafe requests, Redis-backed slowapi storage with broader route coverage, persisted Bearer-token revocation checks, stale session/user revalidation, MCP Streamable HTTP session-summary parity, LLM provider private-network URL rejection by default, and stricter LanceDB user/project/tag validation.
- Surfaced the previously API-only team feature in the web app: `/teams` is now in the app shell navigation and supports team creation, pending invite handling, member visibility, email invites, and shared team document create/update/delete flows through typed frontend API methods.
- Added backend regression coverage for the new hardening areas and team routes, including CSRF middleware, auth revocation/stale-user validation, private LLM URL validation, LanceDB unsafe input rejection, MCP auth/session summary behavior, and full team invite/document flows. Team route tests exposed a real SQLite timezone comparison bug in invite expiry handling, fixed by normalizing team-route timestamps to naive UTC.
- Updated project docs and status tracking: `PLAN.md`, `README.md`, and `README.ko.md` now reflect LanceDB/ADR completion, the security hardening changes, and the `/teams` workspace. Coverage gate was raised from `27` to `73` after full-suite coverage reached `73.44%`.
- Verification: `uv run black src tests && uv run isort src tests && uv run ruff check src tests` passed; targeted team integration tests passed (`2 passed`); full backend suite passed (`750 passed, 1 skipped`, total coverage `73.44%`); web checks passed with `pnpm exec tsc --noEmit`, `pnpm run lint`, `pnpm run test:coverage` (`12 passed`), and `pnpm build`.

## 2026-05-10

- Simplified the landing page install CTA: the separate install/update buttons are now one “설치 및 업데이트” / “Install and Update” command, copying `uvx oc-piloci@latest setup` so fresh installs and refreshes use the same path.
- Prepared patch release `0.3.11` for the unified install/update CTA so the package version and release tag can stay aligned.

## 2026-05-03

- Closed Phase 10 (data portability): `src/piloci/api/data_portability.py` already provided per-user zip export (manifest + projects.json + memories.parquet w/ vectors + profiles.json) and import-with-merge that renames colliding project slugs and re-embeds when the archive's embed model differs; routes `GET /api/data/export` and `POST /api/data/import` are wired in `src/piloci/api/routes.py` and unit-tested via `tests/test_data_portability.py` (13 passed, 1 intentionally skipped).
- Hardened the public deployment surface for the slice: `.mcp.json` (which contained a real long-lived user-scope JWT) is now in `.gitignore` alongside `web/playwright-report/` and `web/test-results/`, and `.mcp.json.example` was added with a placeholder Bearer.
- Added route-level regression coverage in `tests/test_api_data_portability.py` for 401 unauth, 400 empty body, 413 oversize import, 200 round-trip export→import, reembed query flag, and 409 embed-model mismatch.
- Applied slowapi rate limit `RATE_DATA_IO` to both `/api/data/export` and `/api/data/import` so bulk export/import cannot be abused for DoS, and reduced export memory pressure on Pi 5 by streaming directly into the pyarrow row dict instead of materializing two intermediate `dict[str, Any]` lists.
- Added `web/app/settings` data portability section with download/upload buttons, reembed toggle, and Korean/English copy that follows the “quiet curator” voice rule.

## 2026-04-27

- Added comprehensive backend API regression coverage for `src/piloci/api/audit.py` and `src/piloci/api/routes.py` via new `tests/test_api_audit.py` and expanded `tests/test_api_routes_extra.py`, covering audit logging, auth/project/token helpers, workspace/vault routes, audit listing, 2FA flows, password change, and OAuth login/callback/disconnect branches without modifying `src/`.
- Updated stale suite expectations in `tests/test_main_extra.py` and `tests/test_mcp_server_extra.py` so they match current Starlette mount behavior and MCP low-level error wrapping, which was required to make the requested full-suite verification command green again.
- Revalidated with zero LSP error diagnostics on the touched test files and full `uv run pytest` (`484 passed`, total coverage `89.67%`), with `src/piloci/api/audit.py` at `100%` and `src/piloci/api/routes.py` at `81%` in the final coverage report.

- Expanded backend regression coverage for the requested gaps in `src/piloci/main.py`, `src/piloci/auth/middleware.py`, and `src/piloci/cli.py` via `tests/test_main_extra.py`, new `tests/test_auth_middleware.py`, and new `tests/test_cli_extra.py`.
- The new tests cover stdio/server bootstrap wiring, Starlette app/middleware registration, startup/shutdown worker orchestration, auth middleware JWT/session/no-auth branches, CLI dispatch for `serve` / `stdio` / `bootstrap` / `profile-baseline`, and bootstrap success plus credential error paths without touching `src/` code.
- Revalidated the exact requested outcome with zero LSP error diagnostics on the three changed test files and full `uv run pytest` (`473 passed`, total coverage `83.56%`), with `src/piloci/main.py` at `97%`, `src/piloci/auth/middleware.py` at `89%`, and `src/piloci/cli.py` at `97%` in the full-suite report.

- Expanded MCP regression coverage with `tests/test_mcp_server_extra.py` and `tests/test_mcp_sse_extra.py`: the new server tests now drive the real low-level MCP request handlers for tool/resource/prompt paths, auth/project-scope error contracts, vault-cache invalidation, instinct-tool branches, and context prompt assembly, while the SSE tests now cover route registration, `/healthz`, successful bearer-auth SSE setup, contextvar lifecycle, and summary-notify failure handling.
- Revalidated the exact requested outcome with zero LSP error diagnostics on both new/updated test files, targeted MCP pytest (`34 passed`), and full `uv run pytest` (`473 passed`, total coverage `83.56%`), with `src/piloci/mcp/server.py` and `src/piloci/mcp/sse.py` both reaching `100%` coverage in the full run.

- Fixed Google OAuth deploy-time redirect URI drift: `src/piloci/config.py` now accepts `BASE_URL` and `PILOCI_PUBLIC_URL` as aliases for `settings.base_url`, so `/auth/{provider}/login` and `/auth/{provider}/callback` can generate the public callback origin instead of falling back to an internal host from `request.base_url`.
- Documented and wired the operator path for that fix across `.env.example`, `README.md`, `README.ko.md`, and `deploy/setup.sh`, and set the local deployment `.env` to `BASE_URL=https://piloci.opencourse.kr` so Google OAuth callbacks can stay pinned to the public domain behind a proxy/tunnel.
- Added regression coverage in `tests/test_auth_oauth.py` for both `BASE_URL` and legacy `PILOCI_PUBLIC_URL` env loading, then revalidated the OAuth/provider slice with `uv run pytest tests/test_auth_oauth.py tests/test_auth_rate_limits.py -v --no-cov` (`26 passed`) and `pnpm build` in `web/`.

- Fixed the landing-page hydration mismatch behind production React error #418: `web/app/page.tsx` now waits for a mounted client pass before switching away from the server-rendered pending shell, and `web/lib/auth.ts` now persists only `user` instead of persisting `hasHydrated`, preventing the home page from rendering a different first client tree than the server.
- Revalidated the frontend slice with zero LSP diagnostics on `web/app/page.tsx` and `web/lib/auth.ts`, plus `pnpm build` in `web/` (`next build` passed).

- Fixed the missing OAuth provider discovery API: `src/piloci/api/routes.py` now serves `GET /api/auth/providers` by reflecting configured providers from `piloci.auth.oauth.get_provider_credentials`, which unblocks the login/signup UI from showing non-local buttons when env credentials are present.
- Re-enabled the previously skipped regression in `tests/test_auth_rate_limits.py` so the provider-status route shape stays locked; revalidated with `uv run pytest tests/test_auth_rate_limits.py -v --no-cov` (`5 passed`).

- Added encrypted OAuth token persistence for provider logins: `src/piloci/auth/crypto.py` derives a Fernet key from `settings.jwt_secret`, `src/piloci/db/models.py` now stores nullable `oauth_access_token` / `oauth_refresh_token`, and `src/piloci/auth/oauth.py` encrypts tokens during `upsert_oauth_user()` while keeping the old call shape backward-compatible for existing tests.
- Added provider disconnect support across the auth callback and route layer: `src/piloci/api/routes.py` now stores exchanged OAuth tokens on callback, exposes `POST /auth/{provider}/disconnect`, validates the logged-in Redis session plus password-presence safety check, revokes provider tokens through `revoke_provider_token()`, and clears linked OAuth fields locally even if remote revoke/decrypt fails.
- Revalidated the slice with LSP error diagnostics on `src/piloci/auth/crypto.py`, `src/piloci/auth/oauth.py`, `src/piloci/api/routes.py`, and `src/piloci/db/models.py`, `uv run pytest tests/test_auth_oauth.py -q --cov-fail-under=0` (`19 passed`), full `uv run pytest tests -q` (`252 passed, 1 skipped`), and `uv build`.

## 2026-04-25

- Added a preview-first workspace path for the project vault: `GET /api/projects/slug/{slug}/workspace/preview` reuses the cached vault when available, returns graph/stats plus the first five note previews, and drops heavy markdown from the default project workspace payload.
- `web/lib/api.ts` now points the project page at the preview endpoint, `web/lib/types.ts` marks markdown as optional, and `web/components/VaultNoteDetail.tsx` falls back to excerpts with a preview notice when full markdown is not included.
- Added preview coverage in `tests/test_vault_cache.py`; revalidated with LSP error diagnostics on touched backend/frontend files, `uv run pytest tests/test_vault_cache.py -v --no-cov` (`8 passed`), `uv run black`, `uv run ruff check`, and `pnpm build` in `web/`.

- Reframed the landing page around piLoci as a quiet automatic memory curator: `web/lib/copy.ts` now uses paragraph-based Korean/English copy for the 우렁각시/quiet house fairy metaphor, and `web/app/page.tsx` renders a dedicated curation section with a static memory graph preview instead of a dash-joined feature sentence.
- Added `CLAUDE.md` frontend copy rules so future product copy avoids dash-heavy feature lists, translates technical optimizations into user experience, and keeps the “뒤에서 조용히 돕는 자동 기억 큐레이터” metaphor plus the graph/workspace direction of a curator peeling messy post-it notes off the wall and organizing them one by one. Revalidated with `pnpm build` in `web/` and LSP error diagnostics on `web/app/page.tsx`.
- Researched future graph UI direction: keep the current landing preview dependency-free, prefer React Flow for a polished interactive curated-memory graph, and reserve Sigma.js/WebGL for large workspace graphs if React Flow hits node-count limits.

- Added the narrow v0.3 memory-create/UI speed slice: `src/piloci/api/routes.py` now exposes project-scoped `POST /api/memories` using the existing embed/store/cache-invalidation path, and `web/app/projects/page.tsx` adds number-based quick note selection over the already-loaded workspace notes.
- Added route-level coverage for successful REST memory creation plus project-scope and blank-content rejection in `tests/test_api_ingest.py`; revalidated with `uv run pytest tests/test_api_ingest.py -v --no-cov`, `uv run ruff check src/piloci/api/routes.py tests/test_api_ingest.py`, and `pnpm build` in `web/`.

- Optimized curator ingest persistence in `src/piloci/curator/worker.py` and `src/piloci/storage/lancedb_store.py`: in-job vector duplicates are now filtered before LanceDB search, and accepted memories are written through one `save_many(...)` batch upsert instead of per-memory saves.
- Added regression coverage for batched curator saves, in-batch duplicate skipping, and LanceDB `save_many` profiling; revalidated the slice with `uv run pytest tests/test_curator_worker.py tests/test_storage_lancedb.py -v --no-cov` (`38 passed`) plus `ruff check` on touched files.

- Completed the repo-wide stdlib `json` cleanup for runtime paths: CLI/profile/curator/Gemma/MCP/ingest/baseline code now uses `orjson`, and grep confirms no remaining `json.loads`/`json.dumps`/`json.load` usage under `src/piloci`.
- Hardened commit-time quality gates in `.pre-commit-config.yaml`: Black, isort, Ruff, and full pytest now run through local `uv run ...` hooks so the hook uses the project environment instead of failing on missing `python3.11` hook virtualenvs.
- Removed lint-exposed dead/noisy code while validating the hooks: unused signup assignment was dropped, embedding batch cache update now uses `zip(..., strict=True)`, empty/opaque `pass` exception paths were replaced with explicit continue/debug behavior, and the full pre-commit suite passes.

- Optimized curator ingest embedding in `src/piloci/curator/worker.py`: extracted memories are now normalized first and embedded with a single `embed_texts(...)` batch call instead of `embed_one()` per memory, while duplicate checks and `store.save()` remain per-item for low-risk behavior.
- Cleaned the remaining basedpyright warnings in touched backend files (`src/piloci/auth/oauth.py`, `src/piloci/api/routes.py`, `src/piloci/mcp/server.py`) and revalidated the slice with required hygiene commands (`black`, `ruff`, targeted pytest).
- Expanded `tests/test_curator_worker.py` with multi-memory ingest coverage for batched embeddings, duplicate skipping, and vault-cache invalidation; targeted regressions now pass with `43 passed`.

- Implemented the Phase 11 vault/export slice: `src/piloci/curator/vault.py` now supports cached vault JSON persistence under `vault_dir`, cache loads, cache invalidation, and Obsidian-style zip export containing both markdown notes and `vault.json`.
- `src/piloci/api/routes.py` now serves cached workspace data from `GET /api/projects/slug/{slug}/workspace` by default, supports `refresh=true` rebuilds, and adds `GET /api/vault/{slug}/export` for downloadable Obsidian-style vault archives.
- Wired vault cache invalidation across REST memory mutations, MCP memory save/forget, project deletion, and curator ingest saves so cached graph/note output stays aligned with LanceDB-backed memories.
- Added `tests/test_vault_cache.py` for cache save/load, invalidate, workspace cache-hit behavior, and zip export shape; revalidated the combined backend slice with targeted regressions (`32 passed`).

- Enforced patch-only release hygiene: `src/piloci/version.py` now derives `__version__` from package metadata with a pyproject fallback for source-tree runs, removing the duplicate hardcoded version that could drift from `[project].version`.
- Added `tests/test_version.py` to assert the imported package version matches `pyproject.toml`, and documented the `+0.0.1` default bump policy in `README.md`, `README.ko.md`, and `CLAUDE.md`.

- Replaced stdlib `json` with `orjson` on the LanceDB metadata hot path in `src/piloci/storage/lancedb_store.py`, covering save, update/merge, vector upsert, and row parsing while keeping the stored `metadata` column as a JSON string for schema compatibility.
- Added LanceDB storage regressions for byte metadata parsing and metadata-update merge semantics in `tests/test_storage_lancedb.py`; revalidated the storage slice with `uv run pytest tests/test_storage_lancedb.py -v --no-cov` (`25 passed`).

## 2026-04-24

- Implemented the next low-token MCP cleanup slice: `src/piloci/main.py` now has a real per-user 5-minute `listProjects` cache with `refresh=true` bypass, eliminating the old mismatch where the tool description promised caching but every call still hit SQLite.
- Removed dead MCP schema noise from `src/piloci/tools/memory_tools.py` by deleting the unused `container_tag` field from both `MemoryInput` and `RecallInput`, reducing tool-schema token overhead and removing a misleading parameter the handlers never consumed.
- Added `tests/test_main_projects_cache.py` to lock cache hit/copy semantics, expiry/invalidate behavior, and absence of `container_tag` in the generated MCP schemas; revalidated the combined backend slice with targeted regressions (`24 passed`).

- Added token-free MCP session Telegram notifications: `src/piloci/mcp/session_state.py` now tracks per-session tool-call counts/tags, `src/piloci/mcp/server.py` records successful tool usage, and `src/piloci/mcp/sse.py` sends a summary from the session `finally` block without affecting MCP flow on notifier failure.
- Added `src/piloci/notify/telegram.py` with direct Telegram Bot API `sendMessage` integration using plain text, explicit timeout, 429 retry with `retry_after`, disabled push noise, and 4096-char truncation; exposed the related runtime knobs in `src/piloci/config.py` (`telegram_bot_token`, `telegram_chat_id`, duration/memory-op thresholds, timeout).
- Reworked MCP recall into a token-saving 3-mode flow in `src/piloci/tools/memory_tools.py`: default preview responses now return excerpt/length/score/tags only, `fetch_ids` loads full content only for selected memories, and `to_file=true` writes large recall results to markdown under `export_dir` so the LLM can stay out of the full payload path.
- Updated `src/piloci/mcp/server.py` to pass `export_dir` into recall handling and expanded targeted regression coverage in `tests/test_tools_memory.py` plus new `tests/test_notify_telegram.py`; revalidated the slice with `uv run pytest tests/test_tools_memory.py tests/test_notify_telegram.py -v --no-cov` (`19 passed`).

- Reframed `README.md` around the actual Obsidian-adjacent functionality already in the repo: transcript ingest via `piloci-ingest`, the `/api/projects/slug/{slug}/workspace` vault workspace API, markdown/frontmatter note generation, graph data, and the current boundary that full on-disk Obsidian sync is not implemented yet.
- Tightened `src/piloci/storage/lancedb_store.py` again so `get()` now pushes `(user_id, project_id, memory_id)` isolation directly into the LanceDB query instead of materializing a row first and rejecting it in Python.
- Expanded `tests/test_storage_lancedb.py` around the get/isolation path and revalidated the LanceDB + profiling + embed regression slice after the query-level isolation change (`33 passed`).
- Tightened `src/piloci/auth/session.py` so `_enforce_session_limit()` checks Redis set cardinality first and skips the expensive `SMEMBERS`/per-session scan on the common under-limit login path.
- Expanded `tests/test_auth_session.py` with explicit coverage for the new fast path and for oldest-session eviction once the max-session limit is actually exceeded, then revalidated the auth/session + profiling + LanceDB slice (`44 passed`).
- Tightened `src/piloci/storage/lancedb_store.py` again so `delete()` and `clear_project()` use LanceDB delete-result counts directly, removing extra pre-count scans while keeping the same boolean/count return semantics.
- Revalidated the optimized store mutation path with `tests/test_storage_lancedb.py`, `tests/test_ops_profiling.py`, and `tests/test_storage_embed.py` after the delete-result change (`33 passed`).
- Tightened `src/piloci/storage/lancedb_store.py` mutation paths so common `update()` and `delete()` operations enforce isolation with direct filtered mutations instead of paying an extra internal `get()` round trip first.
- Expanded `tests/test_storage_lancedb.py` to assert successful `update()`/`delete()` no longer emit nested `lancedb.get` profiler metrics, then revalidated the targeted LanceDB/profiling regression slice.
- Switched the idle baseline collector to env-first defaults: `src/piloci/profiling_baseline.py` now resolves `PILOCI_PROFILE_BASELINE_*` with fallback to shared `PILOCI_ENDPOINT` / `PILOCI_TOKEN`, and `src/piloci/cli.py` keeps flags as explicit overrides.
- Expanded `tests/test_profiling_baseline.py` to cover env-based default resolution plus CLI override behavior for `piloci profile-baseline`.
- Updated the `README.md` idle-baseline section so the operator workflow is env-first like `mfa-servicenow-mcp`, including shared-token fallback and one-off flag override examples.
- Optimized `src/piloci/ops/maintenance.py` so retention cleanup counts and deletes old rows with SQL filters instead of loading full raw-session and audit tables into Python.
- Fixed `src/piloci/storage/cache.py` to promote keys on reads, making the embedding cache a true LRU and reducing repeated embedding work under hot-key reuse.
- Added `src/piloci/profiling_baseline.py` plus the `piloci profile-baseline` CLI subcommand so an empty deployment can still collect a repeatable idle baseline from `/healthz`, `/readyz`, and `/profilez` without requiring seeded data.
- Added `tests/test_profiling_baseline.py` to cover latency summary shape, public endpoint collection, bearer-token passthrough, and degraded `/readyz` handling for the new baseline utility.
- Documented the idle profiling workflow in `README.md` so operators have a concrete no-data-safe baseline command before authenticated/data-heavy paths exist.
- Closed the remaining LanceDB profiling gap in `src/piloci/storage/lancedb_store.py`: `update()`, `delete()`, and `clear_project()` now emit runtime profiler metrics in addition to the previously timed read paths.
- Expanded `tests/test_storage_lancedb.py` so mutation profiling is covered for success and no-op cases, then revalidated the profiling regression slice (`42 passed`) after the change.
- Added in-process runtime profiling to `src/piloci/utils/logging.py`: bounded latency windows now track HTTP path timings plus embed and LanceDB operation timings, and `/profilez` exposes the current snapshot with RSS, p50/p95, averages, and maxima.
- Wired the profiling baseline through `src/piloci/main.py`, `src/piloci/api/routes.py`, `src/piloci/storage/embed.py`, and `src/piloci/storage/lancedb_store.py`, and added `tests/test_ops_profiling.py` to verify snapshot summaries, middleware HTTP timing, and `/profilez` output.
- Marked the final `PLAN.md` backend hardening item complete for runtime profiling baselines; the `v0.2.x 백엔드 개선 예정` checklist is now fully closed.
- Added retention/ops guardrails: `src/piloci/ops/maintenance.py` now runs periodic cleanup for processed `raw_sessions` and old `audit_logs`, and `src/piloci/main.py` starts that maintenance worker during app startup.
- Strengthened SQLite operational defaults in `src/piloci/db/session.py` with `WAL`, `foreign_keys=ON`, configurable `busy_timeout`, `synchronous`, and `temp_store=MEMORY`; exposed the related runtime knobs in `src/piloci/config.py` alongside retention settings.
- Added `tests/test_ops_maintenance.py` to verify retention cleanup deletes only old processed raw sessions and old audit logs while leaving pending/recent data intact.
- Updated `README.md` and `PLAN.md` so the final backend hardening area now reflects real retention policy, SQLite guardrails, and backup/cleanup guidance rather than a docs-only placeholder.
- Added `low_spec_mode` and curator pacing knobs in `src/piloci/config.py`, with the preset clamping worker count, embed cache/concurrency, ingest queue size, transcript size, and profile cadence to safer Pi-class defaults.
- Updated `src/piloci/curator/worker.py` and `src/piloci/curator/profile.py` so low-spec operation is real runtime behavior: bounded queue usage is enforced during startup requeue, worker polling uses config instead of a hardcoded timeout, transcript shortening honors config, and profile refresh cycles now respect a per-pass project limit plus inter-project pause.
- Added `tests/test_curator_low_spec.py` to cover the low-spec preset, bounded startup requeue behavior, and profile refresh pacing limits, then validated the combined backend hardening surface with targeted regressions.
- Marked both `PLAN.md` items complete for `curator worker 저사양 모드 추가` and `저사양 기본값 재조정`; the next remaining backend hardening work is SQLite/LanceDB guardrails and retention/ops cleanup.
- Hardened `src/piloci/storage/embed.py` with a dedicated embedding `ThreadPoolExecutor`, a semaphore-based concurrency cap, and low-spec config knobs (`embed_executor_workers`, `embed_max_concurrency`) so bursty embedding work no longer spills into the shared default executor.
- Threaded the new embedding limits through API update, MCP search, and curator worker paths, and added `tests/test_storage_embed.py` to verify dedicated-executor use and enforced max concurrency.
- Marked the `PLAN.md` embedding executor/concurrency-cap item complete; the next backend hardening target is low-spec preset tuning / worker-mode cleanup.
- Expanded `/readyz` in `src/piloci/api/routes.py` so readiness now checks LanceDB, SQLite, Redis session-store reachability, and ingest queue pressure, and returns explicit degraded causes instead of a shallow pass/fail.
- Added `tests/test_api_readyz.py` to cover both healthy and degraded readiness states, including Redis failure and full ingest queue reporting.
- Marked the `PLAN.md` readiness/health hardening item complete and moved directly to the embedding executor/concurrency-cap step.
- Implemented the first `v0.2.x` backend hardening item: `src/piloci/curator/queue.py` is now bounded by config, and `src/piloci/api/routes.py` returns `429` with `Retry-After` plus queue depth/capacity when ingest backpressure kicks in.
- Added targeted regression coverage in `tests/test_curator_worker.py` and `tests/test_api_ingest.py` for queue capacity, full-queue rejection, raw-session cleanup on enqueue failure, and normal enqueue success.
- Marked the `PLAN.md` checklist item for ingest queue backpressure complete so the next backend step can move to readiness/health depth.
- Added a new `v0.2.x` backend hardening roadmap to `PLAN.md` focused on speed, stability, and low-spec operation.
- Updated stale PLAN references from Qdrant-era wording to the current LanceDB/Redis deployment model where they directly affected backend planning clarity.
- The new backend priorities are explicit: bounded ingest queue, readiness depth, embedding concurrency limits, low-spec presets, and retention/ops guardrails.
- Reworked `README.md` into a current project entrypoint: added status snapshot, v0.1/v0.2/v0.3 phase roadmap, LanceDB-based architecture summary, and aligned deploy/release instructions with the actual stack.
- Split the combined v0.2 docs checkbox in `PLAN.md` into separate README/ADR items so implementation progress is visible instead of hidden behind one mixed task.
- Hardened release hygiene for `piloci`: expanded `.gitignore` and `.dockerignore` to exclude local env files, caches, tool artifacts, build outputs, and editor state from commits and Docker contexts.
- Documented the tag-driven release flow in `README.md` and `CLAUDE.md`, matching the `mfa-servicenow-mcp` release model (`git tag v{version}` + tagged publish).
- Verified release readiness locally with `uv build`, `uv run pytest tests/ -v` (156 passed), and `pnpm build` in `web/`.
- Updated `PLAN.md` to mark the PyPI dry-run build checklist item complete.
- Optimized `src/piloci/utils/logging.py` profiling middleware: skipped profiling on operational endpoints (`/healthz`, `/readyz`, `/profilez`) to eliminate probe traffic overhead, and moved `_last_updated` timestamp out of `observe()` into `snapshot()` to avoid a `datetime.now()` call on every sample.
- Added regression tests in `tests/test_ops_profiling.py` for skipped operational paths and empty-snapshot `updated_at: None`, then validated all 8 profiling tests pass.
- Optimized `src/piloci/curator/vault.py` tag counting from O(n) to O(1) by tracking `_tag_count` incrementally in `add_node()` instead of filtering the full nodes list at the end of `build_project_vault()`.
- Stabilized `src/piloci/auth/session.py` session eviction by sorting Redis `smembers()` results before oldest-session analysis, removing nondeterministic full-suite failures from unordered set iteration.
- Cleaned up `tests/test_auth_session.py` mocks so Redis pipeline methods behave like the real synchronous pipeline API and eviction assertions bind payloads by session key instead of call order; full test suite now passes cleanly (`193 passed`).
- Updated `README.md` to reflect the actual MCP surface (`4` tools: `memory`, `recall`, `listProjects`, `whoAmI`) and marked the `PLAN.md` Cloudflare Tunnel checkbox as user/operator-side work outside the repository implementation scope so it no longer appears as false pending engineering work.

## 2026-04-23

- Added a v0.3-style vault workspace MVP for project detail pages.
- Backend now exposes `GET /api/projects/slug/{slug}/workspace` and derives Obsidian-compatible markdown notes plus graph nodes/edges from project memories.
- Frontend project detail page now loads the workspace, lets the user browse generated notes, and shows graph relationships in-browser without requiring a separate export step.

## 2026-04-24

- Fixed deployment secret wiring so the app could read `JWT_SECRET_FILE` and `SESSION_SECRET_FILE` from Docker secrets while still supporting direct env vars for native/local runs. This was later superseded by the 2026-04-26 env-only deployment cleanup.
- Updated deployment templates to match the LanceDB-based architecture: added `LANCEDB_PATH`, removed stale Qdrant guidance from dev config, and clarified Cloudflare Tunnel secret handling.
- Refreshed `README.md` so the Docker deployment flow, required runtime variables, and release steps reflect the current production setup.

## 2026-04-26

- Removed Docker secret-file fallback and standardized deployment on env-only `JWT_SECRET` / `SESSION_SECRET` values.
- Simplified `deploy/setup.sh` so first-run setup now generates those secrets directly into `.env` instead of writing `secrets/*` files.
- Updated `docker-compose.yml`, `.env.example`, README/README.ko, `PLAN.md`, and `docs/index.md` so reverse proxies/tunnels stay outside Compose and the documented runtime contract matches the code.
