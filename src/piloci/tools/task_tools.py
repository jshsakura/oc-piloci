from __future__ import annotations

"""piLoci `ask` tool — pull-form, on-demand assistant task.

Thin MCP/REST-facing wrapper over ``piloci.assistant.run_task``. Runs the
local model only when explicitly called (idle = no run).
"""

import logging
from typing import Annotated, Any

from pydantic import BaseModel, Field

from piloci.assistant import run_task

logger = logging.getLogger(__name__)

ASK_DESC = (
    "Run a one-off task on the local model: summarize, classify, or answer. "
    "use_memory adds project memories as context."
)


class AskInput(BaseModel):
    instruction: Annotated[
        str,
        Field(description="What to do, e.g. 'summarize in 3 lines'.", max_length=20_000),
    ]
    context: Annotated[
        str | None,
        Field(default=None, description="Text to operate on (optional).", max_length=200_000),
    ] = None
    use_memory: Annotated[
        bool,
        Field(default=False, description="Ground the answer in this project's memories."),
    ] = False


async def handle_ask(
    args: AskInput,
    user_id: str,
    project_id: str | None,
    store: Any,
    embed_fn: Any,
    settings: Any,
) -> dict[str, Any]:
    return await run_task(
        instruction=args.instruction,
        context_text=args.context,
        use_memory=args.use_memory,
        user_id=user_id,
        project_id=project_id,
        store=store,
        embed_fn=embed_fn,
        settings=settings,
    )
