from __future__ import annotations

"""Heuristic prefilter — rejects trivial sessions before they enter distillation.

Runs at ingest time. Pure-CPU, sub-millisecond. No LLM, no I/O. Pi 5-friendly.
The goal is to keep the device from spending Gemma cycles on transcripts that
have no durable signal: empty sessions, single-command lookups, sessions where
the user only read files. Anything ambiguous passes through — false negatives
(filtering a useful session) are worse than false positives.
"""

import re
from dataclasses import dataclass
from typing import Any

import orjson

# Thresholds raised in v0.3.77 — earlier values (300/30/100) were so
# generous that any chat fragment slipped through, flooding the user's wiki
# with "잘잘한 쓰레기". The new floors are calibrated to drop one-off
# back-and-forth exchanges and toolbar-style single-turn lookups while still
# admitting real working sessions (which routinely cross 1k chars).
MIN_TRANSCRIPT_CHARS = 600
MIN_DISTINCT_WORDS = 60
MIN_ASSISTANT_CHARS = 200

# Hard cap for "looks like a one-off notification". Anything longer than this
# might still be a short notification but the false-positive risk of dropping
# a real session grows; cap conservatively.
NOTIFICATION_MAX_CHARS = 600

# Patterns we've observed turning into tiny, semantically-useless "memories":
# GitHub / Snyk / Dependabot / Renovate webhook-style notifications that arrive
# via /api/ingest. They look like prose but they're templated automation
# output — distilling them just produces noise notes the user can't act on
# and that pile up faster than real session learnings.
_NOTIFICATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^A security scan revealed", re.I),
    re.compile(r"\bvulnerabilit(?:y|ies)\b.*\bseverit", re.I),
    re.compile(r"^Dependabot\b", re.I),
    re.compile(r"^Renovate\b", re.I),
    re.compile(r"^Snyk\b", re.I),
    re.compile(r"^npm audit\b", re.I),
    re.compile(r"^GitHub Actions\b", re.I),
    re.compile(r"^Workflow run\b", re.I),
    re.compile(r"\b(opened|closed|merged|reopened) (?:a |the )?(?:pull request|issue)\b", re.I),
    re.compile(r"^Build (?:#\d+ )?(?:failed|succeeded)\b", re.I),
    re.compile(r"^Stale (?:issue|pull request)\b", re.I),
]


def _looks_like_system_notification(text: str) -> bool:
    """True when ``text`` reads like a single short automated notification.

    Length-gated so long sessions that happen to mention scans still pass —
    the false-positive cost of dropping a real session is much worse than
    keeping a notification in the queue.
    """
    stripped = text.strip()
    if not stripped or len(stripped) > NOTIFICATION_MAX_CHARS:
        return False
    return any(p.search(stripped) for p in _NOTIFICATION_PATTERNS)


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

    # System notification gate runs BEFORE the length check: notifications are
    # short by nature and would otherwise either pass the length floor or be
    # logged as "too_short" with no hint about WHY this kind of input keeps
    # appearing. The dedicated reason makes the dashboard actionable.
    if _looks_like_system_notification(full_text):
        return PrefilterDecision(
            passes=False,
            reason="system_notification",
            char_count=char_count,
        )

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
