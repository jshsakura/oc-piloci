from __future__ import annotations

"""Heuristic prefilter — rejects trivial sessions before they enter distillation.

Runs at ingest time. Pure-CPU, sub-millisecond. No LLM, no I/O. Pi 5-friendly.
The goal is to keep the device from spending Gemma cycles on transcripts that
have no durable signal: empty sessions, single-command lookups, sessions where
the user only read files. Anything ambiguous passes through — false negatives
(filtering a useful session) are worse than false positives.
"""

from dataclasses import dataclass
from typing import Any

import orjson

# Each threshold is intentionally generous: prefilter favors letting marginal
# sessions through. The lazy worker downstream is the cheap path; refusing
# work here only makes sense when the transcript is *clearly* sterile.
MIN_TRANSCRIPT_CHARS = 300
MIN_DISTINCT_WORDS = 30
MIN_ASSISTANT_CHARS = 100


@dataclass
class PrefilterDecision:
    """Result of prefilter evaluation.

    ``passes`` is True when the session should enter the distillation queue.
    ``reason`` is populated only when ``passes`` is False — this string is
    persisted to RawSession.filter_reason so the user can audit what got
    dropped (and why) from the observability dashboard.
    """

    passes: bool
    reason: str | None = None
    char_count: int = 0
    distinct_words: int = 0
    assistant_chars: int = 0


def _flatten_content(content: Any) -> str:
    """Render a single message's content (which may be a list of blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return ""


def _normalize(transcript: str | list[dict[str, Any]]) -> tuple[str, str]:
    """Return (full_text, assistant_only_text) for whichever input shape we got.

    Tracking assistant-only text separately catches sessions that are 90% tool
    output noise: long char count but no real assistant reasoning to distill.
    """
    if isinstance(transcript, str):
        # Plain-string transcripts (analyzer-style) lose role info. Treat the
        # whole string as both 'full' and 'assistant' — assistant-chars check
        # becomes equivalent to total-chars.
        return transcript, transcript

    full_parts: list[str] = []
    assistant_parts: list[str] = []
    for msg in transcript:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        text = _flatten_content(msg.get("content", ""))
        full_parts.append(f"[{role}] {text}")
        if role == "assistant":
            assistant_parts.append(text)
    return "\n".join(full_parts), "\n".join(assistant_parts)


def _parse_if_json(raw: str) -> str | list[dict[str, Any]]:
    """Best-effort: detect transcript_json strings and parse, else pass through."""
    stripped = raw.lstrip()
    if not stripped or stripped[0] not in "[{":
        return raw
    try:
        parsed = orjson.loads(raw)
    except orjson.JSONDecodeError:
        return raw
    if isinstance(parsed, list):
        return parsed
    return raw


def evaluate(transcript: str | list[dict[str, Any]]) -> PrefilterDecision:
    """Decide whether a transcript is worth distilling.

    Three-stage gate:
      1. Empty/whitespace → reject ("empty").
      2. Length below MIN_TRANSCRIPT_CHARS → reject ("too_short").
      3. Distinct-word count below MIN_DISTINCT_WORDS → reject ("low_diversity").
      4. Assistant content below MIN_ASSISTANT_CHARS → reject ("no_assistant_content").

    Anything else passes. Order matters: cheaper checks first so the common
    "pass" path skips the expensive distinct-word tokenization.
    """
    if isinstance(transcript, str):
        transcript = _parse_if_json(transcript)

    full_text, assistant_text = _normalize(transcript)

    if not full_text.strip():
        return PrefilterDecision(passes=False, reason="empty", char_count=0)

    char_count = len(full_text)
    if char_count < MIN_TRANSCRIPT_CHARS:
        return PrefilterDecision(
            passes=False,
            reason="too_short",
            char_count=char_count,
        )

    assistant_chars = len(assistant_text)
    if assistant_chars < MIN_ASSISTANT_CHARS:
        return PrefilterDecision(
            passes=False,
            reason="no_assistant_content",
            char_count=char_count,
            assistant_chars=assistant_chars,
        )

    # Distinct-word count catches "ls"-spam and tight retry loops where the
    # transcript looks long but has no vocabulary diversity.
    words = {w for w in full_text.lower().split() if w.isalnum()}
    distinct = len(words)
    if distinct < MIN_DISTINCT_WORDS:
        return PrefilterDecision(
            passes=False,
            reason="low_diversity",
            char_count=char_count,
            distinct_words=distinct,
            assistant_chars=assistant_chars,
        )

    return PrefilterDecision(
        passes=True,
        char_count=char_count,
        distinct_words=distinct,
        assistant_chars=assistant_chars,
    )
