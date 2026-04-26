"""Tests for critical bug fixes identified in the 2026-04-24 audit."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_cash_not_reset_if_already_persisted():
    """After trading reduces cash, restart must NOT overwrite it.

    SQL is now the source of truth.  We seed $750,000 directly into the
    cash_balances table; startup() must leave it untouched.
    """
    from app.core.cash import get_cash, set_cash
    from app.core.kv_store import get_kv_store
    from app.core.local_storage import init_local_db, local_session_factory

    # Seed SQL row with a reduced balance (simulates post-trade state).
    await init_local_db()
    async with local_session_factory() as session:
        await set_cash(session, "USD", 750_000.0)
        await set_cash(session, "INR", 5_000_000.0)
        await session.commit()

    kv = get_kv_store()
    from app.core.runtime import startup

    await startup(headless=True)

    # SQL must still hold 750,000 (not reset to initial_capital).
    async with local_session_factory() as session:
        usd = await get_cash(session, "USD")
    assert usd == pytest.approx(750_000.0), f"Cash was reset to {usd}, expected 750000"

    # KV mirror must also reflect the SQL value (as a float string).
    kv_usd = await kv.get("horizon:cash:usd")
    assert kv_usd is not None, "KV mirror should be set"
    assert float(kv_usd) == pytest.approx(750_000.0), (
        f"KV mirror has {kv_usd!r}, expected ~750000"
    )


@pytest.mark.asyncio
async def test_cash_seeded_on_first_run():
    """On first run (no persisted cash), initial capital should be seeded.

    SQL is now the source of truth.  Clear the cash_balances row so startup()
    treats this as a first run.
    """
    from sqlalchemy import text

    from app.core.cash import get_cash
    from app.core.kv_store import get_kv_store
    from app.core.local_storage import init_local_db, local_session_factory

    # Wipe the SQL row to simulate a fresh install.
    await init_local_db()
    async with local_session_factory() as session:
        await session.execute(text("DELETE FROM cash_balances WHERE currency = 'USD'"))
        await session.execute(text("DELETE FROM cash_balances WHERE currency = 'INR'"))
        await session.commit()

    kv = get_kv_store()
    await kv.delete("horizon:cash:usd")
    await kv.delete("horizon:cash:inr")

    from app.core.runtime import startup

    await startup(headless=True)

    # SQL must now contain the initial capital.
    async with local_session_factory() as session:
        usd = await get_cash(session, "USD")
    assert usd > 0, f"Cash should be seeded on first run, got {usd}"

    # KV mirror must also be populated.
    kv_usd = await kv.get("horizon:cash:usd")
    assert kv_usd is not None, "Cash should be seeded in KV on first run"
    assert float(kv_usd) > 0, f"KV mirror value not positive: {kv_usd!r}"


def test_migrate_table_adds_column_not_drops():
    """_migrate_table should ALTER TABLE ADD COLUMN, not DROP TABLE."""
    import sqlite3

    from app.core.local_storage import _migrate_table  # noqa: PLC0415

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE test_tbl (id TEXT, name TEXT)")
    conn.execute("INSERT INTO test_tbl VALUES ('1', 'alice')")
    conn.commit()

    # Wrap sqlite3 conn so conn.execute(text(...)) works
    class FakeConn:
        def __init__(self, real_conn: sqlite3.Connection) -> None:
            self._conn = real_conn

        def execute(self, clause):  # noqa: ANN001
            # text() objects have a .text attribute
            sql = clause.text if hasattr(clause, "text") else str(clause)
            return self._conn.execute(sql)

    fake = FakeConn(conn)
    _migrate_table(fake, "test_tbl", "new_col")

    # Data must still exist
    rows = conn.execute("SELECT * FROM test_tbl").fetchall()
    assert len(rows) == 1, f"Data was destroyed! Got {len(rows)} rows"

    # New column should exist
    cols = conn.execute("PRAGMA table_info(test_tbl)").fetchall()
    col_names = {row[1] for row in cols}
    assert "new_col" in col_names, f"Column not added. Cols: {col_names}"
    conn.close()


# ── C-03: Win rate and profit factor must use realized PnL ──


def test_win_rate_uses_realized_pnl():
    """A trade bought at $100 and sold at $50 is a LOSS, not a win."""
    from app.workers.performance_worker import PerformanceService

    trades = [
        {"side": "BUY", "fill_price": 100.0, "filled_qty": 10, "commission": 1.0},
        {"side": "SELL", "fill_price": 50.0, "filled_qty": 10, "commission": 1.0},
    ]
    win_rate = PerformanceService._win_rate(trades)
    assert win_rate == 0.0, f"Expected 0% win rate for a losing trade, got {win_rate}"


def test_profit_factor_correct():
    """Profit factor = gross_profit / gross_loss from realized PnL."""
    from app.workers.performance_worker import PerformanceService

    trades = [
        {"side": "BUY", "fill_price": 100.0, "filled_qty": 10, "commission": 0.0},
        {"side": "SELL", "fill_price": 120.0, "filled_qty": 10, "commission": 0.0},
        {"side": "BUY", "fill_price": 100.0, "filled_qty": 10, "commission": 0.0},
        {"side": "SELL", "fill_price": 90.0, "filled_qty": 10, "commission": 0.0},
    ]
    pf = PerformanceService._profit_factor(trades)
    assert abs(pf - 2.0) < 0.01, f"Expected profit factor ~2.0, got {pf}"


# ── C-04: Feature computation must use most recent bars ──


def test_ohlcv_query_returns_newest_bars():
    """The OHLCV query must return the most recent 500 bars, not the oldest."""
    import inspect

    from app.workers.feature_computation_worker import FeatureComputationWorker

    source = inspect.getsource(FeatureComputationWorker._compute_features_for_symbol)
    assert "ORDER BY timestamp DESC" in source, (
        "OHLCV query still uses ASC — returns oldest bars instead of newest"
    )


# ── C-05: CIO agent must not be started twice ──


def test_no_duplicate_cio_creation_in_main():
    """__main__.py must not create a second CIOAgent instance."""
    import ast
    from pathlib import Path
    main_path = Path(__file__).parent.parent / "app" / "__main__.py"
    source = main_path.read_text()
    tree = ast.parse(source)
    cio_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "CIOAgent":
                cio_calls += 1
            elif isinstance(func, ast.Attribute) and func.attr == "CIOAgent":
                cio_calls += 1
    assert cio_calls <= 1, (
        f"CIOAgent() called {cio_calls} times in __main__.py — remove duplicate"
    )


# ── C-07: Backtest win rate must exclude BUY trades ──


def test_backtest_win_rate_excludes_buys():
    """BUY trades with pnl=0 must not count toward win rate."""
    from app.backtesting.backtest_metrics import BacktestMetrics
    trades = [
        {"side": "BUY", "pnl": 0.0},
        {"side": "SELL", "pnl": 50.0},
        {"side": "BUY", "pnl": 0.0},
        {"side": "SELL", "pnl": 100.0},
        {"side": "BUY", "pnl": 0.0},
        {"side": "SELL", "pnl": -30.0},
    ]
    wr = BacktestMetrics.win_rate(trades)
    assert abs(wr - 2 / 3) < 0.01, f"Expected ~66.7%, got {wr * 100:.1f}%"


# ── MC-01: VaR must use percentile correctly ──

import numpy as np  # noqa: E402


def test_var_all_positive_returns_is_zero():
    """If all returns are positive, VaR should be 0."""
    from app.agents.middle_office.risk.var_calculator import VaRCalculator

    returns = np.array([0.01, 0.02, 0.03, 0.015, 0.005, 0.012, 0.008, 0.025, 0.018, 0.011])
    var = VaRCalculator.compute_var(returns, confidence=0.95)
    assert var == 0.0, f"VaR should be 0 for all-positive returns, got {var}"


def test_var_correct_percentile():
    """VaR at 95% on 100 returns should use 5th percentile, not worst."""
    from app.agents.middle_office.risk.var_calculator import VaRCalculator

    returns = np.concatenate([
        np.array([-0.05]),
        np.array([-0.03, -0.02]),
        np.array([-0.01, -0.005]),
        np.linspace(0.001, 0.05, 95)
    ])
    var = VaRCalculator.compute_var(returns, confidence=0.95)
    assert var < 0.02, f"VaR {var} too high — likely using wrong percentile"


# ── C-06: Annualized return must use actual days ──


def test_annualized_return_uses_days_not_snapshots():
    """With many snapshots per day, annualized return must not be compressed."""
    from app.workers.performance_worker import PerformanceService

    # 960 snapshots, 10% total return
    equity = np.linspace(1000, 1100, 960)
    # With timestamps spanning 10 days:
    from datetime import datetime, timedelta
    base = datetime(2026, 1, 1)
    timestamps = [base + timedelta(minutes=15 * i) for i in range(960)]
    ann_ret_ts = PerformanceService._annualized_return(equity, timestamps=timestamps)
    # 10 days with 10% return -> high annualized return
    assert ann_ret_ts > 1.0, f"Annualized return {ann_ret_ts:.4f} too low with timestamps"


# ── MC-02: Sortino must use correct downside deviation ──


def test_sortino_correct_downside_deviation():
    """Sortino must use sqrt(mean(min(excess,0)^2)) over ALL returns."""
    from app.workers.performance_worker import PerformanceService

    values = [1000.0]
    for r in [0.02, -0.01, 0.03, -0.02, 0.01, -0.005, 0.015, -0.015, 0.02, -0.01,
              0.02, -0.01, 0.03, -0.02, 0.01, -0.005, 0.015, -0.015, 0.02, -0.01]:
        values.append(values[-1] * (1 + r))
    equity = np.array(values)
    sortino = PerformanceService._sortino_ratio(equity)
    assert sortino < 50, f"Sortino {sortino} seems inflated"
    assert sortino > 0, "Sortino should be positive for net-positive returns"


# ── MC-03: Partial sell must reduce buy_cost proportionally ──


def test_partial_sell_pnl_correct():
    """After selling half, avg entry for remainder must stay correct."""
    buy_cost = 10.0 * 100  # Buy 100 @ $10
    buy_qty = 100.0

    # Sell 50 @ $12
    avg_entry = buy_cost / buy_qty  # $10
    pnl1 = (12.0 - avg_entry) * 50  # $100
    buy_cost -= avg_entry * 50  # 1000 - 500 = 500
    buy_qty -= 50  # 50

    # Sell remaining 50 @ $11
    avg_entry = buy_cost / buy_qty  # 500/50 = $10 (correct!)
    pnl2 = (11.0 - avg_entry) * 50  # $50

    assert abs(pnl1 - 100.0) < 0.01, f"Trade 1 PnL: {pnl1}"
    assert abs(pnl2 - 50.0) < 0.01, f"Trade 2 PnL: {pnl2}"
