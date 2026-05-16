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
        from sqlalchemy import select

        from piloci.db.models import Project

        result = await db_session.execute(
            select(
                Project.id,
                Project.slug,
                Project.name,
                Project.description,
                Project.created_at,
                Project.memory_count,
                Project.bytes_used,
            )
            .where(Project.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
        return [dict(row) for row in result.mappings().all()]
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
        from sqlalchemy import select

        from piloci.db.models import Project

        existing = await db_session.execute(
            select(Project.id).where(Project.user_id == user_id, Project.slug == args.slug)
        )
        if existing.first() is not None:
            return {"error": f"slug '{args.slug}' already exists"}

        now = datetime.now(tz=timezone.utc)
        project = Project(
            id=str(uuid.uuid4()),
            user_id=user_id,
            slug=args.slug,
            name=args.name,
            description=args.description,
            created_at=now,
            updated_at=now,
        )
        db_session.add(project)
        await db_session.commit()
        return {"project_id": project.id, "slug": project.slug, "name": project.name}
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
        from sqlalchemy import delete as sql_delete
        from sqlalchemy import or_, select

        from piloci.db.models import Project

        # Match by slug or id, and enforce ownership.
        row = await db_session.execute(
            select(Project.id).where(
                Project.user_id == user_id,
                or_(Project.slug == args.project, Project.id == args.project),
            )
        )
        record = row.first()
        if record is None:
            return {"deleted": False, "reason": "not found"}

        project_id = record[0]
        await db_session.execute(sql_delete(Project).where(Project.id == project_id))
        await db_session.commit()
        return {"deleted": True, "project_id": project_id}
    except Exception:
        logger.exception(
            "handle_delete_project failed (user_id=%s, project=%s)", user_id, args.project
        )
        return {"deleted": False, "reason": "internal error"}
