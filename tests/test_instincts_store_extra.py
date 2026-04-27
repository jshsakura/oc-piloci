from unittest.mock import AsyncMock, MagicMock

import pytest

from piloci.storage import instincts_store

_USER = "00000000-0000-0000-0000-000000000001"
_PROJECT = "00000000-0000-0000-0000-000000000002"


@pytest.fixture
def mock_istore():
    store = MagicMock(spec=instincts_store.InstinctsStore)
    store.delete_instinct = AsyncMock()
    store.clear_project = AsyncMock()
    return store


@pytest.mark.asyncio
async def test_delete_instinct_existing(mock_istore):
    mock_istore.delete_instinct.return_value = True
    result = await mock_istore.delete_instinct(_USER, _PROJECT, "inst-1")
    assert result is True


@pytest.mark.asyncio
async def test_delete_instinct_nonexistent(mock_istore):
    mock_istore.delete_instinct.return_value = False
    result = await mock_istore.delete_instinct(_USER, _PROJECT, "nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_clear_project_with_data(mock_istore):
    mock_istore.clear_project.return_value = 3
    count = await mock_istore.clear_project(_USER, _PROJECT)
    assert count == 3


@pytest.mark.asyncio
async def test_clear_project_empty(mock_istore):
    mock_istore.clear_project.return_value = 0
    count = await mock_istore.clear_project(_USER, _PROJECT)
    assert count == 0
