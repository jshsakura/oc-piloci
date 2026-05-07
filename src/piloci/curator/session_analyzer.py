from __future__ import annotations

"""Analyze Claude Code session transcripts and extract behavioral instincts.

Uses the local Gemma endpoint (same as the curator) to keep everything on-device.
"""

import logging
from typing import Any

from piloci.curator.gemma import chat_json

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a behavioral pattern extractor. "
    "Analyze the Claude Code session transcript and return a JSON object "
    "with a single key 'instincts' containing an array of extracted patterns. "
    "Each instinct must have: trigger (string), action (string), domain (one of: "
    "code-style, testing, git, debugging, workflow, architecture, performance, security, api, frontend, other), "
    "evidence (string, one short sentence). "
    "Extract 3-7 instincts. Focus on repeated corrections, user preferences, and workflow patterns. "
    "Ignore one-time fixes and external API failures."
)

_USER_TEMPLATE = (
    "Session transcript (truncated to most recent {n_chars} chars):\n\n{transcript}\n\n"
    "Extract behavioral instincts as JSON."
)

_MAX_TRANSCRIPT_CHARS = 6000


def _truncate_transcript(transcript: str) -> str:
    if len(transcript) <= _MAX_TRANSCRIPT_CHARS:
        return transcript
    return "...[truncated]...\n" + transcript[-_MAX_TRANSCRIPT_CHARS:]


def _validate_instinct(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    trigger = item.get("trigger")
    action = item.get("action")
    domain = item.get("domain", "other")
    evidence = item.get("evidence", "")
    if not isinstance(trigger, str) or not trigger.strip():
        return None
    if not isinstance(action, str) or not action.strip():
        return None
    return {
        "trigger": trigger.strip()[:300],
        "action": action.strip()[:300],
        "domain": domain if isinstance(domain, str) else "other",
        "evidence": evidence.strip()[:200] if isinstance(evidence, str) else "",
    }


async def extract_instincts(
    transcript: str,
    endpoint: str = "http://localhost:9090/v1/chat/completions",
    model: str = "gemma",
    fallbacks: list | None = None,
) -> list[dict[str, str]]:
    """Call Gemma to extract instincts from a session transcript.

    Returns a list of validated instinct dicts. Returns [] on failure.
    ``fallbacks`` is forwarded to ``chat_json`` so external providers (e.g.
    Z.AI) take over when local Gemma is unavailable.
    """
    if not transcript or not transcript.strip():
        return []

    truncated = _truncate_transcript(transcript)
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": _USER_TEMPLATE.format(n_chars=_MAX_TRANSCRIPT_CHARS, transcript=truncated),
        },
    ]

    try:
        result = await chat_json(
            messages=messages,
            endpoint=endpoint,
            model=model,
            temperature=0.1,
            max_tokens=1024,
            fallbacks=fallbacks,
        )
    except Exception as exc:
        logger.warning("session_analyzer: Gemma call failed: %s", exc)
        return []

    raw_instincts = result.get("instincts")
    if not isinstance(raw_instincts, list):
        logger.warning("session_analyzer: unexpected Gemma response shape: %s", list(result.keys()))
        return []

    validated = []
    for item in raw_instincts:
        inst = _validate_instinct(item)
        if inst:
            validated.append(inst)

    logger.info("session_analyzer: extracted %d instincts", len(validated))
    return validated
