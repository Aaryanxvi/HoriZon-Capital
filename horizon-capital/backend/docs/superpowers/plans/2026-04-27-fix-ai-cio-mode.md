# Fix AI CIO Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `CIO_MODE=AI` actually drive trading, prevent unbounded LLM spend, restore halt state across restarts, fix the fake confirmation gate, add a RESUME path, enrich the LLM digest, and clean up schema collisions and dead code.

**Architecture:**
The AI CIO agent (`app/agents/executive/cio/cio_agent.py`) publishes `CIO_ADVISORY` and `CIO_OVERRIDE` messages on `horizon.executive.cio`. Today only `ExecutionAgent` consumes overrides; advisories die at the dashboard. We extend `PortfolioAgent` to consume advisories as soft-throttle hints, gate Mode B with a per-trigger semaphore + cooldown, persist + rehydrate kill-switch state via the KV store, split the halt flow into `propose -> confirm -> dispatch`, add a RESUME REPL command + bus emission, enrich the digest with positions/exposure, separate Mode A and Mode B persistence into distinct tables, and remove dead state.

**Tech Stack:** Python 3.11+, asyncio, SQLAlchemy (async), pytest-asyncio, MemoryKVStore/Redis, structlog. No new deps.

---

## File Map

**Modify:**
- `backend/app/agents/executive/cio/cio_agent.py` — split halt flow, add cooldown + concurrency cap, rehydrate kill-switch on start, enrich digest, fix Mode B persistence, drop `_alerts` dead deque, separate task sets, RESUME emission
- `backend/app/agents/front_office/portfolio/portfolio_agent.py` — subscribe `horizon.executive.cio`, treat advisory `recommended_adjustments` as soft throttle on new BUYs for flagged symbols
- `backend/app/agents/front_office/trading/execution_agent.py` — accept new `CIO_PROPOSED_HALT` payload as a no-op (stays armed; only `HALT` actions trip the flag); already handles RESUME
- `backend/app/core/local_storage.py` — add `cio_crisis_advisories` table for Mode B writes (no schema collision with Mode A `cio_advisories`)
- `backend/app/tui/commands.py` — fix `cio` REPL HUMAN-mode message; add `cio resume` subcommand
- `backend/app/__main__.py` — no behavioral change; verify wiring still works

**Create:**
- `backend/tests/test_cio_mode_a_advisory_consumed.py` — PortfolioAgent applies CIO recommendations
- `backend/tests/test_cio_mode_b_throttling.py` — Mode B dedup + concurrency cap
- `backend/tests/test_cio_kill_switch_rehydrate.py` — kill-switch state survives restart
- `backend/tests/test_cio_halt_confirmation_gate.py` — halt only enforced after confirm
- `backend/tests/test_cio_resume_path.py` — RESUME command + emission round-trip
- `backend/tests/test_cio_digest_enriched.py` — digest includes positions/exposure
- `backend/tests/test_cio_persistence_split.py` — Mode B writes to `cio_crisis_advisories`

---

## Task 1: Stop Mode B from firing on every signal rejection

**Why:** [risk_agent.py:102-113](../../../app/agents/middle_office/risk/risk_agent.py) emits `RISK_ALERT severity=HIGH` for every position-limit / daily-loss reject. CIO subscribes `horizon.risk.*` and treats HIGH as crisis ([cio_agent.py:124](../../../app/agents/executive/cio/cio_agent.py)) → unbounded concurrent LLM calls. Add (a) per-trigger cooldown, (b) global concurrency semaphore, (c) explicit allow-list of trigger types instead of "any HIGH severity".

**Files:**
- Modify: `backend/app/agents/executive/cio/cio_agent.py`
- Test: `backend/tests/test_cio_mode_b_throttling.py`

- [ ] **Step 1: Write failing test for cooldown**

```python
# backend/tests/test_cio_mode_b_throttling.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.executive.cio.cio_agent import CIOAgent
from app.core.messaging import AgentMessage, MessageType


@pytest.mark.asyncio
async def test_mode_b_dedup_within_cooldown_window():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)
    agent._running = True

    fake_provider = MagicMock()
    fake_provider.provider_name = "claude"
    fake_provider.complete = AsyncMock(
        return_value='{"stance":"HOLD","confidence":0.5,"reasoning":"x","specific_actions":[]}'
    )
    with patch.object(agent, "_get_provider", return_value=fake_provider), \
         patch.object(agent, "_build_portfolio_digest", AsyncMock(return_value={})), \
         patch.object(agent, "_persist_advisory_sync"):
        payload = {"severity": "HIGH", "action": "REJECTED", "symbol": "AAPL"}
        msg = AgentMessage(
            sender_id="risk-agent",
            channel="horizon.risk.alert",
            message_type=MessageType.RISK_ALERT,
            payload=payload,
        )
        await agent.on_message(msg)
        await agent.on_message(msg)
        await agent.on_message(msg)
        # Drain background tasks
        await asyncio.gather(*list(agent._mode_b_tasks), return_exceptions=True)

    assert fake_provider.complete.await_count == 1, (
        "Identical RISK_ALERT triggers within cooldown must dedup to one LLM call"
    )


@pytest.mark.asyncio
async def test_mode_b_concurrency_cap():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)
    agent._running = True

    inflight = 0
    peak = 0

    async def slow_complete(**_kw):
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.05)
        inflight -= 1
        return '{"stance":"HOLD","confidence":0.5,"reasoning":"x","specific_actions":[]}'

    fake_provider = MagicMock()
    fake_provider.provider_name = "claude"
    fake_provider.complete = AsyncMock(side_effect=slow_complete)
    with patch.object(agent, "_get_provider", return_value=fake_provider), \
         patch.object(agent, "_build_portfolio_digest", AsyncMock(return_value={})), \
         patch.object(agent, "_persist_advisory_sync"):
        # Distinct symbols -> bypass dedup, but cap concurrency at 1
        msgs = [
            AgentMessage(
                sender_id="risk-agent",
                channel="horizon.risk.alert",
                message_type=MessageType.RISK_ALERT,
                payload={"severity": "HIGH", "action": "REJECTED", "symbol": s},
            )
            for s in ("AAPL", "MSFT", "GOOG", "AMZN", "META")
        ]
        for m in msgs:
            await agent.on_message(m)
        await asyncio.gather(*list(agent._mode_b_tasks), return_exceptions=True)

    assert peak <= 1, f"Mode B concurrency must be capped at 1, peak={peak}"
```

- [ ] **Step 2: Run test — confirm both fail**

```bash
cd backend && python -m pytest tests/test_cio_mode_b_throttling.py -v
```
Expected: both fail (no `_mode_b_tasks` attribute, no dedup, no semaphore).

- [ ] **Step 3: Implement cooldown + semaphore + task set split**

In `app/agents/executive/cio/cio_agent.py`:

Add module constants near the top (after `CIO_LLM_TIMEOUT_S`):

```python
CIO_MODE_B_COOLDOWN_S = 60          # per (trigger, symbol) dedup window
CIO_MODE_B_MAX_CONCURRENT = 1       # one crisis LLM call at a time
```

Replace the `__init__` body of `CIOAgent` (keep signature):

```python
    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="cio-agent-1",
            agent_type="cio",
            bus=bus,
        )
        self._kill_switch_active: bool = False
        self._proposed_halt: dict | None = None  # awaiting human confirm
        self._last_override: dict | None = None

        # Circuit breaker state for LLM calls
        self._llm_failures: int = 0
        self._llm_circuit_open_until: float = 0

        # Mode B throttling
        self._mode_b_recent: dict[tuple[str, str], float] = {}
        self._mode_b_sem = asyncio.Semaphore(CIO_MODE_B_MAX_CONCURRENT)

        # Tracked background tasks (separate sets so we can bound them)
        self._mode_b_tasks: set[asyncio.Task] = set()
        self._persist_tasks: set[asyncio.Task] = set()
```

Note: this also drops `self._alerts` (dead deque, finding #9) and `self._pending_halt_confirmation` (replaced by `self._proposed_halt`, see Task 4).

Replace `on_message`:

```python
    async def on_message(self, message: AgentMessage) -> None:
        if message.message_type != MessageType.RISK_ALERT:
            return

        action = message.payload.get("action", "")
        severity = message.payload.get("severity", "")

        if action == "KILL_SWITCH_CLEARED":
            self._kill_switch_active = False
            await self._kv_clear_kill_switch()
            logger.info("cio_kill_switch_cleared")
            return
        if action == "KILL_SWITCH_TRIGGERED":
            self._kill_switch_active = True
            await self._kv_set_kill_switch()
            logger.warning("cio_kill_switch_activated")
            trigger = "KILL_SWITCH"
        elif action == "METRICS_UPDATE":
            return  # routine metric emit; not a crisis
        elif severity in ("HIGH", "CRITICAL", "EMERGENCY"):
            trigger = "RISK_ALERT"
        else:
            return

        symbol = message.payload.get("symbol", "*")
        key = (trigger, symbol)
        now = time.monotonic()
        last = self._mode_b_recent.get(key, 0.0)
        if now - last < CIO_MODE_B_COOLDOWN_S:
            logger.debug("cio_mode_b_dedup_skip", trigger=trigger, symbol=symbol)
            return
        self._mode_b_recent[key] = now

        task = asyncio.create_task(
            self._run_mode_b_throttled(message.payload, trigger=trigger)
        )
        self._mode_b_tasks.add(task)
        task.add_done_callback(self._mode_b_tasks.discard)

    async def _run_mode_b_throttled(self, payload: dict, trigger: str) -> None:
        async with self._mode_b_sem:
            await self._run_mode_b(payload, trigger=trigger)
```

The `_kv_set_kill_switch` / `_kv_clear_kill_switch` helpers are added in Task 3. For now stub them:

```python
    async def _kv_set_kill_switch(self) -> None:
        return

    async def _kv_clear_kill_switch(self) -> None:
        return
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd backend && python -m pytest tests/test_cio_mode_b_throttling.py -v
```
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/executive/cio/cio_agent.py \
        backend/tests/test_cio_mode_b_throttling.py
git commit -m "fix(cio): cap Mode B concurrency and dedup repeated triggers"
```

---

## Task 2: Persist + rehydrate kill-switch state across CIO restarts

**Why:** `_kill_switch_active` is in-process only ([cio_agent.py:92](../../../app/agents/executive/cio/cio_agent.py)). RiskAgent gates re-emit on `horizon:system:halted` and won't re-fire ([risk_agent.py:232-245](../../../app/agents/middle_office/risk/risk_agent.py)). Restarting CIO while halted leaves Mode C unreachable.

**Files:**
- Modify: `backend/app/agents/executive/cio/cio_agent.py`
- Test: `backend/tests/test_cio_kill_switch_rehydrate.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_cio_kill_switch_rehydrate.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.executive.cio.cio_agent import CIOAgent


@pytest.mark.asyncio
async def test_cio_rehydrates_kill_switch_from_kv():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    agent = CIOAgent(bus=bus)
    assert agent._kill_switch_active is False

    fake_kv = MagicMock()
    fake_kv.get = AsyncMock(return_value="1")
    with patch("app.agents.executive.cio.cio_agent._get_kv", return_value=fake_kv):
        await agent._rehydrate_kill_switch()

    assert agent._kill_switch_active is True


@pytest.mark.asyncio
async def test_cio_rehydrate_when_not_halted():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    agent = CIOAgent(bus=bus)

    fake_kv = MagicMock()
    fake_kv.get = AsyncMock(return_value=None)
    with patch("app.agents.executive.cio.cio_agent._get_kv", return_value=fake_kv):
        await agent._rehydrate_kill_switch()

    assert agent._kill_switch_active is False
```

- [ ] **Step 2: Run — confirm fail**

```bash
cd backend && python -m pytest tests/test_cio_kill_switch_rehydrate.py -v
```
Expected: fail (no `_rehydrate_kill_switch`, no `_get_kv` in cio_agent module).

- [ ] **Step 3: Add KV helpers and call from `run()`**

In `app/agents/executive/cio/cio_agent.py`, add at module level next to `_get_session_factory`:

```python
def _get_kv():
    """Lazy KV store lookup -- avoids importing at module load."""
    from app.core.kv_store import get_kv_store
    return get_kv_store()


KILL_SWITCH_KV_KEY = "horizon:system:halted"
```

Replace the stub `_kv_set_kill_switch` / `_kv_clear_kill_switch` and add `_rehydrate_kill_switch`:

```python
    async def _kv_set_kill_switch(self) -> None:
        try:
            await _get_kv().set(KILL_SWITCH_KV_KEY, "1")
        except Exception as exc:
            logger.warning("cio_kv_set_halt_failed", error=str(exc))

    async def _kv_clear_kill_switch(self) -> None:
        try:
            await _get_kv().set(KILL_SWITCH_KV_KEY, "0")
        except Exception as exc:
            logger.warning("cio_kv_clear_halt_failed", error=str(exc))

    async def _rehydrate_kill_switch(self) -> None:
        try:
            val = await _get_kv().get(KILL_SWITCH_KV_KEY)
        except Exception as exc:
            logger.warning("cio_kv_rehydrate_failed", error=str(exc))
            return
        if val == "1":
            self._kill_switch_active = True
            logger.warning("cio_kill_switch_rehydrated_from_kv")
```

Update `run()` to call rehydrate before the loop:

```python
    async def run(self) -> None:
        await self._rehydrate_kill_switch()
        await asyncio.sleep(30)
        while self._running:
            try:
                await self._run_mode_a()
            except Exception as exc:
                logger.error("cio_mode_a_error", error=str(exc))
            await asyncio.sleep(CIO_ADVISORY_INTERVAL)
```

- [ ] **Step 4: Run — confirm pass**

```bash
cd backend && python -m pytest tests/test_cio_kill_switch_rehydrate.py -v
```
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/executive/cio/cio_agent.py \
        backend/tests/test_cio_kill_switch_rehydrate.py
git commit -m "fix(cio): rehydrate kill-switch state from KV on startup"
```

---

## Task 3: Make halt confirmation gate real (propose → confirm → dispatch)

**Why:** Mode C currently publishes `CIO_OVERRIDE` immediately ([cio_agent.py:330-336](../../../app/agents/executive/cio/cio_agent.py)) and ExecutionAgent flips `_cio_halt_active=True` on receipt ([execution_agent.py:78-83](../../../app/agents/front_office/trading/execution_agent.py)). The "confirm halt" REPL is theatre. Split the flow: Mode C now stores a *proposed* halt and emits a non-blocking `CIO_PROPOSED_HALT`. The real `CIO_OVERRIDE` actions=["HALT"] only fires from `set_halt_confirmed`.

**Files:**
- Modify: `backend/app/agents/executive/cio/cio_agent.py`
- Modify: `backend/app/agents/front_office/trading/execution_agent.py`
- Test: `backend/tests/test_cio_halt_confirmation_gate.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_cio_halt_confirmation_gate.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agents.executive.cio.cio_agent import CIOAgent
from app.core.messaging import MessageType


@pytest.mark.asyncio
async def test_mode_c_does_not_emit_halt_until_confirmed():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)

    crisis = {"stance": "HALT", "confidence": 0.95,
              "reasoning": "test", "specific_actions": ["close_all"]}
    provider = MagicMock(); provider.provider_name = "claude"

    await agent._run_mode_c(crisis, {"trigger": "KILL_SWITCH"}, provider)

    published_types = [c.args[0].message_type for c in bus.publish.await_args_list]
    assert MessageType.CIO_PROPOSED_HALT in published_types
    halt_overrides = [
        c.args[0] for c in bus.publish.await_args_list
        if c.args[0].message_type == MessageType.CIO_OVERRIDE
        and "HALT" in c.args[0].payload.get("actions", [])
    ]
    assert halt_overrides == [], "HALT override must NOT publish before confirm"
    assert agent._proposed_halt is not None


@pytest.mark.asyncio
async def test_set_halt_confirmed_emits_real_override():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)
    agent._proposed_halt = {
        "override_id": "abc", "trigger": "KILL_SWITCH",
        "confidence": 0.9, "actions": ["close_all"],
        "reasoning": "test", "provider": "claude",
    }

    await agent.set_halt_confirmed()

    halt_overrides = [
        c.args[0] for c in bus.publish.await_args_list
        if c.args[0].message_type == MessageType.CIO_OVERRIDE
        and "HALT" in c.args[0].payload.get("actions", [])
    ]
    assert len(halt_overrides) == 1
    assert agent._proposed_halt is None


@pytest.mark.asyncio
async def test_set_halt_confirmed_noop_when_no_proposal():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)

    await agent.set_halt_confirmed()
    assert bus.publish.await_count == 0
```

- [ ] **Step 2: Run — confirm fail**

```bash
cd backend && python -m pytest tests/test_cio_halt_confirmation_gate.py -v
```
Expected: fail (no `CIO_PROPOSED_HALT`, current Mode C emits override eagerly).

- [ ] **Step 3: Add new MessageType**

In `backend/app/core/messaging.py`, inside the `MessageType(StrEnum)` block, add:

```python
    CIO_PROPOSED_HALT = "cio_proposed_halt"
```

- [ ] **Step 4: Rewrite Mode C and `set_halt_confirmed`**

In `app/agents/executive/cio/cio_agent.py`, replace `_run_mode_c`:

```python
    async def _run_mode_c(
        self,
        crisis_result: dict,
        trigger_payload: dict,
        provider,
        rendered_prompt: str = "",
        raw_response: str = "",
    ) -> None:
        """Stage a halt proposal -- requires explicit operator confirmation."""
        override_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        audit = {
            "override_id": override_id,
            "timestamp": now.isoformat(),
            "trigger": "KILL_SWITCH",
            "confidence": crisis_result.get("confidence", 0.0),
            "actions": crisis_result.get("specific_actions", []),
            "reasoning": crisis_result.get("reasoning", ""),
            "provider": provider.provider_name,
        }

        self._last_override = audit
        self._proposed_halt = audit

        msg = AgentMessage(
            sender_id=self.agent_id,
            channel="horizon.executive.cio",
            message_type=MessageType.CIO_PROPOSED_HALT,
            payload=audit,
        )
        await self.bus.publish(msg)

        self._persist_override_sync(
            audit, crisis_result, trigger_payload, provider.provider_name,
            rendered_prompt=rendered_prompt, raw_response=raw_response,
        )

        logger.critical(
            "cio_halt_proposed",
            override_id=override_id,
            confidence=audit["confidence"],
        )
```

Replace `set_halt_confirmed`:

```python
    async def set_halt_confirmed(self) -> None:
        """Publish the queued halt proposal as a real CIO_OVERRIDE."""
        proposal = self._proposed_halt
        if proposal is None:
            logger.info("cio_halt_confirm_no_pending_proposal")
            return
        self._proposed_halt = None

        payload = {
            "override_id": proposal["override_id"],
            "timestamp": datetime.now(UTC).isoformat(),
            "trigger": proposal["trigger"],
            "actions": ["HALT"],
            "confidence": proposal["confidence"],
            "reasoning": proposal["reasoning"],
        }
        msg = AgentMessage(
            sender_id=self.agent_id,
            channel="horizon.executive.cio",
            message_type=MessageType.CIO_OVERRIDE,
            payload=payload,
        )
        await self.bus.publish(msg)
        logger.warning("cio_halt_confirmed", override_id=proposal["override_id"])
```

- [ ] **Step 5: Make ExecutionAgent ignore proposals (only react to overrides)**

In `app/agents/front_office/trading/execution_agent.py`, leave the existing CIO_OVERRIDE handler untouched. Add a defensive ignore in `on_message` before the override branch:

```python
        if message.message_type == MessageType.CIO_PROPOSED_HALT:
            logger.info(
                "execution_cio_halt_proposed",
                override_id=message.payload.get("override_id"),
            )
            return
```

- [ ] **Step 6: Run tests — confirm pass**

```bash
cd backend && python -m pytest tests/test_cio_halt_confirmation_gate.py -v
```
Expected: all three PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agents/executive/cio/cio_agent.py \
        backend/app/agents/front_office/trading/execution_agent.py \
        backend/app/core/messaging.py \
        backend/tests/test_cio_halt_confirmation_gate.py
git commit -m "fix(cio): split halt flow into proposal + confirmation"
```

---

## Task 4: Add RESUME path

**Why:** ExecutionAgent only clears halt on `actions=["RESUME"]` ([execution_agent.py:84-87](../../../app/agents/front_office/trading/execution_agent.py)). Nothing in CIO emits RESUME → halt is permanent.

**Files:**
- Modify: `backend/app/agents/executive/cio/cio_agent.py`
- Modify: `backend/app/tui/commands.py`
- Test: `backend/tests/test_cio_resume_path.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_cio_resume_path.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agents.executive.cio.cio_agent import CIOAgent
from app.core.messaging import MessageType


@pytest.mark.asyncio
async def test_resume_emits_override_and_clears_kill_switch():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)
    agent._kill_switch_active = True

    await agent.resume_trading(reason="manual operator unhalt")

    resumes = [
        c.args[0] for c in bus.publish.await_args_list
        if c.args[0].message_type == MessageType.CIO_OVERRIDE
        and "RESUME" in c.args[0].payload.get("actions", [])
    ]
    assert len(resumes) == 1
    assert agent._kill_switch_active is False
```

- [ ] **Step 2: Run — confirm fail**

```bash
cd backend && python -m pytest tests/test_cio_resume_path.py -v
```
Expected: fail (no `resume_trading` method).

- [ ] **Step 3: Implement `resume_trading`**

In `app/agents/executive/cio/cio_agent.py`, add to `CIOAgent`:

```python
    async def resume_trading(self, reason: str = "manual") -> None:
        """Clear halt locally and broadcast a RESUME override."""
        self._kill_switch_active = False
        self._proposed_halt = None
        await self._kv_clear_kill_switch()

        override_id = str(uuid.uuid4())
        msg = AgentMessage(
            sender_id=self.agent_id,
            channel="horizon.executive.cio",
            message_type=MessageType.CIO_OVERRIDE,
            payload={
                "override_id": override_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "trigger": "MANUAL_RESUME",
                "actions": ["RESUME"],
                "confidence": 1.0,
                "reasoning": reason,
            },
        )
        await self.bus.publish(msg)
        logger.warning("cio_resume_published", override_id=override_id, reason=reason)
```

- [ ] **Step 4: Wire `cio resume` REPL command**

In `backend/app/tui/commands.py`, in `_cmd_cio`, add a branch *before* the `else` fallback:

```python
        elif sub == "resume":
            cio = self._get_cio_agent()
            if cio is None:
                from app.config import CIOMode, settings
                if settings.cio_mode != CIOMode.AI:
                    return "[yellow]CIO is in HUMAN mode. Set CIO_MODE=AI.[/yellow]"
                return "[yellow]CIO agent not running.[/yellow]"
            await cio.resume_trading(reason="REPL operator resume")
            return "[green]RESUME published. Trading will re-enable on the next signal.[/green]"
```

- [ ] **Step 5: Run — confirm pass**

```bash
cd backend && python -m pytest tests/test_cio_resume_path.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/executive/cio/cio_agent.py \
        backend/app/tui/commands.py \
        backend/tests/test_cio_resume_path.py
git commit -m "feat(cio): add RESUME path via cio_agent.resume_trading + REPL"
```

---

## Task 5: Wire Mode A advisory into PortfolioAgent (soft throttle)

**Why:** Today CIO advisory is cosmetic — only the dashboard reads `CIO_ADVISORY` ([__main__.py:329](../../../app/__main__.py)). PortfolioAgent never sees it. Implement a *soft* effect (not blind execution): for every advisory, store the latest `risk_flags` symbols and `recommended_adjustments` with action `EXIT` / `TRIM`. Block new BUYs (and shrink ADDs to zero) for those symbols until the next advisory clears them. This is the minimum useful integration — it does NOT auto-execute LLM trade ideas (which would require a separate spec).

**Files:**
- Modify: `backend/app/agents/front_office/portfolio/portfolio_agent.py`
- Test: `backend/tests/test_cio_mode_a_advisory_consumed.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_cio_mode_a_advisory_consumed.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
from app.core.messaging import AgentMessage, MessageType


@pytest.mark.asyncio
async def test_portfolio_records_cio_exit_recommendation():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    agent = PortfolioAgent(bus=bus)

    advisory = AgentMessage(
        sender_id="cio-agent-1",
        channel="horizon.executive.cio",
        message_type=MessageType.CIO_ADVISORY,
        payload={
            "outlook": "bearish",
            "summary": "tighten",
            "recommended_adjustments": [
                {"symbol": "AAPL", "action": "EXIT", "reason": "overbought"},
                {"symbol": "MSFT", "action": "TRIM", "reason": "concentration"},
                {"symbol": "GOOG", "action": "ADD", "reason": "n/a"},
            ],
            "risk_flags": ["NVDA"],
            "is_crisis": False,
        },
    )
    await agent.on_message(advisory)

    assert agent.is_cio_blocked("AAPL") is True
    assert agent.is_cio_blocked("MSFT") is True
    assert agent.is_cio_blocked("NVDA") is True
    assert agent.is_cio_blocked("GOOG") is False


@pytest.mark.asyncio
async def test_portfolio_blocks_new_buy_for_cio_blocked_symbol(monkeypatch):
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    agent = PortfolioAgent(bus=bus)
    agent._cio_blocked_symbols = {"AAPL"}

    sent = []

    async def fake_emit(**kw):
        sent.append(kw)

    monkeypatch.setattr(agent, "emit", fake_emit)

    fake_kv = MagicMock()
    fake_kv.get = AsyncMock(return_value=None)
    agent.redis = fake_kv

    await agent._handle_signal({
        "symbol": "AAPL", "direction": 1, "signal_id": "s1",
        "strategy_id": "test", "confidence": 0.8, "exchange": "NASDAQ",
    })

    assert sent == [], "BUY for CIO-blocked symbol must be suppressed"
```

- [ ] **Step 2: Run — confirm fail**

```bash
cd backend && python -m pytest tests/test_cio_mode_a_advisory_consumed.py -v
```
Expected: fail (no `is_cio_blocked`, no `_cio_blocked_symbols`).

- [ ] **Step 3: Subscribe + record advisory**

In `app/agents/front_office/portfolio/portfolio_agent.py`:

Add to `__init__` (end of body):

```python
        # Symbols the CIO has flagged EXIT/TRIM or risk-flagged.
        # New BUYs for these are dropped until the next advisory clears them.
        self._cio_blocked_symbols: set[str] = set()
```

Append to `_subscribe`:

```python
        await self.bus.subscribe("horizon.executive.cio", self.on_message)
```

Extend `on_message` — add a branch alongside the existing ones:

```python
        elif message.message_type == MessageType.CIO_ADVISORY:
            self._record_cio_advisory(message.payload)
```

Add new methods:

```python
    def _record_cio_advisory(self, payload: dict) -> None:
        """Refresh the CIO-blocked symbol set from a Mode A advisory."""
        if payload.get("is_crisis"):
            return  # crisis advisories handled via CIO_OVERRIDE on Execution
        blocked: set[str] = set()
        for adj in payload.get("recommended_adjustments") or []:
            if not isinstance(adj, dict):
                continue
            action = (adj.get("action") or "").upper()
            symbol = (adj.get("symbol") or "").upper()
            if symbol and symbol != "PORTFOLIO" and action in {"EXIT", "TRIM"}:
                blocked.add(symbol)
        for flag in payload.get("risk_flags") or []:
            if isinstance(flag, str) and flag.isupper() and flag.isalnum():
                blocked.add(flag)
        self._cio_blocked_symbols = blocked
        logger.info("cio_advisory_applied",
                    blocked_count=len(blocked),
                    blocked=sorted(blocked))

    def is_cio_blocked(self, symbol: str) -> bool:
        return (symbol or "").upper() in self._cio_blocked_symbols
```

- [ ] **Step 4: Suppress BUYs for blocked symbols**

In `_handle_signal`, immediately after the `halted == "1"` block, add:

```python
        symbol_in = (payload.get("symbol") or "").upper()
        if int(payload.get("direction", 0) or 0) > 0 and self.is_cio_blocked(symbol_in):
            logger.info("signal_blocked_by_cio_advisory", symbol=symbol_in)
            return
```

- [ ] **Step 5: Run — confirm pass**

```bash
cd backend && python -m pytest tests/test_cio_mode_a_advisory_consumed.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/front_office/portfolio/portfolio_agent.py \
        backend/tests/test_cio_mode_a_advisory_consumed.py
git commit -m "feat(portfolio): consume CIO_ADVISORY as soft BUY throttle"
```

---

## Task 6: Enrich Mode A portfolio digest

**Why:** [`_build_portfolio_digest`](../../../app/agents/executive/cio/cio_agent.py) returns `{nav, open_positions}` only. Prompt asks for symbol-level recommendations the LLM cannot ground. Add: top 10 positions (symbol, qty, market_value, weight_pct, unrealized_pnl), realized/unrealized PnL totals, gross + net exposure %, recent fills (last 10), and current drawdown.

**Files:**
- Modify: `backend/app/agents/executive/cio/cio_agent.py`
- Test: `backend/tests/test_cio_digest_enriched.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_cio_digest_enriched.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.executive.cio.cio_agent import CIOAgent


@pytest.mark.asyncio
async def test_digest_includes_required_keys():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    agent = CIOAgent(bus=bus)

    fake_kv = MagicMock()
    fake_kv.get = AsyncMock(return_value="100000")
    fake_kv.hgetall = AsyncMock(return_value={
        "current_drawdown": "0.05", "max_drawdown": "0.12",
    })

    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)

    class _Result:
        def __init__(self, rows): self._rows = rows
        def fetchall(self): return self._rows
        def scalar(self): return self._rows[0][0] if self._rows else 0
        def fetchone(self): return self._rows[0] if self._rows else None

    pos_rows = [
        ("AAPL", 100, 18000.0, 18.0, 500.0),
        ("MSFT", 50, 20000.0, 20.0, -300.0),
    ]
    fill_rows = [
        ("AAPL", "BUY", 100, 180.0, "2026-04-27T09:00:00+00:00"),
    ]

    async def execute(stmt, *_a, **_kw):
        sql = str(stmt)
        if "FROM positions" in sql and "SUM" in sql:
            return _Result([(38000.0,)])
        if "FROM positions" in sql and "ORDER BY" in sql:
            return _Result(pos_rows)
        if "FROM positions" in sql:
            return _Result([(2,)])
        if "FROM trades" in sql or "FROM order_fills" in sql:
            return _Result(fill_rows)
        return _Result([])

    fake_session.execute = AsyncMock(side_effect=execute)

    with patch("app.agents.executive.cio.cio_agent._get_kv", return_value=fake_kv), \
         patch("app.agents.executive.cio.cio_agent._get_session_factory",
               return_value=lambda: fake_session):
        digest = await agent._build_portfolio_digest()

    assert "nav" in digest
    assert "open_positions" in digest
    assert "top_positions" in digest and len(digest["top_positions"]) == 2
    assert "gross_exposure_pct" in digest
    assert "current_drawdown_pct" in digest
    assert "recent_fills" in digest
```

- [ ] **Step 2: Run — confirm fail**

```bash
cd backend && python -m pytest tests/test_cio_digest_enriched.py -v
```
Expected: fail (digest is missing the new keys).

- [ ] **Step 3: Replace `_build_portfolio_digest`**

In `app/agents/executive/cio/cio_agent.py`:

```python
    async def _build_portfolio_digest(self) -> dict:
        """Gather portfolio state for LLM context.

        Pulls NAV from KV, top 10 positions + open count + total market value
        from the positions table, recent fills, and drawdown from KV.
        """
        digest: dict = {
            "nav": None,
            "open_positions": 0,
            "top_positions": [],
            "gross_exposure_pct": 0.0,
            "current_drawdown_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "recent_fills": [],
        }

        try:
            kv = _get_kv()
            nav_str = await kv.get("horizon:portfolio:nav")
            if nav_str is not None:
                digest["nav"] = float(nav_str)
        except Exception as exc:
            logger.debug("cio_digest_kv_nav_error", error=str(exc))

        try:
            kv = _get_kv()
            risk = await kv.hgetall("horizon:risk:latest")
            if risk:
                digest["current_drawdown_pct"] = float(risk.get("current_drawdown", 0.0)) * 100
                digest["max_drawdown_pct"] = float(risk.get("max_drawdown", 0.0)) * 100
        except Exception as exc:
            logger.debug("cio_digest_kv_risk_error", error=str(exc))

        try:
            from sqlalchemy import text
            async with _get_session_factory()() as session:
                cnt = await session.execute(
                    text("SELECT COUNT(*) FROM positions WHERE status = 'OPEN'")
                )
                digest["open_positions"] = int(cnt.scalar() or 0)

                gross = await session.execute(
                    text("SELECT COALESCE(SUM(ABS(quantity * current_price)), 0) "
                         "FROM positions WHERE status = 'OPEN'")
                )
                gross_val = float(gross.scalar() or 0.0)
                if digest["nav"] and digest["nav"] > 0:
                    digest["gross_exposure_pct"] = round(gross_val / digest["nav"] * 100, 2)

                top = await session.execute(
                    text("""
                        SELECT symbol, quantity, quantity * current_price AS mv,
                               unrealized_pnl
                        FROM positions
                        WHERE status = 'OPEN'
                        ORDER BY ABS(quantity * current_price) DESC
                        LIMIT 10
                    """)
                )
                rows = top.fetchall()
                for row in rows:
                    mv = float(row[2] or 0.0)
                    weight = round(mv / digest["nav"] * 100, 2) if digest["nav"] else 0.0
                    digest["top_positions"].append({
                        "symbol": row[0],
                        "qty": float(row[1] or 0.0),
                        "market_value": round(mv, 2),
                        "weight_pct": weight,
                        "unrealized_pnl": round(float(row[3] or 0.0), 2),
                    })

                fills = await session.execute(
                    text("""
                        SELECT symbol, side, quantity, price, created_at
                        FROM trades
                        ORDER BY created_at DESC
                        LIMIT 10
                    """)
                )
                for row in fills.fetchall():
                    digest["recent_fills"].append({
                        "symbol": row[0],
                        "side": row[1],
                        "qty": float(row[2] or 0.0),
                        "price": float(row[3] or 0.0),
                        "ts": str(row[4]),
                    })
        except Exception as exc:
            logger.debug("cio_digest_db_error", error=str(exc))

        return digest
```

- [ ] **Step 4: Run — confirm pass**

```bash
cd backend && python -m pytest tests/test_cio_digest_enriched.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/executive/cio/cio_agent.py \
        backend/tests/test_cio_digest_enriched.py
git commit -m "feat(cio): enrich Mode A digest with positions, exposure, fills"
```

---

## Task 7: Split Mode B persistence into its own table

**Why:** Mode B writes `outlook = stance.lower()` ∈ {halt, reduce, hold} into `cio_advisories.outlook` declared as bullish/neutral/bearish ([cio_agent.py:275](../../../app/agents/executive/cio/cio_agent.py)), and `recommended_adjustments` is list[str] not list[dict] ([cio_agent.py:277](../../../app/agents/executive/cio/cio_agent.py)). Add a dedicated `cio_crisis_advisories` table for Mode B, leave Mode A untouched.

**Files:**
- Modify: `backend/app/core/local_storage.py`
- Modify: `backend/app/agents/executive/cio/cio_agent.py`
- Test: `backend/tests/test_cio_persistence_split.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_cio_persistence_split.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.executive.cio.cio_agent import CIOAgent


@pytest.mark.asyncio
async def test_mode_b_writes_to_crisis_table():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)

    captured_sql: list[str] = []

    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)

    async def execute(stmt, params=None):
        captured_sql.append(str(stmt))
        return MagicMock()

    fake_session.execute = AsyncMock(side_effect=execute)
    fake_session.commit = AsyncMock()

    with patch("app.agents.executive.cio.cio_agent._get_session_factory",
               return_value=lambda: fake_session):
        await agent._persist_crisis_advisory(
            stance="HALT",
            confidence=0.9,
            reasoning="test",
            specific_actions=["close_all"],
            trigger="KILL_SWITCH",
            provider="claude",
        )

    joined = " ".join(captured_sql)
    assert "INSERT INTO cio_crisis_advisories" in joined
    assert "cio_advisories" not in joined
```

- [ ] **Step 2: Run — confirm fail**

```bash
cd backend && python -m pytest tests/test_cio_persistence_split.py -v
```
Expected: fail (no `_persist_crisis_advisory`, no `cio_crisis_advisories` table).

- [ ] **Step 3: Add table to schema**

In `backend/app/core/local_storage.py`, immediately after the existing `cio_overrides` table block:

```python
    # --- CIO Crisis Advisories (Mode B) ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cio_crisis_advisories (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            stance TEXT NOT NULL,
            confidence REAL NOT NULL,
            reasoning TEXT NOT NULL,
            specific_actions TEXT NOT NULL,
            trigger TEXT NOT NULL,
            provider TEXT NOT NULL
        )
    """))
```

- [ ] **Step 4: Add `_persist_crisis_advisory`, route Mode B to it**

In `app/agents/executive/cio/cio_agent.py`, add:

```python
    def _persist_crisis_advisory_sync(
        self, stance: str, confidence: float, reasoning: str,
        specific_actions: list, trigger: str, provider: str,
    ) -> None:
        try:
            task = asyncio.create_task(self._persist_crisis_advisory(
                stance=stance, confidence=confidence, reasoning=reasoning,
                specific_actions=specific_actions, trigger=trigger, provider=provider,
            ))
        except RuntimeError:
            return
        self._persist_tasks.add(task)
        task.add_done_callback(self._persist_tasks.discard)

    async def _persist_crisis_advisory(
        self, stance: str, confidence: float, reasoning: str,
        specific_actions: list, trigger: str, provider: str,
    ) -> None:
        try:
            from sqlalchemy import text
            async with _get_session_factory()() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO cio_crisis_advisories
                            (id, timestamp, stance, confidence, reasoning,
                             specific_actions, trigger, provider)
                        VALUES
                            (:id, :ts, :stance, :confidence, :reasoning,
                             :actions, :trigger, :provider)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "ts": datetime.now(UTC).isoformat(),
                        "stance": stance,
                        "confidence": float(confidence),
                        "reasoning": reasoning,
                        "actions": json.dumps(specific_actions or []),
                        "trigger": trigger,
                        "provider": provider,
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.error("cio_persist_crisis_error", error=str(exc))
```

In `_run_mode_b`, replace the `_persist_advisory_sync({...}, provider.provider_name, trigger)` call with:

```python
        self._persist_crisis_advisory_sync(
            stance=stance,
            confidence=confidence,
            reasoning=crisis.get("reasoning", ""),
            specific_actions=crisis.get("specific_actions", []),
            trigger=trigger,
            provider=provider.provider_name,
        )
```

- [ ] **Step 5: Run — confirm pass**

```bash
cd backend && python -m pytest tests/test_cio_persistence_split.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/local_storage.py \
        backend/app/agents/executive/cio/cio_agent.py \
        backend/tests/test_cio_persistence_split.py
git commit -m "fix(cio): persist Mode B to cio_crisis_advisories (no schema collision)"
```

---

## Task 8: REPL `cio` HUMAN-mode message + cleanup of dead state

**Why:** [commands.py:1100](../../../app/tui/commands.py) `cio` (no args) hits DB regardless of mode and lies with "No CIO advisory recorded yet" in HUMAN mode. Also drop residual references to `_pending_halt_confirmation` and `_alerts` from any tests that import them; the cleanup is in earlier tasks but verify nothing else still touches them.

**Files:**
- Modify: `backend/app/tui/commands.py`

- [ ] **Step 1: Add the mode check to default branch**

In `_cmd_cio`, replace the trailing `else: return await self._cmd_cio_latest()` block with:

```python
        else:
            from app.config import CIOMode, settings
            if settings.cio_mode != CIOMode.AI:
                return (
                    "[yellow]CIO is in HUMAN mode. "
                    "Set CIO_MODE=AI to enable AI advisories.[/yellow]"
                )
            return await self._cmd_cio_latest()
```

- [ ] **Step 2: Verify no orphan references**

```bash
cd backend && grep -RIn "_pending_halt_confirmation\|self\._alerts\b" app/ tests/
```
Expected: zero hits in `app/`. If tests still reference them, delete those assertions.

- [ ] **Step 3: Run the full CIO test suite**

```bash
cd backend && python -m pytest tests/test_cio_agent.py tests/test_cio_mode_b_throttling.py \
    tests/test_cio_kill_switch_rehydrate.py tests/test_cio_halt_confirmation_gate.py \
    tests/test_cio_resume_path.py tests/test_cio_mode_a_advisory_consumed.py \
    tests/test_cio_digest_enriched.py tests/test_cio_persistence_split.py -v
```
Expected: all PASS. Pre-existing tests in `test_cio_agent.py` may need targeted edits where they assert legacy behavior (eager halt emit, deque presence). Update the asserts; do not weaken the new contracts.

- [ ] **Step 4: Commit**

```bash
git add backend/app/tui/commands.py backend/tests/
git commit -m "chore(cio): fix REPL HUMAN-mode message; reconcile legacy tests"
```

---

## Task 9: End-to-end smoke test

**Files:**
- Test: `backend/tests/test_cio_e2e_smoke.py` (new)

- [ ] **Step 1: Write integration smoke**

```python
# backend/tests/test_cio_e2e_smoke.py
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.executive.cio.cio_agent import CIOAgent
from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
from app.agents.front_office.trading.execution_agent import ExecutionAgent
from app.core.messaging import AgentMessage, MessageType


@pytest.mark.asyncio
async def test_advisory_flows_into_portfolio_block_set():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    cio = CIOAgent(bus=bus)
    pf = PortfolioAgent(bus=bus)

    fake_provider = MagicMock()
    fake_provider.provider_name = "claude"
    fake_provider.complete = AsyncMock(return_value=json.dumps({
        "outlook": "bearish",
        "summary": "tighten exposure",
        "recommended_adjustments": [
            {"symbol": "AAPL", "action": "EXIT", "reason": "rich"},
        ],
        "risk_flags": ["TSLA"],
    }))

    captured: list[AgentMessage] = []
    async def publish(msg): captured.append(msg)
    bus.publish = publish

    with patch.object(cio, "_get_provider", return_value=fake_provider), \
         patch.object(cio, "_build_portfolio_digest", AsyncMock(return_value={"nav": 100000.0})), \
         patch.object(cio, "_persist_advisory_sync"):
        await cio._run_mode_a()

    advisories = [m for m in captured if m.message_type == MessageType.CIO_ADVISORY]
    assert len(advisories) == 1
    await pf.on_message(advisories[0])
    assert pf.is_cio_blocked("AAPL")
    assert pf.is_cio_blocked("TSLA")
```

- [ ] **Step 2: Run — must pass**

```bash
cd backend && python -m pytest tests/test_cio_e2e_smoke.py -v
```

- [ ] **Step 3: Run full suite for regressions**

```bash
cd backend && python -m pytest tests/ -x --ignore=tests/test_paper_trading_honest.py
```
Expected: all PASS. Investigate any failures before commit.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_cio_e2e_smoke.py
git commit -m "test(cio): e2e smoke from advisory to PortfolioAgent throttle"
```

---

## Self-Review

Spec coverage:
- #1 advisory unused → Task 5 (PortfolioAgent throttle) + Task 9 (smoke).
- #2 Mode B per-reject LLM spend → Task 1 (cooldown + semaphore + METRICS_UPDATE skip).
- #3 kill-switch lost on restart → Task 2 (rehydrate from KV).
- #4 fake confirmation gate → Task 3 (proposal vs override split).
- #5 no RESUME path → Task 4.
- #6 anemic digest → Task 6.
- #7 outlook column collision → Task 7 (separate `cio_crisis_advisories`).
- #8 list[str] vs list[dict] → Task 7 (`specific_actions` column).
- #9 dead `_alerts` deque → Task 1 (removed in `__init__` rewrite).
- #10 REPL HUMAN-mode lie → Task 8.
- #11 shared task set → Task 1 (`_mode_b_tasks` vs `_persist_tasks`).
- #12 (Mode A first-call backoff) — kept; existing 30s sleep is acceptable. Not addressed.

Placeholder scan: every step has full code or an exact command. No "TBD".

Type consistency: `CIO_PROPOSED_HALT` declared in Task 3, used in Task 3 and Task 8 cleanup. `_proposed_halt`, `_mode_b_tasks`, `_mode_b_recent`, `_mode_b_sem`, `_cio_blocked_symbols`, `is_cio_blocked`, `resume_trading`, `_persist_crisis_advisory_sync` are all introduced and consumed under the same names.

Known follow-ups out of scope: forwarding LLM-proposed BUY/ADD instructions as actual orders (would need a separate spec — current plan is intentionally a *throttle*, not an *autopilot*); Mode B prompt engineering and confidence calibration; CIO REPL natural-language chat surface.
