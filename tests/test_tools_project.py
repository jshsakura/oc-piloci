from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from piloci.tools.project_tools import (
    CreateProjectInput,
    DeleteProjectInput,
    ListProjectsInput,
    handle_create_project,
    handle_delete_project,
    handle_list_projects,
)

USER = "user-abc"


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_projects_no_db_returns_empty_list() -> None:
    args = ListProjectsInput()
    result = await handle_list_projects(args, USER, db_session=None)
    assert result == []


@pytest.mark.asyncio
async def test_list_projects_with_db_returns_rows() -> None:
    mock_row = {"id": "p1", "slug": "my-proj", "name": "My Project", "description": None,
                "created_at": "2026-01-01", "memory_count": 0, "bytes_used": 0}

    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = [mock_row]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    args = ListProjectsInput()
    result = await handle_list_projects(args, USER, db_session=db)
    assert len(result) == 1
    assert result[0]["slug"] == "my-proj"


# ---------------------------------------------------------------------------
# create_project
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_project_no_db_returns_error() -> None:
    args = CreateProjectInput(slug="test-proj", name="Test")
    result = await handle_create_project(args, USER, db_session=None)
    assert "error" in result


@pytest.mark.asyncio
async def test_create_project_success() -> None:
    # First execute (duplicate check) returns no row; second (insert) succeeds.
    no_row_result = MagicMock()
    no_row_result.first.return_value = None

    db = AsyncMock()
    db.execute = AsyncMock(return_value=no_row_result)
    db.commit = AsyncMock()

    args = CreateProjectInput(slug="new-proj", name="New Project", description="desc")
    result = await handle_create_project(args, USER, db_session=db)

    assert "error" not in result
    assert result["slug"] == "new-proj"
    assert result["name"] == "New Project"
    assert "project_id" in result


@pytest.mark.asyncio
async def test_create_project_duplicate_slug() -> None:
    existing_result = MagicMock()
    existing_result.first.return_value = ("existing-id",)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=existing_result)

    args = CreateProjectInput(slug="dup-slug", name="Dup")
    result = await handle_create_project(args, USER, db_session=db)

    assert "error" in result
    assert "dup-slug" in result["error"]


# ---------------------------------------------------------------------------
# delete_project
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_project_confirm_false() -> None:
    args = DeleteProjectInput(project="some-proj", confirm=False)
    result = await handle_delete_project(args, USER, db_session=None)
    assert result["deleted"] is False
    assert result["reason"] == "confirm must be true"


@pytest.mark.asyncio
async def test_delete_project_not_found() -> None:
    not_found_result = MagicMock()
    not_found_result.first.return_value = None

    db = AsyncMock()
    db.execute = AsyncMock(return_value=not_found_result)

    args = DeleteProjectInput(project="ghost-proj", confirm=True)
    result = await handle_delete_project(args, USER, db_session=db)
    assert result["deleted"] is False
    assert result["reason"] == "not found"


@pytest.mark.asyncio
async def test_delete_project_success() -> None:
    found_result = MagicMock()
    found_result.first.return_value = ("proj-id-123",)

    delete_result = MagicMock()

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[found_result, delete_result])
    db.commit = AsyncMock()

    args = DeleteProjectInput(project="my-proj", confirm=True)
    result = await handle_delete_project(args, USER, db_session=db)
    assert result["deleted"] is True
    assert result["project_id"] == "proj-id-123"


@pytest.mark.asyncio
async def test_delete_project_no_db_with_confirm() -> None:
    args = DeleteProjectInput(project="some-proj", confirm=True)
    result = await handle_delete_project(args, USER, db_session=None)
    assert result["deleted"] is False
    assert "database" in result["reason"]
