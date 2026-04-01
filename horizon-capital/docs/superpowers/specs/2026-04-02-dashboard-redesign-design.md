# Dashboard Redesign — Intelligence Hub

**Date**: 2026-04-02
**Status**: Approved
**Scope**: Replace `app/tui/dashboard.py` layout and add supporting data panels

## Summary

Redesign the Rich TUI dashboard from the current 2-column layout (agents+signals | regimes+risk+alerts+debates) into a 3-column Intelligence Hub focused on actionable trading information. Remove low-priority panels (debates, regimes, log tail). Add live watchlist prices, portfolio positions with P&L, pending orders, and trade history.

## Layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ HORIZON CAPITAL v0.2 │ PAPER │ CIO:HUMAN │ NAV │ Today P&L │ VaR │ DD │ Up │
├──────────────────┬───────────────────────┬───────────────────────────────────┤
│ AGENTS           │ WATCHLIST             │ PORTFOLIO                        │
│  ● strategy      │  RELIANCE ▁▂▃ ₹2,847 │  Cash: $241K (23%)              │
│    analyzing...  │    ▲+1.2%  BUY↑      │  RELIANCE ×100    +₹4,200       │
│  ● debate        │  TCS    ▃▄▅ ₹3,912   │  BTC-USD ×0.5     +$840        │
│    debating...   │    ▲+0.8%  HOLD      │  TCS ×50          -₹1,100      │
│  ● execution     │  BTC-USD ▂▃▄ $67,420 │                                 │
│    executing...  │    ▲+2.1%  BUY↑      │ RISK METRICS                    │
│  ● risk     IDLE │  ETH-USD ▆▅▄ $3,521  │  VaR 95%: 0.0182               │
│  ● regime   IDLE │    ▼-0.3%  HOLD      │  VaR 99%: 0.0241               │
│  ● portfolio IDLE│  ...                  │  Max DD: 3.8%                   │
│                  │                       │  Curr DD: 1.2%                  │
│ ALERTS           │                       │  Sharpe (30d): 1.84            │
│  ⚠ DD near limit │                       │  Kill Switch: OFF               │
│  ℹ BUY RELIANCE  │                       │                                 │
├──────────────────┴───────────────────────┴───────────────────────────────────┤
│ PENDING ORDERS                    │ TRADE HISTORY                           │
│  #183 BUY RELIANCE MKT AWAITING  │  14:21 BUY BTC-USD 50@$67,400 FILLED   │
│  #184 SELL INFY ₹1,660 IN DEBATE │  13:47 SELL HDFCBANK 100@₹1,720 FILLED │
└───────────────────────────────────┴─────────────────────────────────────────┘
```

## Panels

### 1. Header (size=3, full width)

Existing header enriched with:
- **Today's P&L**: absolute + percentage, green/red coloring
- **VaR 95%** and **Current Drawdown**: pulled from `_risk` dict
- Remove storage backend label (not useful during operation)

Data source: existing `_portfolio`, `_risk` dicts.

### 2. Agents Panel (left column, top)

Compact list of all registered agents. Each agent shows:
- Color-coded status dot: green=ANALYZING, blue=DEBATING, orange=EXECUTING, dim=IDLE
- Agent name (truncated to ~16 chars)
- Current state
- **Current task text** (new): 1 line below in dim, showing what the agent is doing (e.g., "momentum scan · RELIANCE · str=0.82")

Data source: existing `_agent_statuses` dict. **New field needed**: `current_task` string in agent status payloads. Agents must emit a short description of their current action when publishing `AGENT_STATE_CHANGE`.

### 3. Alerts Panel (left column, bottom, size=8)

Existing `_build_alerts_panel()` — no changes needed. Shows last 4-6 alerts with severity coloring.

### 4. Watchlist Panel (center column)

**New panel.** Shows active watchlist symbols (5-8) with:
- Symbol name (color-coded green if up, red if down)
- ASCII sparkline (last 10 price points using `▁▂▃▄▅▆▇█` chars)
- Current price
- % change from previous close
- Latest signal direction badge: `BUY↑` (green bg), `SELL↓` (red bg), `HOLD` (yellow bg), or `—` (no signal)

Data sources:
- **Prices**: new `_watchlist` dict keyed by symbol → `{price, change_pct, sparkline: list[float]}`. Fed by `DataIngestionWorker` publishing a new `PRICE_UPDATE` message type, or by reading latest from the `market_data` SQLite table.
- **Signal direction**: from existing `_signals` list, latest signal per symbol.

Sparkline rendering: utility function `render_sparkline(values: list[float], width: int = 10) -> str` that maps values to `▁▂▃▄▅▆▇█` chars.

### 5. Portfolio Panel (right column, top)

**New panel.** Shows:
- Cash balance and % of NAV
- List of open positions: symbol, quantity, unrealized P&L (green/red)

Data source: existing `_portfolio` dict. **Needs enrichment**: `positions` field should be a list of `{symbol, qty, unrealized_pnl}` instead of just a count. `PositionMonitorWorker` already computes mark-to-market — it should include position details in `PORTFOLIO_UPDATE` payload.

### 6. Risk Metrics Panel (right column, bottom)

Existing `_build_risk_panel()` with additions:
- **Sharpe ratio (30d)**: from `PerformanceWorker` output
- Remove kill switch text if `OFF` (only show when `ACTIVE` as a red warning)

Data source: existing `_risk` dict, enriched with `sharpe_30d` field.

### 7. Orders Panel (bottom strip, left half)

**New panel.** Shows pending/active orders:
- Order ID, direction (BUY/SELL), symbol, qty @ price, status
- Status values: `AWAITING APPROVAL` (yellow), `IN DEBATE` (blue), `SUBMITTED` (cyan), `PARTIAL` (yellow)

Data source: new `_pending_orders` list. Fed by `ORDER_NEW` messages from the bus. Removed when `ORDER_FILLED` or `ORDER_REJECT` received.

### 8. Trade History Panel (bottom strip, right half)

**New panel.** Shows last N completed trades:
- Timestamp (HH:MM), direction, symbol, qty @ fill price, status (FILLED)

Data source: new `_trade_history` list. Fed by `ORDER_FILLED` messages from the bus. Keep last 10.

## Panels Removed

- **Debates panel**: accessible via `debate history` REPL command
- **Market Regimes panel**: lower priority, accessible via `regime` REPL command
- **Log tail panel**: replaced by orders/trades (logs still in file, accessible via `log` REPL command)

## Data Flow Changes

### New MessageType: `PRICE_UPDATE`

```python
PRICE_UPDATE = "price_update"  # payload: {symbol, price, change_pct, volume}
```

Published by `DataIngestionWorker` on each price poll. Dashboard subscribes and updates `_watchlist`.

### Enriched `PORTFOLIO_UPDATE` payload

Current: `{nav, cash, positions: int}`
New: `{nav, cash, positions: [{symbol, qty, avg_cost, current_price, unrealized_pnl}]}`

### Enriched `AGENT_STATE_CHANGE` payload

Current: `{agent_id, state}`
New: `{agent_id, state, current_task: str | None}`

### New dashboard subscriptions in `__main__.py`

Wire `PRICE_UPDATE` → `dashboard.update_watchlist()`
Wire `ORDER_NEW` → `dashboard.add_pending_order()`
Wire `ORDER_FILLED` → `dashboard.complete_order()`
Wire `ORDER_REJECT` → `dashboard.remove_order()`

## Layout Structure (Rich)

```python
layout = Layout()
layout.split_column(
    Layout(header, name="header", size=3),
    Layout(name="body"),
    Layout(name="orders", size=8),
)
layout["body"].split_row(
    Layout(name="left", ratio=1),
    Layout(name="center", ratio=1.3),
    Layout(name="right", ratio=1),
)
layout["left"].split_column(
    Layout(agents_panel, name="agents"),
    Layout(alerts_panel, name="alerts", size=8),
)
layout["right"].split_column(
    Layout(portfolio_panel, name="portfolio"),
    Layout(risk_panel, name="risk", size=10),
)
layout["orders"].split_row(
    Layout(pending_orders, name="pending", ratio=1),
    Layout(trade_history, name="history", ratio=1),
)
```

## Files Modified

| File | Changes |
|------|---------|
| `app/tui/dashboard.py` | Rewrite `build_layout()`, add `_build_watchlist_panel()`, `_build_portfolio_panel()`, `_build_orders_panel()`, `_build_trades_panel()`. Remove `_build_regime_panel()`, `_build_debates_panel()`, `_build_log_panel()`. Enrich `_build_header()`. Add `update_watchlist()`, `add_pending_order()`, `complete_order()`, `remove_order()`. Add `render_sparkline()` utility. |
| `app/core/messaging.py` | Add `PRICE_UPDATE` to `MessageType` enum |
| `app/workers/data_ingestion_worker.py` | Publish `PRICE_UPDATE` messages on each poll cycle |
| `app/workers/position_worker.py` | Enrich `PORTFOLIO_UPDATE` payload with position details list |
| `app/agents/base_agent.py` | Add `current_task` field to `AGENT_STATE_CHANGE` payloads |
| `app/__main__.py` | Wire new message types to dashboard methods |
| `tests/test_smoke.py` | Update dashboard tests for new panels/removed panels |

## Non-Goals

- No ASCII chart rendering beyond sparklines (REPL `chart` command handles that)
- No tab/view switching — everything visible at once
- No mouse interaction — this is a terminal dashboard
- No patterns force-fit from external repos
