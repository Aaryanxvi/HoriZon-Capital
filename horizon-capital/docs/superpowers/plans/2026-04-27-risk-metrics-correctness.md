# Risk Metrics Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `var_1d_95`, `var_1d_99`, `cvar_1d_95`, `max_drawdown`, `current_drawdown` actually mean what their names say — values derived from daily-aggregated portfolio returns and lifetime equity, not from 60-second snapshot noise.

**Architecture:** Add a `daily_aggregator` helper that resamples `portfolio_snapshots` to one row per UTC trading day (last value of the day). RiskAgent loads daily aggregates for return/drawdown math instead of raw snapshots. Reject computations when fewer than 30 daily points exist. Detect calendar gaps and skip return points spanning >3 days (weekends OK). Drop dead duplicate static helpers. Standardise emitted payload units to fractions throughout.

**Tech Stack:** Python 3.11, SQLAlchemy `text()` queries, NumPy, pytest-asyncio.

---

## File Structure

- Create: `app/agents/middle_office/risk/daily_aggregator.py` — pure function `aggregate_daily(rows) -> list[(date, float)]`
- Modify: `app/agents/middle_office/risk/risk_agent.py` — replace `_load_portfolio_returns` and `_load_equity_curve`, fix payload units, drop dead static helpers
- Create: `tests/test_risk_metrics_correctness.py` — unit tests for aggregator + integration test for risk recompute

---

## Task 1: Daily aggregator (pure function, easy to test)

**Files:**
- Create: `horizon-capital/backend/app/agents/middle_office/risk/daily_aggregator.py`
- Test: `horizon-capital/backend/tests/test_risk_metrics_correctness.py`

- [ ] **Step 1: Write failing test for aggregator basics**

```python
# tests/test_risk_metrics_correctness.py
from datetime import datetime, timezone, timedelta

from app.agents.middle_office.risk.daily_aggregator import aggregate_daily


def _ts(d: str) -> datetime:
    return datetime.fromisoformat(d).replace(tzinfo=timezone.utc)


def test_aggregate_daily_returns_last_value_per_day():
    rows = [
        (_ts("2026-04-25T09:30"), 100_000.0),
        (_ts("2026-04-25T15:59"), 100_500.0),
        (_ts("2026-04-26T09:30"), 100_200.0),
        (_ts("2026-04-26T15:59"), 101_000.0),
    ]
    out = aggregate_daily(rows)
    assert len(out) == 2
    assert out[0][1] == 100_500.0
    assert out[1][1] == 101_000.0


def test_aggregate_daily_handles_empty():
    assert aggregate_daily([]) == []


def test_aggregate_daily_single_day_single_row():
    rows = [(_ts("2026-04-25T09:30"), 100_000.0)]
    out = aggregate_daily(rows)
    assert out == [(_ts("2026-04-25T09:30").date(), 100_000.0)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd horizon-capital/backend && python -m pytest tests/test_risk_metrics_correctness.py -v`
Expected: FAIL with `ModuleNotFoundError: app.agents.middle_office.risk.daily_aggregator`

- [ ] **Step 3: Write minimal aggregator**

```python
# app/agents/middle_office/risk/daily_aggregator.py
"""Resample intraday portfolio snapshots to one row per UTC trading day."""

from __future__ import annotations

from datetime import date, datetime


def aggregate_daily(
    rows: list[tuple[datetime, float]],
) -> list[tuple[date, float]]:
    """Collapse (timestamp, value) rows to one (date, last_value) per UTC day.

    Rows must be sorted oldest-first.
    """
    out: dict[date, float] = {}
    for ts, val in rows:
        out[ts.date()] = val  # later iterations overwrite, last-wins
    return sorted(out.items(), key=lambda kv: kv[0])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd horizon-capital/backend && python -m pytest tests/test_risk_metrics_correctness.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/daily_aggregator.py horizon-capital/backend/tests/test_risk_metrics_correctness.py
git commit -m "feat(risk): add daily aggregator for portfolio snapshots"
```

---

## Task 2: Gap-aware return calculation

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/daily_aggregator.py`
- Test: `horizon-capital/backend/tests/test_risk_metrics_correctness.py`

- [ ] **Step 1: Write failing test for gap detection**

```python
# tests/test_risk_metrics_correctness.py — append
from datetime import date

from app.agents.middle_office.risk.daily_aggregator import (
    aggregate_daily,
    daily_returns_with_gap_filter,
)


def test_returns_skip_long_gaps():
    series = [
        (date(2026, 4, 20), 100.0),
        (date(2026, 4, 21), 101.0),  # +1%
        (date(2026, 4, 24), 110.0),  # 3-day gap (Fri->Mon = OK)
        (date(2026, 5, 5), 50.0),    # 11-day gap → SKIP
        (date(2026, 5, 6), 55.0),    # +10% from prior valid (50)
    ]
    rets = daily_returns_with_gap_filter(series, max_gap_days=4)
    # Pairs: 20→21, 21→24, skip 24→5/5, then 5/5→5/6
    assert len(rets) == 3
    assert abs(rets[0] - 0.01) < 1e-9
    assert abs(rets[1] - (110.0 / 101.0 - 1)) < 1e-9
    assert abs(rets[2] - 0.10) < 1e-9


def test_returns_drop_zero_baseline():
    series = [(date(2026, 4, 20), 0.0), (date(2026, 4, 21), 100.0)]
    rets = daily_returns_with_gap_filter(series)
    assert rets == []
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_risk_metrics_correctness.py::test_returns_skip_long_gaps -v`
Expected: FAIL `ImportError: cannot import name 'daily_returns_with_gap_filter'`

- [ ] **Step 3: Implement gap-aware returns**

```python
# Append to app/agents/middle_office/risk/daily_aggregator.py
def daily_returns_with_gap_filter(
    series: list[tuple["date", float]],
    max_gap_days: int = 4,
) -> list[float]:
    """Compute simple returns between consecutive daily points.

    Skips pairs whose calendar gap exceeds ``max_gap_days`` (default 4 — covers
    Fri→Mon and one holiday). Drops returns with non-positive denominator.
    """
    rets: list[float] = []
    for i in range(1, len(series)):
        d_prev, v_prev = series[i - 1]
        d_curr, v_curr = series[i]
        gap = (d_curr - d_prev).days
        if gap <= 0 or gap > max_gap_days:
            continue
        if v_prev <= 0:
            continue
        rets.append((v_curr - v_prev) / v_prev)
    return rets
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd horizon-capital/backend && python -m pytest tests/test_risk_metrics_correctness.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/daily_aggregator.py horizon-capital/backend/tests/test_risk_metrics_correctness.py
git commit -m "feat(risk): add gap-aware daily returns"
```

---

## Task 3: Wire aggregator into RiskAgent

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py:400-444`
- Test: `horizon-capital/backend/tests/test_risk_metrics_correctness.py`

- [ ] **Step 1: Write failing integration test**

Use SQLite in-memory via existing conftest fixture pattern. Inspect `tests/conftest.py` first for the right fixture name.

```python
# tests/test_risk_metrics_correctness.py — append
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_risk_agent_uses_daily_aggregates(db_session_factory):
    """Insert intraday snapshots spanning 40 days and confirm risk computes
    a non-trivial VaR and lifetime drawdown derived from daily values, not
    from intraday minute noise."""
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.core.memory_bus import MemoryBus

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with db_session_factory()() as session:
        for d in range(40):
            for h in (9, 12, 15):
                # Daily close drops 1% per day — clear deterministic curve
                day_close = 100_000.0 * (0.99 ** d)
                # Intraday wiggle ±0.5% to prove aggregator picks last
                val = day_close * (1.005 if h != 15 else 1.0)
                await session.execute(
                    text(
                        "INSERT INTO portfolio_snapshots "
                        "(id, total_value, created_at, updated_at) "
                        "VALUES (:id, :v, :t, :t)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "v": val,
                        "t": base + timedelta(days=d, hours=h),
                    },
                )
        await session.commit()

    bus = MemoryBus()
    agent = RiskAgent(bus)
    returns = await agent._load_daily_returns()
    equity = await agent._load_daily_equity()

    # Should have ~39 returns (40 days, gap filter doesn't kill any)
    assert 35 <= len(returns) <= 39
    # Each return ~ -0.01 (1% daily decline)
    for r in returns:
        assert -0.011 < r < -0.009

    # Lifetime drawdown ~ 1 - 0.99**39 ≈ 32.5%
    from app.agents.middle_office.risk.var_calculator import VaRCalculator
    import numpy as np
    dd = VaRCalculator.compute_max_drawdown(np.array(equity))
    assert 0.30 < dd < 0.35
```

- [ ] **Step 2: Run test, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_risk_metrics_correctness.py::test_risk_agent_uses_daily_aggregates -v`
Expected: FAIL `AttributeError: '_load_daily_returns'`

- [ ] **Step 3: Replace loaders in RiskAgent**

Open `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py`. Replace the entire `_load_portfolio_returns` and `_load_equity_curve` methods (lines ~400-444) with:

```python
    async def _load_daily_returns(self) -> list[float]:
        """Return up to ~252 daily returns from the last year of snapshots."""
        from app.agents.middle_office.risk.daily_aggregator import (
            aggregate_daily,
            daily_returns_with_gap_filter,
        )

        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT created_at, total_value
                    FROM portfolio_snapshots
                    WHERE created_at >= :cutoff
                    ORDER BY created_at ASC
                    """
                ),
                {"cutoff": datetime.now(UTC).replace(
                    year=datetime.now(UTC).year - 1
                )},
            )
            rows = result.fetchall()

        if len(rows) < 2:
            return []

        intraday = [(r.created_at, float(r.total_value)) for r in rows]
        daily = aggregate_daily(intraday)
        return daily_returns_with_gap_filter(daily)

    async def _load_daily_equity(self) -> list[float]:
        """Lifetime equity curve, one point per UTC day, oldest-first."""
        from app.agents.middle_office.risk.daily_aggregator import aggregate_daily

        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT created_at, total_value
                    FROM portfolio_snapshots
                    ORDER BY created_at ASC
                    """
                )
            )
            rows = result.fetchall()

        if not rows:
            return []
        intraday = [(r.created_at, float(r.total_value)) for r in rows]
        return [v for _, v in aggregate_daily(intraday)]
```

Update `_recompute_risk` callsites:
- Replace `await self._load_portfolio_returns()` → `await self._load_daily_returns()`
- Replace `await self._load_equity_curve()` → `await self._load_daily_equity()`

- [ ] **Step 4: Run test to verify pass**

Run: `cd horizon-capital/backend && python -m pytest tests/test_risk_metrics_correctness.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py horizon-capital/backend/tests/test_risk_metrics_correctness.py
git commit -m "fix(risk): compute VaR and drawdown from daily aggregates"
```

---

## Task 4: Minimum-history guard

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py` (`_recompute_risk`)
- Test: `horizon-capital/backend/tests/test_risk_metrics_correctness.py`

- [ ] **Step 1: Failing test — short history must yield 0.0 metrics + flag**

```python
# Append to tests/test_risk_metrics_correctness.py
@pytest.mark.asyncio
async def test_short_history_zeroes_metrics(db_session_factory, kv_store):
    """With <30 days of data, risk metrics should be 0.0 and flagged insufficient."""
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.core.memory_bus import MemoryBus

    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    async with db_session_factory()() as session:
        for d in range(5):
            await session.execute(
                text("INSERT INTO portfolio_snapshots (id, total_value, created_at, updated_at) "
                     "VALUES (:id, :v, :t, :t)"),
                {"id": str(uuid.uuid4()), "v": 100_000.0, "t": base + timedelta(days=d)},
            )
        await session.commit()

    agent = RiskAgent(MemoryBus())
    await agent._recompute_risk()
    cached = await kv_store.hgetall("horizon:risk:latest")
    assert float(cached["var_1d_95"]) == 0.0
    assert cached.get("insufficient_history") == "1"
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_risk_metrics_correctness.py::test_short_history_zeroes_metrics -v`
Expected: FAIL — key `insufficient_history` missing.

- [ ] **Step 3: Add guard in `_recompute_risk`**

In `risk_agent.py` `_recompute_risk`, after `returns_arr = ...`, replace VaR computation block:

```python
        MIN_DAYS = 30
        insufficient = len(returns_arr) < MIN_DAYS
        if insufficient:
            var_95 = var_99 = cvar_95 = 0.0
        else:
            var_95 = VaRCalculator.compute_var(returns_arr, confidence=0.95)
            var_99 = VaRCalculator.compute_var(returns_arr, confidence=0.99)
            cvar_95 = VaRCalculator.compute_cvar(returns_arr, confidence=0.95)

        max_dd = VaRCalculator.compute_max_drawdown(equity_arr) if len(equity_arr) >= 2 else 0.0
        current_dd = VaRCalculator.compute_current_drawdown(equity_arr) if len(equity_arr) >= 2 else 0.0
```

Add `"insufficient_history": "1" if insufficient else "0"` to the `redis.hset` mapping.

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_risk_metrics_correctness.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py horizon-capital/backend/tests/test_risk_metrics_correctness.py
git commit -m "feat(risk): zero metrics + flag when daily history under 30 points"
```

---

## Task 5: Payload unit consistency

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py:217-227`

- [ ] **Step 1: Failing test — emitted payload uses fractions throughout**

```python
# Append to tests/test_risk_metrics_correctness.py
@pytest.mark.asyncio
async def test_metrics_payload_units_are_fractions(db_session_factory):
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.core.memory_bus import MemoryBus

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with db_session_factory()() as session:
        for d in range(40):
            v = 100_000.0 * (0.99 ** d)
            await session.execute(
                text("INSERT INTO portfolio_snapshots (id, total_value, created_at, updated_at) "
                     "VALUES (:id, :v, :t, :t)"),
                {"id": str(uuid.uuid4()), "v": v, "t": base + timedelta(days=d)},
            )
        await session.commit()

    bus = MemoryBus()
    captured = []
    async def grab(msg):
        if msg.channel == "horizon.risk.metrics":
            captured.append(msg.payload)
    await bus.subscribe("horizon.risk.metrics", grab)

    agent = RiskAgent(bus)
    await agent._recompute_risk()
    assert captured, "metrics never emitted"
    p = captured[-1]
    assert p["max_drawdown"] < 1.0  # fraction, not percent
    assert p["current_drawdown"] < 1.0
    assert p["var_95"] < 1.0
```

- [ ] **Step 2: Run, expect failure** (current code multiplies dd by 100)

Run: `cd horizon-capital/backend && python -m pytest tests/test_risk_metrics_correctness.py::test_metrics_payload_units_are_fractions -v`
Expected: FAIL — `max_drawdown` is ~32.5 not 0.325.

- [ ] **Step 3: Drop `*100` from emitted payload**

In `risk_agent.py:222-223`, change:

```python
                "max_drawdown": max_dd * 100,
                "current_drawdown": current_dd * 100,
```

to:

```python
                "max_drawdown": max_dd,
                "current_drawdown": current_dd,
```

Update kill-switch threshold check at `risk_agent.py:170`:

```python
        kill_switch = current_dd * 100 >= _s.risk_max_drawdown_pct
```

→

```python
        kill_switch = current_dd >= _s.risk_max_drawdown_pct / 100.0
```

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_risk_metrics_correctness.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py horizon-capital/backend/tests/test_risk_metrics_correctness.py
git commit -m "refactor(risk): emit drawdown as fraction, not percent (consistent units)"
```

---

## Task 6: Drop dead duplicate static helpers

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py:359-394`

- [ ] **Step 1: Verify nothing imports them**

Run: `cd horizon-capital/backend && python -m grep -rn "RiskAgent._compute_var\|RiskAgent._compute_max_drawdown\|RiskAgent._compute_current_drawdown" app/ tests/`
Expected: zero hits.

(If anything found: convert it to use `VaRCalculator` instead, then proceed.)

- [ ] **Step 2: Delete the three static methods**

Remove lines ~359-394 (`_compute_var`, `_compute_max_drawdown`, `_compute_current_drawdown` static methods on `RiskAgent`).

- [ ] **Step 3: Run all risk-related tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_risk_metrics_correctness.py tests/test_smoke.py -v`
Expected: all PASS.

- [ ] **Step 4: Run linter**

Run: `cd horizon-capital/backend && python -m ruff check app/agents/middle_office/risk/`
Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py
git commit -m "chore(risk): drop dead duplicate VaR/drawdown statics"
```

---

## Self-Review

- Spec coverage: VaR mislabel → Tasks 1-3. Drawdown window → Task 3. Gap detection → Task 2. Dead helpers → Task 6. Unit mismatch → Task 5. ✓
- Min-history guard not in original audit but follows from "VaR mislabelled" — added as Task 4.
- Type consistency: `_load_daily_returns`/`_load_daily_equity` names used uniformly across Tasks 3, 4, 5. ✓
- No placeholders. All code shown inline. ✓
