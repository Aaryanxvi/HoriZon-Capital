# Dashboard Redesign — Intelligence Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current 2-column dashboard with a 3-column Intelligence Hub showing agents, live watchlist prices, portfolio positions, risk metrics, pending orders, and trade history — all fed by live data from the bus and KV store.

**Architecture:** The dashboard pulls live data from three sources: (1) bus messages routed via `__main__.py` subscriptions, (2) KV store reads for cached prices, and (3) enriched payloads from `PositionMonitorWorker` and `DataIngestionWorker`. New `PRICE_UPDATE` message type carries price data from ingestion to dashboard. Agent status payloads gain a `current_task` field. Bottom strip replaces log tail with pending orders and trade history.

**Tech Stack:** Python 3.14, Rich (Layout, Panel, Table, Text, Live), SQLite (LOCAL mode), MemoryBus, MemoryKVStore

---

### Task 1: Add `PRICE_UPDATE` message type and publish from `DataIngestionWorker`

**Files:**
- Modify: `backend/app/core/messaging.py:24-71` (MessageType enum)
- Modify: `backend/app/workers/data_ingestion_worker.py:183-220` (_poll_yahoo_eod)
- Modify: `backend/app/workers/data_ingestion_worker.py:224-265` (_poll_coingecko)
- Test: `backend/tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_smoke.py` in the `TestMessageTypes` class (or create one near line 769):

```python
class TestPriceUpdate:
    def test_price_update_message_type_exists(self):
        from app.core.messaging import MessageType
        assert hasattr(MessageType, "PRICE_UPDATE")

    @pytest.mark.asyncio
    async def test_price_update_message_roundtrip(self):
        from app.core.messaging import AgentMessage, MessageType
        msg = AgentMessage(
            sender_id="data-ingestion-worker",
            channel="horizon.market.price",
            message_type=MessageType.PRICE_UPDATE,
            payload={
                "symbol": "RELIANCE.NSE",
                "price": 2847.50,
                "change_pct": 1.2,
                "volume": 2_100_000,
                "prev_close": 2813.82,
            },
        )
        serialized = msg.serialize()
        deserialized = AgentMessage.deserialize(serialized)
        assert deserialized.message_type == MessageType.PRICE_UPDATE
        assert deserialized.payload["symbol"] == "RELIANCE.NSE"
        assert deserialized.payload["price"] == 2847.50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_smoke.py::TestPriceUpdate -v`
Expected: FAIL with `AttributeError: PRICE_UPDATE`

- [ ] **Step 3: Add `PRICE_UPDATE` to `MessageType` enum**

In `backend/app/core/messaging.py`, add after line 71 (after `ORDER_CANCEL_ALL`):

```python
    # Live price updates for dashboard watchlist
    PRICE_UPDATE = "PRICE_UPDATE"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_smoke.py::TestPriceUpdate -v`
Expected: PASS

- [ ] **Step 5: Publish `PRICE_UPDATE` from Yahoo EOD poll**

In `backend/app/workers/data_ingestion_worker.py`, add a helper method to the `DataIngestionWorker` class:

```python
    async def _publish_price_update(self, symbol: str, price: float) -> None:
        """Publish a PRICE_UPDATE message for the dashboard watchlist."""
        from app.core.messaging import AgentMessage, MessageType
        from app.core.runtime import get_bus

        # Read previous close for change_pct calculation
        kv = get_kv_store()
        prev_str = await kv.get(f"horizon:price:prev_close:{symbol}")
        prev_close = float(prev_str) if prev_str else price
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0.0

        bus = get_bus()
        await bus.publish(
            AgentMessage(
                sender_id="data-ingestion-worker",
                channel="horizon.market.price",
                message_type=MessageType.PRICE_UPDATE,
                payload={
                    "symbol": symbol,
                    "price": price,
                    "change_pct": round(change_pct, 2),
                    "prev_close": prev_close,
                },
            )
        )
```

- [ ] **Step 6: Call `_publish_price_update` after each Yahoo fetch**

In `_poll_yahoo_eod`, after the successful `self._yahoo_cb.call(...)` block (around line 199), add the price publish. Replace the inner try block for each symbol:

```python
                    for symbol in symbols:
                        try:
                            await self._yahoo_cb.call(
                                with_timeout,
                                self.data_manager.yahoo_feed.fetch_latest(symbol),
                                FETCH_TIMEOUT,
                                operation_name=f"yahoo_fetch_{symbol}",
                            )
                            # Publish price update for dashboard
                            price_str = await get_kv_store().get(
                                f"horizon:price:{symbol}"
                            )
                            if price_str:
                                try:
                                    await self._publish_price_update(
                                        symbol, float(price_str)
                                    )
                                except Exception:
                                    pass  # non-critical for dashboard
                        except CircuitOpenError:
                            logger.debug("yahoo_circuit_open_skipping", symbol=symbol)
                            break
                        except TimeoutError:
                            logger.warning("yahoo_fetch_timeout", symbol=symbol)
                        except Exception as exc:
                            logger.warning(
                                "yahoo_eod_fetch_error",
                                symbol=symbol,
                                error=str(exc),
                            )
```

- [ ] **Step 7: Same for CoinGecko poll**

In `_poll_coingecko`, after the successful crypto fetch (around line 239), add price publish. Replace the inner try block:

```python
                    for symbol in crypto_symbols:
                        try:
                            await self._crypto_cb.call(
                                with_timeout,
                                self.data_manager.crypto_feed.fetch_latest(symbol),
                                FETCH_TIMEOUT,
                                operation_name=f"crypto_fetch_{symbol}",
                            )
                            # Publish price update for dashboard
                            raw = symbol.split("-")[0] if "-" in symbol else symbol
                            price_str = await get_kv_store().get(
                                f"horizon:price:{raw}"
                            ) or await get_kv_store().get(
                                f"horizon:price:{symbol}"
                            )
                            if price_str:
                                try:
                                    await self._publish_price_update(
                                        symbol, float(price_str)
                                    )
                                except Exception:
                                    pass
                        except CircuitOpenError:
                            logger.debug("crypto_circuit_open_skipping", symbol=symbol)
                            break
                        except TimeoutError:
                            logger.warning("crypto_fetch_timeout", symbol=symbol)
                        except Exception as exc:
                            logger.warning(
                                "coingecko_fetch_error",
                                symbol=symbol,
                                error=str(exc),
                            )
```

- [ ] **Step 8: Store `prev_close` on first poll for change_pct baseline**

Add to `_poll_yahoo_eod`, right before the inner for loop, a one-time prev_close seeding:

```python
                    # Seed prev_close on first cycle (for change_pct calculation)
                    kv = get_kv_store()
                    for symbol in symbols:
                        prev_key = f"horizon:price:prev_close:{symbol}"
                        existing = await kv.get(prev_key)
                        if not existing:
                            current = await kv.get(f"horizon:price:{symbol}")
                            if current:
                                await kv.set(prev_key, current)
```

- [ ] **Step 9: Run full test suite**

Run: `cd backend && python -m pytest tests/test_smoke.py -v --tb=short -q`
Expected: All existing tests pass + new tests pass

- [ ] **Step 10: Commit**

```bash
cd backend
git add app/core/messaging.py app/workers/data_ingestion_worker.py tests/test_smoke.py
git commit -m "feat: add PRICE_UPDATE message type, publish live prices from data ingestion"
```

---

### Task 2: Enrich `PORTFOLIO_UPDATE` with position details

**Files:**
- Modify: `backend/app/workers/position_worker.py:180-200` (PORTFOLIO_UPDATE publish)
- Test: `backend/tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

```python
class TestPortfolioUpdatePayload:
    @pytest.mark.asyncio
    async def test_portfolio_update_contains_position_details(self):
        """PORTFOLIO_UPDATE payload should include a list of position dicts."""
        from app.core.messaging import AgentMessage, MessageType
        msg = AgentMessage(
            sender_id="position-monitor-worker",
            channel="horizon.portfolio.update",
            message_type=MessageType.PORTFOLIO_UPDATE,
            payload={
                "nav": 1_024_350.0,
                "cash": 241_000.0,
                "positions": [
                    {
                        "symbol": "RELIANCE.NSE",
                        "qty": 100,
                        "avg_cost": 2_805.0,
                        "current_price": 2_847.50,
                        "unrealized_pnl": 4250.0,
                        "side": "LONG",
                    },
                ],
                "total_unrealized": 4250.0,
                "total_realized": 0.0,
            },
        )
        positions = msg.payload["positions"]
        assert isinstance(positions, list)
        assert len(positions) == 1
        assert positions[0]["symbol"] == "RELIANCE.NSE"
        assert positions[0]["qty"] == 100
        assert positions[0]["unrealized_pnl"] == 4250.0
```

- [ ] **Step 2: Run test to verify it passes (this is a payload shape test)**

Run: `cd backend && python -m pytest tests/test_smoke.py::TestPortfolioUpdatePayload -v`
Expected: PASS (payload is just a dict — this validates the shape we expect)

- [ ] **Step 3: Modify `PositionMonitorWorker._cycle` to include position details**

In `backend/app/workers/position_worker.py`, replace the PORTFOLIO_UPDATE publish block (lines 183-200) with:

```python
        # Build position details list for dashboard
        position_details = []
        for pos in positions:
            if pos["quantity"] > 0:
                position_details.append({
                    "symbol": pos["symbol"],
                    "qty": pos["quantity"],
                    "avg_cost": pos["avg_entry_price"],
                    "current_price": pos.get("current_price") or pos["avg_entry_price"],
                    "unrealized_pnl": round(pos.get("unrealized_pnl", 0.0), 2),
                    "side": pos["side"],
                })

        # Publish PORTFOLIO_UPDATE
        from app.core.messaging import AgentMessage, MessageType
        bus = _get_bus()
        await bus.publish(
            AgentMessage(
                sender_id="position-monitor-worker",
                channel="horizon.portfolio.update",
                message_type=MessageType.PORTFOLIO_UPDATE,
                payload={
                    "nav": nav,
                    "cash": cash_usd_equiv,
                    "positions": position_details,
                    "total_unrealized": total_unrealized,
                    "total_realized": total_realized,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        )
```

- [ ] **Step 4: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --tb=short -q`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/workers/position_worker.py tests/test_smoke.py
git commit -m "feat: enrich PORTFOLIO_UPDATE with per-position details for dashboard"
```

---

### Task 3: Add `current_task` to agent status via `BaseAgent.emit_state`

**Files:**
- Modify: `backend/app/agents/base_agent.py`
- Test: `backend/tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

```python
class TestAgentCurrentTask:
    @pytest.mark.asyncio
    async def test_emit_state_publishes_current_task(self):
        from unittest.mock import AsyncMock
        from app.agents.base_agent import BaseAgent

        class StubAgent(BaseAgent):
            async def run(self): pass
            async def on_message(self, msg): pass

        bus = AsyncMock()
        bus.publish = AsyncMock()
        bus.subscribe = AsyncMock()
        agent = StubAgent(
            agent_id="test-strat",
            agent_type="strategy",
            bus=bus,
            department="front_office",
        )
        await agent.emit_state("ANALYZING", current_task="momentum scan RELIANCE str=0.82")

        bus.publish.assert_called_once()
        msg = bus.publish.call_args[0][0]
        assert msg.payload["state"] == "ANALYZING"
        assert msg.payload["current_task"] == "momentum scan RELIANCE str=0.82"
        assert msg.payload["agent_id"] == "test-strat"
        assert msg.payload["department"] == "front_office"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_smoke.py::TestAgentCurrentTask -v`
Expected: FAIL with `AttributeError: 'StubAgent' object has no attribute 'emit_state'`

- [ ] **Step 3: Add `emit_state` method to `BaseAgent`**

In `backend/app/agents/base_agent.py`, add after the `emit()` method (after line 138):

```python
    async def emit_state(
        self,
        state: str,
        current_task: str | None = None,
    ) -> None:
        """Publish an AGENT_STATE_CHANGE message with optional task description."""
        msg = AgentMessage(
            sender_id=self.agent_id,
            channel="horizon.agent.state",
            message_type=MessageType.AGENT_STATE_CHANGE,
            payload={
                "agent_id": self.agent_id,
                "state": state,
                "department": self.department,
                "current_task": current_task,
            },
        )
        await self.bus.publish(msg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_smoke.py::TestAgentCurrentTask -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --tb=short -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/agents/base_agent.py tests/test_smoke.py
git commit -m "feat: add emit_state() to BaseAgent for current_task broadcasting"
```

---

### Task 4: Rewrite `dashboard.py` — new 3-column layout

**Files:**
- Modify: `backend/app/tui/dashboard.py` (full rewrite of layout + new panels)
- Test: `backend/tests/test_integration.py:782-827` (TestDashboard class)

- [ ] **Step 1: Write the failing tests for new panels**

Add to `backend/tests/test_integration.py`, replacing the existing `TestDashboard` class:

```python
class TestDashboard:
    """Dashboard correctly accumulates and limits data."""

    def test_add_signal_limits(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        for i in range(30):
            dash.add_signal({"symbol": f"SYM{i}", "direction": 1})
        assert len(dash._signals) == 20

    def test_add_alert_limits(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        for i in range(30):
            dash.add_alert({"title": f"Alert {i}"})
        assert len(dash._alerts) == 20

    def test_update_agent_status(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.update_agent_status("test-agent", {
            "status": "RUNNING",
            "department": "front_office",
        })
        assert "test-agent" in dash._agent_statuses
        assert dash.pixel_agents.get_agent_count() == 1

    def test_build_layout(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.update_risk({"var_95": 0.02, "var_99": 0.04, "max_drawdown": 5.0})
        layout = dash.build_layout()
        assert layout is not None

    def test_update_watchlist(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.update_watchlist({
            "symbol": "RELIANCE.NSE",
            "price": 2847.50,
            "change_pct": 1.2,
            "prev_close": 2813.82,
        })
        assert "RELIANCE.NSE" in dash._watchlist
        assert dash._watchlist["RELIANCE.NSE"]["price"] == 2847.50
        # Check sparkline history is stored
        assert len(dash._watchlist["RELIANCE.NSE"]["history"]) == 1

    def test_watchlist_sparkline_caps_at_20(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        for i in range(25):
            dash.update_watchlist({
                "symbol": "TCS.NSE",
                "price": 3900 + i,
                "change_pct": 0.1 * i,
            })
        assert len(dash._watchlist["TCS.NSE"]["history"]) == 20

    def test_update_portfolio_with_positions(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.update_portfolio({
            "nav": 1_024_350.0,
            "cash": 241_000.0,
            "positions": [
                {"symbol": "RELIANCE.NSE", "qty": 100, "unrealized_pnl": 4200.0},
            ],
        })
        assert dash._portfolio["nav"] == 1_024_350.0
        assert len(dash._portfolio["positions"]) == 1

    def test_add_pending_order(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.add_pending_order({
            "order_id": "ORD-001",
            "symbol": "RELIANCE.NSE",
            "side": "BUY",
            "quantity": 100,
            "order_type": "MARKET",
            "status": "PENDING",
        })
        assert len(dash._pending_orders) == 1
        assert dash._pending_orders[0]["order_id"] == "ORD-001"

    def test_complete_order_moves_to_history(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.add_pending_order({
            "order_id": "ORD-001",
            "symbol": "RELIANCE.NSE",
            "side": "BUY",
            "quantity": 100,
            "status": "PENDING",
        })
        dash.complete_order({
            "order_id": "ORD-001",
            "symbol": "RELIANCE.NSE",
            "side": "BUY",
            "quantity": 100,
            "fill_price": 2847.50,
            "status": "FILLED",
        })
        assert len(dash._pending_orders) == 0
        assert len(dash._trade_history) == 1

    def test_remove_order_on_reject(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.add_pending_order({
            "order_id": "ORD-002",
            "symbol": "TCS.NSE",
            "side": "SELL",
            "quantity": 50,
            "status": "PENDING",
        })
        dash.remove_order("ORD-002")
        assert len(dash._pending_orders) == 0

    def test_trade_history_limited_to_20(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        for i in range(25):
            dash.complete_order({
                "order_id": f"ORD-{i:03d}",
                "symbol": "TEST",
                "side": "BUY",
                "quantity": 1,
                "fill_price": 100.0,
                "status": "FILLED",
            })
        assert len(dash._trade_history) == 20

    def test_render_sparkline(self):
        from app.tui.dashboard import render_sparkline
        result = render_sparkline([1, 2, 3, 4, 5, 6, 7, 8])
        assert len(result) == 8
        assert result[0] == "▁"
        assert result[-1] == "█"

    def test_render_sparkline_empty(self):
        from app.tui.dashboard import render_sparkline
        result = render_sparkline([])
        assert result == ""

    def test_render_sparkline_constant(self):
        from app.tui.dashboard import render_sparkline
        result = render_sparkline([5, 5, 5])
        assert len(result) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_integration.py::TestDashboard -v`
Expected: FAIL — `update_watchlist`, `add_pending_order`, `complete_order`, `remove_order`, `render_sparkline` don't exist yet

- [ ] **Step 3: Write the `render_sparkline` utility**

At the top of `backend/app/tui/dashboard.py`, add after the existing imports:

```python
SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"


def render_sparkline(values: list[float], width: int = 0) -> str:
    """Render a list of values as a Unicode sparkline string."""
    if not values:
        return ""
    if width and len(values) > width:
        values = values[-width:]
    mn, mx = min(values), max(values)
    spread = mx - mn
    if spread == 0:
        return SPARKLINE_CHARS[3] * len(values)
    return "".join(
        SPARKLINE_CHARS[min(int((v - mn) / spread * 7), 7)] for v in values
    )
```

- [ ] **Step 4: Rewrite `TerminalDashboard.__init__` with new data stores**

Replace the `__init__` method:

```python
    def __init__(self) -> None:
        self.console = Console()
        self._running = False
        self._agent_statuses: dict[str, dict[str, Any]] = {}
        self._signals: list[dict[str, Any]] = []
        self._risk: dict[str, Any] = {}
        self._start_time: datetime = datetime.now(UTC)
        self._portfolio: dict[str, Any] = {
            "nav": 0.0, "cash": 0.0, "positions": [],
        }
        self._alerts: list[dict[str, Any]] = []
        self._watchlist: dict[str, dict[str, Any]] = {}
        self._pending_orders: list[dict[str, Any]] = []
        self._trade_history: list[dict[str, Any]] = []

        # Pixel agent office view
        from app.tui.pixel_agents import PixelAgentVisualizer
        self.pixel_agents = PixelAgentVisualizer()
```

- [ ] **Step 5: Add new data update methods**

Add after the existing `update_portfolio` method:

```python
    def update_watchlist(self, data: dict[str, Any]) -> None:
        """Update a symbol's price data in the watchlist."""
        symbol = data.get("symbol", "")
        if not symbol:
            return
        if symbol not in self._watchlist:
            self._watchlist[symbol] = {
                "price": 0.0,
                "change_pct": 0.0,
                "prev_close": 0.0,
                "history": [],
            }
        entry = self._watchlist[symbol]
        entry["price"] = data.get("price", entry["price"])
        entry["change_pct"] = data.get("change_pct", 0.0)
        entry["prev_close"] = data.get("prev_close", entry.get("prev_close", 0.0))
        entry["history"].append(entry["price"])
        if len(entry["history"]) > 20:
            entry["history"] = entry["history"][-20:]

    def add_pending_order(self, order: dict[str, Any]) -> None:
        """Add an order to the pending orders list."""
        self._pending_orders.insert(0, order)
        self._pending_orders = self._pending_orders[:20]

    def complete_order(self, fill: dict[str, Any]) -> None:
        """Move a filled order from pending to trade history."""
        order_id = fill.get("order_id", "")
        self._pending_orders = [
            o for o in self._pending_orders if o.get("order_id") != order_id
        ]
        self._trade_history.insert(0, fill)
        self._trade_history = self._trade_history[:20]

    def remove_order(self, order_id: str) -> None:
        """Remove a rejected/cancelled order from pending."""
        self._pending_orders = [
            o for o in self._pending_orders if o.get("order_id") != order_id
        ]
```

- [ ] **Step 6: Rewrite `_build_header` to include today's P&L, VaR, drawdown**

```python
    def _build_header(self) -> Panel:
        uptime = datetime.now(UTC) - self._start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        mode_colors = {
            "PAPER_TRADING": "yellow",
            "HUMAN_APPROVAL": "cyan",
            "FULLY_AUTONOMOUS": "red",
        }
        mode = settings.system_mode.value
        mode_color = mode_colors.get(mode, "white")

        nav = self._portfolio.get("nav", 0.0)
        var_95 = self._risk.get("var_95", 0.0)
        curr_dd = self._risk.get("current_drawdown", 0.0)
        dd_color = "red" if curr_dd > 5.0 else "yellow" if curr_dd > 2.0 else "green"

        header = Text()
        header.append("HORIZON CAPITAL ", style="bold white")
        header.append("v0.2.0 ", style="dim")
        header.append("│ ", style="dim")
        header.append(f"{mode}", style=f"bold {mode_color}")
        header.append(" │ ", style="dim")
        header.append("CIO:", style="white")
        cio_mode = settings.cio_mode.value
        cio_color = "cyan" if cio_mode == "HUMAN" else "bright_red"
        header.append(f"{cio_mode}", style=f"bold {cio_color}")
        header.append(" │ ", style="dim")
        header.append("NAV: ", style="white")
        header.append(f"${nav:,.2f}", style="bold green")
        header.append(" │ ", style="dim")
        header.append("VaR: ", style="white")
        header.append(f"{var_95:.4f}", style="bright_red")
        header.append(" │ ", style="dim")
        header.append("DD: ", style="white")
        header.append(f"{curr_dd:.1f}%", style=f"{dd_color}")
        header.append(" │ ", style="dim")
        header.append(f"{hours:02d}:{minutes:02d}:{seconds:02d}", style="cyan")

        return Panel(header, style="blue", height=3)
```

- [ ] **Step 7: Rewrite `_build_agents_table` to show `current_task`**

```python
    def _build_agents_table(self) -> Panel:
        status_colors = {
            "RUNNING": "green", "ANALYZING": "green",
            "DEBATING": "blue", "EXECUTING": "bright_red",
            "INIT": "yellow", "STOPPED": "red",
            "CRASHED": "bold red", "IDLE": "dim",
        }
        status_dots = {
            "RUNNING": "●", "ANALYZING": "●", "DEBATING": "●",
            "EXECUTING": "●", "IDLE": "●", "INIT": "●",
            "STOPPED": "●", "CRASHED": "●",
        }

        lines: list[Text] = []
        if not self._agent_statuses:
            lines.append(Text("  (no agents registered)", style="dim"))
        else:
            for agent_id in sorted(self._agent_statuses.keys()):
                info = self._agent_statuses[agent_id]
                status = info.get("status", "IDLE")
                s_color = status_colors.get(status, "dim")
                dot = status_dots.get(status, "●")
                current_task = info.get("current_task")

                line = Text()
                line.append(f" {dot} ", style=s_color)
                # Truncate agent name to fit
                name = agent_id[:18]
                line.append(f"{name:<18} ", style="white" if status != "IDLE" else "dim")
                line.append(f"{status}", style=s_color)
                lines.append(line)

                if current_task and status not in ("IDLE", "STOPPED"):
                    task_line = Text()
                    task_line.append(f"     {current_task[:40]}", style="dim")
                    lines.append(task_line)

        content = Text("\n").join(lines) if lines else Text("(no agents)")
        return Panel(content, title="[bold]Agents[/bold]", border_style="cyan")
```

- [ ] **Step 8: Write `_build_watchlist_panel`**

```python
    def _build_watchlist_panel(self) -> Panel:
        if not self._watchlist:
            return Panel(
                "[dim]Awaiting price data...[/dim]",
                title="[bold]Watchlist[/bold]",
                border_style="green",
            )

        table = Table(show_header=True, header_style="bold green", expand=True)
        table.add_column("Symbol", width=14)
        table.add_column("Trend", width=10)
        table.add_column("Price", width=12, justify="right")
        table.add_column("Chg%", width=7, justify="right")
        table.add_column("Signal", width=6, justify="center")

        # Get latest signal per symbol
        latest_signals: dict[str, int] = {}
        for sig in self._signals:
            sym = sig.get("symbol", "")
            if sym and sym not in latest_signals:
                latest_signals[sym] = sig.get("direction", 0)

        for symbol in sorted(self._watchlist.keys()):
            data = self._watchlist[symbol]
            price = data["price"]
            change_pct = data["change_pct"]
            history = data["history"]

            # Color based on change
            price_color = "green" if change_pct >= 0 else "red"
            arrow = "▲" if change_pct > 0 else "▼" if change_pct < 0 else " "

            # Sparkline from history
            spark = render_sparkline(history, width=10)

            # Signal badge
            direction = latest_signals.get(symbol, 0)
            if direction > 0:
                sig_str = "[bold green]BUY↑[/]"
            elif direction < 0:
                sig_str = "[bold red]SELL↓[/]"
            else:
                sig_str = "[dim]—[/]"

            # Format price (₹ for NSE/BSE, $ for rest)
            if ".NSE" in symbol or ".BSE" in symbol:
                price_str = f"₹{price:,.2f}"
            else:
                price_str = f"${price:,.2f}"

            table.add_row(
                f"[{price_color}]{symbol}[/]",
                f"[dim]{spark}[/]",
                f"[{price_color}]{price_str}[/]",
                f"[{price_color}]{arrow}{change_pct:+.1f}%[/]",
                sig_str,
            )

        return Panel(table, title="[bold]Watchlist[/bold]", border_style="green")
```

- [ ] **Step 9: Write `_build_portfolio_panel`**

```python
    def _build_portfolio_panel(self) -> Panel:
        positions = self._portfolio.get("positions", [])
        cash = self._portfolio.get("cash", 0.0)
        nav = self._portfolio.get("nav", 0.0)

        lines: list[str] = []
        cash_pct = (cash / nav * 100) if nav > 0 else 0
        lines.append(f"  [dim]Cash[/dim]{'':>20} ${cash:>12,.0f} [dim]({cash_pct:.0f}%)[/]")

        if not positions:
            lines.append("  [dim]No open positions[/dim]")
        elif isinstance(positions, list):
            for pos in positions[:8]:
                symbol = pos.get("symbol", "?")
                qty = pos.get("qty", 0)
                pnl = pos.get("unrealized_pnl", 0.0)
                pnl_color = "green" if pnl >= 0 else "red"
                # Currency formatting
                if ".NSE" in symbol or ".BSE" in symbol:
                    pnl_str = f"₹{pnl:+,.0f}"
                else:
                    pnl_str = f"${pnl:+,.0f}"
                lines.append(
                    f"  {symbol:<18} ×{qty:<6} [{pnl_color}]{pnl_str:>10}[/]"
                )

        return Panel(
            "\n".join(lines),
            title="[bold]Portfolio[/bold]",
            border_style="magenta",
        )
```

- [ ] **Step 10: Write `_build_risk_panel` (updated)**

```python
    def _build_risk_panel(self) -> Panel:
        if not self._risk:
            return Panel(
                "Awaiting risk data...",
                title="[bold]Risk[/bold]",
                border_style="red",
            )

        var_95 = self._risk.get("var_95", 0.0)
        var_99 = self._risk.get("var_99", 0.0)
        max_dd = self._risk.get("max_drawdown", 0.0)
        curr_dd = self._risk.get("current_drawdown", 0.0)
        sharpe = self._risk.get("sharpe_30d", 0.0)
        kill = self._risk.get("kill_switch_active", False)

        dd_color = "red" if curr_dd > 5.0 else "yellow" if curr_dd > 2.0 else "green"

        lines = [
            f"  [dim]VaR (95%)[/dim]   {var_95:>10.4f}",
            f"  [dim]VaR (99%)[/dim]   {var_99:>10.4f}",
            f"  [dim]Max DD[/dim]      {max_dd:>10.2f}%",
            f"  [dim]Curr DD[/dim]     [{dd_color}]{curr_dd:>9.2f}%[/]",
            f"  [dim]Sharpe 30d[/dim]  {sharpe:>10.2f}",
        ]
        if kill:
            lines.append("  [bold red]KILL SWITCH   ACTIVE[/bold red]")

        return Panel("\n".join(lines), title="[bold]Risk[/bold]", border_style="red")
```

- [ ] **Step 11: Write `_build_orders_panel`**

```python
    def _build_orders_panel(self) -> Panel:
        if not self._pending_orders:
            return Panel(
                "[dim]No pending orders[/dim]",
                title="[bold]Pending Orders[/bold]",
                border_style="cyan",
            )

        table = Table(show_header=True, header_style="bold cyan", expand=True)
        table.add_column("ID", width=8)
        table.add_column("Side", width=5)
        table.add_column("Symbol", width=14)
        table.add_column("Qty", width=6, justify="right")
        table.add_column("Status", width=18)

        status_colors = {
            "PENDING": "yellow",
            "AWAITING_APPROVAL": "yellow",
            "IN_DEBATE": "blue",
            "SUBMITTED": "cyan",
            "PARTIAL": "yellow",
        }

        for order in self._pending_orders[:6]:
            oid = str(order.get("order_id", ""))[-8:]
            side = order.get("side", "?")
            side_color = "green" if side == "BUY" else "red"
            symbol = order.get("symbol", "?")
            qty = str(order.get("quantity", 0))
            status = order.get("status", "PENDING")
            s_color = status_colors.get(status, "white")

            table.add_row(
                f"[dim]{oid}[/]",
                f"[{side_color}]{side}[/]",
                symbol,
                qty,
                f"[{s_color}]{status}[/]",
            )

        return Panel(table, title="[bold]Pending Orders[/bold]", border_style="cyan")
```

- [ ] **Step 12: Write `_build_trades_panel`**

```python
    def _build_trades_panel(self) -> Panel:
        if not self._trade_history:
            return Panel(
                "[dim]No trades yet[/dim]",
                title="[bold]Trade History[/bold]",
                border_style="cyan",
            )

        table = Table(show_header=True, header_style="bold cyan", expand=True)
        table.add_column("Time", width=6)
        table.add_column("Side", width=5)
        table.add_column("Symbol", width=14)
        table.add_column("Qty @ Price", width=18)
        table.add_column("Status", width=8)

        for trade in self._trade_history[:6]:
            ts = trade.get("timestamp", "")
            if isinstance(ts, str) and len(ts) > 16:
                ts = ts[11:16]
            elif not ts:
                ts = "--:--"
            side = trade.get("side", "?")
            side_color = "green" if side == "BUY" else "red"
            symbol = trade.get("symbol", "?")
            qty = trade.get("quantity", 0)
            fill_price = trade.get("fill_price", 0.0)
            status = trade.get("status", "FILLED")

            table.add_row(
                f"[dim]{ts}[/]",
                f"[{side_color}]{side}[/]",
                symbol,
                f"{qty} @ {fill_price:,.2f}",
                f"[green]{status}[/]",
            )

        return Panel(table, title="[bold]Trade History[/bold]", border_style="cyan")
```

- [ ] **Step 13: Rewrite `build_layout` — 3-column structure**

```python
    def build_layout(self) -> Layout:
        """Compose the full 3-column Intelligence Hub layout."""
        layout = Layout()
        layout.split_column(
            Layout(self._build_header(), name="header", size=3),
            Layout(name="body"),
            Layout(name="orders", size=10),
        )

        layout["body"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="center", ratio=1.3),
            Layout(name="right", ratio=1),
        )

        layout["left"].split_column(
            Layout(self._build_agents_table(), name="agents"),
            Layout(self._build_alerts_panel(), name="alerts", size=8),
        )

        layout["center"].update(self._build_watchlist_panel())

        layout["right"].split_column(
            Layout(self._build_portfolio_panel(), name="portfolio"),
            Layout(self._build_risk_panel(), name="risk", size=10),
        )

        layout["orders"].split_row(
            Layout(self._build_orders_panel(), name="pending", ratio=1),
            Layout(self._build_trades_panel(), name="history", ratio=1),
        )

        return layout
```

- [ ] **Step 14: Remove `_build_regime_panel`, `_build_debates_panel`, `_build_log_panel`, `_build_signals_panel`**

Delete these methods entirely. Also remove `_regimes`, `_debates`, `_logs` from `__init__` and their update methods (`update_regime`, `add_debate`, `add_log`). Keep `_signals` and `add_signal` because watchlist uses them for signal direction badges.

Remove `update_regime`, `add_debate`, `add_log` methods.

Remove the `AgentVisualizer` import and `self.agent_visualizer` from `__init__` (the agents panel replaces it).

- [ ] **Step 15: Run tests to verify everything passes**

Run: `cd backend && python -m pytest tests/test_integration.py::TestDashboard -v`
Expected: All PASS

- [ ] **Step 16: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --tb=short -q`
Expected: All pass (some tests that called `add_log` or `update_regime` may need fixes — see Task 5)

- [ ] **Step 17: Commit**

```bash
cd backend
git add app/tui/dashboard.py tests/test_integration.py
git commit -m "feat: rewrite dashboard as 3-column Intelligence Hub with watchlist, portfolio, orders"
```

---

### Task 5: Wire new dashboard methods in `__main__.py`

**Files:**
- Modify: `backend/app/__main__.py:263-307` (_on_any_message handler)

- [ ] **Step 1: Write a test for the message routing**

```python
class TestDashboardWiring:
    @pytest.mark.asyncio
    async def test_price_update_routes_to_watchlist(self):
        from app.core.messaging import AgentMessage, MessageType
        from app.tui.dashboard import TerminalDashboard

        dash = TerminalDashboard()
        msg = AgentMessage(
            sender_id="data-ingestion-worker",
            channel="horizon.market.price",
            message_type=MessageType.PRICE_UPDATE,
            payload={
                "symbol": "RELIANCE.NSE",
                "price": 2847.50,
                "change_pct": 1.2,
            },
        )
        # Simulate what _on_any_message does
        dash.update_watchlist(msg.payload)
        assert "RELIANCE.NSE" in dash._watchlist

    @pytest.mark.asyncio
    async def test_order_new_routes_to_pending(self):
        from app.core.messaging import AgentMessage, MessageType
        from app.tui.dashboard import TerminalDashboard

        dash = TerminalDashboard()
        msg = AgentMessage(
            sender_id="portfolio-agent",
            channel="horizon.execution.order.new",
            message_type=MessageType.ORDER_NEW,
            payload={
                "signal_id": "abc-123",
                "order_id": "ORD-001",
                "symbol": "RELIANCE.NSE",
                "side": "BUY",
                "quantity": 100,
                "order_type": "MARKET",
                "status": "PENDING",
            },
        )
        dash.add_pending_order(msg.payload)
        assert len(dash._pending_orders) == 1

    @pytest.mark.asyncio
    async def test_order_fill_completes_pending(self):
        from app.core.messaging import AgentMessage, MessageType
        from app.tui.dashboard import TerminalDashboard

        dash = TerminalDashboard()
        dash.add_pending_order({
            "order_id": "ORD-001",
            "symbol": "RELIANCE.NSE",
            "side": "BUY",
            "quantity": 100,
            "status": "PENDING",
        })
        fill_msg = AgentMessage(
            sender_id="execution-agent",
            channel="horizon.execution.order.fill",
            message_type=MessageType.ORDER_FILL,
            payload={
                "order_id": "ORD-001",
                "symbol": "RELIANCE.NSE",
                "side": "BUY",
                "quantity": 100,
                "fill_price": 2847.50,
                "status": "FILLED",
                "timestamp": "2026-04-02T14:21:30",
            },
        )
        dash.complete_order(fill_msg.payload)
        assert len(dash._pending_orders) == 0
        assert len(dash._trade_history) == 1
```

- [ ] **Step 2: Run the tests**

Run: `cd backend && python -m pytest tests/test_integration.py::TestDashboardWiring -v`
Expected: PASS

- [ ] **Step 3: Update `_on_any_message` in `__main__.py`**

Replace the `_on_any_message` function inside `_run_with_tui` (lines 263-306):

```python
    async def _on_any_message(msg: AgentMessage) -> None:
        """Route bus messages to the dashboard."""
        if msg.message_type == MessageType.HEARTBEAT:
            payload = msg.payload.copy()
            agent_id = payload.get("agent_id", msg.sender_id)
            statuses = orchestrator.get_agent_statuses()
            if agent_id in statuses:
                payload["department"] = statuses[agent_id].get("department", "")
            dashboard.update_agent_status(agent_id, payload)
        elif msg.message_type == MessageType.AGENT_STATE_CHANGE:
            agent_id = msg.payload.get("agent_id", msg.sender_id)
            dashboard.update_agent_status(agent_id, msg.payload)
        elif msg.message_type == MessageType.SIGNAL:
            dashboard.add_signal(msg.payload)
        elif msg.message_type == MessageType.RISK_ALERT:
            # Enrich risk data with Sharpe from performance cache
            risk_data = msg.payload.copy()
            try:
                from app.core.kv_store import get_kv_store
                kv = get_kv_store()
                sharpe_str = await kv.get("horizon:performance:30d")
                if sharpe_str is None:
                    perf = await kv.hgetall("horizon:performance:30d")
                    if perf:
                        risk_data["sharpe_30d"] = float(
                            perf.get("sharpe_ratio", 0.0)
                        )
            except Exception:
                pass
            dashboard.update_risk(risk_data)
        elif msg.message_type == MessageType.PORTFOLIO_UPDATE:
            dashboard.update_portfolio(msg.payload)
        elif msg.message_type == MessageType.PRICE_UPDATE:
            dashboard.update_watchlist(msg.payload)
        elif msg.message_type == MessageType.ORDER_NEW:
            dashboard.add_pending_order(msg.payload)
        elif msg.message_type == MessageType.ORDER_FILL:
            dashboard.complete_order(msg.payload)
        elif msg.message_type == MessageType.ORDER_REJECT:
            order_id = msg.payload.get("order_id", "")
            dashboard.remove_order(order_id)
        elif msg.message_type == MessageType.SYSTEM:
            if msg.channel == "horizon.alerts.console":
                dashboard.add_alert(msg.payload)
```

- [ ] **Step 4: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --tb=short -q`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/__main__.py tests/test_integration.py
git commit -m "feat: wire PRICE_UPDATE, ORDER_NEW, ORDER_FILL, ORDER_REJECT to dashboard"
```

---

### Task 6: Fix broken references from removed panels

**Files:**
- Modify: `backend/tests/test_integration.py` (remove test_add_log_limits, test_update_regime)
- Modify: `backend/tests/test_smoke.py` (any references to removed methods)

- [ ] **Step 1: Find and fix broken test references**

In `test_integration.py`, the old `TestDashboard` class was replaced in Task 4. Verify no other tests call `dashboard.add_log()`, `dashboard.update_regime()`, or `dashboard.add_debate()`:

Search for these patterns. If found, remove or update them.

- [ ] **Step 2: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: All pass, 0 failures

- [ ] **Step 3: Run ruff lint**

Run: `cd backend && python -m ruff check app/tui/dashboard.py app/__main__.py app/workers/data_ingestion_worker.py app/workers/position_worker.py app/agents/base_agent.py`
Expected: 0 errors

- [ ] **Step 4: Commit**

```bash
cd backend
git add -A
git commit -m "fix: remove broken refs to removed dashboard panels, pass lint"
```

---

### Task 7: Smoke test the full dashboard visually

**Files:** None (manual verification)

- [ ] **Step 1: Run the system and verify dashboard renders**

Run: `cd backend && python -m app`
Expected: Dashboard renders with 3-column layout — agents left, watchlist center, portfolio+risk right, orders at bottom. Header shows NAV, VaR, drawdown.

- [ ] **Step 2: Verify price data flows in**

Wait 60 seconds for the first Yahoo/CoinGecko poll. Watchlist panel should populate with symbols from `settings.all_symbols` (RELIANCE.NSE, TCS.NSE, INFY.NSE, HDFCBANK.NSE, ICICIBANK.NSE, AAPL.NASDAQ, MSFT.NASDAQ, GOOGL.NASDAQ, AMZN.NASDAQ, TSLA.NASDAQ, BTC-USD, ETH-USD). Sparklines should appear after 2+ polls.

- [ ] **Step 3: Verify agent statuses populate**

Agents table should show all agents with their department-based grouping and RUNNING/IDLE status.

- [ ] **Step 4: Final commit**

```bash
cd backend
git add -A
git commit -m "chore: dashboard Intelligence Hub redesign complete"
```
