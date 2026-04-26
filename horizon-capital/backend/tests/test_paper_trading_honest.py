"""Tests for honest-paper-trading plan (2026-04-26)."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_cash_module_round_trip():
    """set_cash then get_cash returns the value via the same session."""
    from app.core.cash import get_cash, set_cash
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as session:
        await set_cash(session, "USD", 123_456.78)
        await session.commit()

    async with local_session_factory() as session:
        amount = await get_cash(session, "USD")
    assert amount == pytest.approx(123_456.78)


@pytest.mark.asyncio
async def test_cash_module_atomic_with_caller_session():
    """If caller rolls back, set_cash effect must not persist."""
    from app.core.cash import get_cash, set_cash
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as session:
        await set_cash(session, "USD", 999_999.0)
        await session.commit()

    async with local_session_factory() as session:
        await set_cash(session, "USD", 1.0)
        await session.rollback()

    async with local_session_factory() as session:
        amount = await get_cash(session, "USD")
    assert amount == pytest.approx(999_999.0), "rollback did not undo set_cash"


@pytest.mark.asyncio
async def test_adjust_cash_returns_new_total_and_persists():
    """adjust_cash applies the delta atomically and returns the new total."""
    from app.core.cash import adjust_cash, get_cash, set_cash
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as session:
        await set_cash(session, "USD", 1_000.0)
        await session.commit()

    async with local_session_factory() as session:
        new_total = await adjust_cash(session, "USD", 250.0)
        await session.commit()
    assert new_total == pytest.approx(1_250.0)

    async with local_session_factory() as session:
        amount = await get_cash(session, "USD")
    assert amount == pytest.approx(1_250.0)


@pytest.mark.asyncio
async def test_adjust_cash_negative_delta():
    """A negative delta correctly deducts."""
    from app.core.cash import adjust_cash, set_cash
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as session:
        await set_cash(session, "USD", 5_000.0)
        await session.commit()

    async with local_session_factory() as session:
        new_total = await adjust_cash(session, "USD", -1_500.0)
        await session.commit()
    assert new_total == pytest.approx(3_500.0)


@pytest.mark.asyncio
async def test_adjust_cash_inserts_when_row_missing():
    """If no row exists for the currency, adjust_cash inserts at exactly delta.

    This documents (and pins) the contract that callers must seed before they
    expect ``adjust_cash`` to deduct from an existing balance.
    """
    from sqlalchemy import text

    from app.core.cash import adjust_cash, get_cash
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as session:
        await session.execute(text("DELETE FROM cash_balances WHERE currency = 'INR'"))
        await session.commit()

    async with local_session_factory() as session:
        new_total = await adjust_cash(session, "INR", 999.0)
        await session.commit()
    assert new_total == pytest.approx(999.0)

    async with local_session_factory() as session:
        amount = await get_cash(session, "INR")
    assert amount == pytest.approx(999.0)
