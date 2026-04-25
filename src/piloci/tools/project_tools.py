from __future__ import annotations

"""Project management MCP tools (user-token only)."""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]{0,48}[a-zA-Z0-9]$|^[a-zA-Z0-9]$")


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class ListProjectsInput(BaseModel):
    """No parameters required."""


class CreateProjectInput(BaseModel):
    slug: Annotated[
        str,
        Field(
            description="URL-safe identifier: alphanumeric and hyphens, max 50 chars", max_length=50
        ),
    ]
    name: Annotated[str, Field(description="Human-readable project name")]
    description: Annotated[str | None, Field(description="Optional project description")] = None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*$", v):
            raise ValueError(
                "slug must start with alphanumeric and contain only alphanumerics and hyphens"
            )
        return v


class DeleteProjectInput(BaseModel):
    project: Annotated[str, Field(description="Project slug or id to delete")]
    confirm: Annotated[bool, Field(description="Must be true to confirm deletion")]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def handle_list_projects(
    args: ListProjectsInput,
    user_id: str,
    db_session: AsyncSession | None,
) -> list[dict[str, Any]]:
    """Return all projects owned by user_id."""
    if db_session is None:
        logger.debug("handle_list_projects: no db_session (M1 mode), returning []")
        return []

    try:
        from sqlalchemy import text

        result = await db_session.execute(
            text(
                "SELECT id, slug, name, description, created_at, memory_count, bytes_used"
                " FROM projects WHERE user_id = :uid ORDER BY created_at DESC"
            ),
            {"uid": user_id},
        )
        rows = result.mappings().all()
        return [dict(row) for row in rows]
    except Exception:
        logger.exception("handle_list_projects failed (user_id=%s)", user_id)
        return []


async def handle_create_project(
    args: CreateProjectInput,
    user_id: str,
    db_session: AsyncSession | None,
) -> dict[str, Any]:
    """Create a new project for user_id. Returns project_id, slug, name."""
    if db_session is None:
        logger.debug("handle_create_project: no db_session (M1 mode)")
        return {"error": "database not available"}

    try:
        from sqlalchemy import text

        # Duplicate slug check
        existing = await db_session.execute(
            text("SELECT id FROM projects WHERE user_id = :uid AND slug = :slug"),
            {"uid": user_id, "slug": args.slug},
        )
        if existing.first() is not None:
            return {"error": f"slug '{args.slug}' already exists"}

        now = datetime.now(tz=timezone.utc)
        project_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO projects (id, user_id, slug, name, description, created_at, updated_at)"
                " VALUES (:id, :uid, :slug, :name, :desc, :now, :now)"
            ),
            {
                "id": project_id,
                "uid": user_id,
                "slug": args.slug,
                "name": args.name,
                "desc": args.description,
                "now": now,
            },
        )
        await db_session.commit()
        return {"project_id": project_id, "slug": args.slug, "name": args.name}
    except Exception:
        logger.exception("handle_create_project failed (user_id=%s, slug=%s)", user_id, args.slug)
        return {"error": "failed to create project"}


async def handle_delete_project(
    args: DeleteProjectInput,
    user_id: str,
    db_session: AsyncSession | None,
) -> dict[str, Any]:
    """Delete a project. Requires confirm=True and ownership by user_id."""
    if not args.confirm:
        return {"deleted": False, "reason": "confirm must be true"}

    if db_session is None:
        logger.debug("handle_delete_project: no db_session (M1 mode)")
        return {"deleted": False, "reason": "database not available"}

    try:
        from sqlalchemy import text

        # Match by slug or id, and enforce ownership
        row = await db_session.execute(
            text(
                "SELECT id FROM projects" " WHERE user_id = :uid AND (slug = :proj OR id = :proj)"
            ),
            {"uid": user_id, "proj": args.project},
        )
        record = row.first()
        if record is None:
            return {"deleted": False, "reason": "not found"}

        await db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": record[0]},
        )
        await db_session.commit()
        return {"deleted": True, "project_id": record[0]}
    except Exception:
        logger.exception(
            "handle_delete_project failed (user_id=%s, project=%s)", user_id, args.project
        )
        return {"deleted": False, "reason": "internal error"}
