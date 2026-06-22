from __future__ import annotations

"""piLoci pull-form assistant — on-demand task execution on the local model.

This is the pivot's new center. Unlike the (retired) autonomous curator
workers, it runs ONLY when explicitly invoked: no background polling, no
scheduler, idle = 0 cores. A scoped instruction (summarize / classify /
answer) goes to the local Gemma exactly once, optionally grounded in the
project's saved memories via vector + FTS search.

It never touches RawSession / distillation_state — so it is NOT an eager
distillation path; it is a direct user request → single LLM call.
"""

import logging
from typing import Any

from piloci.curator.gemma import ProviderTarget, chat_text

logger = logging.getLogger(__name__)

_SYSTEM = (
    "너는 piLoci 비서다. 주어진 작업만 정확히 수행하고 한국어로 간결히 답하라. "
    "제공된 자료 밖의 내용을 지어내지 말고, 모르면 모른다고 답하라."
)

# Keep each retrieved memory bounded so the prompt stays small on the Pi.
_MAX_BLOCK_CHARS = 1500


def _build_messages(
    instruction: str,
    context_text: str | None,
    blocks: list[str],
) -> list[dict[str, str]]:
    parts = [f"# 작업\n{instruction.strip()}"]
    if context_text and context_text.strip():
        parts.append(f"\n# 대상 자료\n{context_text.strip()}")
    if blocks:
        joined = "\n\n".join(f"- {b[:_MAX_BLOCK_CHARS]}" for b in blocks)
        parts.append(f"\n# 참고 기억(이 프로젝트)\n{joined}")
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": "\n".join(parts)},
    ]


async def run_task(
    *,
    instruction: str,
    context_text: str | None = None,
    use_memory: bool = False,
    user_id: str,
    project_id: str | None,
    store: Any,
    embed_fn: Any,
    settings: Any,
    record_target: list[str] | None = None,
) -> dict[str, Any]:
    """Run one scoped assistant task on the local model (pull-form).

    When ``use_memory`` is set and a ``project_id`` is present, the project's
    memories are searched (hybrid vector + BM25, scoped to (user_id, project_id))
    and injected as context. Calls the local model exactly once; retrieval is
    best-effort and never fails the task.
    """
    blocks: list[str] = []
    if use_memory and project_id:
        try:
            vec = await embed_fn(instruction)
            hits = await store.hybrid_search(user_id, project_id, instruction, vec, top_k=5)
            blocks = [h.get("content", "") for h in hits if h.get("content")]
        except Exception as exc:  # retrieval is best-effort
            logger.warning("run_task memory retrieval failed: %s", exc)

    targets = [
        ProviderTarget(
            endpoint=settings.gemma_endpoint,
            model=settings.gemma_model,
            label="local",
        )
    ]
    rt: list[str] = record_target if record_target is not None else []
    answer = await chat_text(
        _build_messages(instruction, context_text, blocks),
        targets=targets,
        record_target=rt,
        max_tokens=2000,
        temperature=0.2,
    )
    return {
        "answer": answer,
        "used_memory": bool(blocks),
        "memory_hits": len(blocks),
        "path": rt[-1] if rt else "local",
    }
