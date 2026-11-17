"""Tests for the read-only trade timeline endpoint."""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"

pytestmark = pytest.mark.asyncio

T0 = "2026-10-12 19:28:1{}.000000+00:00"


@pytest.fixture
def client():
    """TestClient over the real app; lifespan seeds the per-test SQLite DB."""
    from fastapi.testclient import TestClient

    from app.main import app

    os.environ.pop("HORIZON_RUN_AGENTS", None)
    with TestClient(app) as test_client:
        yield test_client


def _db():
    return sqlite3.connect(os.path.join(os.environ["HORIZON_DATA_DIR"], "horizon.db"))


def _order(db, oid, side="BUY", status="FILLED", signal_id=None, debate_id=None,
           strategy="sleeve_system", mode="PAPER_TRADING", created=T0.format(5)):
    db.execute(
        "INSERT INTO orders (id, symbol, exchange, order_type, side, quantity, status, broker,"
        " mode, signal_id, debate_id, strategy_name, created_at)"
        " VALUES (?, 'SPY.NYSE', 'NYSE', 'MARKET', ?, 10, ?, 'ALPACA', ?, ?, ?, ?, ?)",
        (oid, side, status, mode, signal_id, debate_id, strategy, created),
    )


def _bus(db, mid, channel, payload, created):
    db.execute(
        "INSERT INTO agent_messages (message_id, sender_id, channel, message_type, payload,"
        " created_at) VALUES (?, 'x', ?, 'signal', ?, ?)",
        (mid, channel, json.dumps(payload), created),
    )


def _steps(client, oid):
    res = client.get(f"/api/desktop/trades/{oid}/timeline")
    assert res.status_code == 200
    return {s["key"]: s for s in res.json()["steps"]}


async def test_unknown_order_is_404(client):
    assert client.get("/api/desktop/trades/nope/timeline").status_code == 404


async def test_id_linked_chain_end_to_end(client):
    db = _db()
    with db:
        db.execute(
            "INSERT INTO signals (signal_id, agent_id, symbol, direction, strength, confidence,"
            " strategy_name, metadata, created_at) VALUES ('s1', 'strat', 'SPY.NYSE', 'BUY',"
            " 0.6, 0.6, 'sleeve_system', '{\"reasoning\": \"sleeve_target 0% -> 33%\"}', ?)",
            (T0.format(1),),
        )
        _bus(db, "m1", "horizon.risk.approved.SPY.NYSE",
             {"signal_id": "s1", "direction": 1, "timestamp": "2026-10-12T19:28:12+00:00"},
             T0.format(2))
        _bus(db, "m2", "horizon.execution.order.new",
             {"signal_id": "s1", "quantity": 10, "allocation_usd": 1000.0}, T0.format(5))
        db.execute(
            "INSERT INTO debate_sessions (id, symbol, proposed_action, status, final_decision,"
            " consensus_score, total_rounds, created_at)"
            " VALUES ('d1', 'SPY.NYSE', 'BUY', 'COMPLETED', 'APPROVED', 0.7, 2, ?)",
            (T0.format(4),),
        )
        db.executemany(
            "INSERT INTO debate_arguments (id, session_id, agent_id, role, vote, round_number)"
            " VALUES (?, 'd1', 'a', 'R', ?, ?)",
            [("v1", "AGAINST", 1), ("v2", "FOR", 2), ("v3", "FOR", 2), ("v4", "AGAINST", 2)],
        )
        _order(db, "o1", signal_id="s1", debate_id="d1")
        db.execute(
            "INSERT INTO fills (id, order_id, filled_qty, fill_price, filled_at)"
            " VALUES ('f1', 'o1', 10, 101.0, ?)", (T0.format(8),),
        )
        db.execute(
            "INSERT INTO positions (id, symbol, exchange, side, quantity, avg_entry_price,"
            " current_price) VALUES ('p1', 'SPY.NYSE', 'NYSE', 'LONG', 10, 101, 110)"
        )
    db.close()

    s = _steps(client, "o1")
    assert [s[k]["status"] for k in ("signal", "risk", "debate", "order", "fill", "pnl")] == [
        "done"] * 6
    assert s["signal"]["detail"]["reasoning"] == "sleeve_target 0% -> 33%"
    assert s["risk"]["detail"]["decision"] == "APPROVED" and s["risk"]["link"] == "id"
    # Votes are the final round only.
    assert s["debate"]["detail"]["votes"] == {"FOR": 2, "AGAINST": 1}
    assert s["debate"]["link"] == "id"
    # Sized at 1000/10 = 100, filled at 101 -> paid 100 bps.
    assert s["fill"]["detail"]["slippage_bps"] == pytest.approx(100.0)
    assert s["pnl"]["detail"]["pnl"] == pytest.approx(90.0)


async def test_unlinked_steps_are_honest(client):
    db = _db()
    with db:
        # BUY without debate_id: nearest same-side debate within the window, marked "time".
        db.execute(
            "INSERT INTO debate_sessions (id, symbol, proposed_action, status, final_decision,"
            " consensus_score, created_at)"
            " VALUES ('d2', 'SPY.NYSE', 'BUY', 'COMPLETED', 'REJECTED', 0.3, ?)",
            (T0.format(6),),
        )
        _order(db, "o2", signal_id="gone")
        # Reconcile SELL: no signal, no risk, no debate, rejected -> nothing filled.
        _order(db, "o3", side="SELL", status="REJECTED", signal_id=None, strategy="reconcile")
    db.close()

    s = _steps(client, "o2")
    assert s["signal"]["status"] == "unknown"
    assert s["risk"]["status"] == "unknown"
    assert s["debate"]["link"] == "time"
    # A REJECTED debate in PAPER_TRADING did not stop the order.
    assert s["debate"]["status"] == "done" and "Not binding" in s["debate"]["note"]
    assert s["fill"]["status"] == "unknown"

    s = _steps(client, "o3")
    assert [s[k]["status"] for k in ("signal", "risk", "debate", "fill", "pnl")] == [
        "skipped"] * 5
    assert s["order"]["status"] == "blocked"
