# Halt Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the kill-switch halt actually clearable, restrict post-trade recompute to fills, serialise concurrent recomputes, and bound `risk_metrics` table growth.

**Architecture:** RiskAgent reads `horizon:system:halted:ack` on each recompute — if `1`, it clears `horizon:system:halted` and the ack key, emits `KILL_SWITCH_CLEARED`. Recompute method wraps work in an `asyncio.Lock`. Post-trade subscription is narrowed from `horizon.execution.order.*` to `horizon.execution.order.fill`. A retention task prunes `risk_metrics` rows older than 90 days every recompute when the table exceeds 100k rows.

**Tech Stack:** Python 3.11, asyncio.Lock, SQLAlchemy DELETE.

---

## File Structure

- Modify: `app/agents/middle_office/risk/risk_agent.py` — `__init__` (lock), `_subscribe` (narrow channel), `_recompute_risk` (ack check + retention), new `_check_halt_ack`, new `_prune_old_metrics`
- Create: `tests/test_halt_control.py`
- Modify: `app/tui/commands.py` — add `/halt clear` REPL command (writes the ack key)

---

## Task 1: Halt-ack reader

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py`
- Test: `horizon-capital/backend/tests/test_halt_control.py`

- [ ] **Step 1: Failing test — ack key clears halt**

```python
# horizon-capital/backend/tests/test_halt_control.py
import pytest
from datetime import datetime, timezone

from app.agents.middle_office.risk.risk_agent import RiskAgent
from app.core.memory_bus import MemoryBus


@pytest.mark.asyncio
async def test_ack_clears_halt(kv_store, db_session_factory):
    await kv_store.set("horizon:system:halted", "1")
    await kv_store.set("horizon:system:halted:ack", "1")

    bus = MemoryBus()
    cleared = []
    async def grab(msg):
        if msg.payload.get("action") == "KILL_SWITCH_CLEARED":
            cleared.append(msg.payload)
    await bus.subscribe("horizon.risk.alert", grab)

    agent = RiskAgent(bus)
    await agent._check_halt_ack()

    assert await kv_store.get("horizon:system:halted") in (None, "0")
    assert await kv_store.get("horizon:system:halted:ack") in (None, "0")
    assert cleared, "expected KILL_SWITCH_CLEARED alert"


@pytest.mark.asyncio
async def test_ack_without_halt_is_noop(kv_store):
    # Stray ack with no halt → just clear the ack, no alert
    await kv_store.set("horizon:system:halted:ack", "1")
    bus = MemoryBus()
    agent = RiskAgent(bus)
    await agent._check_halt_ack()
    assert await kv_store.get("horizon:system:halted:ack") in (None, "0")
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_halt_control.py::test_ack_clears_halt -v`
Expected: FAIL — `_check_halt_ack` does not exist.

- [ ] **Step 3: Implement `_check_halt_ack`**

Add to `risk_agent.py`:

```python
    async def _check_halt_ack(self) -> None:
        """If the human-ack key is set, clear the halt and emit a CLEARED alert."""
        ack = await self.redis.get("horizon:system:halted:ack")
        if ack != "1":
            return
        was_halted = (await self.redis.get("horizon:system:halted")) == "1"
        await self.redis.delete("horizon:system:halted:ack")
        if was_halted:
            await self.redis.delete("horizon:system:halted")
            await self.emit(
                channel="horizon.risk.alert",
                message_type=MessageType.RISK_ALERT,
                payload={
                    "action": "KILL_SWITCH_CLEARED",
                    "severity": "INFO",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.info("kill_switch_cleared")
```

Call it at the top of `_recompute_risk`:

```python
    async def _recompute_risk(self) -> None:
        await self._check_halt_ack()
        ...
```

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_halt_control.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py horizon-capital/backend/tests/test_halt_control.py
git commit -m "feat(risk): implement halt-ack reader to clear sticky kill switch"
```

---

## Task 2: REPL command to set ack key

**Files:**
- Modify: `horizon-capital/backend/app/tui/commands.py`
- Test: `horizon-capital/backend/tests/test_halt_control.py`

- [ ] **Step 1: Failing test — `halt clear` writes ack key**

```python
# Append
@pytest.mark.asyncio
async def test_halt_clear_command_writes_ack(kv_store):
    from app.tui.commands import handle_command
    await kv_store.set("horizon:system:halted", "1")
    out = await handle_command("halt clear", context={})
    assert "ack" in out.lower() or "clear" in out.lower()
    assert await kv_store.get("horizon:system:halted:ack") == "1"
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_halt_control.py::test_halt_clear_command_writes_ack -v`
Expected: FAIL — command unknown.

- [ ] **Step 3: Add command handler**

Locate the dispatch table in `app/tui/commands.py` (search for `"halt"` or the command-registration pattern). Add:

```python
    elif cmd == "halt":
        return await _handle_halt(args)
```

Define:

```python
async def _handle_halt(args: list[str]) -> str:
    from app.core.kv_store import get_kv_store
    kv = get_kv_store()
    if args and args[0] == "clear":
        await kv.set("horizon:system:halted:ack", "1")
        return "halt-ack written; risk agent will clear the kill switch on next recompute"
    if args and args[0] == "status":
        halted = await kv.get("horizon:system:halted")
        return f"halted={halted!r}"
    return "usage: halt status | halt clear"
```

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_halt_control.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/tui/commands.py horizon-capital/backend/tests/test_halt_control.py
git commit -m "feat(tui): /halt clear and /halt status REPL commands"
```

---

## Task 3: Narrow post-trade subscription to fills only

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py:50-52`
- Test: `horizon-capital/backend/tests/test_halt_control.py`

- [ ] **Step 1: Failing test — ORDER_NEW does not trigger recompute**

```python
# Append
@pytest.mark.asyncio
async def test_order_new_does_not_trigger_recompute():
    from app.core.messaging import AgentMessage, MessageType
    bus = MemoryBus()
    agent = RiskAgent(bus)
    await agent._subscribe()

    calls = {"n": 0}
    orig = agent._recompute_risk
    async def counting():
        calls["n"] += 1
        return None
    agent._recompute_risk = counting  # type: ignore[assignment]

    await bus.publish(AgentMessage(
        message_type=MessageType.ORDER_NEW,
        channel="horizon.execution.order.new",
        payload={"symbol": "AAPL", "side": "BUY"},
    ))
    await bus.publish(AgentMessage(
        message_type=MessageType.ORDER_FILL,
        channel="horizon.execution.order.fill",
        payload={"symbol": "AAPL", "side": "BUY", "quantity": 1},
    ))
    import asyncio
    await asyncio.sleep(0)

    assert calls["n"] == 1, "only ORDER_FILL should trigger recompute"
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_halt_control.py::test_order_new_does_not_trigger_recompute -v`
Expected: FAIL — `calls["n"]` will be 2 with the wildcard subscription.

- [ ] **Step 3: Narrow subscription**

In `risk_agent.py:52`, change:

```python
        await self.bus.subscribe("horizon.execution.order.*", self.on_message)
```

to:

```python
        await self.bus.subscribe("horizon.execution.order.fill", self.on_message)
```

In `on_message`, the `elif message.channel.startswith("horizon.execution.order."):` branch can stay as-is — it'll only fire for fills now.

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_halt_control.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py horizon-capital/backend/tests/test_halt_control.py
git commit -m "fix(risk): narrow post-trade trigger to ORDER_FILL only"
```

---

## Task 4: Recompute mutex

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py`
- Test: `horizon-capital/backend/tests/test_halt_control.py`

- [ ] **Step 1: Failing test — concurrent recompute serialised**

```python
# Append
@pytest.mark.asyncio
async def test_concurrent_recompute_serialised(monkeypatch):
    import asyncio
    bus = MemoryBus()
    agent = RiskAgent(bus)

    state = {"in": 0, "max": 0}
    async def stub_real_work():
        state["in"] += 1
        state["max"] = max(state["max"], state["in"])
        await asyncio.sleep(0.05)
        state["in"] -= 1

    monkeypatch.setattr(agent, "_recompute_body", stub_real_work, raising=False)

    await asyncio.gather(
        agent._recompute_risk(),
        agent._recompute_risk(),
        agent._recompute_risk(),
    )
    assert state["max"] == 1
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_halt_control.py::test_concurrent_recompute_serialised -v`
Expected: FAIL — no `_recompute_body`, no lock.

- [ ] **Step 3: Refactor `_recompute_risk` around a lock**

In `__init__`, add:

```python
        self._recompute_lock = asyncio.Lock()
```

(Add `import asyncio` at top if not already imported — it is.)

Refactor `_recompute_risk`:

```python
    async def _recompute_risk(self) -> None:
        async with self._recompute_lock:
            await self._check_halt_ack()
            await self._recompute_body()

    async def _recompute_body(self) -> None:
        """Compute historical VaR and drawdown, persist metrics."""
        # ... existing body, minus the _check_halt_ack call which moved up ...
```

Move the existing body of `_recompute_risk` (computation + DB write + KV write + emit + kill-switch check) into `_recompute_body`. Keep `_check_halt_ack` only at the entry point.

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_halt_control.py tests/test_risk_metrics_correctness.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py horizon-capital/backend/tests/test_halt_control.py
git commit -m "fix(risk): serialise recompute via asyncio.Lock"
```

---

## Task 5: `risk_metrics` retention

**Files:**
- Modify: `horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py`
- Test: `horizon-capital/backend/tests/test_halt_control.py`

- [ ] **Step 1: Failing test — rows older than 90 days are pruned when over 100k**

```python
# Append
@pytest.mark.asyncio
async def test_metrics_retention_prunes_old_rows(db_session_factory):
    import uuid
    from datetime import timedelta
    from sqlalchemy import text

    bus = MemoryBus()
    agent = RiskAgent(bus)

    old = datetime.now(timezone.utc) - timedelta(days=100)
    new = datetime.now(timezone.utc) - timedelta(days=10)
    async with db_session_factory()() as session:
        # 100_001 rows: 50_000 old + 50_001 new — exceeds threshold; old must go
        for _ in range(50_000):
            await session.execute(
                text("INSERT INTO risk_metrics (id, var_1d_95, max_drawdown, "
                     "current_drawdown, kill_switch_active, created_at, updated_at) "
                     "VALUES (:id, 0, 0, 0, 0, :t, :t)"),
                {"id": str(uuid.uuid4()), "t": old},
            )
        for _ in range(50_001):
            await session.execute(
                text("INSERT INTO risk_metrics (id, var_1d_95, max_drawdown, "
                     "current_drawdown, kill_switch_active, created_at, updated_at) "
                     "VALUES (:id, 0, 0, 0, 0, :t, :t)"),
                {"id": str(uuid.uuid4()), "t": new},
            )
        await session.commit()

    await agent._prune_old_metrics()

    async with db_session_factory()() as session:
        result = await session.execute(text("SELECT COUNT(*) AS n FROM risk_metrics"))
        n = result.fetchone().n
    assert n == 50_001
```

- [ ] **Step 2: Run, expect failure**

Run: `cd horizon-capital/backend && python -m pytest tests/test_halt_control.py::test_metrics_retention_prunes_old_rows -v`
Expected: FAIL — `_prune_old_metrics` does not exist.

- [ ] **Step 3: Implement pruner**

Add to `risk_agent.py`:

```python
    METRICS_RETENTION_DAYS = 90
    METRICS_PRUNE_THRESHOLD = 100_000

    async def _prune_old_metrics(self) -> None:
        """Delete risk_metrics rows older than retention window once table exceeds threshold."""
        async with _get_session_factory()() as session:
            count_row = await session.execute(
                text("SELECT COUNT(*) AS n FROM risk_metrics")
            )
            count = int(count_row.fetchone().n or 0)
            if count < self.METRICS_PRUNE_THRESHOLD:
                return

            cutoff = datetime.now(UTC) - timedelta(days=self.METRICS_RETENTION_DAYS)
            await session.execute(
                text("DELETE FROM risk_metrics WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
            await session.commit()
            logger.info("risk_metrics_pruned",
                        before=count, cutoff=cutoff.isoformat())
```

Add `from datetime import timedelta` at the top (currently `datetime` only).

Call it once per recompute, after the body runs:

```python
    async def _recompute_risk(self) -> None:
        async with self._recompute_lock:
            await self._check_halt_ack()
            await self._recompute_body()
            try:
                await self._prune_old_metrics()
            except Exception as exc:
                logger.warning("metrics_prune_failed", error=str(exc))
```

- [ ] **Step 4: Run tests**

Run: `cd horizon-capital/backend && python -m pytest tests/test_halt_control.py -v`
Expected: PASS. Test inserts 100k rows — slow but acceptable for CI; if needed, drop the threshold inside the agent for the test or use `monkeypatch.setattr(RiskAgent, "METRICS_PRUNE_THRESHOLD", 1000)`.

- [ ] **Step 5: Commit**

```bash
git add horizon-capital/backend/app/agents/middle_office/risk/risk_agent.py horizon-capital/backend/tests/test_halt_control.py
git commit -m "feat(risk): prune risk_metrics older than 90 days when over 100k rows"
```

---

## Self-Review

- Spec coverage:
  - Halt-ack reader → Tasks 1, 2. ✓
  - Recompute mutex → Task 4. ✓
  - Narrow post-trade trigger → Task 3. ✓
  - `risk_metrics` retention → Task 5. ✓
- Type consistency: `_recompute_lock: asyncio.Lock`, `_check_halt_ack`, `_recompute_body`, `_prune_old_metrics` — names stable across tasks. ✓
- Placeholder scan: `handle_command` shape (Task 2 step 3) describes "locate dispatch table" but shows the patch verbatim — engineer must locate the existing pattern, but the change is shown. ✓
