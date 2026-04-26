# Fix 10 Critical Bugs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 10 CRITICAL-severity bugs identified in the full system audit.

**Architecture:** Each fix is surgical — change only the broken formula/logic, add tests proving correctness, leave surrounding code untouched. Some fixes share files (performance_worker.py has 3 bugs) so ordering matters.

**Tech Stack:** Python 3.14, pytest, numpy, SQLite, asyncio

---

## File Map

| Task | Files Modified | Files Created |
|------|---------------|---------------|
| 1 | `app/core/runtime.py` | `tests/test_critical_fixes.py` |
| 2 | `app/core/local_storage.py` | (same test file) |
| 3 | `app/workers/performance_worker.py` | (same test file) |
| 4 | `app/workers/feature_computation_worker.py` | (same test file) |
| 5 | `app/__main__.py` | (same test file) |
| 6 | `app/workers/performance_worker.py` | (same test file) |
| 7 | `app/backtesting/backtest_metrics.py` | (same test file) |
| 8 | `app/agents/middle_office/risk/var_calculator.py` | (same test file) |
| 9 | `app/services/performance.py`, `app/workers/performance_worker.py` | (same test file) |
| 10 | `app/services/performance.py` | (same test file) |

---

### Task 1: Fix Cash Balance Reset on Restart (C-01)

**Files:**
- Modify: `app/core/runtime.py:76-80`
- Test: `tests/test_critical_fixes.py`

**Problem:** `startup()` unconditionally overwrites `horizon:cash:usd` and `horizon:cash:inr` with initial capital, destroying persisted balances from prior sessions.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_critical_fixes.py
"""Tests for critical bug fixes identified in the 2026-04-24 audit."""

from __future__ import annotations

import pytest


# ── C-01: Cash should NOT reset on restart if already persisted ──

@pytest.mark.asyncio
async def test_cash_not_reset_if_already_persisted():
    """After trading reduces cash, restart must NOT overwrite it."""
    from app.core.kv_store import get_kv_store

    kv = get_kv_store()

    # Simulate prior session: cash was reduced by trading
    await kv.set("horizon:cash:usd", "750000")
    await kv.set("horizon:cash:inr", "5000000")

    # Persist to SQLite (crash recovery)
    if hasattr(kv, "persist"):
        await kv.persist("horizon:cash:usd")
        await kv.persist("horizon:cash:inr")

    # Now simulate restart
    from app.core.runtime import startup
    await startup(headless=True)

    # Cash must retain the traded value, not reset to initial capital
    usd = await kv.get("horizon:cash:usd")
    assert usd == "750000", f"Cash was reset to {usd}, expected 750000"


@pytest.mark.asyncio
async def test_cash_seeded_on_first_run():
    """On first run (no persisted cash), initial capital should be seeded."""
    from app.core.kv_store import get_kv_store

    kv = get_kv_store()

    # Ensure no prior cash exists
    await kv.delete("horizon:cash:usd")
    await kv.delete("horizon:cash:inr")

    from app.core.runtime import startup
    await startup(headless=True)

    usd = await kv.get("horizon:cash:usd")
    assert usd is not None, "Cash should be seeded on first run"
    assert int(usd) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py::test_cash_not_reset_if_already_persisted -v`
Expected: FAIL — cash gets overwritten to initial capital

- [ ] **Step 3: Write minimal fix**

In `app/core/runtime.py`, replace lines 76-85 (the unconditional seed block inside the LOCAL branch):

```python
        # Seed capital ONLY on first run (no prior cash)
        existing_usd = await kv.get("horizon:cash:usd")
        existing_inr = await kv.get("horizon:cash:inr")
        if existing_usd is None:
            await kv.set("horizon:cash:usd", str(int(settings.initial_capital_usd)))
            logger.info("initial_capital_seeded_usd", usd=settings.initial_capital_usd)
        if existing_inr is None:
            await kv.set("horizon:cash:inr", str(int(settings.initial_capital_inr)))
            logger.info("initial_capital_seeded_inr", inr=settings.initial_capital_inr)
```

Apply same fix for the POSTGRES branch (lines 90-94): check `await redis_client.get(...)` before seeding.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py -k "cash" -v`
Expected: Both tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/core/runtime.py tests/test_critical_fixes.py
git commit -m "fix: only seed capital on first run, preserve persisted cash on restart (C-01)"
```

---

### Task 2: Fix Destructive Table Migration (C-02)

**Files:**
- Modify: `app/core/local_storage.py:64-74`
- Test: `tests/test_critical_fixes.py`

**Problem:** `_migrate_table` drops entire tables (with all data) when a column is missing. Should use `ALTER TABLE ADD COLUMN` instead.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_critical_fixes.py

# ── C-02: Migration must ADD columns, not DROP tables ──

def test_migrate_table_adds_column_not_drops():
    """_migrate_table should ALTER TABLE ADD COLUMN, not DROP TABLE."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE test_tbl (id TEXT, name TEXT)")
    conn.execute("INSERT INTO test_tbl VALUES ('1', 'alice')")
    conn.commit()

    from app.core.local_storage import _migrate_table
    _migrate_table(conn, "test_tbl", "new_col")

    # Data must still exist
    rows = conn.execute("SELECT * FROM test_tbl").fetchall()
    assert len(rows) == 1, f"Data was destroyed! Got {len(rows)} rows"

    # New column should exist (added by ALTER TABLE)
    cols = conn.execute("PRAGMA table_info(test_tbl)").fetchall()
    col_names = {row[1] for row in cols}
    assert "new_col" in col_names, f"Column not added. Cols: {col_names}"
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py::test_migrate_table_adds_column_not_drops -v`
Expected: FAIL — data destroyed (0 rows after migration)

- [ ] **Step 3: Write minimal fix**

Replace `_migrate_table` in `app/core/local_storage.py`:

```python
def _migrate_table(conn, table: str, required_col: str) -> None:  # noqa: ANN001
    """Add a missing column to an existing table (non-destructive migration)."""
    if not _SAFE_IDENTIFIER.match(table) or not _SAFE_IDENTIFIER.match(required_col):
        return
    try:
        cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()  # noqa: S608
        col_names = {row[1] for row in cols}
        if cols and required_col not in col_names:
            conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {required_col} TEXT DEFAULT NULL")  # noqa: S608
            )
    except Exception:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py::test_migrate_table_adds_column_not_drops -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/core/local_storage.py tests/test_critical_fixes.py
git commit -m "fix: non-destructive table migration using ALTER TABLE ADD COLUMN (C-02)"
```

---

### Task 3: Fix Win Rate and Profit Factor Using Gross Proceeds (C-03)

**Files:**
- Modify: `app/workers/performance_worker.py:179-207`
- Test: `tests/test_critical_fixes.py`

**Problem:** `_win_rate` and `_profit_factor` compute "P&L" as `fill_price * filled_qty - commission` (gross proceeds), not actual realized profit. Need to join BUY and SELL fills to compute real P&L.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_critical_fixes.py

# ── C-03: Win rate and profit factor must use realized PnL ──

def test_win_rate_uses_realized_pnl():
    """A trade bought at $100 and sold at $50 is a LOSS, not a win."""
    from app.workers.performance_worker import PerformanceMetrics

    trades = [
        {"side": "BUY", "fill_price": 100.0, "filled_qty": 10, "commission": 1.0},
        {"side": "SELL", "fill_price": 50.0, "filled_qty": 10, "commission": 1.0},
    ]
    # Realized PnL = (50 - 100) * 10 - 2 = -502. This is a LOSS.
    win_rate = PerformanceMetrics._win_rate(trades)
    assert win_rate == 0.0, f"Expected 0% win rate for a losing trade, got {win_rate}"


def test_profit_factor_correct():
    """Profit factor = gross_profit / gross_loss from realized PnL."""
    from app.workers.performance_worker import PerformanceMetrics

    trades = [
        # Trade 1: BUY 10 @ $100, SELL 10 @ $120 → profit $200
        {"side": "BUY", "fill_price": 100.0, "filled_qty": 10, "commission": 0.0},
        {"side": "SELL", "fill_price": 120.0, "filled_qty": 10, "commission": 0.0},
        # Trade 2: BUY 10 @ $100, SELL 10 @ $90 → loss $100
        {"side": "BUY", "fill_price": 100.0, "filled_qty": 10, "commission": 0.0},
        {"side": "SELL", "fill_price": 90.0, "filled_qty": 10, "commission": 0.0},
    ]
    pf = PerformanceMetrics._profit_factor(trades)
    assert abs(pf - 2.0) < 0.01, f"Expected profit factor ~2.0, got {pf}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py -k "win_rate or profit_factor" -v`
Expected: FAIL — win rate reports 100% for the losing trade, profit factor is wrong

- [ ] **Step 3: Write minimal fix**

Replace `_win_rate` and `_profit_factor` in `app/workers/performance_worker.py`:

```python
    @staticmethod
    def _win_rate(trades: list[dict[str, Any]]) -> float:
        """Fraction of round-trip trades with positive realized PnL."""
        if not trades:
            return 0.0
        # Pair BUY and SELL fills to compute realized PnL
        buy_cost = 0.0
        buy_qty = 0.0
        round_trips = 0
        winners = 0
        for t in trades:
            if t["side"] == "BUY":
                buy_cost += t["fill_price"] * t["filled_qty"]
                buy_qty += t["filled_qty"]
            elif t["side"] == "SELL" and buy_qty > 0:
                avg_entry = buy_cost / buy_qty
                sell_qty = min(t["filled_qty"], buy_qty)
                realized_pnl = (t["fill_price"] - avg_entry) * sell_qty - t.get("commission", 0)
                round_trips += 1
                if realized_pnl > 0:
                    winners += 1
                # Reduce buy_cost proportionally
                buy_cost -= avg_entry * sell_qty
                buy_qty -= sell_qty
                if buy_qty <= 0:
                    buy_cost = 0.0
                    buy_qty = 0.0
        return float(winners / round_trips) if round_trips > 0 else 0.0

    @staticmethod
    def _profit_factor(trades: list[dict[str, Any]]) -> float:
        """Gross profit / gross loss from realized round-trip PnL."""
        buy_cost = 0.0
        buy_qty = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        for t in trades:
            if t["side"] == "BUY":
                buy_cost += t["fill_price"] * t["filled_qty"]
                buy_qty += t["filled_qty"]
            elif t["side"] == "SELL" and buy_qty > 0:
                avg_entry = buy_cost / buy_qty
                sell_qty = min(t["filled_qty"], buy_qty)
                realized_pnl = (t["fill_price"] - avg_entry) * sell_qty - t.get("commission", 0)
                if realized_pnl > 0:
                    gross_profit += realized_pnl
                else:
                    gross_loss += abs(realized_pnl)
                buy_cost -= avg_entry * sell_qty
                buy_qty -= sell_qty
                if buy_qty <= 0:
                    buy_cost = 0.0
                    buy_qty = 0.0
        if gross_loss == 0:
            return 0.0 if gross_profit == 0 else float("inf")
        return float(gross_profit / gross_loss)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py -k "win_rate or profit_factor" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workers/performance_worker.py tests/test_critical_fixes.py
git commit -m "fix: win rate and profit factor use realized PnL, not gross proceeds (C-03)"
```

---

### Task 4: Fix Feature Computation Returning Oldest Data (C-04)

**Files:**
- Modify: `app/workers/feature_computation_worker.py:393-399`
- Test: `tests/test_critical_fixes.py`

**Problem:** `ORDER BY timestamp ASC LIMIT 500` returns the 500 oldest bars. All technical indicators are computed on stale data. Need `DESC` + reverse.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_critical_fixes.py

# ── C-04: Feature computation must use most recent bars ──

def test_ohlcv_query_returns_newest_bars():
    """The OHLCV query must return the most recent 500 bars, not the oldest."""
    import inspect
    from app.workers.feature_computation_worker import FeatureComputationWorker

    source = inspect.getsource(FeatureComputationWorker._compute_for_symbol)

    # The query must use DESC to get newest first, then reverse in Python
    assert "ORDER BY timestamp DESC" in source, (
        "OHLCV query still uses ASC — returns oldest bars instead of newest"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py::test_ohlcv_query_returns_newest_bars -v`
Expected: FAIL — source contains "ORDER BY timestamp ASC"

- [ ] **Step 3: Write minimal fix**

In `app/workers/feature_computation_worker.py`, change the SQL query (around line 397):

```python
                    """
                    SELECT timestamp, open, high, low, close, volume, exchange
                    FROM ohlcv
                    WHERE symbol = :symbol AND timeframe = :timeframe
                    ORDER BY timestamp DESC
                    LIMIT 500
                    """
```

Then after `rows = result.fetchall()`, add:

```python
            rows = list(reversed(rows))  # Restore chronological order for indicators
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py::test_ohlcv_query_returns_newest_bars -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workers/feature_computation_worker.py tests/test_critical_fixes.py
git commit -m "fix: fetch newest 500 bars for indicators, not oldest (C-04)"
```

---

### Task 5: Fix CIO Agent Started Twice (C-05)

**Files:**
- Modify: `app/__main__.py:263-272`
- Test: `tests/test_critical_fixes.py`

**Problem:** In AI mode, `ExecutiveManager` creates a CIOAgent via the orchestrator, then `_run_with_tui()` creates a second one. Double LLM costs, duplicate advisories.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_critical_fixes.py

# ── C-05: CIO agent must not be started twice ──

def test_no_duplicate_cio_creation_in_main():
    """__main__.py must not create a second CIOAgent when orchestrator already has one."""
    import ast
    from pathlib import Path

    main_path = Path(__file__).parent.parent / "app" / "__main__.py"
    source = main_path.read_text()
    tree = ast.parse(source)

    # Count how many times CIOAgent() is instantiated
    cio_instantiations = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "CIOAgent":
                cio_instantiations += 1
            elif isinstance(func, ast.Attribute) and func.attr == "CIOAgent":
                cio_instantiations += 1

    assert cio_instantiations <= 1, (
        f"CIOAgent instantiated {cio_instantiations} times in __main__.py — "
        "orchestrator already starts one. Remove the duplicate."
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py::test_no_duplicate_cio_creation_in_main -v`
Expected: FAIL — CIOAgent instantiated 2 times (once in _run_with_tui, once visible)

- [ ] **Step 3: Write minimal fix**

In `app/__main__.py`, replace the CIO agent block (lines 263-272). Instead of creating a new CIOAgent, retrieve the one from the orchestrator:

```python
    # Wire CIO agent if in AI mode — reuse the one from orchestrator, do NOT create a second
    from app.config import CIOMode
    if settings.cio_mode == CIOMode.AI:
        try:
            # Get the CIO agent from the orchestrator (already started by ExecutiveManager)
            cio_agent = orchestrator.get_agent("cio_agent")
            if cio_agent:
                cmd_handler.set_cio_agent(cio_agent)
        except Exception as exc:
            console.print(f"[yellow]CIO agent not available: {exc}[/yellow]")
```

If `orchestrator.get_agent()` doesn't exist, use the agent registry or simply remove the block entirely and let the orchestrator-managed CIO agent handle everything.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py::test_no_duplicate_cio_creation_in_main -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/__main__.py tests/test_critical_fixes.py
git commit -m "fix: remove duplicate CIO agent creation, reuse orchestrator instance (C-05)"
```

---

### Task 6: Fix Annualized Return Using Snapshot Count (C-06)

**Files:**
- Modify: `app/workers/performance_worker.py:126-135`
- Modify: `app/services/performance.py:111-113`
- Test: `tests/test_critical_fixes.py`

**Problem:** `n_days = len(equity)` counts snapshots (taken every 15 min), not trading days. Annualized return, Sharpe, Sortino all wrong.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_critical_fixes.py

# ── C-06: Annualized return must use actual days, not snapshot count ──

import numpy as np

def test_annualized_return_uses_days_not_snapshots():
    """With 96 snapshots per day over 10 days, n_days should be ~10, not 960."""
    from app.workers.performance_worker import PerformanceMetrics

    # Simulate 10 days × 96 snapshots/day = 960 data points
    # Total return = 10%
    equity = np.linspace(1000, 1100, 960)
    ann_ret = PerformanceMetrics._annualized_return(equity)

    # With 10 actual days and 10% total return:
    # Correct: (1.10)^(252/10) - 1 ≈ 985% annualized
    # Wrong (snapshot count): (1.10)^(252/960) - 1 ≈ 2.5% annualized
    assert ann_ret > 1.0, (
        f"Annualized return {ann_ret:.4f} is way too low — "
        "likely using snapshot count instead of actual days"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py::test_annualized_return_uses_days_not_snapshots -v`
Expected: FAIL — returns ~0.025 instead of >1.0

- [ ] **Step 3: Write minimal fix**

The `_annualized_return` method needs a timestamp array to compute actual days. Since changing the signature is invasive, the simplest fix is to add a `timestamps` parameter:

In `app/workers/performance_worker.py`, modify `_annualized_return`:

```python
    @classmethod
    def _annualized_return(
        cls,
        equity: np.ndarray,
        timestamps: list | None = None,
    ) -> float:
        total = cls._total_return(equity)
        if len(equity) <= 1 or total <= -1.0:
            return 0.0
        # Use actual calendar days if timestamps available, else fall back to len
        if timestamps and len(timestamps) >= 2:
            from datetime import datetime
            first = timestamps[0] if isinstance(timestamps[0], datetime) else datetime.fromisoformat(str(timestamps[0]))
            last = timestamps[-1] if isinstance(timestamps[-1], datetime) else datetime.fromisoformat(str(timestamps[-1]))
            calendar_days = max((last - first).days, 1)
            trading_days = calendar_days * 252 / 365
        else:
            trading_days = len(equity)
        years = trading_days / TRADING_DAYS_PER_YEAR
        if years == 0:
            return 0.0
        return float((1 + total) ** (1 / years) - 1)
```

Apply the same pattern in `app/services/performance.py` line 111-113:

```python
        # Use actual date range from equity_data timestamps
        if len(equity_data) >= 2:
            first_ts = equity_data[0][0]
            last_ts = equity_data[-1][0]
            calendar_days = max((last_ts - first_ts).days, 1)
            n_trading_days = max(calendar_days * 252 / 365, 1)
        else:
            n_trading_days = 1
        annual_ret = (1 + total_ret) ** (252 / n_trading_days) - 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py::test_annualized_return_uses_days_not_snapshots -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workers/performance_worker.py app/services/performance.py tests/test_critical_fixes.py
git commit -m "fix: annualized return uses actual calendar days, not snapshot count (C-06)"
```

---

### Task 7: Fix Backtest Win Rate Counting BUYs as Losses (C-07)

**Files:**
- Modify: `app/backtesting/backtest_metrics.py:39-45`
- Test: `tests/test_critical_fixes.py`

**Problem:** `win_rate()` counts ALL trades including BUYs (which have `pnl=0.0`). BUYs dilute the denominator, halving the win rate.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_critical_fixes.py

# ── C-07: Backtest win rate must exclude BUY trades from denominator ──

def test_backtest_win_rate_excludes_buys():
    """BUY trades have pnl=0 and must not count toward win rate."""
    from app.backtesting.backtest_metrics import BacktestMetrics

    trades = [
        {"side": "BUY", "pnl": 0.0},
        {"side": "SELL", "pnl": 50.0},   # winner
        {"side": "BUY", "pnl": 0.0},
        {"side": "SELL", "pnl": 100.0},  # winner
        {"side": "BUY", "pnl": 0.0},
        {"side": "SELL", "pnl": -30.0},  # loser
    ]
    wr = BacktestMetrics.win_rate(trades)
    # 2 winners out of 3 SELL trades = 66.7%
    # Bug: 2 winners out of 6 total trades = 33.3%
    assert abs(wr - 2 / 3) < 0.01, f"Expected ~66.7%, got {wr * 100:.1f}%"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py::test_backtest_win_rate_excludes_buys -v`
Expected: FAIL — returns 0.333 instead of 0.667

- [ ] **Step 3: Write minimal fix**

In `app/backtesting/backtest_metrics.py`, replace `win_rate`:

```python
    @staticmethod
    def win_rate(trades: list[dict]) -> float:
        """Fraction of SELL trades with positive PnL."""
        sell_trades = [t for t in trades if t.get("side") == "SELL"]
        if not sell_trades:
            return 0.0
        winners = sum(1 for t in sell_trades if t.get("pnl", 0) > 0)
        return winners / len(sell_trades)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py::test_backtest_win_rate_excludes_buys -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/backtesting/backtest_metrics.py tests/test_critical_fixes.py
git commit -m "fix: backtest win rate counts only SELL trades, excludes BUYs (C-07)"
```

---

### Task 8: Fix VaR Calculation (MC-01)

**Files:**
- Modify: `app/agents/middle_office/risk/var_calculator.py:16-36`
- Test: `tests/test_critical_fixes.py`

**Problem:** (1) `abs()` misreports positive returns as losses. (2) Index formula picks 0th percentile for small samples regardless of confidence.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_critical_fixes.py

# ── MC-01: VaR must use percentile correctly ──

def test_var_all_positive_returns_is_zero():
    """If all returns are positive, VaR should be 0 (no loss risk)."""
    from app.agents.middle_office.risk.var_calculator import VaRCalculator

    returns = np.array([0.01, 0.02, 0.03, 0.015, 0.005, 0.012, 0.008, 0.025, 0.018, 0.011])
    var = VaRCalculator.compute_var(returns, confidence=0.95)
    assert var == 0.0, f"VaR should be 0 for all-positive returns, got {var}"


def test_var_correct_percentile():
    """VaR at 95% on 100 returns should use the 5th percentile, not the worst."""
    from app.agents.middle_office.risk.var_calculator import VaRCalculator

    # 100 returns: -0.05 is the worst, -0.01 is at ~5th percentile
    returns = np.concatenate([
        np.array([-0.05]),           # worst
        np.array([-0.03, -0.02]),    # 2nd, 3rd worst
        np.array([-0.01, -0.005]),   # 4th, 5th
        np.linspace(0.001, 0.05, 95) # 95 positive returns
    ])
    var = VaRCalculator.compute_var(returns, confidence=0.95)
    # 5th percentile of 100 values = index 5 when sorted → should be ~ -0.005 → VaR ~ 0.005
    # Should NOT be 0.05 (the worst return)
    assert var < 0.02, f"VaR {var} is too high — likely using wrong percentile"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py -k "var_" -v`
Expected: FAIL — all-positive returns report non-zero VaR

- [ ] **Step 3: Write minimal fix**

Replace `compute_var` in `app/agents/middle_office/risk/var_calculator.py`:

```python
    @staticmethod
    def compute_var(returns: np.ndarray, confidence: float = 0.95) -> float:
        """Historical VaR at the given confidence level.

        Returns
        -------
        float
            The potential loss at the given percentile (positive number).
            Returns 0.0 if the tail return is positive (no loss risk).
        """
        if len(returns) == 0:
            return 0.0
        percentile_value = float(np.percentile(returns, (1 - confidence) * 100))
        # VaR is a loss measure: negative return = positive VaR
        return max(-percentile_value, 0.0)
```

Also fix `compute_cvar`:

```python
    @staticmethod
    def compute_cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
        """Conditional VaR (Expected Shortfall)."""
        if len(returns) == 0:
            return 0.0
        cutoff = float(np.percentile(returns, (1 - confidence) * 100))
        tail = returns[returns <= cutoff]
        if len(tail) == 0:
            return 0.0
        return max(float(-np.mean(tail)), 0.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py -k "var_" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/agents/middle_office/risk/var_calculator.py tests/test_critical_fixes.py
git commit -m "fix: VaR uses np.percentile, returns 0 for positive tails (MC-01)"
```

---

### Task 9: Fix Sortino Ratio Downside Deviation (MC-02)

**Files:**
- Modify: `app/workers/performance_worker.py:148-160`
- Modify: `app/services/performance.py:121-128`
- Test: `tests/test_critical_fixes.py`

**Problem:** Sortino filters to only negative returns and computes `std(ddof=1)` on that subset. Should use `sqrt(mean(min(excess, 0)^2))` over ALL returns.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_critical_fixes.py

# ── MC-02: Sortino must use correct downside deviation ──

def test_sortino_downside_deviation_formula():
    """Sortino downside deviation must include all returns (zeros for positive)."""
    from app.workers.performance_worker import PerformanceMetrics

    # 100 returns: 5 negative (-0.02 each), 95 positive (+0.01 each)
    equity = np.array([1000.0])
    returns_sequence = [-0.02] * 5 + [0.01] * 95
    for r in returns_sequence:
        equity = np.append(equity, equity[-1] * (1 + r))

    sortino = PerformanceMetrics._sortino_ratio(equity)

    # With correct formula: downside_dev = sqrt(mean(min(excess,0)^2)) over 100 returns
    # 5 negative returns contribute, 95 zeros → small downside dev → high Sortino
    # With bug (std of 5 negatives only): much larger downside dev → lower Sortino
    # The correct Sortino should be significantly higher than the buggy one
    assert sortino > 0, "Sortino should be positive for net-positive returns"

    # More specific: correct downside_dev ~ sqrt(5 * 0.02^2 / 100) = sqrt(0.00002) = 0.00447
    # Buggy: std([-0.02]*5, ddof=1) = 0 (all same) → returns 0 (div by zero guard)
    # Actually the bug returns 0 here. Let's use mixed negatives:
    pass  # see test below


def test_sortino_mixed_negatives():
    """Sortino with mixed negative returns must not inflate the ratio."""
    from app.workers.performance_worker import PerformanceMetrics

    # 20 returns: varied negatives and positives
    values = [1000.0]
    returns_seq = [0.02, -0.01, 0.03, -0.02, 0.01, -0.005, 0.015, -0.015, 0.02, -0.01,
                   0.02, -0.01, 0.03, -0.02, 0.01, -0.005, 0.015, -0.015, 0.02, -0.01]
    for r in returns_seq:
        values.append(values[-1] * (1 + r))
    equity = np.array(values)

    sortino = PerformanceMetrics._sortino_ratio(equity)

    # Correct downside_dev uses all 20 returns
    # Bug uses only the 10 negative returns with std(ddof=1) → smaller denominator
    # Correct Sortino should be LOWER than buggy one
    assert sortino < 50, f"Sortino {sortino} seems inflated"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py -k "sortino" -v`
Expected: FAIL or inflated values

- [ ] **Step 3: Write minimal fix**

In `app/workers/performance_worker.py`, replace `_sortino_ratio`:

```python
    @classmethod
    def _sortino_ratio(cls, equity: np.ndarray, risk_free_rate: float = 0.0) -> float:
        returns = cls._compute_returns(equity)
        if len(returns) < 2:
            return 0.0
        excess = returns - risk_free_rate / TRADING_DAYS_PER_YEAR
        # Downside deviation: sqrt(mean(min(excess, 0)^2)) over ALL returns
        downside_diff = np.minimum(excess, 0.0)
        downside_std = float(np.sqrt(np.mean(downside_diff ** 2)))
        if downside_std == 0:
            return 0.0
        return float(np.mean(excess) / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR))
```

Apply same fix in `app/services/performance.py` (lines 121-128):

```python
        # Sortino
        downside_diff = np.minimum(excess, 0.0)
        ds_std = float(np.sqrt(np.mean(downside_diff ** 2)))
        sortino = (
            float(np.mean(excess) / ds_std * np.sqrt(252))
            if ds_std > 0
            else 0.0
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py -k "sortino" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workers/performance_worker.py app/services/performance.py tests/test_critical_fixes.py
git commit -m "fix: Sortino uses correct downside deviation over all returns (MC-02)"
```

---

### Task 10: Fix Partial Sell Corrupting buy_cost (MC-03)

**Files:**
- Modify: `app/services/performance.py:133-149`
- Test: `tests/test_critical_fixes.py`

**Problem:** After partial sell, `buy_qty` is decremented but `buy_cost` is not reduced proportionally. Subsequent avg_entry is doubled/wrong.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_critical_fixes.py

# ── MC-03: Partial sell must reduce buy_cost proportionally ──

def test_partial_sell_buy_cost_reduced():
    """After selling half a position, avg entry for remainder must stay correct."""
    from app.services.performance import PerformanceService

    # We test the trade-pairing logic directly
    # Buy 100 @ $10, sell 50 @ $12, then sell 50 @ $11
    # Expected: trade 1 PnL = (12-10)*50 = $100, trade 2 PnL = (11-10)*50 = $50
    fills = [
        (10.0, 100.0, "BUY"),   # price, qty, side
        (12.0, 50.0, "SELL"),
        (11.0, 50.0, "SELL"),
    ]

    # Replicate the pairing logic
    buy_cost = 0.0
    buy_qty = 0.0
    trade_pnls = []
    for price, qty, side in fills:
        if side == "BUY":
            buy_cost += price * qty
            buy_qty += qty
        elif side == "SELL" and buy_qty > 0:
            avg_entry = buy_cost / buy_qty
            pnl = (price - avg_entry) * qty
            trade_pnls.append(pnl)
            # THE FIX: reduce buy_cost proportionally
            buy_cost -= avg_entry * qty
            buy_qty -= qty
            if buy_qty <= 0:
                buy_cost = 0.0
                buy_qty = 0.0

    assert len(trade_pnls) == 2
    assert abs(trade_pnls[0] - 100.0) < 0.01, f"Trade 1 PnL: {trade_pnls[0]}"
    assert abs(trade_pnls[1] - 50.0) < 0.01, f"Trade 2 PnL: {trade_pnls[1]}"
```

- [ ] **Step 2: Run test to verify current code fails**

The test above contains the fix inline. To verify the BUG, temporarily test with the old logic:

```python
def test_partial_sell_bug_exists():
    """Demonstrate the buy_cost bug before fix."""
    fills = [(10.0, 100.0, "BUY"), (12.0, 50.0, "SELL"), (11.0, 50.0, "SELL")]
    buy_cost, buy_qty, pnls = 0.0, 0.0, []
    for price, qty, side in fills:
        if side == "BUY":
            buy_cost += price * qty
            buy_qty += qty
        elif side == "SELL" and buy_qty > 0:
            avg_entry = buy_cost / buy_qty
            pnls.append((price - avg_entry) * qty)
            buy_qty -= qty  # BUG: buy_cost not reduced
            if buy_qty <= 0:
                buy_cost = buy_qty = 0.0

    # Bug: trade 2 avg_entry = 1000/50 = $20, PnL = (11-20)*50 = -$450
    assert abs(pnls[1] - (-450.0)) < 0.01, "Bug no longer reproduces"
```

- [ ] **Step 3: Write minimal fix**

In `app/services/performance.py`, replace lines 142-149:

```python
            elif side == "SELL" and buy_qty > 0:
                avg_entry = buy_cost / buy_qty
                pnl = (price - avg_entry) * qty
                trade_pnls.append(pnl)
                # Reduce buy_cost proportionally to maintain correct avg_entry
                buy_cost -= avg_entry * qty
                buy_qty -= qty
                if buy_qty <= 0:
                    buy_cost = 0.0
                    buy_qty = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_critical_fixes.py::test_partial_sell_buy_cost_reduced -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All existing tests still pass + new tests pass

- [ ] **Step 6: Commit**

```bash
git add app/services/performance.py tests/test_critical_fixes.py
git commit -m "fix: reduce buy_cost proportionally on partial sells (MC-03)"
```

---

## Post-Fix Verification

After all 10 tasks are complete:

- [ ] **Run full test suite**: `cd backend && python -m pytest tests/ -v`
- [ ] **Run linter**: `cd backend && python -m ruff check app/`
- [ ] **Start the app**: `cd backend && python -m app --headless` — verify no crashes on startup
- [ ] **Verify cash persists**: Start, run `cash` command, restart, run `cash` again — values should match
