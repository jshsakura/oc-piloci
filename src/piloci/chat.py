from __future__ import annotations

"""RAG chat over a project's memories.

Pipeline:
1. Embed user query
2. Vector-search memories scoped to (user_id, project_id)
3. Build a tight, grounded prompt under a char budget
4. Stream answer through whatever ``ChatProvider`` is configured

Context budget is enforced because Pi-local LLMs have small effective
windows and large prompts blow the token budget on remote APIs too. The
prompt deliberately omits tags/scores — those go to the client as
citation metadata, not into the LLM context.
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
MAX_TOP_K = 20
MAX_QUERY_CHARS = 1500

# Per-snippet hard cap (after which we cut with an ellipsis).
DEFAULT_MAX_MEMORY_CHARS = 400
# Total budget across all retrieved snippets in the prompt.
DEFAULT_MAX_CONTEXT_CHARS = 3500

_SYSTEM_PROMPT = (
    "Answer strictly from the provided memories. "
    "Cite ids inline like [m1], [m2]. "
    "If they do not contain enough info, say so plainly. "
    "Be concise. Match the user's language."
)


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _pack_context(
    memories: list[dict[str, Any]],
    *,
    per_memory_limit: int,
    total_limit: int,
) -> str:
    """Build the in-prompt memory block, dropping items past the total budget.

    Memories are truncated per-item then accumulated until the running total
    would exceed ``total_limit``. Anything past that is dropped — the caller
    keeps full citation metadata so dropped items still show up in the UI
    list, just not in the LLM context.
    """
    if not memories:
        return "(none)"

    lines: list[str] = []
    used = 0
    for idx, mem in enumerate(memories, start=1):
        snippet = _truncate(str(mem.get("content") or ""), per_memory_limit)
        if not snippet:
            continue
        block = f"[m{idx}] {snippet}"
        # +2 for the blank line separator
        cost = len(block) + 2
        if used + cost > total_limit and lines:
            break
        lines.append(block)
        used += cost
    return "\n\n".join(lines) if lines else "(none)"


def build_messages(
    query: str,
    memories: list[dict[str, Any]],
    *,
    per_memory_limit: int = DEFAULT_MAX_MEMORY_CHARS,
    total_context_limit: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> list[dict[str, str]]:
    """Render system + user messages within the configured char budget."""
    context = _pack_context(
        memories,
        per_memory_limit=per_memory_limit,
        total_limit=total_context_limit,
    )
    user_message = (
        f"Q: {query.strip()[:MAX_QUERY_CHARS]}\n\n"
        f"Memories:\n{context}\n\n"
        "Answer using ONLY the memories. Cite [mN]. If insufficient, say so."
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def format_citations(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Citation payload for the client. Truncates content for transport."""
    citations = []
    for idx, mem in enumerate(memories, start=1):
        citations.append(
            {
                "ref": f"m{idx}",
                "memory_id": mem.get("memory_id") or mem.get("id"),
                "content": _truncate(str(mem.get("content") or ""), DEFAULT_MAX_MEMORY_CHARS),
                "score": mem.get("score"),
                "tags": mem.get("tags") or [],
            }
        )
    return citations


async def retrieve(
    *,
    query: str,
    user_id: str,
    project_id: str,
    store: Any,
    embed_fn: Any,
    top_k: int = DEFAULT_TOP_K,
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Embed the query and pull the top-k memories for the (user, project)."""
    top_k = max(1, min(MAX_TOP_K, top_k))
    vector = await embed_fn(query)
    return await store.search(
        user_id=user_id,
        project_id=project_id,
        query_vector=vector,
        top_k=top_k,
        tags=tags,
    )


async def stream_answer(
    *,
    query: str,
    memories: list[dict[str, Any]],
    provider: Any,
    max_tokens: int = 768,
    temperature: float = 0.2,
    per_memory_limit: int = DEFAULT_MAX_MEMORY_CHARS,
    total_context_limit: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> AsyncIterator[str]:
    """Stream the grounded answer through whatever provider was selected."""
    messages = build_messages(
        query,
        memories,
        per_memory_limit=per_memory_limit,
        total_context_limit=total_context_limit,
    )
    async for chunk in provider.stream(messages, max_tokens=max_tokens, temperature=temperature):
        yield chunk
