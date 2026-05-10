from __future__ import annotations

"""Unified session distillation: one LLM call yields both memories and instincts.

Replaces the two-call eager pipeline (curator.worker._extract_memories +
session_analyzer.extract_instincts) with a single Gemma round-trip that
returns a combined JSON object. Cuts inference work in half on the Pi 5.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from piloci.curator.gemma import ProviderTarget, chat_json

logger = logging.getLogger(__name__)


# Single transcript char budget for the unified prompt. Sized to fit comfortably
# inside a 4096-token context after system prompt + output budget. Curator's
# old 4000-char cap and analyzer's 6000-char cap are unified here.
DEFAULT_TRANSCRIPT_MAX_CHARS = 4000

# Output JSON budget. Memories tend toward 5-15 items, instincts 3-7.
# 1500 tokens accommodates both lists with room for tags/evidence.
DEFAULT_MAX_TOKENS = 1500

# Default request timeout (seconds). Pi 5 with 4.6B Gemma routinely needs
# 120-180s for a full 4000-char transcript pass; old 120s default caused
# spurious retries that tripled actual workload.
DEFAULT_TIMEOUT_SEC = 300.0


_SYSTEM = (
    "You distill an AI coding session transcript into two structured outputs:\n"
    "  1. memories  — durable facts/decisions/preferences/patterns/errors/solutions.\n"
    "  2. instincts — repeated behavioral patterns (trigger → action) the user expects.\n"
    "\n"
    "Output ONE JSON object, no prose, with this exact schema:\n"
    "{\n"
    '  "memories": [\n'
    '    {"content": "<single self-contained sentence>",\n'
    '     "tags": ["tag1", "tag2"],\n'
    '     "category": "fact|decision|preference|pattern|error|solution"}\n'
    "  ],\n"
    '  "instincts": [\n'
    '    {"trigger": "<short condition>",\n'
    '     "action": "<short response>",\n'
    '     "domain": "code-style|testing|git|debugging|workflow|architecture|'
    'performance|security|api|frontend|other",\n'
    '     "evidence": "<one short sentence justifying this>"}\n'
    "  ]\n"
    "}\n"
    "\n"
    "Rules:\n"
    "- Skip chitchat, tool traces, routine commands.\n"
    "- 1-2 sentences per memory, self-contained.\n"
    "- Extract 3-7 instincts. Focus on repeated corrections and preferences.\n"
    "- Ignore one-time fixes and external API failures.\n"
    "- If the transcript yields nothing useful, output empty arrays."
)

_USER_TEMPLATE = (
    "Session transcript (truncated to most recent {n_chars} chars):\n\n"
    "{transcript}\n\n"
    "Distill the session. Output ONLY the JSON object."
)


@dataclass
class DistilledMemory:
    content: str
    tags: list[str] = field(default_factory=list)
    category: str = "fact"


@dataclass
class DistilledInstinct:
    trigger: str
    action: str
    domain: str = "other"
    evidence: str = ""


@dataclass
class DistilledSession:
    """Unified output of one Gemma extraction call.

    ``processing_path`` records which provider actually answered: 'local' for
    on-device Gemma, 'external' for an OpenAI-compatible fallback. Persisted on
    RawSession so the user can see the local/external split in observability.
    """

    memories: list[DistilledMemory]
    instincts: list[DistilledInstinct]
    processing_path: str = "local"


def _normalize_transcript(transcript: str | list[dict[str, Any]]) -> str:
    """Accept either a raw string or a chat-message list (curator format).

    The two call sites historically passed different shapes — curator passed
    parsed JSON message arrays, analyzer passed a flat string. Normalize so
    extract_session is agnostic.
    """
    if isinstance(transcript, str):
        return transcript

    lines: list[str] = []
    for msg in transcript:
        role = msg.get("role", "?") if isinstance(msg, dict) else "?"
        content = msg.get("content", "") if isinstance(msg, dict) else ""
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") if isinstance(c, dict) else str(c) for c in content
            )
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    marker = "\n...[truncated]...\n"
    budget = max_chars - len(marker)
    head_budget = min(budget // 3, 500)
    tail_budget = budget - head_budget
    return text[:head_budget] + marker + (text[-tail_budget:] if tail_budget > 0 else "")


def _validate_memory(item: Any) -> DistilledMemory | None:
    if not isinstance(item, dict):
        return None
    content = item.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    raw_tags = item.get("tags")
    tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []
    category = item.get("category")
    return DistilledMemory(
        content=content.strip(),
        tags=tags[:5],
        category=category if isinstance(category, str) else "fact",
    )


def _validate_instinct(item: Any) -> DistilledInstinct | None:
    if not isinstance(item, dict):
        return None
    trigger = item.get("trigger")
    action = item.get("action")
    if not isinstance(trigger, str) or not trigger.strip():
        return None
    if not isinstance(action, str) or not action.strip():
        return None
    domain = item.get("domain", "other")
    evidence = item.get("evidence", "")
    return DistilledInstinct(
        trigger=trigger.strip()[:300],
        action=action.strip()[:300],
        domain=domain if isinstance(domain, str) else "other",
        evidence=evidence.strip()[:200] if isinstance(evidence, str) else "",
    )


async def extract_session(
    transcript: str | list[dict[str, Any]],
    *,
    endpoint: str = "http://localhost:9090/v1/chat/completions",
    model: str = "gemma",
    fallbacks: list[ProviderTarget] | None = None,
    prefer_external: bool = False,
    max_chars: int = DEFAULT_TRANSCRIPT_MAX_CHARS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    retries: int = 2,
) -> DistilledSession:
    """Run one unified Gemma call and return both memories and instincts.

    ``prefer_external`` reorders the provider chain to put external fallbacks
    ahead of the local endpoint — used by the overflow scheduler when the
    backlog grows past threshold and the user has external keys configured.
    Returns an empty DistilledSession (not an exception) on total failure so
    the worker can stamp the row 'failed' without unwinding the batch.
    """
    text = _normalize_transcript(transcript)
    if not text.strip():
        return DistilledSession(memories=[], instincts=[])

    truncated = _truncate(text, max_chars)
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _USER_TEMPLATE.format(n_chars=max_chars, transcript=truncated)},
    ]

    if prefer_external and fallbacks:
        # Externals first, local at the tail as last-resort.
        targets = list(fallbacks) + [
            ProviderTarget(endpoint=endpoint, model=model, label="local-after")
        ]
    else:
        targets = [ProviderTarget(endpoint=endpoint, model=model, label="primary")]
        if fallbacks:
            targets.extend(fallbacks)

    winning_target: list[str] = []
    try:
        result = await chat_json(
            messages,
            timeout=timeout,
            retries=retries,
            max_tokens=max_tokens,
            targets=targets,
            record_target=winning_target,
        )
    except Exception as exc:
        logger.warning("extract_session: all providers exhausted: %s", exc)
        return DistilledSession(memories=[], instincts=[])

    memories_raw = result.get("memories") if isinstance(result, dict) else None
    instincts_raw = result.get("instincts") if isinstance(result, dict) else None

    memories: list[DistilledMemory] = []
    if isinstance(memories_raw, list):
        for item in memories_raw:
            mem = _validate_memory(item)
            if mem is not None:
                memories.append(mem)

    instincts: list[DistilledInstinct] = []
    if isinstance(instincts_raw, list):
        for item in instincts_raw:
            inst = _validate_instinct(item)
            if inst is not None:
                instincts.append(inst)

    label = winning_target[0] if winning_target else ""
    path = "local" if label in ("primary", "local-after") else "external"
    return DistilledSession(memories=memories, instincts=instincts, processing_path=path)
