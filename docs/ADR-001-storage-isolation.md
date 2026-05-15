# ADR-001: Storage Isolation Model

## Status

Accepted. Updated for the LanceDB backend.

## Context

piLoci is multi-user and project-scoped. A memory query must never return data from another user or project, even when all tenants share the same embedded vector table.

The original design used a single vector collection with payload filters. The backend is now LanceDB, so the same isolation model is expressed as SQL `WHERE` filters over one table.

## Decision

Use one LanceDB memories table and require every read, search, update, delete, and project-clear operation to include both `user_id` and `project_id` filters.

The storage adapter owns the enforcement point. Callers pass user and project IDs to the store API, and the store builds the mandatory filter before touching LanceDB.

IDs and tag filters are validated before being interpolated into LanceDB filter expressions. Batch writes validate the same boundary so invalid scope identifiers cannot be persisted.

## Consequences

- Project isolation remains a code-level invariant instead of a caller convention.
- The data model stays simple for Raspberry Pi deployments because no per-project collection management is needed.
- Future vector backends must preserve the same `(user_id, project_id)` mandatory-filter contract.
- Tests must cover cross-user and cross-project isolation for every storage operation.
