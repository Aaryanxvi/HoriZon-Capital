# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-F28ABFCF4BCD
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Persistence of HUMAN_APPROVAL pending orders across restarts."""

from __future__ import annotations

import os

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "HUMAN_APPROVAL"


def _make_bus():
    from unittest.mock import AsyncMock, MagicMock

    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    return bus


@pytest.mark.asyncio
async def test_persist_and_rehydrate():
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.local_storage import init_local_db

    await init_local_db()

    a = ExecutionAgent(bus=_make_bus())
    await a._persist_pending(
        {"id": "ord-123", "symbol": "AAPL", "side": "BUY", "quantity": 5, "order_type": "MARKET"}
    )

    b = ExecutionAgent(bus=_make_bus())
    await b._rehydrate_pending()

    assert "ord-123" in b._pending_approval
    assert b._pending_approval["ord-123"]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_delete_pending():
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.local_storage import init_local_db

    await init_local_db()

    a = ExecutionAgent(bus=_make_bus())
    await a._persist_pending(
        {"id": "ord-123", "symbol": "AAPL", "side": "BUY", "quantity": 5, "order_type": "MARKET"}
    )
    await a._delete_pending("ord-123")

    b = ExecutionAgent(bus=_make_bus())
    await b._rehydrate_pending()

    assert b._pending_approval == {}


@pytest.mark.asyncio
async def test_rehydrate_skips_corrupt_rows():
    from sqlalchemy import text

    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()

    async with local_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO pending_approvals (id, payload, created_at)"
                " VALUES (:id, :payload, :ts)"
            ),
            {"id": "bad-order", "payload": "not-json{{{", "ts": "2026-01-01T00:00:00+00:00"},
        )
        await session.execute(
            text(
                "INSERT INTO pending_approvals (id, payload, created_at)"
                " VALUES (:id, :payload, :ts)"
            ),
            {
                "id": "good-order",
                "payload": '{"id": "good-order", "symbol": "MSFT"}',
                "ts": "2026-01-01T00:00:00+00:00",
            },
        )
        await session.commit()

    a = ExecutionAgent(bus=_make_bus())
    await a._rehydrate_pending()

    assert "good-order" in a._pending_approval
    assert "bad-order" not in a._pending_approval
    assert len(a._pending_approval) == 1


@pytest.mark.asyncio
async def test_reject_removes_persisted():
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.local_storage import init_local_db

    await init_local_db()

    a = ExecutionAgent(bus=_make_bus())
    order = await a.order_manager.create_order(
        {
            "symbol": "TSLA",
            "exchange": "NASDAQ",
            "order_type": "MARKET",
            "side": "BUY",
            "quantity": 3,
            "broker": "PAPER",
            "mode": "HUMAN_APPROVAL",
        }
    )
    order_id = order["id"]
    a._pending_approval[order_id] = order
    await a._persist_pending(order)

    ok = await a.reject_order(order_id[:8])
    assert ok is True

    b = ExecutionAgent(bus=_make_bus())
    await b._rehydrate_pending()

    assert b._pending_approval == {}
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token F28ABFCF4BCD - verify with scripts/authorship.py verify
