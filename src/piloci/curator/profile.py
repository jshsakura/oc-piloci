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


def _normalize_profile_payload(payload: object) -> dict[str, list[str]]:
    if not isinstance(payload, dict):
        return {"static": [], "dynamic": []}

    static_raw = payload.get("static")
    dynamic_raw = payload.get("dynamic")
    static = [str(item) for item in static_raw[:20]] if isinstance(static_raw, list) else []
    dynamic = [str(item) for item in dynamic_raw[:10]] if isinstance(dynamic_raw, list) else []
    return {"static": static, "dynamic": dynamic}


async def _summarize(memories: list[dict[str, object]], settings: Settings) -> dict[str, list[str]]:
    if not memories:
        return {"static": [], "dynamic": []}

    # Render most recent first, truncate to reasonable size
    lines = []
    for m in memories:
        content_raw = m.get("content", "")
        content = content_raw if isinstance(content_raw, str) else str(content_raw)
        tags_raw = m.get("tags")
        tags = [str(tag) for tag in tags_raw] if isinstance(tags_raw, list) else []
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
    return _normalize_profile_payload(result)


async def refresh_profile(
    user_id: str,
    project_id: str,
    settings: Settings,
    store: MemoryStore,
    force: bool = False,
) -> dict[str, list[str]]:
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
                return _normalize_profile_payload(json.loads(existing.profile_json))
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


async def get_profile(user_id: str, project_id: str) -> dict[str, list[str]] | None:
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
            return _normalize_profile_payload(json.loads(existing.profile_json))
        except json.JSONDecodeError:
            return None


async def _run_profile_refresh_cycle(
    settings: Settings,
    store: MemoryStore,
    stop_event: asyncio.Event,
) -> int:
    from piloci.db.models import Project

    async with async_session() as db:
        projects = (
            await db.execute(
                select(Project.user_id, Project.id)
                .order_by(Project.updated_at.desc())
                .limit(settings.curator_profile_project_limit)
            )
        ).all()

    processed = 0
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
        processed += 1
        if settings.curator_profile_pause_ms > 0 and not stop_event.is_set():
            await asyncio.sleep(settings.curator_profile_pause_ms / 1000)

    return processed


async def run_profile_worker(
    settings: Settings,
    store: MemoryStore,
    stop_event: asyncio.Event,
) -> None:
    """Background loop: periodically refresh profiles for active users."""
    logger.info("Profile worker started")
    while not stop_event.is_set():
        try:
            processed = await _run_profile_refresh_cycle(settings, store, stop_event)
            logger.debug("Profile worker refreshed %d projects", processed)
        except Exception as e:
            logger.exception("Profile worker iteration failed: %s", e)

        # Sleep in small chunks so stop_event is responsive
        for _ in range(settings.profile_refresh_min_interval_sec // 5):
            if stop_event.is_set():
                break
            await asyncio.sleep(5)

    logger.info("Profile worker stopped")
