# MEMORY

## 2026-04-24

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

- Fixed deployment secret wiring so the app can read `JWT_SECRET_FILE` and `SESSION_SECRET_FILE` from Docker secrets while still supporting direct env vars for native/local runs.
- Updated deployment templates to match the LanceDB-based architecture: added `LANCEDB_PATH`, removed stale Qdrant guidance from dev config, and clarified Cloudflare Tunnel secret handling.
- Refreshed `README.md` so the Docker deployment flow, required runtime variables, and release steps reflect the current production setup.
