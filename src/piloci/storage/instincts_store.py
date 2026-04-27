from __future__ import annotations

"""piloci_instincts LanceDB table.

Atomic behavioral patterns extracted from Claude Code sessions.
Each instinct has a confidence score (0.3–0.9) that rises when the pattern
is observed again and decays when contradicted.
"""

import logging
import time
import uuid
from typing import Any

import orjson
import pyarrow as pa
from lancedb.index import BTree

from piloci.config import Settings
from piloci.storage.lancedb_store import VECTOR_SIZE, _safe_id

logger = logging.getLogger(__name__)

INSTINCTS_TABLE = "piloci_instincts"

DOMAINS = frozenset(
    [
        "code-style",
        "testing",
        "git",
        "debugging",
        "workflow",
        "architecture",
        "performance",
        "security",
        "api",
        "frontend",
        "other",
    ]
)

# ECC skill suggestions per domain
DOMAIN_SKILL_MAP: dict[str, list[str]] = {
    "git": ["git-workflow", "github-ops"],
    "testing": ["tdd-workflow", "python-testing", "verification-loop"],
    "code-style": ["coding-standards", "python-patterns"],
    "debugging": ["verification-loop", "agent-introspection-debugging"],
    "architecture": ["architecture-decision-records", "hexagonal-architecture"],
    "performance": ["python-patterns", "backend-patterns"],
    "security": ["security-review", "security-scan"],
    "workflow": ["autonomous-loops", "continuous-agent-loop"],
    "api": ["api-design", "api-connector-builder"],
    "frontend": ["frontend-patterns", "nextjs-turbopack"],
    "other": [],
}

_CONFIDENCE_INIT = 0.3
_CONFIDENCE_BOOST = 0.1
_CONFIDENCE_DECAY = 0.15
_CONFIDENCE_MAX = 0.9
_CONFIDENCE_MIN = 0.1
_SIMILARITY_MERGE_THRESHOLD = 0.85
_PROMOTE_COUNT = 3
_PROMOTE_CONFIDENCE = 0.6

_SCHEMA = pa.schema(
    [
        pa.field("instinct_id", pa.string(), nullable=False),
        pa.field("user_id", pa.string(), nullable=False),
        pa.field("project_id", pa.string(), nullable=False),
        pa.field("trigger", pa.string()),
        pa.field("action", pa.string()),
        pa.field("domain", pa.string()),
        pa.field("confidence", pa.float32()),
        pa.field("instinct_count", pa.int32()),
        pa.field("evidence", pa.string()),  # JSON array of note strings
        pa.field("created_at", pa.int64()),
        pa.field("updated_at", pa.int64()),
        pa.field("vector", pa.list_(pa.float32(), VECTOR_SIZE)),
    ]
)

_SCALAR_COLS = [
    "instinct_id",
    "user_id",
    "project_id",
    "trigger",
    "action",
    "domain",
    "confidence",
    "instinct_count",
    "evidence",
    "created_at",
    "updated_at",
]


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    evidence = row.get("evidence") or "[]"
    if isinstance(evidence, str | bytes | bytearray):
        try:
            evidence = orjson.loads(evidence)
        except Exception:
            evidence = []
    return {
        "instinct_id": row["instinct_id"],
        "user_id": row["user_id"],
        "project_id": row["project_id"],
        "trigger": row.get("trigger", ""),
        "action": row.get("action", ""),
        "domain": row.get("domain", "other"),
        "confidence": float(row.get("confidence", _CONFIDENCE_INIT)),
        "instinct_count": int(row.get("instinct_count", 1)),
        "evidence": evidence,
        "created_at": row.get("created_at", 0),
        "updated_at": row.get("updated_at", 0),
    }


class InstinctsStore:
    """LanceDB-backed instinct store. All ops enforce (user_id, project_id) isolation."""

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
            self._table = await db.create_table(INSTINCTS_TABLE, schema=_SCHEMA, exist_ok=True)
        return self._table

    async def ensure_collection(self) -> None:
        tbl = await self._get_table()
        for col, cfg in [
            ("user_id", BTree()),
            ("project_id", BTree()),
            ("domain", BTree()),
        ]:
            try:
                await tbl.create_index(col, config=cfg, replace=False)
            except Exception:
                pass
        logger.info("LanceDB table %s ready", INSTINCTS_TABLE)

    def _filter(self, user_id: str, project_id: str) -> str:
        uid = _safe_id(user_id)
        pid = _safe_id(project_id)
        return f"user_id = '{uid}' AND project_id = '{pid}'"

    async def observe(
        self,
        user_id: str,
        project_id: str,
        trigger: str,
        action: str,
        domain: str,
        evidence_note: str,
        vector: list[float],
    ) -> dict[str, Any]:
        """Upsert an instinct. Boosts confidence if similar one already exists."""
        tbl = await self._get_table()
        where = self._filter(user_id, project_id)
        now = int(time.time())

        # Vector search for similar existing instinct
        existing_rows = await (
            tbl.vector_search(vector).distance_type("cosine").where(where).limit(1).to_list()
        )

        if existing_rows:
            distance = existing_rows[0].get("_distance", 1.0)
            similarity = 1.0 - distance
            if similarity >= _SIMILARITY_MERGE_THRESHOLD:
                existing = _row_to_dict(existing_rows[0])
                new_conf = min(_CONFIDENCE_MAX, existing["confidence"] + _CONFIDENCE_BOOST)
                new_count = existing["instinct_count"] + 1
                evidence_list = existing["evidence"]
                if evidence_note and len(evidence_list) < 10:
                    evidence_list = [*evidence_list, evidence_note]
                await tbl.update(
                    updates={
                        "confidence": new_conf,
                        "instinct_count": new_count,
                        "evidence": orjson.dumps(evidence_list).decode(),
                        "updated_at": now,
                    },
                    where=f"{where} AND instinct_id = '{_safe_id(existing['instinct_id'])}'",
                )
                existing["confidence"] = new_conf
                existing["instinct_count"] = new_count
                existing["evidence"] = evidence_list
                existing["updated_at"] = now
                return existing

        # New instinct
        instinct_id = str(uuid.uuid4())
        row = {
            "instinct_id": instinct_id,
            "user_id": user_id,
            "project_id": project_id,
            "trigger": trigger,
            "action": action,
            "domain": domain if domain in DOMAINS else "other",
            "confidence": _CONFIDENCE_INIT,
            "instinct_count": 1,
            "evidence": orjson.dumps([evidence_note] if evidence_note else []).decode(),
            "created_at": now,
            "updated_at": now,
            "vector": vector,
        }
        await (
            tbl.merge_insert("instinct_id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute([row])
        )
        return _row_to_dict(row)

    async def contradict(
        self,
        user_id: str,
        project_id: str,
        instinct_id: str,
    ) -> bool:
        """Decay confidence when user contradicts an instinct."""
        tbl = await self._get_table()
        where = f"{self._filter(user_id, project_id)} AND instinct_id = '{_safe_id(instinct_id)}'"
        rows = await tbl.query().where(where).select(_SCALAR_COLS).limit(1).to_list()
        if not rows:
            return False
        existing = _row_to_dict(rows[0])
        new_conf = max(_CONFIDENCE_MIN, existing["confidence"] - _CONFIDENCE_DECAY)
        await tbl.update(
            updates={"confidence": new_conf, "updated_at": int(time.time())},
            where=where,
        )
        return True

    async def list_instincts(
        self,
        user_id: str,
        project_id: str,
        domain: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        tbl = await self._get_table()
        where = self._filter(user_id, project_id)
        if domain:
            safe_domain = domain.replace("'", "''")
            where += f" AND domain = '{safe_domain}'"
        if min_confidence > 0.0:
            where += f" AND confidence >= {min_confidence}"
        rows = await tbl.query().where(where).select(_SCALAR_COLS).limit(limit).to_list()
        results = [_row_to_dict(r) for r in rows]
        results.sort(key=lambda x: x["confidence"] * x["instinct_count"], reverse=True)
        return results

    async def get_recommendations(
        self,
        user_id: str,
        project_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return promoted instincts with matched ECC skill suggestions."""
        instincts = await self.list_instincts(
            user_id=user_id,
            project_id=project_id,
            min_confidence=_PROMOTE_CONFIDENCE,
            limit=limit * 3,
        )
        promoted = [
            i
            for i in instincts
            if i["instinct_count"] >= _PROMOTE_COUNT and i["confidence"] >= _PROMOTE_CONFIDENCE
        ][:limit]

        recommendations = []
        for inst in promoted:
            domain = inst.get("domain", "other")
            skills = DOMAIN_SKILL_MAP.get(domain, [])
            recommendations.append(
                {
                    **inst,
                    "suggested_skills": skills,
                }
            )
        return recommendations

    async def delete_instinct(self, user_id: str, project_id: str, instinct_id: str) -> bool:
        tbl = await self._get_table()
        where = f"{self._filter(user_id, project_id)} AND instinct_id = '{_safe_id(instinct_id)}'"
        result = await tbl.delete(where)
        deleted = getattr(result, "num_deleted_rows", 0)
        return isinstance(deleted, int) and deleted > 0

    async def clear_project(self, user_id: str, project_id: str) -> int:
        tbl = await self._get_table()
        where = self._filter(user_id, project_id)
        result = await tbl.delete(where)
        deleted = getattr(result, "num_deleted_rows", 0)
        return deleted if isinstance(deleted, int) else 0

    async def close(self) -> None:
        self._table = None
        self._db = None
