from __future__ import annotations

from unittest.mock import patch

import pytest

from piloci.curator.extraction import (
    DistilledInstinct,
    DistilledMemory,
    DistilledSession,
    _merge_distilled,
    _split_into_chunks,
    _truncate,
    _validate_instinct,
    _validate_memory,
    extract_session,
    extract_session_multipass,
)


def test_validate_memory_accepts_well_formed() -> None:
    mem = _validate_memory(
        {"content": "user prefers argon2", "tags": ["security", "auth"], "category": "preference"}
    )
    assert mem is not None
    assert mem.content == "user prefers argon2"
    assert mem.tags == ["security", "auth"]
    assert mem.category == "preference"


def test_validate_memory_rejects_missing_content() -> None:
    assert _validate_memory({"content": "", "tags": []}) is None
    assert _validate_memory({"content": "   "}) is None
    assert _validate_memory({}) is None
    assert _validate_memory("not a dict") is None


def test_validate_memory_caps_tags() -> None:
    mem = _validate_memory(
        {"content": "x", "tags": ["a", "b", "c", "d", "e", "f", "g"], "category": "fact"}
    )
    assert mem is not None
    assert len(mem.tags) == 5


def test_validate_instinct_accepts_well_formed() -> None:
    inst = _validate_instinct(
        {
            "trigger": "before commit",
            "action": "run pre-commit",
            "domain": "git",
            "evidence": "user kept asking for it",
        }
    )
    assert inst is not None
    assert inst.trigger == "before commit"
    assert inst.action == "run pre-commit"
    assert inst.domain == "git"


def test_validate_instinct_rejects_missing_trigger_or_action() -> None:
    assert _validate_instinct({"trigger": "x", "action": ""}) is None
    assert _validate_instinct({"trigger": "", "action": "y"}) is None
    assert _validate_instinct({"action": "y"}) is None
    assert _validate_instinct({"trigger": "x"}) is None


def test_truncate_under_limit_passes_through() -> None:
    text = "abc" * 10
    assert _truncate(text, 1000) == text


def test_truncate_over_limit_keeps_head_and_tail() -> None:
    text = "A" * 100 + "B" * 5000 + "C" * 100
    truncated = _truncate(text, 500)
    assert len(truncated) <= 500
    # First chars should still be A's
    assert truncated[0] == "A"
    # Last chars should be C's
    assert truncated[-1] == "C"
    assert "...[truncated]..." in truncated


@pytest.mark.asyncio
async def test_extract_session_empty_returns_empty() -> None:
    result = await extract_session("")
    assert isinstance(result, DistilledSession)
    assert result.memories == []
    assert result.instincts == []


@pytest.mark.asyncio
async def test_extract_session_parses_well_formed_response() -> None:
    fake_response = {
        "memories": [
            {"content": "uses argon2id", "tags": ["security"], "category": "preference"},
            {"content": "", "tags": []},  # invalid, should be dropped
        ],
        "instincts": [
            {
                "trigger": "before commit",
                "action": "run pre-commit",
                "domain": "git",
                "evidence": "repeated three times",
            },
            {"trigger": "x"},  # invalid, should be dropped
        ],
    }

    async def fake_chat_json(*args, **kwargs):
        record = kwargs.get("record_target")
        if record is not None:
            record.append("primary")
        return fake_response

    with patch("piloci.curator.extraction.chat_json", side_effect=fake_chat_json):
        result = await extract_session(
            "[user] please use argon2id\n[assistant] sure, here's the change."
        )
    assert len(result.memories) == 1
    assert len(result.instincts) == 1
    assert result.processing_path == "local"
    assert isinstance(result.memories[0], DistilledMemory)
    assert isinstance(result.instincts[0], DistilledInstinct)


@pytest.mark.asyncio
async def test_extract_session_external_path_marked() -> None:
    async def fake_chat_json(*args, **kwargs):
        record = kwargs.get("record_target")
        if record is not None:
            record.append("openai")
        return {"memories": [], "instincts": []}

    from piloci.curator.gemma import ProviderTarget

    fallbacks = [
        ProviderTarget(endpoint="https://x", model="gpt-4o-mini", api_key="k", label="openai")
    ]
    with patch("piloci.curator.extraction.chat_json", side_effect=fake_chat_json):
        result = await extract_session(
            "non-empty transcript with at least one assistant turn here.",
            fallbacks=fallbacks,
            prefer_external=True,
        )
    assert result.processing_path == "external"


@pytest.mark.asyncio
async def test_extract_session_failure_returns_empty() -> None:
    async def fake_chat_json(*args, **kwargs):
        raise RuntimeError("all providers down")

    with patch("piloci.curator.extraction.chat_json", side_effect=fake_chat_json):
        result = await extract_session("something with content.")
    # Should swallow the exception and return empty rather than crashing the worker.
    assert result.memories == []
    assert result.instincts == []


def test_split_into_chunks_short_text_one_chunk() -> None:
    text = "short transcript"
    chunks = _split_into_chunks(text, n_chunks=4, chunk_chars=4000, overlap=200)
    assert chunks == [text]


def test_split_into_chunks_empty_returns_empty_list() -> None:
    assert _split_into_chunks("", n_chunks=4, chunk_chars=4000, overlap=200) == []


def test_split_into_chunks_two_chunks_covers_head_and_tail() -> None:
    text = "H" * 100 + "M" * 9800 + "T" * 100
    chunks = _split_into_chunks(text, n_chunks=2, chunk_chars=4000, overlap=200)
    assert len(chunks) == 2
    assert chunks[0].startswith("H")
    assert chunks[-1].endswith("T")
    # Each window obeys the cap.
    assert all(len(c) == 4000 for c in chunks)


def test_split_into_chunks_four_chunks_evenly_spaced() -> None:
    # 20K text with 4 chunks of 4000 chars → starts at 0, 5333, 10666, 16000.
    text = "x" * 20_000
    chunks = _split_into_chunks(text, n_chunks=4, chunk_chars=4000, overlap=200)
    assert len(chunks) == 4
    assert all(len(c) == 4000 for c in chunks)


def test_split_into_chunks_collapses_overlapping_starts() -> None:
    # 5K text with 4 chunks of 4000 — starts would be ~0, 333, 666, 1000.
    # Overlap is 200 so min_stride = 3800; only two distinct starts survive.
    text = "y" * 5000
    chunks = _split_into_chunks(text, n_chunks=4, chunk_chars=4000, overlap=200)
    assert len(chunks) <= 2


def test_merge_distilled_dedupes_memories_by_normalized_content() -> None:
    a = DistilledSession(
        memories=[DistilledMemory(content="Uses argon2id", tags=["security"])],
        instincts=[],
    )
    b = DistilledSession(
        memories=[
            # Same content modulo whitespace + case → deduped
            DistilledMemory(content="  uses   ARGON2id  ", tags=["auth"]),
            DistilledMemory(content="Prefers black formatter", tags=["style"]),
        ],
        instincts=[],
    )
    merged = _merge_distilled([a, b])
    assert len(merged.memories) == 2
    assert merged.memories[0].content == "Uses argon2id"
    assert merged.memories[1].content == "Prefers black formatter"


def test_merge_distilled_dedupes_instincts_by_trigger_action() -> None:
    a = DistilledSession(
        memories=[],
        instincts=[DistilledInstinct(trigger="before commit", action="run pre-commit")],
    )
    b = DistilledSession(
        memories=[],
        instincts=[
            DistilledInstinct(trigger="Before Commit", action="Run Pre-commit"),  # dup
            DistilledInstinct(trigger="on push", action="run tests"),
        ],
    )
    merged = _merge_distilled([a, b])
    assert len(merged.instincts) == 2


def test_merge_distilled_marks_external_if_any_chunk_was_external() -> None:
    a = DistilledSession(memories=[], instincts=[], processing_path="local")
    b = DistilledSession(memories=[], instincts=[], processing_path="external")
    merged = _merge_distilled([a, b])
    assert merged.processing_path == "external"


@pytest.mark.asyncio
async def test_extract_session_multipass_short_transcript_one_call() -> None:
    calls: list[int] = []

    async def fake_chat_json(*args, **kwargs):
        calls.append(1)
        record = kwargs.get("record_target")
        if record is not None:
            record.append("primary")
        return {"memories": [{"content": "x", "tags": [], "category": "fact"}], "instincts": []}

    with patch("piloci.curator.extraction.chat_json", side_effect=fake_chat_json):
        result = await extract_session_multipass(
            "tiny transcript with at least one assistant turn",
            chunk_chars=4000,
            max_chunks=4,
        )
    assert len(calls) == 1
    assert len(result.memories) == 1


@pytest.mark.asyncio
async def test_extract_session_multipass_long_transcript_calls_per_chunk() -> None:
    calls: list[int] = []

    async def fake_chat_json(*args, **kwargs):
        calls.append(1)
        record = kwargs.get("record_target")
        if record is not None:
            record.append("primary")
        # Each chunk returns one unique memory so dedupe doesn't collapse them.
        idx = len(calls)
        return {
            "memories": [{"content": f"chunk-{idx} memory", "tags": [], "category": "fact"}],
            "instincts": [],
        }

    long_text = "z" * 20_000  # > 4 × 4000, forces 4 chunks
    with patch("piloci.curator.extraction.chat_json", side_effect=fake_chat_json):
        result = await extract_session_multipass(
            long_text,
            chunk_chars=4000,
            max_chunks=4,
            chunk_overlap=200,
        )
    assert len(calls) == 4
    assert len(result.memories) == 4
