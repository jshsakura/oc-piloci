"""User-scoped export/import for piloci data.

Produces a single zip containing manifest, project rows, memories (parquet
including vectors), and gemma-summarised profiles. Import merges the archive
into the currently logged-in user, renaming colliding project slugs and
re-embedding memories when the source archive used a different embed model.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import orjson
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from piloci.config import Settings
from piloci.db.models import Project, UserProfile
from piloci.db.session import async_session
from piloci.storage.lancedb_store import VECTOR_SIZE, MemoryStore, MemoryWrite

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _safe_id(value: str) -> str:
    """Defense-in-depth: reject anything containing characters that could break
    out of a LanceDB where-clause string literal (quotes, semicolons,
    whitespace, backslashes). UUIDs and our internal `user-*`/`proj-*` ids pass;
    attacker-shaped values do not."""
    if not isinstance(value, str) or not _SAFE_ID_RE.match(value):
        raise ValueError(f"unsafe identifier for query: {value!r}")
    return value


logger = logging.getLogger(__name__)

ARCHIVE_VERSION = 1
MANIFEST_NAME = "manifest.json"
PROJECTS_NAME = "projects.json"
MEMORIES_NAME = "memories.parquet"
PROFILES_NAME = "profiles.json"

EmbedFn = Callable[[str], Awaitable[list[float]]]


class ArchiveError(Exception):
    """Raised when the import archive is malformed or rejected."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class ImportSummary:
    projects_imported: int
    projects_renamed: int
    memories_imported: int
    profiles_imported: int
    re_embedded: bool


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _sha256_hex(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _project_to_dict(p: Project) -> dict[str, Any]:
    return {
        "id": p.id,
        "slug": p.slug,
        "name": p.name,
        "description": p.description,
        "memory_count": p.memory_count,
        "bytes_used": p.bytes_used,
        "created_at": (
            p.created_at.replace(tzinfo=timezone.utc).isoformat()
            if p.created_at.tzinfo is None
            else p.created_at.isoformat()
        ),
        "updated_at": (
            p.updated_at.replace(tzinfo=timezone.utc).isoformat()
            if p.updated_at.tzinfo is None
            else p.updated_at.isoformat()
        ),
    }


async def _load_user_projects(user_id: str) -> list[Project]:
    async with async_session() as db:
        result = await db.execute(
            select(Project).where(Project.user_id == user_id).order_by(Project.created_at)
        )
        return list(result.scalars().all())


async def _load_user_profiles(user_id: str) -> list[dict[str, Any]]:
    async with async_session() as db:
        result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        rows = list(result.scalars().all())
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "project_id": row.project_id,
                "profile_json": row.profile_json,
                "updated_at": (
                    row.updated_at.replace(tzinfo=timezone.utc).isoformat()
                    if row.updated_at.tzinfo is None
                    else row.updated_at.isoformat()
                ),
            }
        )
    return out


_MEMORIES_SCHEMA = pa.schema(
    [
        pa.field("memory_id", pa.string()),
        pa.field("project_id", pa.string()),
        pa.field("content", pa.string()),
        pa.field("tags", pa.list_(pa.string())),
        pa.field("metadata", pa.string()),
        pa.field("created_at", pa.int64()),
        pa.field("updated_at", pa.int64()),
        pa.field("vector", pa.list_(pa.float32())),
    ]
)


def _coerce_metadata_str(value: Any) -> str:
    """Return metadata as a JSON string (the column type stored in parquet)."""
    if isinstance(value, (bytes, bytearray)):
        try:
            parsed = orjson.loads(value)
        except (orjson.JSONDecodeError, ValueError):
            return "{}"
        return orjson.dumps(parsed).decode() if isinstance(parsed, dict) else "{}"
    if isinstance(value, str):
        try:
            parsed = orjson.loads(value)
        except (orjson.JSONDecodeError, ValueError):
            return "{}"
        return orjson.dumps(parsed).decode() if isinstance(parsed, dict) else "{}"
    if isinstance(value, dict):
        return orjson.dumps(value).decode()
    return "{}"


async def _build_memories_parquet(
    user_id: str, projects: list[Project], store: MemoryStore
) -> tuple[bytes, int]:
    """Stream memories+vectors directly into a single pyarrow table and return
    (parquet_bytes, row_count). Avoids holding two full intermediate dict lists
    in memory at the same time on Pi 5."""
    if not projects:
        empty = pa.Table.from_pydict(
            {f.name: [] for f in _MEMORIES_SCHEMA}, schema=_MEMORIES_SCHEMA
        )
        sink = io.BytesIO()
        pq.write_table(empty, sink, compression="zstd")
        return sink.getvalue(), 0

    tbl = await store._get_table()  # noqa: SLF001 — internal use for export only
    safe_user = _safe_id(user_id)
    safe_pids = ", ".join(f"'{_safe_id(p.id)}'" for p in projects)
    where = f"user_id = '{safe_user}' AND project_id IN ({safe_pids})"
    rows = await tbl.query().where(where).to_list()

    columns: dict[str, list[Any]] = {f.name: [] for f in _MEMORIES_SCHEMA}
    for r in rows:
        columns["memory_id"].append(str(r.get("memory_id") or ""))
        columns["project_id"].append(str(r.get("project_id") or ""))
        columns["content"].append(r.get("content") or "")
        columns["tags"].append([str(t) for t in (r.get("tags") or [])])
        columns["metadata"].append(_coerce_metadata_str(r.get("metadata")))
        columns["created_at"].append(int(r.get("created_at") or 0))
        columns["updated_at"].append(int(r.get("updated_at") or 0))
        columns["vector"].append([float(v) for v in (r.get("vector") or [])])

    table = pa.Table.from_pydict(columns, schema=_MEMORIES_SCHEMA)
    sink = io.BytesIO()
    pq.write_table(table, sink, compression="zstd")
    return sink.getvalue(), table.num_rows


async def build_export_archive(
    *,
    user_id: str,
    store: MemoryStore,
    settings: Settings,
    piloci_version: str,
) -> bytes:
    """Assemble an in-memory zip archive of one user's data.

    Includes *all* of the user's memories — coding facts AND private
    ``feedback`` entries (frustration, praise, sarcasm) used by the weekly
    self-retrospective. The caller is the data subject themselves, so this
    is the right default for a "give me everything" export. Callers that
    intend to hand the archive to a third party (team upload, support
    ticket attachment) should filter the memories.parquet client-side or
    use piloci.storage.privacy.is_private_memory to drop them before
    forwarding.
    """
    _safe_id(user_id)
    projects = await _load_user_projects(user_id)
    profiles = await _load_user_profiles(user_id)
    memories_payload, memories_count = await _build_memories_parquet(user_id, projects, store)

    projects_payload = orjson.dumps([_project_to_dict(p) for p in projects])
    profiles_payload = orjson.dumps(profiles)

    manifest = {
        "archive_version": ARCHIVE_VERSION,
        "piloci_version": piloci_version,
        "embed_model": settings.embed_model,
        "vector_size": VECTOR_SIZE,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "counts": {
            "projects": len(projects),
            "memories": memories_count,
            "profiles": len(profiles),
        },
        "checksums": {
            PROJECTS_NAME: _sha256_hex(projects_payload),
            MEMORIES_NAME: _sha256_hex(memories_payload),
            PROFILES_NAME: _sha256_hex(profiles_payload),
        },
    }

    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, orjson.dumps(manifest))
        zf.writestr(PROJECTS_NAME, projects_payload)
        zf.writestr(MEMORIES_NAME, memories_payload)
        zf.writestr(PROFILES_NAME, profiles_payload)
    return sink.getvalue()


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?$")


def _normalize_slug(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    candidate = raw.strip().lower()
    if not _SLUG_RE.match(candidate):
        return None
    return candidate


def _parse_archive(
    archive: bytes,
) -> tuple[dict[str, Any], list[dict[str, Any]], pa.Table, list[dict[str, Any]]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"invalid zip archive: {exc}") from exc

    with zf:
        names = set(zf.namelist())
        if MANIFEST_NAME not in names:
            raise ArchiveError("archive missing manifest.json")
        manifest_raw = zf.read(MANIFEST_NAME)
        try:
            manifest = orjson.loads(manifest_raw)
        except orjson.JSONDecodeError as exc:
            raise ArchiveError(f"manifest.json is not valid JSON: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ArchiveError("manifest.json must be a JSON object")

        archive_version = manifest.get("archive_version")
        if archive_version != ARCHIVE_VERSION:
            raise ArchiveError(
                f"unsupported archive_version {archive_version!r} (expected {ARCHIVE_VERSION})"
            )

        projects_raw = zf.read(PROJECTS_NAME) if PROJECTS_NAME in names else b"[]"
        projects = orjson.loads(projects_raw)
        if not isinstance(projects, list):
            raise ArchiveError("projects.json must be a JSON list")

        if MEMORIES_NAME in names:
            memories_table = pq.read_table(io.BytesIO(zf.read(MEMORIES_NAME)))
        else:
            memories_table = pa.Table.from_pydict(
                {f.name: [] for f in _MEMORIES_SCHEMA}, schema=_MEMORIES_SCHEMA
            )

        profiles_raw = zf.read(PROFILES_NAME) if PROFILES_NAME in names else b"[]"
        profiles = orjson.loads(profiles_raw)
        if not isinstance(profiles, list):
            raise ArchiveError("profiles.json must be a JSON list")

    return manifest, projects, memories_table, profiles


async def _existing_slugs_for_user(user_id: str) -> set[str]:
    async with async_session() as db:
        rows = await db.execute(select(Project.slug).where(Project.user_id == user_id))
        return {row[0] for row in rows.all()}


def _next_free_slug(base: str, taken: set[str]) -> tuple[str, bool]:
    """Return (slug, was_renamed). Picks ``base`` if free, else suffixes."""
    if base not in taken:
        return base, False
    candidate = f"{base}-imported"
    n = 1
    while candidate in taken:
        n += 1
        candidate = f"{base}-imported-{n}"
    return candidate, True


def _normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(t) for t in value]
    return []


def _normalize_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            parsed = orjson.loads(value)
        except (orjson.JSONDecodeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(value, str):
        try:
            parsed = orjson.loads(value)
        except (orjson.JSONDecodeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def import_archive(
    archive: bytes,
    *,
    user_id: str,
    store: MemoryStore,
    settings: Settings,
    embed_one_fn: EmbedFn,
    allow_reembed: bool = False,
) -> ImportSummary:
    """Merge an export archive into the given user's account."""
    manifest, projects_payload, memories_table, profiles_payload = _parse_archive(archive)

    embed_model_in_archive = manifest.get("embed_model")
    vector_size_in_archive = manifest.get("vector_size")

    needs_reembed = (
        embed_model_in_archive != settings.embed_model or vector_size_in_archive != VECTOR_SIZE
    )
    if needs_reembed and not allow_reembed:
        raise ArchiveError(
            (
                f"archive embed model {embed_model_in_archive!r}/{vector_size_in_archive} "
                f"does not match server {settings.embed_model!r}/{VECTOR_SIZE}; "
                "retry with reembed=true to re-embed using current model"
            ),
            status=409,
        )

    # ------------------------------------------------------------------
    # Resolve project slug collisions, build (old_id -> new_id) map
    # ------------------------------------------------------------------
    existing_slugs = await _existing_slugs_for_user(user_id)
    rename_count = 0
    project_id_map: dict[str, str] = {}
    new_project_rows: list[Project] = []
    now = datetime.now(timezone.utc)

    for raw in projects_payload:
        if not isinstance(raw, dict):
            continue
        old_id = raw.get("id")
        slug = _normalize_slug(raw.get("slug"))
        name = raw.get("name") if isinstance(raw.get("name"), str) else None
        if not isinstance(old_id, str) or not slug or not name:
            continue
        chosen_slug, was_renamed = _next_free_slug(slug, existing_slugs)
        if was_renamed:
            rename_count += 1
        existing_slugs.add(chosen_slug)
        new_id = str(uuid.uuid4())
        project_id_map[old_id] = new_id
        description = raw.get("description")
        new_project_rows.append(
            Project(
                id=new_id,
                user_id=user_id,
                slug=chosen_slug,
                name=name,
                description=description if isinstance(description, str) else None,
                created_at=now,
                updated_at=now,
            )
        )

    if new_project_rows:
        async with async_session() as db:
            for row in new_project_rows:
                db.add(row)
            await db.commit()

    # ------------------------------------------------------------------
    # Group memories by *new* project_id and write in batches
    # ------------------------------------------------------------------
    memories_columns = memories_table.to_pydict()
    total = memories_table.num_rows
    grouped: dict[str, list[MemoryWrite]] = {}

    for i in range(total):
        old_pid = memories_columns["project_id"][i]
        new_pid = project_id_map.get(old_pid)
        if new_pid is None:
            continue
        content = memories_columns["content"][i] or ""
        if needs_reembed:
            if not content.strip():
                continue
            vector = await embed_one_fn(content)
        else:
            vector = [float(v) for v in (memories_columns["vector"][i] or [])]
            if len(vector) != VECTOR_SIZE:
                continue
        tags = _normalize_tags(memories_columns["tags"][i])
        metadata = _normalize_metadata(memories_columns["metadata"][i])
        grouped.setdefault(new_pid, []).append(
            {
                "content": content,
                "vector": vector,
                "tags": tags,
                "metadata": metadata,
            }
        )

    memories_imported = 0
    for new_pid, batch in grouped.items():
        if not batch:
            continue
        ids = await store.save_many(user_id=user_id, project_id=new_pid, memories=batch)
        memories_imported += len(ids)

    # ------------------------------------------------------------------
    # Profiles — re-attach to translated project IDs and upsert
    # ------------------------------------------------------------------
    profiles_imported = 0
    for raw in profiles_payload:
        if not isinstance(raw, dict):
            continue
        old_pid = raw.get("project_id")
        new_pid = project_id_map.get(old_pid) if isinstance(old_pid, str) else None
        if new_pid is None:
            continue
        profile_json = raw.get("profile_json")
        if not isinstance(profile_json, str):
            continue
        stmt = sqlite_insert(UserProfile).values(
            user_id=user_id,
            project_id=new_pid,
            profile_json=profile_json,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "project_id"],
            set_={"profile_json": profile_json, "updated_at": now},
        )
        async with async_session() as db:
            await db.execute(stmt)
            await db.commit()
        profiles_imported += 1

    return ImportSummary(
        projects_imported=len(new_project_rows),
        projects_renamed=rename_count,
        memories_imported=memories_imported,
        profiles_imported=profiles_imported,
        re_embedded=needs_reembed,
    )
