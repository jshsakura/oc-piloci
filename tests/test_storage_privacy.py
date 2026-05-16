from __future__ import annotations

from types import SimpleNamespace

from piloci.curator.extraction import DistilledInstinct, DistilledMemory
from piloci.storage.privacy import (
    PRIVATE_INSTINCT_DOMAINS,
    PRIVATE_MEMORY_CATEGORIES,
    is_private_instinct,
    is_private_memory,
)


def test_private_categories_include_feedback() -> None:
    assert "feedback" in PRIVATE_MEMORY_CATEGORIES


def test_private_domains_include_reaction() -> None:
    assert "reaction" in PRIVATE_INSTINCT_DOMAINS


def test_is_private_memory_dict_with_feedback() -> None:
    assert is_private_memory({"category": "feedback"}) is True


def test_is_private_memory_dict_with_other_category() -> None:
    for cat in ("fact", "decision", "preference", "pattern", "error", "solution"):
        assert is_private_memory({"category": cat}) is False


def test_is_private_memory_handles_missing_or_garbage() -> None:
    assert is_private_memory({}) is False
    assert is_private_memory({"category": None}) is False
    assert is_private_memory({"category": 42}) is False
    assert is_private_memory(None) is False


def test_is_private_memory_accepts_dataclass() -> None:
    mem = DistilledMemory(content="기분 좋다", category="feedback")
    assert is_private_memory(mem) is True
    coding_fact = DistilledMemory(content="uses argon2", category="preference")
    assert is_private_memory(coding_fact) is False


def test_is_private_memory_accepts_simplenamespace_row() -> None:
    # LanceDB rows come back as something we can `.get`/getattr on.
    row = SimpleNamespace(category="feedback")
    assert is_private_memory(row) is True


def test_is_private_instinct_reaction_domain() -> None:
    assert is_private_instinct({"domain": "reaction"}) is True


def test_is_private_instinct_other_domains() -> None:
    for dom in ("code-style", "testing", "git", "debugging", "workflow", "other"):
        assert is_private_instinct({"domain": dom}) is False


def test_is_private_instinct_accepts_dataclass() -> None:
    inst = DistilledInstinct(
        trigger="build keeps failing on Pi",
        action="user gets frustrated",
        domain="reaction",
    )
    assert is_private_instinct(inst) is True
    coding_inst = DistilledInstinct(trigger="before commit", action="run pre-commit", domain="git")
    assert is_private_instinct(coding_inst) is False
