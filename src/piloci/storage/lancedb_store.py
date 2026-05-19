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
MEMORY_SCOPE_TEAM = "team"

# Sentinel team_id used on personal rows so the SQL filter is a plain `=`
# instead of `IS NULL` (BTree indexes work on equality, not IS NULL — keeps
# the personal-scope query path identical in cost to before the team column
# was introduced).
_PERSONAL_TEAM_SENTINEL = "__personal__"

_SCHEMA = pa.schema(
    [
        pa.field("memory_id", pa.string(), nullable=False),
        pa.field("user_id", pa.string(), nullable=False),
        pa.field("project_id", pa.string(), nullable=False),
        pa.field("scope", pa.string(), nullable=False),
        pa.field("team_id", pa.string(), nullable=False),
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
    team_id_raw = row.get("team_id") or _PERSONAL_TEAM_SENTINEL
    return {
        "id": row["memory_id"],
        "user_id": row["user_id"],
        "project_id": row["project_id"],
        "scope": row.get("scope", MEMORY_SCOPE_PERSONAL),
        "team_id": None if team_id_raw == _PERSONAL_TEAM_SENTINEL else team_id_raw,
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
            # Open existing table without enforcing schema match — production
            # tables created before the team_id column was added would otherwise
            # fail create_table(exist_ok=True) with "Schema Error: Provided
            # schema does not match existing table schema". add_columns inside
            # ensure_collection() bridges the gap.
            try:
                self._table = await db.open_table(TABLE_NAME)
            except Exception:
                self._table = await db.create_table(TABLE_NAME, schema=_SCHEMA)
        return self._table

    async def ensure_collection(self) -> None:
        tbl = await self._get_table()
        settings = self._settings

        # Backfill team_id column on tables created before the team-memory
        # feature shipped — keeps existing personal memories addressable
        # without a full rewrite. New rows always set team_id explicitly.
        try:
            schema = await tbl.schema()
            if "team_id" not in schema.names:
                await tbl.add_columns(pa.schema([pa.field("team_id", pa.string(), nullable=True)]))
                await tbl.update(
                    updates={"team_id": f"'{_PERSONAL_TEAM_SENTINEL}'"},
                    where="team_id IS NULL",
                )
        except Exception:
            logger.exception("team_id column migration skipped")

        # Scalar indices for fast (user_id, project_id) filter on every query.
        # team_id is on the same axis — every team query and every personal
        # query (sentinel match) hits the BTree.
        for col, cfg in [
            ("user_id", BTree()),
            ("project_id", BTree()),
            ("team_id", BTree()),
            ("tags", LabelList()),
        ]:
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
        """Required filter that enforces project isolation on every personal query.

        team_id is pinned to the personal sentinel so team rows can never leak
        into a personal recall — even if the same project_id were reused.
        """
        uid = _safe_id(user_id)
        pid = _safe_id(project_id)
        return (
            f"user_id = '{uid}' AND project_id = '{pid}' "
            f"AND team_id = '{_PERSONAL_TEAM_SENTINEL}'"
        )

    def _memory_filter_sql(self, user_id: str, project_id: str, memory_id: str) -> str:
        where = self._must_filter_sql(user_id, project_id)
        mid = _safe_id(memory_id)
        return f"{where} AND memory_id = '{mid}'"

    def _team_filter_sql(self, team_id: str) -> str:
        """Team isolation filter. Used by team_* methods only — author SQL stays
        out of this so all team members can see each other's memories."""
        tid = _safe_id(team_id)
        return f"team_id = '{tid}'"

    def _team_memory_filter_sql(self, team_id: str, memory_id: str) -> str:
        where = self._team_filter_sql(team_id)
        mid = _safe_id(memory_id)
        return f"{where} AND memory_id = '{mid}'"

    def _team_build_where(self, team_id: str, tags: list[str] | None) -> str:
        where = self._team_filter_sql(team_id)
        if tags:
            for tag in tags:
                safe_tag = _safe_tag(tag)
                where += f" AND list_contains(tags, '{safe_tag}')"
        return where

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
                    "team_id": _PERSONAL_TEAM_SENTINEL,
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
                    "team_id": _PERSONAL_TEAM_SENTINEL,
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

    # ------------------------------------------------------------------
    # Team-scoped methods
    #
    # These intentionally take team_id (not user_id, not project_id) so the
    # isolation axis is enforced at the call site by signature. The MCP
    # handler must validate that the caller is a member of the team before
    # routing here — store does not re-check.
    # ------------------------------------------------------------------

    async def team_save(
        self,
        team_id: str,
        author_id: str,
        content: str,
        vector: list[float],
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        ids = await self.team_save_many(
            team_id=team_id,
            author_id=author_id,
            memories=[
                {
                    "content": content,
                    "vector": vector,
                    "tags": tags or [],
                    "metadata": metadata or {},
                }
            ],
        )
        return ids[0]

    async def team_save_many(
        self,
        team_id: str,
        author_id: str,
        memories: list[MemoryWrite],
    ) -> list[str]:
        if not memories:
            return []
        team_id = _safe_id(team_id)
        author_id = _safe_id(author_id)

        tbl = await self._get_table()
        now = int(time.time())
        ids: list[str] = []
        rows = []
        for memory in memories:
            memory_id = str(uuid.uuid4())
            ids.append(memory_id)
            meta = dict(memory.get("metadata") or {})
            meta.setdefault("author_id", author_id)
            rows.append(
                {
                    "memory_id": memory_id,
                    "user_id": author_id,
                    "project_id": team_id,  # placeholder; never used for team scope
                    "scope": MEMORY_SCOPE_TEAM,
                    "team_id": team_id,
                    "content": memory["content"],
                    "tags": memory.get("tags", []),
                    "metadata": orjson.dumps(meta).decode(),
                    "created_at": now,
                    "updated_at": now,
                    "vector": memory["vector"],
                }
            )
        with get_runtime_profiler().track("lancedb.team_save"):
            await (
                tbl.merge_insert("memory_id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute(rows)
            )
        return ids

    async def team_search(
        self,
        team_id: str,
        query_vector: list[float],
        top_k: int = 5,
        tags: list[str] | None = None,
        min_score: float | None = None,
    ) -> list[dict[str, Any]]:
        tbl = await self._get_table()
        where = self._team_build_where(team_id, tags)
        with get_runtime_profiler().track("lancedb.team_search"):
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

    async def team_hybrid_search(
        self,
        team_id: str,
        query_text: str,
        query_vector: list[float],
        top_k: int = 5,
        tags: list[str] | None = None,
        min_score: float | None = None,
        rrf_k: int = 60,
    ) -> list[dict[str, Any]]:
        tbl = await self._get_table()
        where = self._team_build_where(team_id, tags)
        fetch_n = max(top_k * 3, 20)

        with get_runtime_profiler().track("lancedb.team_hybrid.vector"):
            vec_rows = await (
                tbl.vector_search(query_vector)
                .distance_type("cosine")
                .where(where)
                .limit(fetch_n)
                .to_list()
            )

        fts_rows: list[dict[str, Any]] = []
        try:
            with get_runtime_profiler().track("lancedb.team_hybrid.fts"):
                fts_rows = await (
                    tbl.search(query_text, query_type="fts", fts_columns="content")
                    .where(where)
                    .limit(fetch_n)
                    .to_list()
                )
        except Exception:
            pass

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

    async def team_get(self, team_id: str, memory_id: str) -> dict[str, Any] | None:
        tbl = await self._get_table()
        where = self._team_memory_filter_sql(team_id, memory_id)
        with get_runtime_profiler().track("lancedb.team_get"):
            rows = await tbl.query().where(where).limit(1).to_list()
        if not rows:
            return None
        return _row_to_dict(rows[0])

    async def team_list(
        self,
        team_id: str,
        tags: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        tbl = await self._get_table()
        where = self._team_build_where(team_id, tags)
        with get_runtime_profiler().track("lancedb.team_list"):
            rows = await tbl.query().where(where).limit(limit).offset(offset).to_list()
        return [_row_to_dict(r) for r in rows]

    async def team_count(self, team_id: str, tags: list[str] | None = None) -> int:
        tbl = await self._get_table()
        where = self._team_build_where(team_id, tags)
        return await tbl.count_rows(where)

    async def team_update(
        self,
        team_id: str,
        memory_id: str,
        requester_id: str,
        *,
        content: str | None = None,
        new_vector: list[float] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        allow_owner: bool = False,
    ) -> bool:
        """Author-only update of a team memory. Owner can pass allow_owner=True.

        Returns False if the row is missing or requester isn't the author.
        Content change requires re-embedding — caller passes ``new_vector``.
        """
        existing = await self.team_get(team_id, memory_id)
        if not existing:
            return False
        if not allow_owner:
            author = (existing.get("metadata") or {}).get("author_id")
            if author and author != requester_id:
                return False

        tbl = await self._get_table()
        where = self._team_memory_filter_sql(team_id, memory_id)
        now = int(time.time())

        if new_vector is not None:
            merged_meta = {**(existing.get("metadata") or {}), **(metadata or {})}
            row = {
                "memory_id": _safe_id(memory_id),
                "user_id": existing.get("user_id"),
                "project_id": existing.get("project_id"),
                "scope": existing.get("scope", MEMORY_SCOPE_TEAM),
                "team_id": _safe_id(team_id),
                "content": content if content is not None else existing.get("content", ""),
                "tags": tags if tags is not None else existing.get("tags", []),
                "metadata": orjson.dumps(merged_meta).decode(),
                "created_at": existing.get("created_at", now),
                "updated_at": now,
                "vector": new_vector,
            }
            with get_runtime_profiler().track("lancedb.team_update"):
                await (
                    tbl.merge_insert("memory_id")
                    .when_matched_update_all()
                    .when_not_matched_insert_all()
                    .execute([row])
                )
            return True

        updates: dict[str, Any] = {"updated_at": now}
        if content is not None:
            updates["content"] = content
        if tags is not None:
            updates["tags"] = tags
        if metadata is not None:
            merged = {**(existing.get("metadata") or {}), **metadata}
            updates["metadata"] = orjson.dumps(merged).decode()
        with get_runtime_profiler().track("lancedb.team_update"):
            await tbl.update(updates=updates, where=where)
        return True

    async def team_delete(
        self,
        team_id: str,
        memory_id: str,
        requester_id: str,
        *,
        allow_owner: bool = False,
    ) -> bool:
        """Delete a team memory.

        Author is always allowed; if allow_owner=True the caller is trusted
        to be the team owner (handler decides via SQLAlchemy lookup) and the
        author check is skipped.
        """
        tbl = await self._get_table()
        existing = await self.team_get(team_id, memory_id)
        if not existing:
            return False
        if not allow_owner:
            author = (existing.get("metadata") or {}).get("author_id")
            if author and author != requester_id:
                return False
        where = self._team_memory_filter_sql(team_id, memory_id)
        with get_runtime_profiler().track("lancedb.team_delete"):
            result = await tbl.delete(where)
        deleted_rows = getattr(result, "num_deleted_rows", 0)
        return isinstance(deleted_rows, int) and deleted_rows > 0

    async def close(self) -> None:
        self._table = None
        self._db = None
        logger.debug("LanceDB connection released")
