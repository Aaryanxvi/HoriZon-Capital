"""Morning brief builder: fault-tolerant sections, empty and populated state."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"


@pytest.mark.asyncio
async def test_brief_empty_state():
    from app.core.local_storage import init_local_db
    from app.services.morning_brief import build_morning_brief

    await init_local_db()

    result = await build_morning_brief(orchestrator=None)

    assert isinstance(result, str)
    assert "MORNING BRIEF" in result


@pytest.mark.asyncio
async def test_brief_with_data():
    from sqlalchemy import text

    from app.core.kv_store import get_kv_store
    from app.core.local_storage import init_local_db, local_session_factory
    from app.services.morning_brief import build_morning_brief

    await init_local_db()

    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    now = datetime.now(UTC).isoformat()

    async with local_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO portfolio_snapshots (id, total_value, created_at) "
                "VALUES (:id, :total_value, :created_at)"
            ),
            {"id": str(uuid.uuid4()), "total_value": 100000.0, "created_at": yesterday},
        )
        await session.execute(
            text(
                "INSERT INTO positions "
                "(id, symbol, exchange, side, quantity, avg_entry_price, "
                "current_price, stop_loss_price) "
                "VALUES (:id, :symbol, :exchange, :side, :quantity, "
                ":avg_entry_price, :current_price, :stop_loss_price)"
            ),
            {
                "id": str(uuid.uuid4()),
                "symbol": "AAPL",
                "exchange": "NASDAQ",
                "side": "LONG",
                "quantity": 10.0,
                "avg_entry_price": 95.0,
                "current_price": 100.0,
                "stop_loss_price": 98.0,
            },
        )
        await session.execute(
            text(
                "INSERT INTO debate_sessions "
                "(id, symbol, final_decision, created_at) "
                "VALUES (:id, :symbol, :final_decision, :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "symbol": "AAPL",
                "final_decision": "REJECTED",
                "created_at": now,
            },
        )
        await session.commit()

    kv = get_kv_store()
    await kv.set("horizon:portfolio:nav", "101000")

    result = await build_morning_brief(orchestrator=None)

    assert "AAPL" in result
    assert "REJECTED" in result
    assert "101" in result
    assert "⚠" in result
