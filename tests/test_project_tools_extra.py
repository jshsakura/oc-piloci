from unittest.mock import AsyncMock, MagicMock

import pytest

from piloci.tools import project_tools


@pytest.mark.asyncio
async def test_handle_delete_project_exception():
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("db error"))

    args = MagicMock()
    args.project = "test-project"
    args.confirm = True

    result = await project_tools.handle_delete_project(args, "user-1", mock_db)
    assert result["deleted"] is False
    assert result["reason"] == "internal error"


@pytest.mark.asyncio
async def test_handle_delete_project_no_db():
    args = MagicMock()
    args.confirm = True
    result = await project_tools.handle_delete_project(args, "user-1", None)
    assert result["deleted"] is False
    assert "not available" in result["reason"]


@pytest.mark.asyncio
async def test_handle_delete_project_not_confirmed():
    args = MagicMock()
    args.confirm = False
    result = await project_tools.handle_delete_project(args, "user-1", AsyncMock())
    assert result["deleted"] is False
    assert "confirm" in result["reason"]


@pytest.mark.asyncio
async def test_handle_delete_project_not_found():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    args = MagicMock()
    args.project = "nonexistent"
    args.confirm = True

    result = await project_tools.handle_delete_project(args, "user-1", mock_db)
    assert result["deleted"] is False
    assert "not found" in result["reason"]


@pytest.mark.asyncio
async def test_handle_delete_project_success():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = ("proj-id-123",)
    mock_db.execute = AsyncMock(return_value=mock_result)

    args = MagicMock()
    args.project = "my-project"
    args.confirm = True

    result = await project_tools.handle_delete_project(args, "user-1", mock_db)
    assert result["deleted"] is True
    assert result["project_id"] == "proj-id-123"
