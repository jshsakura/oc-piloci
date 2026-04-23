from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class MemoryRecord:
    user_id: str
    project_id: str
    content: str
    vector: list[float]
    memory_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class SearchResult:
    memory_id: str
    score: float
    user_id: str
    project_id: str
    content: str
    tags: list[str]
    metadata: dict[str, Any]
    created_at: int
    updated_at: int


@runtime_checkable
class MemoryStoreProtocol(Protocol):
    async def ensure_collection(self) -> None: ...

    async def save(
        self,
        user_id: str,
        project_id: str,
        content: str,
        vector: list[float],
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str: ...

    async def get(
        self,
        user_id: str,
        project_id: str,
        memory_id: str,
    ) -> dict[str, Any] | None: ...

    async def update(
        self,
        user_id: str,
        project_id: str,
        memory_id: str,
        content: str | None = None,
        new_vector: list[float] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool: ...

    async def delete(
        self,
        user_id: str,
        project_id: str,
        memory_id: str,
    ) -> bool: ...

    async def clear_project(self, user_id: str, project_id: str) -> int: ...

    async def search(
        self,
        user_id: str,
        project_id: str,
        query_vector: list[float],
        top_k: int = 5,
        tags: list[str] | None = None,
        min_score: float | None = None,
    ) -> list[dict[str, Any]]: ...

    async def list(
        self,
        user_id: str,
        project_id: str,
        tags: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...

    async def close(self) -> None: ...
