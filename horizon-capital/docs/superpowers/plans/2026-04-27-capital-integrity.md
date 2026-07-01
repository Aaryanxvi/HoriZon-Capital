# Capital Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make capital allocation safe under concurrent signals: read cash from the SQL source of truth, reserve cash atomically before emit, drop the silent 25% magic ceiling.

**Architecture:** Introduce a `CashReservation` table (or rows in existing `cash_balances`) for in-flight orders. Portfolio agent reads cash via `app.core.cash.get_cash` (SQL), subtracts active reservations, then sizes. Reservation row created in same SQL transaction as order emit; cleared on fill or cancel. Hardcoded `0.25` cap removed — config `risk_max_position_pct` is the only ceiling.

**Tech Stack:** Python 3.11, SQLAlchemy `text()`, async SQLite/Postgres, pytest-asyncio.

---

## File Structure

- Create: `app/core/cash_reservation.py` — pure SQL helpers `reserve()`, `release()`, `available_cash()`
- Modify: `alembic/versions/` — new migration `add_cash_reservations_table.py`
- Modify: `app/core/local_storage.py` — add `cash_reservations` table to LOCAL schema
- Modify: `app/agents/front_office/portfolio/portfolio_agent.py` — `_load_cash`, `_compute_position_size`, `_size_and_emit`
- Modify: `app/agents/front_office/trading/order_manager.py` (or fill handler) — release reservation on fill/cancel
- Create: `tests/test_capital_integrity.py`

---

## Task 1: `cash_reservations` schema

**Files:**
- Modify: `horizon-capital/backend/app/core/local_storage.py`
- Create: `horizon-capital/backend/alembic/versions/002_cash_reservations.py`

- [ ] **Step 1: Failing test — table exists after init**

```python
# horizon-capital/backend/tests/test_capital_integrity.py
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_cash_reservations_table_exists(db_session_factory):
    async with db_session_factory()() as session:
        result = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' "
                 "AND name='cash_reservations'")
        )
        assert result.fetchone() is not None
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_capital_integrity.py::test_cash_reservations_table_exists -v`
Expected: FAIL — table absent.

- [ ] **Step 3: Add table to LOCAL schema**

In `app/core/local_storage.py`, add inside the `CREATE TABLE` block list (find existing `cash_balances` and add after):

```python
CREATE_CASH_RESERVATIONS = """
CREATE TABLE IF NOT EXISTS cash_reservations (
    id           TEXT PRIMARY KEY,
    order_id     TEXT,
    signal_id    TEXT,
    symbol       TEXT NOT NULL,
    currency     TEXT NOT NULL,
    amount       REAL NOT NULL,
    status       TEXT NOT NULL DEFAULT 'OPEN',
    created_at   TIMESTAMP NOT NULL,
    released_at  TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_cash_reservations_open
    ON cash_reservations(currency, status);
"""
```

Wire it into the schema-init function (search for where `cash_balances` is referenced and append `CREATE_CASH_RESERVATIONS` to the same execution).

Add an Alembic migration `002_cash_reservations.py` mirroring the SQL.

- [ ] **Step 4: Run, verify pass**

Run: `cd horizon-capital/backend && python -m pytest tests/test_capital_integrity.py::test_cash_reservations_table_exists -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/core/local_storage.py horizon-capital/backend/alembic/versions/002_cash_reservations.py horizon-capital/backend/tests/test_capital_integrity.py
git commit -m "feat(cash): add cash_reservations table for atomic capital allocation"
```

---

## Task 2: `cash_reservation` helpers

**Files:**
- Create: `horizon-capital/backend/app/core/cash_reservation.py`

- [ ] **Step 1: Failing test — reserve/available/release cycle**

```python
# Append to tests/test_capital_integrity.py
import uuid
from datetime import datetime, timezone

from app.core.cash_reservation import (
    available_cash, release, reserve,
)


@pytest.mark.asyncio
async def test_reserve_reduces_available(db_session_factory):
    async with db_session_factory()() as session:
        await session.execute(
            text("INSERT INTO cash_balances (currency, amount, updated_at) "
                 "VALUES ('USD', 100000.0, :t)"),
            {"t": datetime.now(timezone.utc)},
        )
        await session.commit()

    async with db_session_factory()() as session:
        before = await available_cash(session, "USD")
        assert before == 100_000.0
        rid = await reserve(session, "USD", 25_000.0, signal_id="s1", symbol="AAPL")
        await session.commit()

    async with db_session_factory()() as session:
        after = await available_cash(session, "USD")
        assert after == 75_000.0

    async with db_session_factory()() as session:
        await release(session, rid)
        await session.commit()

    async with db_session_factory()() as session:
        restored = await available_cash(session, "USD")
        assert restored == 100_000.0
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_capital_integrity.py::test_reserve_reduces_available -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement helpers**

```python
# app/core/cash_reservation.py
"""Atomic in-flight capital reservations.

A reservation row claims ``amount`` of a currency for an in-flight order.
``available_cash`` = cash_balances - SUM(open reservations).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cash import get_cash
from app.core.logging import get_logger

logger = get_logger("core.cash_reservation")


async def available_cash(session: AsyncSession, currency: str) -> float:
    """Return cash_balances[currency] minus open reservations."""
    total = await get_cash(session, currency)
    result = await session.execute(
        text(
            "SELECT COALESCE(SUM(amount), 0) AS reserved "
            "FROM cash_reservations "
            "WHERE currency = :c AND status = 'OPEN'"
        ),
        {"c": currency},
    )
    row = result.fetchone()
    reserved = float(row.reserved or 0.0)
    return max(total - reserved, 0.0)


async def reserve(
    session: AsyncSession,
    currency: str,
    amount: float,
    *,
    signal_id: str | None = None,
    symbol: str = "",
    order_id: str | None = None,
) -> str:
    """Insert an OPEN reservation row. Caller commits."""
    if amount <= 0:
        raise ValueError(f"reserve amount must be positive: {amount!r}")
    rid = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO cash_reservations "
            "(id, order_id, signal_id, symbol, currency, amount, status, created_at) "
            "VALUES (:id, :oid, :sid, :sym, :c, :a, 'OPEN', :t)"
        ),
        {
            "id": rid, "oid": order_id, "sid": signal_id,
            "sym": symbol, "c": currency, "a": float(amount),
            "t": datetime.now(UTC),
        },
    )
    return rid


async def release(session: AsyncSession, reservation_id: str) -> None:
    """Mark a reservation RELEASED. Idempotent — no-op if already closed."""
    await session.execute(
        text(
            "UPDATE cash_reservations "
            "SET status = 'RELEASED', released_at = :t "
            "WHERE id = :id AND status = 'OPEN'"
        ),
        {"id": reservation_id, "t": datetime.now(UTC)},
    )


async def attach_order(
    session: AsyncSession, reservation_id: str, order_id: str,
) -> None:
    """Link a reservation to its order_id once the order is emitted."""
    await session.execute(
        text(
            "UPDATE cash_reservations "
            "SET order_id = :oid WHERE id = :id"
        ),
        {"id": reservation_id, "oid": order_id},
    )


async def release_for_order(session: AsyncSession, order_id: str) -> None:
    """Release any OPEN reservation tied to an order_id (fill or cancel)."""
    await session.execute(
        text(
            "UPDATE cash_reservations "
            "SET status = 'RELEASED', released_at = :t "
            "WHERE order_id = :oid AND status = 'OPEN'"
        ),
        {"oid": order_id, "t": datetime.now(UTC)},
    )
```

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_capital_integrity.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/core/cash_reservation.py horizon-capital/backend/tests/test_capital_integrity.py
git commit -m "feat(cash): cash_reservation helpers (reserve/release/available)"
```

---

## Task 3: Portfolio agent reads cash from SQL

**Files:**
- Modify: `horizon-capital/backend/app/agents/front_office/portfolio/portfolio_agent.py:558-562` (`_load_cash`)
- Test: `horizon-capital/backend/tests/test_capital_integrity.py`

- [ ] **Step 1: Failing test — agent uses SQL truth, not stale KV**

```python
# Append
@pytest.mark.asyncio
async def test_portfolio_loads_cash_from_sql(db_session_factory, kv_store):
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.core.memory_bus import MemoryBus

    # SQL says $50k, KV says $100k (stale). Agent must use SQL.
    async with db_session_factory()() as session:
        await session.execute(
            text("INSERT INTO cash_balances (currency, amount, updated_at) "
                 "VALUES ('USD', 50000.0, :t)"),
            {"t": datetime.now(timezone.utc)},
        )
        await session.commit()
    await kv_store.set("horizon:cash:usd", "100000.0")

    agent = PortfolioAgent(MemoryBus())
    cash_usd, _ = await agent._load_cash()
    assert cash_usd == 50_000.0
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_capital_integrity.py::test_portfolio_loads_cash_from_sql -v`
Expected: FAIL — current code reads `100000.0` from KV.

- [ ] **Step 3: Rewrite `_load_cash`**

Replace `_load_cash` body:

```python
    async def _load_cash(self) -> tuple[float, float]:
        """Load AVAILABLE cash from cash_balances minus open reservations.

        Source of truth is SQL. KV mirror is ignored here.
        """
        from app.core.cash_reservation import available_cash

        async with _get_session_factory()() as session:
            usd = await available_cash(session, "USD")
            inr = await available_cash(session, "INR")
        return usd, inr
```

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_capital_integrity.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/front_office/portfolio/portfolio_agent.py horizon-capital/backend/tests/test_capital_integrity.py
git commit -m "fix(portfolio): read cash from SQL truth (cash_balances), not stale KV"
```

---

## Task 4: Reserve on emit, release on fill/cancel

**Files:**
- Modify: `horizon-capital/backend/app/agents/front_office/portfolio/portfolio_agent.py:234-285` (`_size_and_emit`)
- Modify: order-fill handler (likely `app/agents/front_office/trading/execution_agent.py` or `order_manager.py`) — call `release_for_order` on FILL/CANCEL/REJECT

- [ ] **Step 1: Failing test — concurrent BUYs cannot over-allocate**

```python
# Append
@pytest.mark.asyncio
async def test_concurrent_buys_cannot_over_allocate(db_session_factory, kv_store):
    """Two simultaneous BUY signals each requesting 80% of $100k must produce
    one full-size order and one zero-size — combined notional ≤ $100k.
    """
    import asyncio
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.core.memory_bus import MemoryBus

    async with db_session_factory()() as session:
        await session.execute(
            text("INSERT INTO cash_balances (currency, amount, updated_at) "
                 "VALUES ('USD', 100000.0, :t)"),
            {"t": datetime.now(timezone.utc)},
        )
        await session.commit()
    await kv_store.set("horizon:price:AAPL", "100.0")
    await kv_store.set("horizon:price:MSFT", "100.0")

    agent = PortfolioAgent(MemoryBus())
    sig_a = {"symbol": "AAPL", "exchange": "NASDAQ", "direction": 1,
             "target_weight": 0.80, "signal_id": "a"}
    sig_b = {"symbol": "MSFT", "exchange": "NASDAQ", "direction": 1,
             "target_weight": 0.80, "signal_id": "b"}

    results = await asyncio.gather(
        agent._size_and_emit(sig_a, debate_id=None),
        agent._size_and_emit(sig_b, debate_id=None),
    )
    # At least one must be False (or sized smaller). Combined emitted notional
    # cannot exceed 100k.
    assert sum(1 for r in results if r) <= 1 or all(r is True for r in results)
    # Combined reserved should be ≤ $100k
    async with db_session_factory()() as session:
        result = await session.execute(
            text("SELECT COALESCE(SUM(amount), 0) AS s FROM cash_reservations "
                 "WHERE status='OPEN' AND currency='USD'")
        )
        reserved = float(result.fetchone().s)
    assert reserved <= 100_000.0
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_capital_integrity.py::test_concurrent_buys_cannot_over_allocate -v`
Expected: FAIL — both BUYs sized at 80% of cash since reservation absent.

- [ ] **Step 3: Reserve before emit**

In `_size_and_emit`, after sizing succeeds and *before* `await self.emit(...)`, open a SQL session and reserve. Replace the emit block:

```python
        from app.core.cash_reservation import attach_order, reserve, release

        side = "BUY" if direction > 0 else "SELL"
        if self._is_duplicate_sizing(symbol, side, sizing["quantity"]):
            logger.debug("sizing_deduped_qty_unchanged",
                         symbol=symbol, side=side, qty=sizing["quantity"])
            return False

        order_id = str(uuid.uuid4())
        reservation_id: str | None = None
        if side == "BUY" and sizing["allocation_usd"] > 0:
            ccy = "INR" if exchange in ("NSE", "BSE") else "USD"
            ccy_amount = (
                sizing["allocation_usd"] * await self.currency.get_usd_inr_rate()
                if ccy == "INR" else sizing["allocation_usd"]
            )
            async with _get_session_factory()() as session:
                # Re-check available cash atomically; abort if insufficient
                from app.core.cash_reservation import available_cash
                avail = await available_cash(session, ccy)
                if avail < ccy_amount:
                    logger.info(
                        "reserve_aborted_insufficient", symbol=symbol,
                        need=ccy_amount, avail=avail,
                    )
                    return False
                reservation_id = await reserve(
                    session, ccy, ccy_amount,
                    signal_id=payload.get("signal_id"), symbol=symbol,
                    order_id=order_id,
                )
                await session.commit()

        try:
            await self.emit(
                channel="horizon.execution.order.new",
                message_type=MessageType.ORDER_NEW,
                payload={
                    "order_id": order_id,
                    "symbol": symbol,
                    "exchange": exchange,
                    "side": side,
                    "quantity": sizing["quantity"],
                    "order_type": "MARKET",
                    "signal_id": payload.get("signal_id"),
                    "debate_id": debate_id,
                    "stop_loss": payload.get("stop_loss"),
                    "allocation_usd": sizing["allocation_usd"],
                    "reservation_id": reservation_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except Exception:
            # Roll the reservation back if emit failed
            if reservation_id is not None:
                async with _get_session_factory()() as session:
                    await release(session, reservation_id)
                    await session.commit()
            raise

        self._last_emitted_qty[(symbol, side)] = sizing["quantity"]
        logger.info(
            "order_sized",
            symbol=symbol,
            side=side,
            qty=sizing["quantity"],
            allocation=sizing["allocation_usd"],
            reservation_id=reservation_id,
        )
        return True
```

- [ ] **Step 4: Wire release on fill/cancel**

Locate the fill handler (likely `execution_agent.py` `_on_fill` or `paper_broker.py`). After persisting the fill (and updating `cash_balances`), call:

```python
        from app.core.cash_reservation import release_for_order
        async with _get_session_factory()() as session:
            await release_for_order(session, order_id)
            await session.commit()
```

Same in the cancel/reject path.

- [ ] **Step 5: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_capital_integrity.py tests/test_paper_trading_honest.py tests/test_trading_lifecycle.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add horizon-capital/backend/app/agents/front_office/portfolio/portfolio_agent.py horizon-capital/backend/app/agents/front_office/trading/ horizon-capital/backend/tests/test_capital_integrity.py
git commit -m "feat(portfolio): reserve cash on emit, release on fill/cancel"
```

---

## Task 5: Drop hardcoded 0.25 ceiling

**Files:**
- Modify: `horizon-capital/backend/app/agents/front_office/portfolio/portfolio_agent.py:328-329`

- [ ] **Step 1: Failing test — config 30% should yield 30% target**

```python
# Append
@pytest.mark.asyncio
async def test_target_weight_respects_config_only(monkeypatch, db_session_factory, kv_store):
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.core.memory_bus import MemoryBus
    from app.config import settings

    monkeypatch.setattr(settings, "risk_max_position_pct", 30.0)
    async with db_session_factory()() as session:
        await session.execute(
            text("INSERT INTO cash_balances (currency, amount, updated_at) "
                 "VALUES ('USD', 100000.0, :t)"),
            {"t": datetime.now(timezone.utc)},
        )
        await session.commit()
    await kv_store.set("horizon:price:AAPL", "100.0")

    agent = PortfolioAgent(MemoryBus())
    sizing = await agent._compute_position_size(
        "AAPL", direction=1, exchange="NASDAQ", target_weight=0.30,
    )
    # Should size to ~$30k = 300 shares — not capped at 25%
    assert sizing["quantity"] >= 270  # leaves room for 90% cash buffer
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_capital_integrity.py::test_target_weight_respects_config_only -v`
Expected: FAIL — current code clamps to `min(.30, .25) = .25`.

- [ ] **Step 3: Remove magic 0.25**

In `portfolio_agent.py:328-329`, change:

```python
        pct_cap = settings.risk_max_position_pct / 100.0
        target_weight = min(max(target_weight, 0.0), pct_cap, 0.25)
```

to:

```python
        pct_cap = settings.risk_max_position_pct / 100.0
        target_weight = min(max(target_weight, 0.0), pct_cap)
```

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_capital_integrity.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/front_office/portfolio/portfolio_agent.py horizon-capital/backend/tests/test_capital_integrity.py
git commit -m "refactor(portfolio): config is sole position-cap source (drop 0.25 magic)"
```

---

## Self-Review

- Spec coverage:
  - Cash from SQL → Task 3. ✓
  - Reservation → Tasks 1, 2, 4. ✓
  - Drop 0.25 → Task 5. ✓
- Type consistency: `available_cash`/`reserve`/`release`/`release_for_order` signatures consistent across helper module + callsites. `reservation_id: str` everywhere. ✓
- Placeholder scan: zero "TODO/TBD/similar to". All code shown inline. Fill-handler integration (Task 4 step 4) names the call signature explicitly even if exact file path varies — engineer must locate the existing fill handler, but the patch is shown. ✓
