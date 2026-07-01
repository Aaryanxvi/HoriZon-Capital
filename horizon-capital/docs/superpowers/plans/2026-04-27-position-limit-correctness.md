# Position Limit Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `_check_position_limit` an actually-correct post-trade check: currency-normalised, NAV-fresh, and fail-closed when NAV is unknown.

**Architecture:** Risk agent stops trusting stale `horizon:portfolio:nav` KV by subscribing to `horizon.portfolio.update` and caching the latest snapshot in-process. Position-limit check converts INR positions to USD using cached `horizon:fx:usd_inr`. Pre-trade simulation: `current_value_usd + intended_buy_usd <= cap`. When NAV is missing or stale (>5 min), gate fails closed (block).

**Tech Stack:** Python 3.11, SQLAlchemy, async Redis/MemoryKV, pytest-asyncio.

---

## File Structure

- Modify: `app/agents/middle_office/risk/risk_agent.py` — `__init__`, `_subscribe`, new `_handle_portfolio_update`, rewritten `_check_position_limit`
- Modify: `app/agents/middle_office/risk/risk_agent.py` — `_handle_signal` passes `intended_usd` and `direction` to check
- Create: `tests/test_position_limit_correctness.py`

---

## Task 1: Cache fresh NAV via bus subscription

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py`
- Test: `horizon-capital/backend/tests/test_position_limit_correctness.py`

- [ ] **Step 1: Failing test — agent updates `_nav_cache` on portfolio update**

```python
# tests/test_position_limit_correctness.py
import pytest
from datetime import datetime, timezone

from app.agents.middle_office.risk.risk_agent import RiskAgent
from app.core.memory_bus import MemoryBus
from app.core.messaging import AgentMessage, MessageType


@pytest.mark.asyncio
async def test_agent_caches_nav_from_portfolio_update():
    bus = MemoryBus()
    agent = RiskAgent(bus)
    await agent._subscribe()

    msg = AgentMessage(
        message_type=MessageType.PORTFOLIO_UPDATE,
        channel="horizon.portfolio.update",
        payload={"total_value": 250_000.0, "timestamp": datetime.now(timezone.utc).isoformat()},
    )
    await bus.publish(msg)

    nav, ts = agent._nav_cache
    assert nav == 250_000.0
    assert ts is not None
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_position_limit_correctness.py::test_agent_caches_nav_from_portfolio_update -v`
Expected: FAIL — `_nav_cache` does not exist.

- [ ] **Step 3: Add subscription + handler**

In `risk_agent.py` `__init__`, after `self.redis = _get_kv()`:

```python
        self._nav_cache: tuple[float | None, datetime | None] = (None, None)
```

In `_subscribe`, append:

```python
        await self.bus.subscribe("horizon.portfolio.update", self.on_message)
```

In `on_message`, add a branch after the existing two `elif`s:

```python
        elif message.channel == "horizon.portfolio.update":
            await self._handle_portfolio_update(message)
```

Add new method:

```python
    async def _handle_portfolio_update(self, message: AgentMessage) -> None:
        """Cache the latest NAV so position-limit checks aren't stale."""
        try:
            nav = float(message.payload.get("total_value") or 0.0)
        except (TypeError, ValueError):
            return
        self._nav_cache = (nav, datetime.now(UTC))
```

- [ ] **Step 4: Run, verify pass**

Run: `cd horizon-capital/backend && python -m pytest tests/test_position_limit_correctness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py horizon-capital/backend/tests/test_position_limit_correctness.py
git commit -m "feat(risk): cache fresh NAV from portfolio.update"
```

---

## Task 2: Fail-closed NAV freshness

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py`
- Test: `horizon-capital/backend/tests/test_position_limit_correctness.py`

- [ ] **Step 1: Failing test — missing NAV blocks BUY**

```python
# Append to tests/test_position_limit_correctness.py
@pytest.mark.asyncio
async def test_missing_nav_blocks_buy():
    bus = MemoryBus()
    agent = RiskAgent(bus)
    # No portfolio update yet — _nav_cache is (None, None)
    ok = await agent._check_position_limit(
        symbol="AAPL", direction=1, intended_usd=1000.0,
    )
    assert ok is False


@pytest.mark.asyncio
async def test_stale_nav_blocks_buy():
    from datetime import timedelta
    bus = MemoryBus()
    agent = RiskAgent(bus)
    agent._nav_cache = (100_000.0, datetime.now(timezone.utc) - timedelta(minutes=10))
    ok = await agent._check_position_limit(
        symbol="AAPL", direction=1, intended_usd=1000.0,
    )
    assert ok is False
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_position_limit_correctness.py::test_missing_nav_blocks_buy -v`
Expected: FAIL — current code returns True on missing NAV.

- [ ] **Step 3: Rewrite `_check_position_limit` signature and freshness logic**

Replace the entire `_check_position_limit` body (`risk_agent.py:260-298`) with:

```python
    NAV_FRESHNESS_SECONDS = 300

    async def _check_position_limit(
        self,
        symbol: str,
        direction: int = 0,
        intended_usd: float = 0.0,
    ) -> bool:
        """Post-trade position-limit check.

        Fails closed when NAV is unknown or stale. SELLs that strictly reduce
        exposure (direction<0) skip the check.
        """
        if direction < 0:
            return True

        nav, ts = self._nav_cache
        if nav is None or ts is None:
            logger.warning("position_limit_blocked_nav_missing")
            return False
        age = (datetime.now(UTC) - ts).total_seconds()
        if age > self.NAV_FRESHNESS_SECONDS:
            logger.warning("position_limit_blocked_nav_stale", age_s=int(age))
            return False
        if nav <= 0:
            logger.warning("position_limit_blocked_nonpositive_nav", nav=nav)
            return False

        current_usd = await self._symbol_exposure_usd(symbol)
        post_usd = current_usd + max(intended_usd, 0.0)
        weight_pct = (post_usd / nav) * 100
        return weight_pct <= settings.risk_max_position_pct
```

Stub `_symbol_exposure_usd` for now (next task implements):

```python
    async def _symbol_exposure_usd(self, symbol: str) -> float:
        return 0.0
```

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_position_limit_correctness.py -v`
Expected: PASS for fail-closed tests.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py horizon-capital/backend/tests/test_position_limit_correctness.py
git commit -m "fix(risk): position-limit fails closed when NAV missing or stale"
```

---

## Task 3: Currency-normalised exposure

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py` (`_symbol_exposure_usd`)
- Test: `horizon-capital/backend/tests/test_position_limit_correctness.py`

- [ ] **Step 1: Failing test — INR positions converted via FX rate**

```python
# Append
import uuid
from sqlalchemy import text


@pytest.mark.asyncio
async def test_inr_exposure_converted_to_usd(db_session_factory, kv_store):
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.core.memory_bus import MemoryBus

    # 1000 shares × INR 250 = INR 250_000 → USD 3000 at 83.33
    async with db_session_factory()() as session:
        await session.execute(
            text("""
                INSERT INTO positions
                    (id, symbol, exchange, side, quantity, current_price,
                     avg_entry_price, currency, created_at, updated_at)
                VALUES
                    (:id, 'RELIANCE', 'NSE', 'LONG', 1000, 250.0, 250.0,
                     'INR', :t, :t)
            """),
            {"id": str(uuid.uuid4()), "t": datetime.now(timezone.utc)},
        )
        await session.commit()
    await kv_store.set("horizon:fx:usd_inr", "83.33")

    agent = RiskAgent(MemoryBus())
    usd = await agent._symbol_exposure_usd("RELIANCE")
    assert 2990.0 < usd < 3010.0


@pytest.mark.asyncio
async def test_usd_exposure_unchanged(db_session_factory):
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.core.memory_bus import MemoryBus

    async with db_session_factory()() as session:
        await session.execute(
            text("""
                INSERT INTO positions
                    (id, symbol, exchange, side, quantity, current_price,
                     avg_entry_price, currency, created_at, updated_at)
                VALUES
                    (:id, 'AAPL', 'NASDAQ', 'LONG', 100, 150.0, 150.0,
                     'USD', :t, :t)
            """),
            {"id": str(uuid.uuid4()), "t": datetime.now(timezone.utc)},
        )
        await session.commit()

    agent = RiskAgent(MemoryBus())
    usd = await agent._symbol_exposure_usd("AAPL")
    assert usd == 15_000.0
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_position_limit_correctness.py::test_inr_exposure_converted_to_usd -v`
Expected: FAIL — stub returns 0.

- [ ] **Step 3: Implement currency-normalised exposure**

Replace stub:

```python
    async def _symbol_exposure_usd(self, symbol: str) -> float:
        """Sum |quantity * current_price| for a symbol, USD-normalised."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    "SELECT currency, "
                    "       COALESCE(SUM(ABS(quantity * current_price)), 0) AS v "
                    "FROM positions WHERE symbol = :symbol "
                    "GROUP BY currency"
                ),
                {"symbol": symbol},
            )
            rows = result.fetchall()

        if not rows:
            return 0.0

        total_usd = 0.0
        usd_inr: float | None = None
        for r in rows:
            ccy = (r.currency or "USD").upper()
            v = float(r.v or 0.0)
            if ccy == "USD":
                total_usd += v
            elif ccy == "INR":
                if usd_inr is None:
                    rate_str = await self.redis.get("horizon:fx:usd_inr")
                    usd_inr = float(rate_str) if rate_str else 0.0
                if usd_inr <= 0:
                    logger.warning(
                        "exposure_skipped_no_fx", symbol=symbol, currency=ccy,
                    )
                    continue
                total_usd += v / usd_inr
            else:
                logger.warning(
                    "exposure_skipped_unknown_currency", symbol=symbol, currency=ccy,
                )
        return total_usd
```

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_position_limit_correctness.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py horizon-capital/backend/tests/test_position_limit_correctness.py
git commit -m "fix(risk): currency-normalise per-symbol exposure to USD"
```

---

## Task 4: Wire `intended_usd` from signal payload

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py` (`_handle_signal`)
- Test: `horizon-capital/backend/tests/test_position_limit_correctness.py`

The portfolio agent computes the order. Risk agent needs an *upper bound* of the intended USD before sizing. Use `target_weight * NAV` as the bound — that's the maximum allocation the sleeve will request.

- [ ] **Step 1: Failing test — over-target weight is rejected**

```python
# Append
@pytest.mark.asyncio
async def test_signal_over_position_cap_rejected(db_session_factory, kv_store, monkeypatch):
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.core.memory_bus import MemoryBus
    from app.core.messaging import AgentMessage, MessageType
    from app.config import settings

    # Existing 4% in AAPL ($4000 of $100k). Signal targets 8% (over the 5% cap).
    async with db_session_factory()() as session:
        await session.execute(
            text("INSERT INTO positions (id, symbol, exchange, side, quantity, "
                 "current_price, avg_entry_price, currency, created_at, updated_at) "
                 "VALUES (:id, 'AAPL', 'NASDAQ', 'LONG', 40, 100.0, 100.0, 'USD', :t, :t)"),
            {"id": str(uuid.uuid4()), "t": datetime.now(timezone.utc)},
        )
        await session.commit()

    bus = MemoryBus()
    rejected = []
    async def grab(msg):
        if msg.channel.startswith("horizon.risk.rejected."):
            rejected.append(msg.payload)
    await bus.subscribe("horizon.risk.rejected.*", grab)

    agent = RiskAgent(bus)
    await agent._subscribe()
    agent._nav_cache = (100_000.0, datetime.now(timezone.utc))

    sig = AgentMessage(
        message_type=MessageType.SIGNAL,
        channel="horizon.signal.AAPL",
        payload={
            "signal_id": "s1", "symbol": "AAPL", "direction": 1,
            "target_weight": 0.08,  # 8% — over 5% cap
        },
    )
    await bus.publish(sig)
    await asyncio.sleep(0)  # let async handler drain

    assert rejected, "expected reject"
    assert any("Position" in v for v in rejected[0]["violations"])
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_position_limit_correctness.py::test_signal_over_position_cap_rejected -v`
Expected: FAIL — current code passes BUYs because `current` is 4% (below 5%), but doesn't account for 8% target.

- [ ] **Step 3: Pass `intended_usd` from signal handler**

In `_handle_signal`, before the position-limit check, compute intended USD:

```python
        target_weight = float(payload.get("target_weight") or 0.0)
        nav, _ = self._nav_cache
        intended_usd = max(0.0, target_weight) * (nav or 0.0)
```

Update call:

```python
        if not await self._check_position_limit(
            symbol, direction=direction, intended_usd=intended_usd,
        ):
```

The exposure check inside `_check_position_limit` already adds `intended_usd` to current — but we want target absolute, not current+target. Adjust:

Replace `post_usd = current_usd + max(intended_usd, 0.0)` with:

```python
        # intended_usd is the *target* exposure for this symbol, not a delta.
        # Take the max of current exposure (already on book) and the intended
        # target — the new exposure post-trade can't be lower than current
        # since SELLs short-circuit above.
        post_usd = max(current_usd, max(intended_usd, 0.0))
```

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_position_limit_correctness.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py horizon-capital/backend/tests/test_position_limit_correctness.py
git commit -m "fix(risk): position-limit gate uses target_weight*NAV as intended exposure"
```

---

## Task 5: Drop legacy KV NAV bypass in daily-loss check

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py` (`_check_daily_loss_limit`)
- Test: `horizon-capital/backend/tests/test_position_limit_correctness.py`

- [ ] **Step 1: Failing test — missing baseline blocks instead of allows**

```python
# Append
@pytest.mark.asyncio
async def test_missing_baseline_blocks_until_first_snapshot(db_session_factory):
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.core.memory_bus import MemoryBus

    agent = RiskAgent(MemoryBus())
    agent._nav_cache = (95_000.0, datetime.now(timezone.utc))
    # No snapshot rows exist → no baseline → must block
    ok = await agent._check_daily_loss_limit()
    assert ok is False
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_position_limit_correctness.py::test_missing_baseline_blocks_until_first_snapshot -v`
Expected: FAIL — current code returns True.

- [ ] **Step 3: Rewrite `_check_daily_loss_limit` to use cached NAV + fail-closed baseline**

Replace the body of `_check_daily_loss_limit`:

```python
    async def _check_daily_loss_limit(self) -> bool:
        """Block trading once intraday loss exceeds the configured cap.

        Fails closed if NAV is unknown/stale or if no snapshot baseline exists
        for the current UTC day.
        """
        nav, ts = self._nav_cache
        if nav is None or ts is None or nav <= 0:
            logger.warning("daily_loss_blocked_nav_unknown")
            return False
        age = (datetime.now(UTC) - ts).total_seconds()
        if age > self.NAV_FRESHNESS_SECONDS:
            logger.warning("daily_loss_blocked_nav_stale", age_s=int(age))
            return False

        today_utc_start = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT total_value
                    FROM portfolio_snapshots
                    WHERE created_at >= :start
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ),
                {"start": today_utc_start},
            )
            row = result.fetchone()

        if row is None or not row.total_value:
            logger.warning("daily_loss_blocked_no_baseline")
            return False

        start_of_day_nav = float(row.total_value)
        if start_of_day_nav <= 0:
            return False

        day_pnl = nav - start_of_day_nav
        if day_pnl >= 0:
            return True

        loss_pct = abs(day_pnl) / start_of_day_nav * 100
        if loss_pct >= settings.risk_daily_loss_limit_pct:
            logger.warning(
                "daily_loss_limit_breach",
                loss_pct=f"{loss_pct:.2f}",
                limit=settings.risk_daily_loss_limit_pct,
            )
            return False
        return True
```

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_position_limit_correctness.py tests/test_critical_fixes.py -v`
Expected: all PASS. (Update any pre-existing test that asserted the old "allow if missing" behaviour — that was the bug.)

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py horizon-capital/backend/tests/test_position_limit_correctness.py
git commit -m "fix(risk): daily-loss check fails closed when NAV/baseline unknown"
```

---

## Self-Review

- Spec coverage:
  - Position cap proxy → Task 4 (uses target absolute, not current proxy). ✓
  - Currency mix → Task 3. ✓
  - NAV freshness via bus → Task 1. ✓
  - Missing-NAV bypass → Tasks 2, 5. ✓
- Type consistency: `_nav_cache: tuple[float|None, datetime|None]`, `intended_usd: float`, `_symbol_exposure_usd` returns `float`. Used consistently across Tasks 1-4. ✓
- No placeholders. All code shown. ✓
- Stale `current_price` issue from audit is acknowledged but not addressed here — belongs in a separate "price freshness" plan; left for follow-up.
