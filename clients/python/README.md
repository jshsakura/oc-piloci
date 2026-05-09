# piloci-client

Python SDK for [piLoci](https://github.com/Sisyphus-Junior/piloci) — a self-hosted memory service for LLM assistants.

## Install

Not yet on PyPI. Install locally from this repository:

```bash
pip install -e clients/python/
```

Or from a wheel:

```bash
pip install piloci-client
```

Requires Python 3.9+ and `httpx` (installed automatically).

## Get a token

Open your piLoci instance → **Settings → Tokens** → create a new token.

For memory, recall, recommend, and contradict you need a **project-scoped** token
(select a project in the token form). A non-project token returns HTTP 403 for
those endpoints — the SDK raises `PilociPermissionError` with a clear message.

## Sync usage

```python
from piloci_client import Piloci

client = Piloci(base_url="https://my.piloci", token="JWT.xxx")
client.memory.save(content="we decided to use argon2id", tags=["security"])
results = client.recall(query="what auth did we pick?", limit=5)
for p in results.previews:
    print(p.excerpt)
projects = client.projects.list()
```

## Async usage

```python
import asyncio
from piloci_client import AsyncPiloci

async def main():
    async with AsyncPiloci(base_url="https://my.piloci", token="JWT.xxx") as client:
        await client.memory.save("we use argon2id", tags=["security"])
        results = await client.recall("what auth did we pick?")
        for p in results.previews:
            print(p.excerpt)

asyncio.run(main())
```

## API surface

| Client method | REST endpoint | Notes |
|---|---|---|
| `memory.save(content, tags)` | `POST /api/v1/memory` | Requires project-scoped token |
| `memory.delete(memory_id)` | `POST /api/v1/memory` | action=forget |
| `memory.list(query, limit)` | `POST /api/v1/recall` | Alias for recall |
| `recall(query, ...)` | `POST /api/v1/recall` | Requires project-scoped token |
| `projects.list(refresh)` | `GET /api/v1/projects` | |
| `projects.init(cwd, ...)` | `POST /api/v1/init` | |
| `whoami()` | `GET /api/v1/whoami` | |
| `recommend(domain, ...)` | `POST /api/v1/recommend` | Requires project-scoped token |
| `contradict(instinct_id)` | `POST /api/v1/contradict` | Requires project-scoped token |

All methods accept an optional `project="slug"` keyword argument that is sent
as `X-Piloci-Project` header for future server-side routing. The JWT's
`project_id` claim is what the server actually enforces today.

## Error types

```python
from piloci_client import (
    PilociError,           # base — all SDK errors
    PilociAuthError,       # HTTP 401
    PilociPermissionError, # HTTP 403 — need project-scoped token
    PilociValidationError, # HTTP 422 — check .details
    PilociServerError,     # HTTP 5xx
)
```

## Development

```bash
cd clients/python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```
