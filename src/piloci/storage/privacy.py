from __future__ import annotations

"""Privacy classification for memories and instincts.

Some categories of distilled output are personal — frustration, praise,
profanity, satisfaction — and exist so the user can run a weekly self-
retrospective. They are *not* meant for team sharing, exports handed to
collaborators, or any aggregate workplace dashboard.

Nothing in the current codebase ships these into team workspaces, but the
team feature is the kind of thing where a future caller adds "let me show
the team's memory map" without realizing some of those memories are the
user's private frustrations. This module centralises the "private?" check
so the gate lives in one place and any sharing path can `from piloci.storage
.privacy import is_private_memory` and refuse to leak.
"""

from typing import Any

# Memory categories the user produces about themselves rather than the work.
PRIVATE_MEMORY_CATEGORIES: frozenset[str] = frozenset({"feedback"})

# Instinct domains describing emotional reaction patterns, not coding habits.
PRIVATE_INSTINCT_DOMAINS: frozenset[str] = frozenset({"reaction"})


def is_private_memory(row: dict[str, Any] | Any) -> bool:
    """Return True when this memory row holds personal feedback content.

    Accepts a mapping (LanceDB row, dict) or a dataclass-like object with a
    ``category`` attribute. Anything we can't classify falls through as
    non-private — that is the conservative default for a *check* (the
    sharing path is responsible for opt-in inclusion, never for guessing).
    """
    category = _extract_field(row, "category")
    return category in PRIVATE_MEMORY_CATEGORIES


def is_private_instinct(row: dict[str, Any] | Any) -> bool:
    """Return True when this instinct describes an emotional reaction pattern."""
    domain = _extract_field(row, "domain")
    return domain in PRIVATE_INSTINCT_DOMAINS


def _extract_field(row: dict[str, Any] | Any, key: str) -> str | None:
    if row is None:
        return None
    if isinstance(row, dict):
        value = row.get(key)
    else:
        value = getattr(row, key, None)
    return value if isinstance(value, str) else None
