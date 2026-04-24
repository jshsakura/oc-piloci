from __future__ import annotations

import asyncio
import random

import httpx

from piloci.config import Settings
from piloci.mcp.session_state import McpSessionTracker

_MAX_TEXT_LEN = 4096


def should_send_session_summary(tracker: McpSessionTracker | None, settings: Settings) -> bool:
    if tracker is None or tracker.tool_calls == 0:
        return False
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False
    if tracker.duration_sec >= settings.telegram_min_duration_sec:
        return True
    return tracker.memory_ops >= settings.telegram_min_memory_ops


def format_session_summary(tracker: McpSessionTracker) -> str:
    stats = [f"⏱ {tracker.duration_sec // 60}m {tracker.duration_sec % 60}s"]
    if tracker.memory_saves:
        stats.append(f"💾 {tracker.memory_saves} save")
    if tracker.recall_calls:
        stats.append(f"🔍 {tracker.recall_calls} recall")
    if tracker.memory_forgets:
        stats.append(f"🗑 {tracker.memory_forgets} forget")
    if tracker.list_projects_calls:
        stats.append(f"📂 {tracker.list_projects_calls} projects")
    if tracker.whoami_calls:
        stats.append(f"🙋 {tracker.whoami_calls} whoami")

    lines = ["📋 piLoci MCP session", " · ".join(stats)]
    if tracker.project_id:
        lines.append(f"📁 {tracker.project_id}")
    if tracker.tags:
        lines.append("🏷 " + ", ".join(sorted(tracker.tags)[:8]))
    if tracker.session_id:
        lines.append(f"🆔 {tracker.session_id}")
    text = "\n".join(lines)
    if len(text) <= _MAX_TEXT_LEN:
        return text
    return text[: _MAX_TEXT_LEN - 3] + "..."


async def send_session_summary(tracker: McpSessionTracker, settings: Settings) -> bool:
    if not should_send_session_summary(tracker, settings):
        return False

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": format_session_summary(tracker),
        "disable_notification": True,
    }
    last_response: httpx.Response | None = None
    async with httpx.AsyncClient(timeout=settings.telegram_timeout_sec) as client:
        for attempt in range(3):
            response = await client.post(url, json=payload)
            last_response = response
            if response.status_code != 429:
                response.raise_for_status()
                return True

            retry_after = 2**attempt
            try:
                data = response.json()
                retry_after = int(data.get("parameters", {}).get("retry_after", retry_after))
            except ValueError:
                pass
            await asyncio.sleep(retry_after + random.uniform(0, 1))

    if last_response is not None:
        last_response.raise_for_status()
    return True
