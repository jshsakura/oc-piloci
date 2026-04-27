"""Tests for InstinctsStore: observe, confidence boost/decay, recommend."""

from __future__ import annotations

import pytest

from piloci.config import Settings
from piloci.storage.instincts_store import (
    _CONFIDENCE_BOOST,
    _CONFIDENCE_DECAY,
    _CONFIDENCE_INIT,
    VECTOR_SIZE,
    InstinctsStore,
)

_USER = "user-instinct-test-001"
_PROJECT = "proj-instinct-test-001"
# Two orthogonal unit vectors — cosine similarity ≈ 0, distance ≈ 1
_VEC = [1.0] * (VECTOR_SIZE // 2) + [0.0] * (VECTOR_SIZE // 2)
_VEC_DIFF = [0.0] * (VECTOR_SIZE // 2) + [1.0] * (VECTOR_SIZE // 2)


@pytest.fixture
async def instincts_store(tmp_path):
    s = Settings(
        lancedb_path=tmp_path / "lancedb",
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
    )
    store = InstinctsStore(s)
    await store.ensure_collection()
    yield store
    await store.close()


# ---------------------------------------------------------------------------
# observe — new instinct
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observe_creates_new_instinct(instincts_store):
    result = await instincts_store.observe(
        user_id=_USER,
        project_id=_PROJECT,
        trigger="when writing tests",
        action="use pytest-asyncio",
        domain="testing",
        evidence_note="user corrected to pytest-asyncio",
        vector=_VEC,
    )
    assert result["instinct_id"]
    assert result["confidence"] == pytest.approx(_CONFIDENCE_INIT)
    assert result["instinct_count"] == 1
    assert result["domain"] == "testing"
    assert result["trigger"] == "when writing tests"


# ---------------------------------------------------------------------------
# observe — similar instinct gets confidence boost
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observe_boosts_similar_instinct(instincts_store):
    first = await instincts_store.observe(
        user_id=_USER,
        project_id=_PROJECT,
        trigger="when writing tests",
        action="use pytest-asyncio",
        domain="testing",
        evidence_note="first observation",
        vector=_VEC,
    )
    second = await instincts_store.observe(
        user_id=_USER,
        project_id=_PROJECT,
        trigger="when writing async tests",
        action="use pytest-asyncio decorator",
        domain="testing",
        evidence_note="second observation",
        vector=_VEC,  # same vector → high similarity
    )
    # Should merge into the same instinct
    assert second["instinct_id"] == first["instinct_id"]
    assert second["confidence"] == pytest.approx(_CONFIDENCE_INIT + _CONFIDENCE_BOOST)
    assert second["instinct_count"] == 2
    assert len(second["evidence"]) == 2


# ---------------------------------------------------------------------------
# observe — different vector creates a new instinct
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observe_different_vector_creates_new(instincts_store):
    await instincts_store.observe(
        user_id=_USER,
        project_id=_PROJECT,
        trigger="when writing tests",
        action="use pytest-asyncio",
        domain="testing",
        evidence_note="obs1",
        vector=_VEC,
    )
    second = await instincts_store.observe(
        user_id=_USER,
        project_id=_PROJECT,
        trigger="when pushing code",
        action="run pre-commit",
        domain="git",
        evidence_note="obs2",
        vector=_VEC_DIFF,
    )
    assert second["domain"] == "git"
    all_instincts = await instincts_store.list_instincts(_USER, _PROJECT)
    assert len(all_instincts) == 2


# ---------------------------------------------------------------------------
# contradict — decays confidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contradict_decays_confidence(instincts_store):
    inst = await instincts_store.observe(
        user_id=_USER,
        project_id=_PROJECT,
        trigger="when writing tests",
        action="use pytest-asyncio",
        domain="testing",
        evidence_note="obs",
        vector=_VEC,
    )
    ok = await instincts_store.contradict(_USER, _PROJECT, inst["instinct_id"])
    assert ok is True

    rows = await instincts_store.list_instincts(_USER, _PROJECT)
    assert rows[0]["confidence"] == pytest.approx(_CONFIDENCE_INIT - _CONFIDENCE_DECAY)


# ---------------------------------------------------------------------------
# get_recommendations — only returns promoted instincts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_recommendations_requires_promotion(instincts_store):
    # Observe 4 times to reach promotion threshold
    for i in range(4):
        await instincts_store.observe(
            user_id=_USER,
            project_id=_PROJECT,
            trigger="when writing tests",
            action="use pytest-asyncio",
            domain="testing",
            evidence_note=f"obs{i}",
            vector=_VEC,
        )

    recs = await instincts_store.get_recommendations(_USER, _PROJECT)
    assert len(recs) >= 1
    assert "suggested_skills" in recs[0]
    assert "tdd-workflow" in recs[0]["suggested_skills"]


# ---------------------------------------------------------------------------
# isolation — different user cannot see instincts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_isolation(instincts_store):
    await instincts_store.observe(
        user_id=_USER,
        project_id=_PROJECT,
        trigger="when writing tests",
        action="use pytest-asyncio",
        domain="testing",
        evidence_note="obs",
        vector=_VEC,
    )
    other_instincts = await instincts_store.list_instincts("other-user", _PROJECT)
    assert other_instincts == []


# ---------------------------------------------------------------------------
# domain unknown → normalized to "other"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_domain_normalized(instincts_store):
    inst = await instincts_store.observe(
        user_id=_USER,
        project_id=_PROJECT,
        trigger="do something",
        action="do it",
        domain="made-up-domain",
        evidence_note="",
        vector=_VEC,
    )
    assert inst["domain"] == "other"
