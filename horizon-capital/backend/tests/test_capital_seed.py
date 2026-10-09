# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-8850EB1CB8E3
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Startup capital seeding must never create money from nothing.

Regression: ``existing_usd <= 0`` used to re-seed INITIAL_CAPITAL on every restart
of a fully-invested book while keeping its positions (seen live: $100k phantom cash
next to 19 open positions).
"""

from __future__ import annotations

import os

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"


async def _ledger(cash_usd: float, positions: int) -> None:
    from sqlalchemy import text

    from app.core.cash import set_cash
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as session:
        await session.execute(text("DELETE FROM positions"))
        for i in range(positions):
            await session.execute(text(
                "INSERT INTO positions (id, symbol, exchange, side, quantity, avg_entry_price)"
                " VALUES (:id, :sym, 'NASDAQ', 'LONG', 10, 100)"
            ), {"id": f"p{i}", "sym": f"SYM{i}"})
        await set_cash(session, "USD", cash_usd)
        await session.commit()


async def _cash() -> float:
    from app.core.cash import get_cash
    from app.core.local_storage import local_session_factory

    async with local_session_factory() as session:
        return await get_cash(session, "USD")


@pytest.mark.asyncio
async def test_zero_cash_fully_invested_is_not_reseeded_on_restart():
    from app.core.kv_store import get_kv_store
    from app.core.runtime import startup

    await _ledger(cash_usd=0.0, positions=1)
    kv = get_kv_store()
    await kv.set("horizon:portfolio:nav", "1000.0")  # restored NAV incl. the position

    await startup(headless=True)

    assert await _cash() == 0.0
    assert await kv.get("horizon:portfolio:nav") == "1000.0"  # not clobbered to cash


@pytest.mark.asyncio
async def test_forced_reseed_refused_while_positions_open_applied_when_flat(monkeypatch):
    from app.config import settings
    from app.core.runtime import startup

    monkeypatch.setattr(settings, "initial_capital_usd", 250_000.0)

    await _ledger(cash_usd=5.0, positions=2)
    monkeypatch.setenv("HORIZON_FORCE_RESEED_CAPITAL", "1")
    await startup(headless=True)
    assert await _cash() == 5.0

    await _ledger(cash_usd=5.0, positions=0)
    monkeypatch.setenv("HORIZON_FORCE_RESEED_CAPITAL", "1")
    await startup(headless=True)
    assert await _cash() == 250_000.0
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 8850EB1CB8E3 - verify with scripts/authorship.py verify
