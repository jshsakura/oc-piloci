from __future__ import annotations
"""Profile summarizer: all memories → compressed {static, dynamic} profile.

Stored in `user_profiles` table. Exposed via `piloci://profile` Resource
and `context` Prompt.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from piloci.config import Settings
from piloci.curator.gemma import chat_json
from piloci.db.models import UserProfile
from piloci.db.session import async_session
from piloci.storage.lancedb_store import MemoryStore

logger = logging.getLogger(__name__)

# last-refresh timestamps per (user_id, project_id)
_last_refresh: dict[tuple[str, str], float] = {}

_PROFILE_SYSTEM = (
    "Summarize a user's memories into a profile. Extract stable preferences "
    "separate from recent activity. Output JSON only."
)

_PROFILE_USER_TEMPLATE = """Memories (most recent first):
{memories}

Output schema:
{{
  "static": [
    "short sentence about stable preference or durable fact",
    ...
  ],
  "dynamic": [
    "short sentence about recent activity",
    ...
  ]
}}
- Max 20 static items, max 10 dynamic items.
- Prefer concise sentences.
- Output ONLY the JSON object."""


async def _summarize(memories: list[dict], settings: Settings) -> dict:
    if not memories:
        return {"static": [], "dynamic": []}

    # Render most recent first, truncate to reasonable size
    lines = []
    for m in memories:
        content = m.get("content", "")
        tags = m.get("tags") or []
        tag_str = f" [{','.join(tags)}]" if tags else ""
        lines.append(f"- {content}{tag_str}")
    text = "\n".join(lines[:200])  # cap at 200 memories

    messages = [
        {"role": "system", "content": _PROFILE_SYSTEM},
        {"role": "user", "content": _PROFILE_USER_TEMPLATE.format(memories=text)},
    ]
    result = await chat_json(
        messages,
        endpoint=settings.gemma_endpoint,
        model=settings.gemma_model,
        max_tokens=1500,
    )
    static = result.get("static") or []
    dynamic = result.get("dynamic") or []
    if not isinstance(static, list):
        static = []
    if not isinstance(dynamic, list):
        dynamic = []
    return {
        "static": [str(s) for s in static[:20]],
        "dynamic": [str(s) for s in dynamic[:10]],
    }


async def refresh_profile(
    user_id: str,
    project_id: str,
    settings: Settings,
    store: MemoryStore,
    force: bool = False,
) -> dict:
    """Regenerate and store the profile. Debounced by min_interval."""
    now = time.time()
    key = (user_id, project_id)
    last = _last_refresh.get(key, 0.0)
    if not force and now - last < settings.profile_refresh_min_interval_sec:
        # Return existing profile without regenerating
        async with async_session() as db:
            row = await db.execute(
                select(UserProfile).where(
                    UserProfile.user_id == user_id,
                    UserProfile.project_id == project_id,
                )
            )
            existing = row.scalar_one_or_none()
            if existing:
                return json.loads(existing.profile_json)
        # fall through to generate if no existing profile

    # Fetch recent memories
    memories = await store.list(
        user_id=user_id, project_id=project_id, limit=200, offset=0
    )
    # sort by updated_at desc (most recent first)
    memories.sort(key=lambda m: m.get("updated_at", 0), reverse=True)

    try:
        profile = await _summarize(memories, settings)
    except Exception as e:
        logger.warning("Profile summarize failed for %s/%s: %s", user_id, project_id, e)
        profile = {"static": [], "dynamic": []}

    payload = json.dumps(profile)
    stmt = sqlite_insert(UserProfile).values(
        user_id=user_id,
        project_id=project_id,
        profile_json=payload,
        updated_at=datetime.now(timezone.utc),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "project_id"],
        set_={"profile_json": payload, "updated_at": datetime.now(timezone.utc)},
    )
    async with async_session() as db:
        await db.execute(stmt)
        await db.commit()

    _last_refresh[key] = now
    return profile


async def get_profile(user_id: str, project_id: str) -> dict | None:
    """Fast read path for Resources/Prompts — no LLM call."""
    async with async_session() as db:
        row = await db.execute(
            select(UserProfile).where(
                UserProfile.user_id == user_id,
                UserProfile.project_id == project_id,
            )
        )
        existing = row.scalar_one_or_none()
        if existing is None:
            return None
        try:
            return json.loads(existing.profile_json)
        except json.JSONDecodeError:
            return None


async def run_profile_worker(
    settings: Settings,
    store: MemoryStore,
    stop_event: asyncio.Event,
) -> None:
    """Background loop: periodically refresh profiles for active users."""
    from piloci.db.models import Project

    logger.info("Profile worker started")
    while not stop_event.is_set():
        try:
            async with async_session() as db:
                projects = (
                    await db.execute(select(Project.user_id, Project.id))
                ).all()
            for user_id, project_id in projects:
                if stop_event.is_set():
                    break
                try:
                    await refresh_profile(user_id, project_id, settings, store)
                except Exception as e:
                    logger.warning(
                        "Profile refresh failed for %s/%s: %s",
                        user_id, project_id, e,
                    )
        except Exception as e:
            logger.exception("Profile worker iteration failed: %s", e)

        # Sleep in small chunks so stop_event is responsive
        for _ in range(settings.profile_refresh_min_interval_sec // 5):
            if stop_event.is_set():
                break
            await asyncio.sleep(5)

    logger.info("Profile worker stopped")
