# MEMORY

## 2026-04-24

- Hardened release hygiene for `piloci`: expanded `.gitignore` and `.dockerignore` to exclude local env files, caches, tool artifacts, build outputs, and editor state from commits and Docker contexts.
- Documented the tag-driven release flow in `README.md` and `CLAUDE.md`, matching the `mfa-servicenow-mcp` release model (`git tag v{version}` + tagged publish).
- Verified release readiness locally with `uv build`, `uv run pytest tests/ -v` (156 passed), and `pnpm build` in `web/`.
- Updated `PLAN.md` to mark the PyPI dry-run build checklist item complete.

## 2026-04-23

- Added a v0.3-style vault workspace MVP for project detail pages.
- Backend now exposes `GET /api/projects/slug/{slug}/workspace` and derives Obsidian-compatible markdown notes plus graph nodes/edges from project memories.
- Frontend project detail page now loads the workspace, lets the user browse generated notes, and shows graph relationships in-browser without requiring a separate export step.
