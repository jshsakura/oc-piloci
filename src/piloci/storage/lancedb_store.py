from __future__ import annotations

import logging
import math
import re
import time
import uuid
from typing import Any, NotRequired, TypedDict

import orjson
import pyarrow as pa
from lancedb.index import FTS, BTree, IvfPq, LabelList

from piloci.config import Settings
from piloci.utils.logging import get_runtime_profiler

logger = logging.getLogger(__name__)

VECTOR_SIZE = 384  # bge-small-en-v1.5
TABLE_NAME = "piloci_memories"

MEMORY_SCOPE_PERSONAL = "personal"
MEMORY_SCOPE_SHARED = "shared"

_SCHEMA = pa.schema(
    [
        pa.field("memory_id", pa.string(), nullable=False),
        pa.field("user_id", pa.string(), nullable=False),
        pa.field("project_id", pa.string(), nullable=False),
        pa.field("scope", pa.string(), nullable=False),
        pa.field("content", pa.string()),
        pa.field("tags", pa.list_(pa.string())),
        pa.field("metadata", pa.string()),  # JSON-encoded
        pa.field("created_at", pa.int64()),
        pa.field("updated_at", pa.int64()),
        pa.field("vector", pa.list_(pa.float32(), VECTOR_SIZE)),
    ]
)

# Allow UUID format plus simple slug IDs like "dev-user", "dev-project"
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_SAFE_TAG_RE = re.compile(r"^[^'\x00\r\n]{1,80}$")


class MemoryWrite(TypedDict):
    content: str
    vector: list[float]
    tags: NotRequired[list[str]]
    metadata: NotRequired[dict[str, Any]]


def _safe_id(value: str) -> str:
    """Validate ID contains only alphanumeric/dash/underscore (SQL injection guard)."""
    if not _SAFE_ID_RE.match(value):
        raise ValueError(f"Invalid ID format: {value!r}")
    return value


def _safe_tag(value: str) -> str:
    if not _SAFE_TAG_RE.match(value):
        raise ValueError(f"Invalid tag format: {value!r}")
    return value


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") or "{}"
    if isinstance(metadata, str | bytes | bytearray):
        try:
            metadata = orjson.loads(metadata)
        except (orjson.JSONDecodeError, ValueError):
            metadata = {}
    tags = row.get("tags") or []
    return {
        "id": row["memory_id"],
        "user_id": row["user_id"],
        "project_id": row["project_id"],
        "scope": row.get("scope", MEMORY_SCOPE_PERSONAL),
        "content": row.get("content", ""),
        "tags": list(tags),
        "metadata": metadata,
        "created_at": row.get("created_at", 0),
        "updated_at": row.get("updated_at", 0),
    }


class MemoryStore:
    """LanceDB-backed memory store. All queries auto-apply (user_id, project_id) filter."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._db = None
        self._table = None

    async def _get_db(self):
        if self._db is None:
            import lancedb

            path = str(self._settings.lancedb_path)
            self._settings.lancedb_path.mkdir(parents=True, exist_ok=True)
            self._db = await lancedb.connect_async(path)
        return self._db

    async def _get_table(self):
        if self._table is None:
            db = await self._get_db()
            self._table = await db.create_table(TABLE_NAME, schema=_SCHEMA, exist_ok=True)
        return self._table

    async def ensure_collection(self) -> None:
        tbl = await self._get_table()
        settings = self._settings

        # Scalar indices for fast (user_id, project_id) filter on every query
        for col, cfg in [("user_id", BTree()), ("project_id", BTree()), ("tags", LabelList())]:
            try:
                await tbl.create_index(col, config=cfg, replace=False)
            except Exception:
                pass  # Index already exists

        # FTS index on content — enables hybrid search (BM25 + vector)
        try:
            await tbl.create_index("content", config=FTS(with_position=False), replace=False)
        except Exception:
            pass  # Already exists or not enough data

        # Vector index once table has enough rows
        if settings.lancedb_index_type == "IVF_PQ":
            try:
                count = await tbl.count_rows()
                if count >= settings.lancedb_index_threshold:
                    await tbl.create_index(
                        "vector",
                        config=IvfPq(distance_type="cosine"),
                        replace=False,
                    )
            except Exception:
                pass  # Index already exists or not enough data

        logger.info("LanceDB table %s ready", TABLE_NAME)

    def _must_filter_sql(self, user_id: str, project_id: str) -> str:
        """Required filter that enforces project isolation on every query."""
        uid = _safe_id(user_id)
        pid = _safe_id(project_id)
        return f"user_id = '{uid}' AND project_id = '{pid}'"

    def _memory_filter_sql(self, user_id: str, project_id: str, memory_id: str) -> str:
        where = self._must_filter_sql(user_id, project_id)
        mid = _safe_id(memory_id)
        return f"{where} AND memory_id = '{mid}'"

    async def save(
        self,
        user_id: str,
        project_id: str,
        content: str,
        vector: list[float],
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        memory_ids = await self.save_many(
            user_id=user_id,
            project_id=project_id,
            memories=[
                {
                    "content": content,
                    "vector": vector,
                    "tags": tags or [],
                    "metadata": metadata or {},
                }
            ],
        )
        return memory_ids[0]

    async def save_many(
        self,
        user_id: str,
        project_id: str,
        memories: list[MemoryWrite],
    ) -> list[str]:
        if not memories:
            return []
        user_id = _safe_id(user_id)
        project_id = _safe_id(project_id)

        tbl = await self._get_table()
        now = int(time.time())
        memory_ids: list[str] = []
        rows = []
        for memory in memories:
            memory_id = str(uuid.uuid4())
            memory_ids.append(memory_id)
            rows.append(
                {
                    "memory_id": memory_id,
                    "user_id": user_id,
                    "project_id": project_id,
                    "scope": MEMORY_SCOPE_PERSONAL,
                    "content": memory["content"],
                    "tags": memory.get("tags", []),
                    "metadata": orjson.dumps(memory.get("metadata", {})).decode(),
                    "created_at": now,
                    "updated_at": now,
                    "vector": memory["vector"],
                }
            )
        with get_runtime_profiler().track("lancedb.save"):
            await (
                tbl.merge_insert("memory_id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute(rows)
            )
        return memory_ids

    @staticmethod
    def _recency_boost(
        results: list[dict[str, Any]],
        weight: float = 0.15,
        half_life_days: float = 30.0,
    ) -> list[dict[str, Any]]:
        """Blend recency decay into relevance scores and re-sort."""
        now = time.time()
        for r in results:
            age_days = max(0.0, (now - r.get("created_at", now)) / 86400.0)
            recency = math.exp(-age_days * math.log(2) / half_life_days)
            r["score"] = min(1.0, (1.0 - weight) * r["score"] + weight * recency)
        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def _build_where(self, user_id: str, project_id: str, tags: list[str] | None) -> str:
        where = self._must_filter_sql(user_id, project_id)
        if tags:
            for tag in tags:
                safe_tag = _safe_tag(tag)
                where += f" AND list_contains(tags, '{safe_tag}')"
        return where

    async def search(
        self,
        user_id: str,
        project_id: str,
        query_vector: list[float],
        top_k: int = 5,
        tags: list[str] | None = None,
        min_score: float | None = None,
    ) -> list[dict[str, Any]]:
        tbl = await self._get_table()
        where = self._build_where(user_id, project_id, tags)

        with get_runtime_profiler().track("lancedb.search"):
            rows = await (
                tbl.vector_search(query_vector)
                .distance_type("cosine")
                .where(where)
                .limit(top_k)
                .to_list()
            )

        results = []
        for row in rows:
            distance = row.get("_distance", 0.0)
            score = min(1.0, max(0.0, 1.0 - distance))
            if min_score is not None and score < min_score:
                continue
            d = _row_to_dict(row)
            d["score"] = score
            results.append(d)
        return self._recency_boost(results)

    async def hybrid_search(
        self,
        user_id: str,
        project_id: str,
        query_text: str,
        query_vector: list[float],
        top_k: int = 5,
        tags: list[str] | None = None,
        min_score: float | None = None,
        rrf_k: int = 60,
    ) -> list[dict[str, Any]]:
        """Reciprocal Rank Fusion of vector search + FTS (BM25)."""
        tbl = await self._get_table()
        where = self._build_where(user_id, project_id, tags)
        fetch_n = max(top_k * 3, 20)

        # 1. Vector search
        with get_runtime_profiler().track("lancedb.hybrid.vector"):
            vec_rows = await (
                tbl.vector_search(query_vector)
                .distance_type("cosine")
                .where(where)
                .limit(fetch_n)
                .to_list()
            )

        # 2. FTS search — falls back to empty list if index not ready
        fts_rows: list[dict[str, Any]] = []
        try:
            with get_runtime_profiler().track("lancedb.hybrid.fts"):
                fts_rows = await (
                    tbl.search(query_text, query_type="fts", fts_columns="content")
                    .where(where)
                    .limit(fetch_n)
                    .to_list()
                )
        except Exception:
            pass

        # 3. RRF merge
        rrf_scores: dict[str, float] = {}
        memory_map: dict[str, dict[str, Any]] = {}

        for rank, row in enumerate(vec_rows, 1):
            mid = row["memory_id"]
            rrf_scores[mid] = rrf_scores.get(mid, 0.0) + 1.0 / (rrf_k + rank)
            memory_map.setdefault(mid, row)

        for rank, row in enumerate(fts_rows, 1):
            mid = row["memory_id"]
            rrf_scores[mid] = rrf_scores.get(mid, 0.0) + 1.0 / (rrf_k + rank)
            memory_map.setdefault(mid, row)

        max_rrf = 2.0 / (rrf_k + 1)
        sorted_ids = sorted(rrf_scores, key=lambda m: rrf_scores[m], reverse=True)[:top_k]

        results = []
        for mid in sorted_ids:
            score = min(1.0, rrf_scores[mid] / max_rrf)
            if min_score is not None and score < min_score:
                continue
            d = _row_to_dict(memory_map[mid])
            d["score"] = score
            results.append(d)

        return self._recency_boost(results)

    async def get(self, user_id: str, project_id: str, memory_id: str) -> dict[str, Any] | None:
        tbl = await self._get_table()
        _SCALAR_COLS = [
            "memory_id",
            "user_id",
            "project_id",
            "scope",
            "content",
            "tags",
            "metadata",
            "created_at",
            "updated_at",
        ]
        where = self._memory_filter_sql(user_id, project_id, memory_id)
        with get_runtime_profiler().track("lancedb.get"):
            rows = await tbl.query().where(where).select(_SCALAR_COLS).limit(1).to_list()
        if not rows:
            return None
        return _row_to_dict(rows[0])

    async def count(self, user_id: str, project_id: str, tags: list[str] | None = None) -> int:
        tbl = await self._get_table()
        where = self._build_where(user_id, project_id, tags)
        return await tbl.count_rows(where)

    async def list(
        self,
        user_id: str,
        project_id: str,
        tags: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        tbl = await self._get_table()
        where = self._build_where(user_id, project_id, tags)

        _SCALAR_COLS = [
            "memory_id",
            "user_id",
            "project_id",
            "scope",
            "content",
            "tags",
            "metadata",
            "created_at",
            "updated_at",
        ]
        with get_runtime_profiler().track("lancedb.list"):
            rows = (
                await tbl.query()
                .where(where)
                .select(_SCALAR_COLS)
                .limit(limit)
                .offset(offset)
                .to_list()
            )
        return [_row_to_dict(r) for r in rows]

    async def update(
        self,
        user_id: str,
        project_id: str,
        memory_id: str,
        content: str | None = None,
        new_vector: list[float] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        with get_runtime_profiler().track("lancedb.update"):
            tbl = await self._get_table()
            where = self._memory_filter_sql(user_id, project_id, memory_id)
            now = int(time.time())

            if new_vector is None and metadata is None:
                updates: dict[str, Any] = {"updated_at": now}
                if content is not None:
                    updates["content"] = content
                if tags is not None:
                    updates["tags"] = tags
                if len(updates) == 1:
                    result = await tbl.update(updates=updates, where=where)
                    return result.rows_updated > 0
                result = await tbl.update(updates=updates, where=where)
                return result.rows_updated > 0

            _SCALAR_COLS = [
                "memory_id",
                "user_id",
                "project_id",
                "scope",
                "content",
                "tags",
                "metadata",
                "created_at",
                "updated_at",
            ]
            rows = await tbl.query().where(where).select(_SCALAR_COLS).limit(1).to_list()
            if not rows:
                return False
            existing = _row_to_dict(rows[0])

            if new_vector is not None:
                merged_meta = {**existing.get("metadata", {}), **(metadata or {})}
                row = {
                    "memory_id": _safe_id(memory_id),
                    "user_id": user_id,
                    "project_id": project_id,
                    "scope": existing.get("scope", MEMORY_SCOPE_PERSONAL),
                    "content": content if content is not None else existing["content"],
                    "tags": tags if tags is not None else existing["tags"],
                    "metadata": orjson.dumps(merged_meta).decode(),
                    "created_at": existing["created_at"],
                    "updated_at": now,
                    "vector": new_vector,
                }
                await (
                    tbl.merge_insert("memory_id")
                    .when_matched_update_all()
                    .when_not_matched_insert_all()
                    .execute([row])
                )
            else:
                updates: dict[str, Any] = {"updated_at": now}
                if content is not None:
                    updates["content"] = content
                if tags is not None:
                    updates["tags"] = tags
                if metadata is not None:
                    merged = {**existing.get("metadata", {}), **metadata}
                    updates["metadata"] = orjson.dumps(merged).decode()
                await tbl.update(updates=updates, where=where)

            return True

    async def delete(self, user_id: str, project_id: str, memory_id: str) -> bool:
        with get_runtime_profiler().track("lancedb.delete"):
            tbl = await self._get_table()
            where = self._memory_filter_sql(user_id, project_id, memory_id)
            result = await tbl.delete(where)
            deleted_rows = getattr(result, "num_deleted_rows", 0)
            return isinstance(deleted_rows, int) and deleted_rows > 0

    async def clear_project(self, user_id: str, project_id: str) -> int:
        with get_runtime_profiler().track("lancedb.clear_project"):
            tbl = await self._get_table()
            where = self._must_filter_sql(user_id, project_id)
            result = await tbl.delete(where)
            deleted_rows = getattr(result, "num_deleted_rows", 0)
            return deleted_rows if isinstance(deleted_rows, int) else 0

    async def close(self) -> None:
        self._table = None
        self._db = None
        logger.debug("LanceDB connection released")
