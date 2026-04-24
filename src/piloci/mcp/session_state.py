from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class McpSessionTracker:
    started_at: float = field(default_factory=time.monotonic)
    user_id: str | None = None
    project_id: str | None = None
    session_id: str | None = None
    tool_calls: int = 0
    memory_saves: int = 0
    memory_forgets: int = 0
    recall_calls: int = 0
    list_projects_calls: int = 0
    whoami_calls: int = 0
    tags: set[str] = field(default_factory=set)

    @property
    def duration_sec(self) -> int:
        return max(0, int(time.monotonic() - self.started_at))

    @property
    def memory_ops(self) -> int:
        return self.memory_saves + self.memory_forgets


mcp_auth_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "mcp_auth_ctx", default=None
)

mcp_session_ctx: contextvars.ContextVar[McpSessionTracker | None] = contextvars.ContextVar(
    "mcp_session_ctx", default=None
)


def build_session_tracker(auth_payload: dict[str, Any] | None) -> McpSessionTracker:
    return McpSessionTracker(
        user_id=(auth_payload or {}).get("sub"),
        project_id=(auth_payload or {}).get("project_id"),
        session_id=(auth_payload or {}).get("jti"),
    )


def record_tool_call(
    tracker: McpSessionTracker | None,
    name: str,
    arguments: dict[str, Any] | None,
) -> None:
    if tracker is None:
        return

    tracker.tool_calls += 1
    payload = arguments or {}

    if name == "memory":
        action = payload.get("action", "save")
        if action == "forget":
            tracker.memory_forgets += 1
        else:
            tracker.memory_saves += 1
        for tag in payload.get("tags") or []:
            tracker.tags.add(str(tag))
        return

    if name == "recall":
        tracker.recall_calls += 1
        for tag in payload.get("tags") or []:
            tracker.tags.add(str(tag))
        return

    if name == "listProjects":
        tracker.list_projects_calls += 1
        return

    if name == "whoAmI":
        tracker.whoami_calls += 1
