# ADR-014: LanceDB As The Embedded Vector Backend

## Status

Accepted.

## Context

piLoci targets Raspberry Pi 5 as a first-class deployment. Qdrant's official container path was unreliable on Pi 5 because its jemalloc dependency does not handle the 16 KB page size in that environment. Native Qdrant builds are also heavy enough to undermine the project's easy-install goal.

The service does not need a networked vector database for the current product shape. It needs reliable local search, simple backups, and low operational weight.

## Decision

Use LanceDB as the only vector storage backend for the current product line.

LanceDB runs embedded in the Python process, stores data under the `/data` volume, and avoids a separate vector database container. piLoci keeps a storage protocol boundary so the rest of the application depends on memory-store behavior rather than LanceDB internals.

## Consequences

- Docker Compose no longer starts or manages a Qdrant service.
- Backups focus on SQLite plus the LanceDB directory under the data volume.
- Readiness checks validate SQLite, Redis, LanceDB, and runtime workers rather than an external vector DB process.
- The storage protocol remains useful for tests and future backend experiments, but LanceDB is the supported production path.
