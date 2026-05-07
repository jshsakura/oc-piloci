from __future__ import annotations

"""Helpers for resolving a user's external LLM fallback chain.

Workers (curator, analyze, profile) call ``load_user_fallbacks(user_id)``
to get a priority-sorted list of ``ProviderTarget`` instances ready to pass
to ``chat_json(..., fallbacks=...)``. API keys are decrypted on demand here
so the ciphertext never escapes the DB layer.
"""

import logging

from sqlalchemy import select

from piloci.auth.crypto import decrypt_token
from piloci.config import get_settings
from piloci.curator.gemma import ProviderTarget
from piloci.db.models import LLMProvider
from piloci.db.session import async_session

logger = logging.getLogger(__name__)


def _normalize_endpoint(base_url: str) -> str:
    """Accept either ``https://x/v1`` or ``https://x/v1/chat/completions``.

    OpenAI-compatible servers expose the chat completions path; users tend to
    paste the base URL only. Append the canonical path when missing.
    """
    url = base_url.rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return url + "/chat/completions"
    return url + "/v1/chat/completions"


async def load_user_fallbacks(user_id: str) -> list[ProviderTarget]:
    """Return the user's enabled providers as ``ProviderTarget`` list.

    Sorted ascending by ``priority`` (lower = tried first). Fails open: any
    decrypt error logs a warning and skips that provider rather than blowing
    up the calling worker.
    """
    settings = get_settings()
    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(LLMProvider)
                    .where(LLMProvider.user_id == user_id, LLMProvider.enabled)
                    .order_by(LLMProvider.priority.asc(), LLMProvider.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    targets: list[ProviderTarget] = []
    for row in rows:
        try:
            api_key = decrypt_token(row.api_key_encrypted, settings)
        except Exception:
            logger.exception("llm_provider %s: decrypt failed — skipping", row.id)
            continue
        targets.append(
            ProviderTarget(
                endpoint=_normalize_endpoint(row.base_url),
                model=row.model,
                api_key=api_key,
                label=f"provider:{row.name}",
            )
        )
    return targets
