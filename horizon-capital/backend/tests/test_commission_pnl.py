"""Commission-correct realized P&L: commission reduces positions.realized_pnl
on every fill (opening and closing legs alike), matching cash exactly."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_buy_then_sell_realized_pnl_nets_commission():
    """BUY 10@100 (comm 1.0) then SELL 10@110 (comm 1.1): realized == -1.0 + 100 - 1.1."""
    from sqlalchemy import text

    from app.agents.front_office.trading.order_manager import OrderManager
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    om = OrderManager()

    async with local_session_factory() as s:
        await s.execute(text("DELETE FROM positions WHERE symbol = 'COMM_TEST_LONG'"))
        await s.commit()

    await om.update_position(
        symbol="COMM_TEST_LONG", exchange="", side="BUY",
        qty=10, price=100.0, commission=1.0,
    )

    async with local_session_factory() as s:
        row = (await s.execute(
            text("SELECT realized_pnl FROM positions WHERE symbol = 'COMM_TEST_LONG'"),
        )).fetchone()
    assert row.realized_pnl == pytest.approx(-1.0)

    await om.update_position(
        symbol="COMM_TEST_LONG", exchange="", side="SELL",
        qty=10, price=110.0, commission=1.1,
    )

    async with local_session_factory() as s:
        row = (await s.execute(
            text("SELECT realized_pnl FROM positions WHERE symbol = 'COMM_TEST_LONG'"),
        )).fetchone()
    assert row.realized_pnl == pytest.approx(-1.0 + 100 - 1.1)


@pytest.mark.asyncio
async def test_short_open_then_cover_realized_pnl_nets_commission():
    """SELL-open 10@100 (comm 1.0) then BUY-cover 10@90 (comm 0.9): same convention."""
    from sqlalchemy import text

    from app.agents.front_office.trading.order_manager import OrderManager
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    om = OrderManager()

    async with local_session_factory() as s:
        await s.execute(text("DELETE FROM positions WHERE symbol = 'COMM_TEST_SHORT'"))
        await s.commit()

    await om.update_position(
        symbol="COMM_TEST_SHORT", exchange="", side="SELL",
        qty=10, price=100.0, commission=1.0,
    )

    async with local_session_factory() as s:
        row = (await s.execute(
            text("SELECT realized_pnl FROM positions WHERE symbol = 'COMM_TEST_SHORT'"),
        )).fetchone()
    assert row.realized_pnl == pytest.approx(-1.0)

    await om.update_position(
        symbol="COMM_TEST_SHORT", exchange="", side="BUY",
        qty=10, price=90.0, commission=0.9,
    )

    async with local_session_factory() as s:
        row = (await s.execute(
            text("SELECT realized_pnl FROM positions WHERE symbol = 'COMM_TEST_SHORT'"),
        )).fetchone()
    # covering short: realized_delta = (old_avg - price) * qty = (100-90)*10 = 100
    assert row.realized_pnl == pytest.approx(-1.0 + 100 - 0.9)
