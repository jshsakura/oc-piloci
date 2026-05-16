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


# Per-chunk transcript budget. One chunk = one Gemma round-trip and must fit
# inside the 4096-token context after system prompt + output budget.
DEFAULT_TRANSCRIPT_MAX_CHARS = 4000

# Multipass cap. Long transcripts get sampled across N chunks (head, evenly
# spaced middles, tail) so the distiller sees the whole arc — not just the
# 4000-char head+tail concatenation _truncate produces. 4 chunks × 4000 chars
# = ~16K chars covered per session, which on real data lifts coverage from
# 0.3% to ~2% of the median 1.2M-char session.
DEFAULT_MAX_CHUNKS = 4
DEFAULT_CHUNK_OVERLAP = 200

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
    "- Write memory `content`, instinct `trigger`/`action`/`evidence` in the\n"
    "  same language the user speaks in the transcript. Korean conversations\n"
    "  → Korean memories. English conversations → English memories. Mixed\n"
    "  conversations → match the language the user uses most. Schema keys\n"
    "  (`category`, `domain` enums) stay English — they are identifiers.\n"
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


def _split_into_chunks(
    text: str,
    n_chunks: int,
    chunk_chars: int,
    overlap: int,
) -> list[str]:
    """Sample a long transcript into up to ``n_chunks`` windows of ``chunk_chars``.

    Short enough to fit in one chunk → returns ``[text]``. Otherwise the
    starts are spread evenly across [0, len-chunk_chars] so the first
    window always covers the session opening (intent/setup) and the last
    always covers the closing (final decisions/code). When windows would
    overlap by more than ``chunk_chars - overlap`` we merge them — keeps
    Pi 5 call count bounded on short-but-over-cap transcripts.
    """
    if n_chunks < 1:
        return []
    if not text or len(text) <= chunk_chars or n_chunks == 1:
        return [text[:chunk_chars]] if text else []
    last_start = len(text) - chunk_chars
    if n_chunks == 2:
        raw_starts = [0, last_start]
    else:
        step = last_start / (n_chunks - 1)
        raw_starts = [int(round(i * step)) for i in range(n_chunks)]
    starts: list[int] = []
    min_stride = max(1, chunk_chars - overlap)
    for s in raw_starts:
        if not starts or s - starts[-1] >= min_stride:
            starts.append(s)
    return [text[s : s + chunk_chars] for s in starts]


def _normalize_for_dedupe(s: str) -> str:
    import re as _re

    return _re.sub(r"\s+", " ", (s or "").strip()).lower()


def _merge_distilled(parts: list["DistilledSession"]) -> "DistilledSession":
    """Combine N per-chunk extractions, deduping by normalized content keys."""
    seen_mem: set[str] = set()
    memories: list[DistilledMemory] = []
    seen_ins: set[tuple[str, str]] = set()
    instincts: list[DistilledInstinct] = []
    for part in parts:
        for mem in part.memories:
            key = _normalize_for_dedupe(mem.content)[:200]
            if not key or key in seen_mem:
                continue
            seen_mem.add(key)
            memories.append(mem)
        for inst in part.instincts:
            key_t = _normalize_for_dedupe(inst.trigger)
            key_a = _normalize_for_dedupe(inst.action)
            if not key_t or not key_a:
                continue
            tup = (key_t, key_a)
            if tup in seen_ins:
                continue
            seen_ins.add(tup)
            instincts.append(inst)
    # External path "wins" — if any chunk routed externally, count the whole
    # session as external so the budget bookkeeping reflects reality.
    path = "external" if any(p.processing_path == "external" for p in parts) else "local"
    return DistilledSession(memories=memories, instincts=instincts, processing_path=path)


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


async def extract_session_multipass(
    transcript: str | list[dict[str, Any]],
    *,
    endpoint: str = "http://localhost:9090/v1/chat/completions",
    model: str = "gemma",
    fallbacks: list[ProviderTarget] | None = None,
    prefer_external: bool = False,
    chunk_chars: int = DEFAULT_TRANSCRIPT_MAX_CHARS,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    retries: int = 2,
) -> DistilledSession:
    """Sample-and-merge variant of ``extract_session`` for long transcripts.

    A median piLoci session is ~1.2M chars; ``extract_session``'s single 4000-
    char window made Gemma see <0.3% of it. This wrapper splits the transcript
    into up to ``max_chunks`` evenly-spaced windows (first window covers the
    session opening, last covers the closing), runs one Gemma call per
    chunk, then dedupes the resulting memories and instincts by normalized
    content keys. Short transcripts (≤ chunk_chars) collapse to one call,
    matching the old behavior — no extra work for trivial sessions.
    """
    text = _normalize_transcript(transcript)
    if not text.strip():
        return DistilledSession(memories=[], instincts=[])

    chunks = _split_into_chunks(text, max_chunks, chunk_chars, chunk_overlap)
    if not chunks:
        return DistilledSession(memories=[], instincts=[])

    parts: list[DistilledSession] = []
    for chunk in chunks:
        part = await extract_session(
            chunk,
            endpoint=endpoint,
            model=model,
            fallbacks=fallbacks,
            prefer_external=prefer_external,
            max_chars=chunk_chars,
            max_tokens=max_tokens,
            timeout=timeout,
            retries=retries,
        )
        parts.append(part)

    if len(parts) == 1:
        return parts[0]
    return _merge_distilled(parts)
