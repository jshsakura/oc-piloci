from __future__ import annotations

"""External LLM budget tracking and enforcement.

The overflow scheduler routes work to a hosted provider when the local Pi
backlog passes threshold. Without a cap that path can quietly run up real
money, so every external call records its cost here and the scheduler asks
``is_budget_exhausted`` before flipping ``use_external=True``.

The dollar figures are best-effort estimates derived from per-provider
pricing tables. Token counts come from the OpenAI-compatible response
``usage`` block when present; for providers that omit it, callers pass 0
and we record cost from a flat per-call estimate. The point isn't accounting
precision — it's a soft cap that keeps a runaway loop from emptying a wallet.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from piloci.db.models import ExternalLLMUsage, UserPreferences

logger = logging.getLogger(__name__)


# Conservative default pricing (USD per 1K tokens) when a provider's record
# doesn't carry explicit cost. Tuned for cheap general-purpose models — if a
# user wires up a premium provider they can override via per-provider config
# later. Goal here is "round number that won't dramatically under-count".
DEFAULT_INPUT_USD_PER_1K = 0.0005
DEFAULT_OUTPUT_USD_PER_1K = 0.0015


def estimate_cost_usd(
    tokens_in: int,
    tokens_out: int,
    *,
    input_per_1k: float = DEFAULT_INPUT_USD_PER_1K,
    output_per_1k: float = DEFAULT_OUTPUT_USD_PER_1K,
) -> float:
    """Compute a USD estimate for a single call from token counts."""
    return (tokens_in / 1000.0) * input_per_1k + (tokens_out / 1000.0) * output_per_1k


def _month_start(now: datetime | None = None) -> datetime:
    """First moment of the current calendar month in UTC.

    Budget caps are calendar-month based — simpler for users to reason about
    than a 30-day rolling window, and matches how most LLM providers bill.
    """
    ref = now or datetime.now(timezone.utc)
    return ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def record_usage(
    db: AsyncSession,
    *,
    user_id: str,
    provider_label: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    estimated_cost_usd: float | None = None,
    provider_id: str | None = None,
) -> ExternalLLMUsage:
    """Persist one external LLM call. Caller commits.

    When ``estimated_cost_usd`` is None, a default rate is applied. The row
    is the source of truth for monthly totals — there's no separate ledger.
    """
    if estimated_cost_usd is None:
        estimated_cost_usd = estimate_cost_usd(tokens_in, tokens_out)
    row = ExternalLLMUsage(
        user_id=user_id,
        provider_id=provider_id,
        provider_label=provider_label,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        estimated_cost_usd=estimated_cost_usd,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    return row


async def month_total_usd(
    db: AsyncSession,
    user_id: str,
    *,
    now: datetime | None = None,
) -> float:
    """Sum estimated cost for the user across the current calendar month."""
    start = _month_start(now)
    stmt = (
        select(func.coalesce(func.sum(ExternalLLMUsage.estimated_cost_usd), 0.0))
        .where(ExternalLLMUsage.user_id == user_id)
        .where(ExternalLLMUsage.created_at >= start)
    )
    result = await db.execute(stmt)
    return float(result.scalar() or 0.0)


async def get_monthly_budget(db: AsyncSession, user_id: str) -> float | None:
    """User's monthly cap, or None when no cap is set."""
    stmt = select(UserPreferences.external_budget_monthly_usd).where(
        UserPreferences.user_id == user_id
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return float(row) if row is not None else None


async def is_budget_exhausted(
    db: AsyncSession,
    user_id: str,
    *,
    now: datetime | None = None,
) -> bool:
    """True iff the user has a cap and the month-to-date spend has reached it.

    A user without a cap is never exhausted — the overflow path remains open.
    The scheduler should call this before flipping ``use_external=True``.
    """
    cap = await get_monthly_budget(db, user_id)
    if cap is None or cap <= 0:
        return False
    spent = await month_total_usd(db, user_id, now=now)
    return spent >= cap


async def remaining_budget_usd(
    db: AsyncSession,
    user_id: str,
    *,
    now: datetime | None = None,
) -> float | None:
    """Monthly cap minus spend, or None when no cap. Floors at 0."""
    cap = await get_monthly_budget(db, user_id)
    if cap is None:
        return None
    spent = await month_total_usd(db, user_id, now=now)
    return max(0.0, cap - spent)
