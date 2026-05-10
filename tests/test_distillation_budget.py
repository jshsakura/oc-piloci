from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from piloci.curator.budget import (
    estimate_cost_usd,
    is_budget_exhausted,
    month_total_usd,
    record_usage,
    remaining_budget_usd,
)
from piloci.db.models import Base, ExternalLLMUsage, User, UserPreferences


@pytest.fixture
async def session_factory(tmp_path):
    """Async sqlite engine + session factory bound to the full schema."""
    db_path = tmp_path / "budget.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _make_user(factory, *, user_id: str = "u1", monthly_cap: float | None = None) -> None:
    async with factory() as db:
        db.add(
            User(
                id=user_id,
                email=f"{user_id}@test",
                created_at=datetime.now(timezone.utc),
            )
        )
        if monthly_cap is not None:
            db.add(
                UserPreferences(
                    user_id=user_id,
                    external_budget_monthly_usd=monthly_cap,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        await db.commit()


def test_estimate_cost_uses_default_rates() -> None:
    cost = estimate_cost_usd(1000, 1000)
    # 0.0005 input + 0.0015 output = 0.002
    assert cost == pytest.approx(0.002, rel=1e-3)


def test_estimate_cost_zero_tokens_zero_cost() -> None:
    assert estimate_cost_usd(0, 0) == 0.0


@pytest.mark.asyncio
async def test_record_usage_persists_row(session_factory) -> None:
    await _make_user(session_factory)
    async with session_factory() as db:
        await record_usage(
            db,
            user_id="u1",
            provider_label="openai",
            model="gpt-4o-mini",
            tokens_in=100,
            tokens_out=200,
        )
        await db.commit()

    async with session_factory() as db:
        from sqlalchemy import select

        rows = (await db.execute(select(ExternalLLMUsage))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == "u1"
    assert rows[0].provider_label == "openai"
    assert rows[0].tokens_in == 100
    assert rows[0].tokens_out == 200
    assert rows[0].estimated_cost_usd > 0


@pytest.mark.asyncio
async def test_month_total_aggregates_current_month_only(session_factory) -> None:
    await _make_user(session_factory)
    async with session_factory() as db:
        # current month
        await record_usage(
            db,
            user_id="u1",
            provider_label="x",
            model="m",
            tokens_in=0,
            tokens_out=0,
            estimated_cost_usd=1.50,
        )
        await db.commit()

    # backdate one row to 60 days ago
    async with session_factory() as db:
        old = ExternalLLMUsage(
            user_id="u1",
            provider_label="x",
            model="m",
            tokens_in=0,
            tokens_out=0,
            estimated_cost_usd=99.0,
            created_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        db.add(old)
        await db.commit()

    async with session_factory() as db:
        total = await month_total_usd(db, "u1")
    assert total == pytest.approx(1.50, rel=1e-3)


@pytest.mark.asyncio
async def test_no_cap_means_never_exhausted(session_factory) -> None:
    await _make_user(session_factory, monthly_cap=None)
    async with session_factory() as db:
        # Spend a lot
        await record_usage(
            db,
            user_id="u1",
            provider_label="x",
            model="m",
            tokens_in=0,
            tokens_out=0,
            estimated_cost_usd=999.0,
        )
        await db.commit()
        assert await is_budget_exhausted(db, "u1") is False
        assert await remaining_budget_usd(db, "u1") is None


@pytest.mark.asyncio
async def test_cap_exhausted_when_spend_exceeds(session_factory) -> None:
    await _make_user(session_factory, monthly_cap=5.0)
    async with session_factory() as db:
        await record_usage(
            db,
            user_id="u1",
            provider_label="x",
            model="m",
            tokens_in=0,
            tokens_out=0,
            estimated_cost_usd=6.0,
        )
        await db.commit()
        assert await is_budget_exhausted(db, "u1") is True
        assert await remaining_budget_usd(db, "u1") == 0.0


@pytest.mark.asyncio
async def test_cap_not_exhausted_under_threshold(session_factory) -> None:
    await _make_user(session_factory, monthly_cap=5.0)
    async with session_factory() as db:
        await record_usage(
            db,
            user_id="u1",
            provider_label="x",
            model="m",
            tokens_in=0,
            tokens_out=0,
            estimated_cost_usd=2.0,
        )
        await db.commit()
        assert await is_budget_exhausted(db, "u1") is False
        remaining = await remaining_budget_usd(db, "u1")
        assert remaining == pytest.approx(3.0, rel=1e-3)
