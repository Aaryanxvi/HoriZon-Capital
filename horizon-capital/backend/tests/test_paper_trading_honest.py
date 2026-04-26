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
