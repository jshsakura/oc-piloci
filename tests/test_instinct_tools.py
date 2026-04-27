"""Tests for tools/instinct_tools.py — handle_recommend & handle_contradict."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from piloci.tools.instinct_tools import (
    ContradictInput,
    RecommendInput,
    handle_contradict,
    handle_recommend,
)

USER = "user-1"
PROJECT = "proj-1"


def _mock_store():
    store = AsyncMock()
    store.list_instincts.return_value = [
        {"id": "i1", "trigger": "t", "action": "a", "domain": "code-style", "confidence": 0.8},
    ]
    store.get_recommendations.return_value = [
        {"id": "i2", "trigger": "t2", "action": "a2", "domain": "testing", "confidence": 0.9},
    ]
    store.contradict.return_value = True
    return store


# ---------------------------------------------------------------------------
# handle_recommend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_default_returns_list_instincts():
    store = _mock_store()
    args = RecommendInput()

    result = await handle_recommend(args, USER, PROJECT, store)

    assert result["total"] == 1
    assert result["instincts"][0]["id"] == "i1"
    assert "suggested_skills" in result["instincts"][0]
    assert "hint" in result
    store.list_instincts.assert_called_once_with(
        user_id=USER, project_id=PROJECT, domain=None, min_confidence=0.0, limit=10
    )


@pytest.mark.asyncio
async def test_recommend_with_domain_filter():
    store = _mock_store()
    args = RecommendInput(domain="testing", min_confidence=0.5)

    await handle_recommend(args, USER, PROJECT, store)

    store.list_instincts.assert_called_once_with(
        user_id=USER, project_id=PROJECT, domain="testing", min_confidence=0.5, limit=10
    )


@pytest.mark.asyncio
async def test_recommend_promoted_only():
    store = _mock_store()
    args = RecommendInput(promoted_only=True)

    result = await handle_recommend(args, USER, PROJECT, store)

    store.get_recommendations.assert_called_once_with(user_id=USER, project_id=PROJECT, limit=10)
    assert result["total"] == 1
    # promoted_only branch does NOT add suggested_skills
    assert "suggested_skills" not in result["instincts"][0]


@pytest.mark.asyncio
async def test_recommend_custom_limit():
    store = _mock_store()
    args = RecommendInput(limit=5)

    await handle_recommend(args, USER, PROJECT, store)

    store.list_instincts.assert_called_once_with(
        user_id=USER, project_id=PROJECT, domain=None, min_confidence=0.0, limit=5
    )


# ---------------------------------------------------------------------------
# handle_contradict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contradict_success():
    store = _mock_store()
    args = ContradictInput(instinct_id="i1")

    result = await handle_contradict(args, USER, PROJECT, store)

    assert result["success"] is True
    assert result["action"] == "confidence_decayed"
    assert result["instinct_id"] == "i1"
    store.contradict.assert_called_once_with(user_id=USER, project_id=PROJECT, instinct_id="i1")


@pytest.mark.asyncio
async def test_contradict_not_found():
    store = _mock_store()
    store.contradict.return_value = False
    args = ContradictInput(instinct_id="missing")

    result = await handle_contradict(args, USER, PROJECT, store)

    assert result["success"] is False
    assert "not found" in result["error"]
