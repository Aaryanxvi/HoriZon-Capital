# Horizon Capital — Complete System Audit

**Date:** 2026-04-24
**Scope:** Every file in `backend/app/` — core infra, agents, workers, TUI, REPL, LLM, wiring
**Method:** 5 parallel deep-dive agents + 3 focused math/logic agents, each reading every function line-by-line

---

## Table of Contents

1. [Summary](#summary)
2. [CRITICAL — System-Breaking Bugs](#critical)
3. [HIGH — Broken Features / Wrong Calculations](#high)
4. [MEDIUM — Partial Failures / Misleading Data](#medium)
5. [LOW — Dead Code / Minor Issues](#low)
6. [Dead Configuration Parameters](#dead-config)
7. [Dead Code & Missing Modules](#dead-code)
8. [Full Issue Index](#index)

---

<a name="summary"></a>
## 1. Summary

| Severity | Count | Description |
|----------|-------|-------------|
| **CRITICAL** | 10 | Data loss, wrong P&L, stale indicators, broken migrations, wrong VaR/Sortino |
| **HIGH** | 21 | Kill switch inert, debate gate bypassable, display broken, cash race conditions, double fills |
| **MEDIUM** | 20 | Wrong channels, missing enforcement, misleading displays, drift detection |
| **LOW** | 15 | Dead code, cosmetic issues, minor inconsistencies |
| **TOTAL** | **66** | Unique issues after deduplication (Pass 1 + Math/Logic Pass 2) |

---

<a name="critical"></a>
## 2. CRITICAL — System-Breaking Bugs

### C-01: Cash Balance Reset on Every Restart (Destroys Trading History)
- **File:** `app/core/runtime.py` lines 77-80
- **Bug:** `startup()` unconditionally overwrites `horizon:cash:usd` and `horizon:cash:inr` with initial capital from settings. Even though `PersistentKVStore.restore()` runs first (line 74) to recover persisted values, the capital is immediately overwritten.
- **Impact:** All paper trading P&L is lost on restart. If trades reduced cash to $800K, restarting resets to $1M. Positions still exist in DB but cash doesn't reflect money spent on them. NAV becomes wrong (double-counting).
- **Fix:** Only seed capital if keys don't already exist: `if not await kv.get("horizon:cash:usd"): await kv.set(...)`

### C-02: `_migrate_table` Drops Entire Tables on Schema Change (Data Destruction)
- **File:** `app/core/local_storage.py` lines 64-74
- **Bug:** When a table exists but is missing a required column, `_migrate_table` runs `DROP TABLE` then `CREATE TABLE`. This destroys ALL data in that table. Called for 8 critical tables on every startup: positions, portfolio_snapshots, risk_metrics, debate_sessions, regime_states, performance_snapshots, narratives, ohlcv.
- **Impact:** A code update that adds a column to `positions` would delete all position history. An update to `ohlcv` would delete all historical price data that took hours to backfill.
- **Fix:** Use `ALTER TABLE ... ADD COLUMN ... DEFAULT ...` instead of drop+recreate.

### C-03: Win Rate Reports ~100% (Gross Proceeds vs Actual P&L)
- **File:** `app/workers/performance_worker.py` lines 187-207
- **Bug:** Both `_win_rate()` and `_profit_factor()` compute "P&L" as `fill_price * filled_qty - commission`. This is **gross proceeds**, not realized profit. A stock sold at $50 × 100 shares - $5 commission = $4,995, which is always positive regardless of what the entry price was. Nearly every SELL is counted as a "winner."
- **Impact:** Win rate always near 100%. Profit factor always infinity or very large. Performance dashboard shows fantasy numbers. Risk assessment based on these metrics is meaningless.
- **Fix:** Need `(fill_price - avg_entry_price) * filled_qty - commission`. Requires joining with BUY fills to get entry price.

### C-04: Feature Computation Returns OLDEST Data, Not Recent (ORDER BY ASC + LIMIT)
- **File:** `app/workers/feature_computation_worker.py` lines 393-402
- **Bug:** SQL query uses `ORDER BY timestamp ASC LIMIT 500`. For a symbol with 1,250+ daily bars, this returns the oldest 500 bars. Technical indicators (SMA, RSI, MACD, Bollinger) are computed on years-old data, not current market conditions.
- **Impact:** ALL strategy signals are based on stale/wrong indicators. Every trading decision is fundamentally wrong. This is arguably the most damaging bug in the system.
- **Fix:** Change to `ORDER BY timestamp DESC LIMIT 500`, then reverse the result, or use `ORDER BY timestamp ASC` with an offset/subquery for the latest 500.

### C-05: CIO Agent Started Twice in AI Mode (Double LLM Costs)
- **File:** `app/__main__.py` lines 265-271, `app/agents/executive/manager.py` lines 23-26
- **Bug:** `ExecutiveManager._create_agents()` creates a CIOAgent that the orchestrator starts. Then `_run_with_tui()` creates a SECOND CIOAgent and starts it via `asyncio.create_task()`. Both subscribe to the same channels, both run the 15-minute advisory loop.
- **Impact:** Double LLM API calls, double API costs, duplicate CIO_ADVISORY messages in dashboard, duplicate DB writes, potential race conditions in override flow.
- **Fix:** Remove the second CIOAgent creation in `_run_with_tui()`.

### C-06: Annualized Return Uses Snapshot Count Instead of Calendar Days
- **Files:** `app/workers/performance_worker.py` lines 127-135, `app/services/performance.py` lines 111-113
- **Bug:** `n_days = len(equity)` counts portfolio snapshots (taken every 15 min), not actual trading days. A single day produces ~96 snapshots, so `252/n_days` becomes `252/96 ≈ 2.6` instead of `252/1 = 252`. Annualized return is dramatically wrong.
- **Impact:** Annualized return, Sharpe ratio, Sortino ratio, and Calmar ratio are all wrong. Sharpe/Sortino use `sqrt(252)` annualization factor on intra-day returns, inflating them. Performance reporting is unreliable.
- **Fix:** Use actual date range: `n_days = (last_timestamp - first_timestamp).days` or count distinct dates.

### C-07: Backtest Win Rate Systematically Halved (BUY Trades Counted as Losses)
- **File:** `app/backtesting/backtest_metrics.py` lines 40-45
- **Bug:** `win_rate()` counts ALL trades where `pnl > 0`. BUY trades are recorded with `pnl: 0.0` (backtest_engine.py line 197). Since `0.0 > 0` is False, every BUY is a "loss." A strategy with 10 buys and 10 profitable sells shows 50% win rate instead of 100%.
- **Impact:** Backtest results make strategies look systematically worse. Users may reject profitable strategies based on deflated win rates.
- **Fix:** Filter to SELL trades only: `sell_trades = [t for t in trades if t["side"] == "SELL"]`

---

<a name="high"></a>
## 3. HIGH — Broken Features / Wrong Calculations

### H-01: Kill Switch Does Not Stop New Orders
- **File:** `app/agents/middle_office/risk/risk_agent.py` lines 166-223
- **Bug:** When kill switch triggers (drawdown exceeds limit), it emits a `RISK_ALERT` and sets a KV flag. But `_handle_signal()` (pre-trade validation) never checks the kill switch state — only position limits and daily loss limits. New signals continue flowing through to execution.
- **Impact:** Kill switch is monitoring-only theater. Does not actually halt trading.

### H-02: Daily Loss Check Uses ALL-TIME P&L, Not Daily
- **File:** `app/agents/middle_office/risk/risk_agent.py` lines 263-296
- **Bug:** `_check_daily_loss_limit` queries `SUM(unrealized_pnl) + SUM(realized_pnl)` from positions table. This is cumulative P&L across all time, not today's loss. Accumulated losses from weeks ago permanently block new trades. Conversely, today's severe loss hidden by prior gains passes the check.
- **Impact:** Daily loss limit is fundamentally broken — measures the wrong thing.

### H-03: Stop-Loss Signals Go Through Full Debate Pipeline (Can Be Blocked)
- **File:** `app/workers/position_worker.py` lines 162-184
- **Bug:** Stop-loss triggers emit a SIGNAL on `horizon.signal.{symbol}`. This goes through: RiskAgent validation → DebateAgent debate → PortfolioAgent sizing. In FULLY_AUTONOMOUS mode, the emergency exit gets queued waiting for LLM debate approval. If debate takes 30+ seconds or rejects, the position keeps bleeding.
- **Impact:** Emergency stop-losses can be delayed or blocked entirely by the debate system.

### H-04: Stop-Loss Only Enforced for LONG Positions
- **File:** `app/workers/position_worker.py` lines 119-131
- **Bug:** Stop-loss check: `pos.side == "LONG" and current_price <= pos.stop_loss_price`. No corresponding check for SHORT positions where stop-loss should trigger when `current_price >= pos.stop_loss_price`.
- **Impact:** SHORT positions have zero stop-loss protection. Potential for unlimited losses.

### H-05: NAV Mixes USD and INR Without Conversion
- **File:** `app/workers/position_worker.py` lines 134-136
- **Bug:** `nav = cash_usd + total_value`. INR-denominated positions (NSE/BSE) are valued in INR but added directly to USD cash. `cash_inr` is fetched but never included. NAV published every 30 seconds is wrong for multi-currency portfolios.
- **Impact:** Dashboard NAV, all P&L calculations, risk metrics — all wrong when Indian stocks are in the portfolio.

### H-06: Poll Loop Records Fills But Never Updates Positions/Cash
- **File:** `app/agents/front_office/trading/execution_agent.py` lines 266-304
- **Bug:** `_poll_open_orders` re-executes stale orders and records fills in DB. But does NOT call `update_position()`, does NOT update cash, does NOT emit ORDER_FILL events.
- **Impact:** Fills exist in DB but positions and cash are stale. P&L leakage — money appears/disappears silently.

### H-07: CIO Agent Uses Wrong KV Keys (Blind to Portfolio State)
- **File:** `app/agents/executive/cio/cio_agent.py` lines 344-375
- **Bug:** CIO reads `portfolio:nav`, `portfolio:positions`, `market:regime`. Actual keys are `horizon:portfolio:nav`, `horizon:portfolio:latest`, `horizon:regime:current`. CIO always gets `None`.
- **Impact:** AI CIO advisories are based on empty data. All CIO analysis and overrides are uninformed.

### H-08: Trade History Panel Shows Quantity as 0
- **File:** `app/tui/dashboard.py` line 434
- **Bug:** Panel reads `trade.get("quantity", 0)` but ORDER_FILL payload uses key `"filled_qty"`.
- **Impact:** Every trade in the Trade History panel shows `0 @ $125.50` instead of actual quantity.

### H-09: Dashboard Portfolio Panel Never Shows Positions
- **File:** `app/tui/dashboard.py` lines 93-98
- **Bug:** `update_portfolio()` populates `self._portfolio["positions"]` only when `"positions"` is in the payload. `PositionMonitorWorker` PORTFOLIO_UPDATE never includes a `"positions"` key — only nav, cash, totals.
- **Impact:** Portfolio panel always shows "No open positions" even with active positions. NAV updates, but position rows never appear.

### H-10: `performance ytd` and `performance all` Return Wrong 30-Day Data
- **File:** `app/tui/commands.py` line 610, `app/services/performance.py` lines 24-60
- **Bug:** Command passes `period.lower()` ("ytd"/"all") but `compute_snapshot()` checks `period == "YTD"` (uppercase). Falls through to `else` branch, defaults to 30 days.
- **Impact:** `performance ytd` and `performance all` silently show 30-day metrics. No error — just wrong data.

### H-11: Watchlist Add/Remove Writes to Wrong .env Path
- **File:** `app/tui/commands.py` lines 975-992
- **Bug:** `_update_env()` computes `.env` path as 2 parents up from `commands.py` → `backend/app/.env`. Actual `.env` is at `backend/.env` (3 parents up).
- **Impact:** `watchlist add NVDA` reports success but writes to wrong file. Symbol gone on restart.

### H-12: Kill Switch Events Never Reach Alert Notifications
- **File:** `app/agents/middle_office/risk/risk_agent.py` lines 211-222, `app/services/alert_manager.py` line 164
- **Bug:** Risk agent publishes kill switch to `horizon.risk.alert`. Alert manager listens on `horizon.risk.kill_switch`. Different channels. Alert manager's `_on_risk_alert` only checks `DRAWDOWN_WARNING`, `DRAWDOWN_CRITICAL`, `VAR_BREACH` — not `KILL_SWITCH_TRIGGERED`.
- **Impact:** Kill switch never triggers Telegram/email notifications. Emergency alerts are dead code.

### H-13: Backtest P&L Excludes Commissions
- **File:** `app/backtesting/backtest_engine.py` line 200
- **Bug:** `pnl = (fill.fill_price - avg_entry) * abs(fill.quantity)` — no commission subtracted. Cash correctly deducts commission, but the recorded PnL per trade doesn't.
- **Impact:** Backtest trades show slightly inflated P&L. Win rate calculation counts marginal winners that are actually losers after commission.

### H-14: `portfolio` Command Shows 0 Positions (Same Root as H-09)
- **File:** `app/tui/commands.py` lines 200-202
- **Bug:** Reads from `self._dashboard._portfolio["positions"]` which is always `[]` (see H-09).
- **Impact:** `portfolio` command contradicts `positions` command (which queries DB directly and shows correct data).

### H-15: `pnl` Shows -100% Return at Startup
- **File:** `app/tui/commands.py` lines 773-791
- **Bug:** `horizon:portfolio:nav` not seeded at startup. First 30 seconds, NAV = 0. Return = (0 - 1M) / 1M = -100%.
- **Impact:** Alarming false -100% loss display on every startup until position worker runs.

### H-16: Debate Approval Logic: Simple Majority vs Documented 3/4 Threshold
- **File:** `app/agents/debate/debate_engine.py` lines 281-286
- **Bug:** Docstring requires "consensus_score > 0.6, at least 3/4 debaters FOR." Code only checks `len(for_votes) > len(against_votes)` (simple majority). A 2-1-1 vote approves.
- **Impact:** Single-provider DebateEngine approves trades too easily compared to its own spec.

---

<a name="medium"></a>
## 4. MEDIUM — Partial Failures / Misleading Data

### M-01: Compliance Concentration Check Uses Position Book Total, Not NAV
- **File:** `app/agents/middle_office/compliance/compliance_agent.py` lines 113-153
- **Bug:** `concentration = value / total_value` where `total_value` = sum of position values. Should divide by NAV (positions + cash). A portfolio 90% cash, 10% in one stock shows 100% concentration.
- **Impact:** False concentration alerts with significant cash holdings.

### M-02: AccountingAgent Reads Wrong Payload Key for NAV
- **File:** `app/agents/back_office/accounting/accounting_agent.py` line 38
- **Bug:** Reads `"nav"` from PORTFOLIO_UPDATE but PortfolioAgent publishes `"total_value"`. Only gets real NAV from PositionMonitorWorker messages (which use both keys).
- **Impact:** `_last_nav` unreliable — depends on which publisher's message arrives.

### M-03: Operations Agent Stuck-Order Detection Broken
- **File:** `app/agents/middle_office/operations/operations_agent.py` lines 36-46
- **Bug:** Reads `order_id` from ORDER_NEW payload, but PortfolioAgent's ORDER_NEW doesn't include `order_id`. All pending orders stored under key `""`.
- **Impact:** Stuck order monitoring is non-functional.

### M-04: Signal-to-Order Traceability Broken
- **File:** `app/agents/middle_office/risk/risk_agent.py` lines 123-131
- **Bug:** Risk-approved signals don't carry `signal_id`. PortfolioAgent's `payload.get("signal_id")` always returns `None`.
- **Impact:** Cannot trace which signal generated which order. Audit trail broken.

### M-05: Conflicting Signals from Multiple Strategies Not Resolved
- **File:** `app/agents/front_office/strategy/strategy_agent.py` lines 108-146
- **Bug:** RSI, MACD, and Bollinger run independently per symbol. RSI can emit BUY while Bollinger emits SELL for the same symbol in the same cycle. No aggregation or conflict resolution.
- **Impact:** Simultaneous opposing orders for same symbol. Double slippage and commissions.

### M-06: RSI Thresholds Don't Match Documentation
- **File:** `app/agents/front_office/strategy/simple_strategies.py` lines 25-38
- **Bug:** Docstring: "Buy RSI < 30, sell RSI > 70." Code: buy RSI < 45, sell RSI > 65.
- **Impact:** Far more aggressive signaling than documented. Excessive low-quality signals.

### M-07: Alert Manager Subscribes to Wrong Debate Channel
- **File:** `app/services/alert_manager.py` line 168
- **Bug:** Subscribes to `"horizon.debate.conclusion"` (exact). Debates publish to `"horizon.debate.{session_id}.conclusion"`.
- **Impact:** Debate rejection alerts never fire.

### M-08: Alert Manager Checks Wrong Payload Field for Debate Decisions
- **File:** `app/services/alert_manager.py` line 263
- **Bug:** Checks `payload.get("final_decision")` — actual key is `"decision"`. Also checks for `"REJECT"` but actual value is `"REJECTED"`.
- **Impact:** Even if M-07 were fixed, debate alerts would still never match. Double failure.

### M-09: `cio why` Shows "No reasoning recorded" Always
- **File:** `app/tui/commands.py` line 831
- **Bug:** Reads `override.get("full_prompt")` but CIO stores reasoning under key `"reasoning"`.
- **Impact:** Users can never see CIO override rationale via REPL.

### M-10: Pixel Agent Visualizer Built But Never Rendered
- **File:** `app/tui/dashboard.py` lines 70-71, 500-534
- **Bug:** `PixelAgentVisualizer` instantiated, updated with state changes, but `build_panel()` never called in layout.
- **Impact:** Wasted computation. Feature is invisible.

### M-11: `buy` Auto-Sizing Broken for Crypto
- **File:** `app/tui/commands.py` line 1079
- **Bug:** `qty = int(allocation / price)` truncates to integer. BTC at $60K with $50K allocation → `int(0.83)` = 0 → "Insufficient cash" error.
- **Impact:** Cannot auto-size crypto buys. Must specify exact fractional quantity.

### M-12: Report Generator Invalid SQL for Regime Query
- **File:** `app/services/report_generator.py` lines 308-318
- **Bug:** `GROUP BY market_scope HAVING created_at = MAX(created_at)` — non-aggregated columns in GROUP BY. SQLite picks arbitrary rows.
- **Impact:** Report regime summary may show stale or random regime states.

### M-13: Performance Service Trade Pairing Is Cross-Symbol
- **File:** `app/services/performance.py` lines 133-149
- **Bug:** Trade pairing pairs ALL buys with ALL sells globally, not per-symbol. AAPL buys can match with MSFT sells. Also ignores commissions.
- **Impact:** Win rate and profit factor wrong for multi-symbol portfolios.

### M-14: Settings Panel Uses Relative .env Path
- **File:** `app/__main__.py` line 441
- **Bug:** `SettingsPanel(env_path=".env")` — relative to CWD, not to project root.
- **Impact:** Settings edits may write to wrong file depending on launch directory.

### M-15: Debate Gate Fragile — Works By Accident
- **File:** `app/agents/front_office/portfolio/portfolio_agent.py` line 68
- **Bug:** PortfolioAgent subscribes to `horizon.debate.*`. DebateEngine publishes to `horizon.debate.{session_id}.conclusion`. Subscription matches via wildcard, but also picks up `.start` and `.argument` messages (filtered by type check). Works, but only because wildcard happens to match.
- **Impact:** Any change to channel naming would break the debate gate silently.

### M-16: Handler Exceptions Silently Lost
- **Files:** `app/core/messaging.py` lines 127-134, `app/core/memory_bus.py` line 61
- **Bug:** Both buses dispatch handlers via `asyncio.create_task()` with no error handling. Exceptions in handlers vanish — no logging, no retry.
- **Impact:** Any handler crash is invisible. Agents can silently stop processing messages.

### M-17: Agent Restart Race Condition
- **File:** `app/workers/agent_orchestrator.py` line 258
- **Bug:** `slot.agent._running = False` directly sets private attribute. If old agent's `stop()` is still running, race condition on `_running` flag.
- **Impact:** Could leave agents in inconsistent state after restart.

---

<a name="low"></a>
## 5. LOW — Dead Code / Minor Issues

### L-01: `fno_value` Always Zero in Portfolio Snapshots
- **File:** `app/agents/front_office/portfolio/portfolio_agent.py` line 258
- Initialized to 0.0, never assigned. F&O value always recorded as 0.

### L-02: Position Sizing Overcounts When Adding to Existing Position
- **File:** `app/agents/front_office/portfolio/portfolio_agent.py` line 223
- `num_positions = len(positions) + 1` — adds 1 for new position even when adding to existing.

### L-03: Exchange Mismatch in Naked Short Check
- **File:** `app/agents/front_office/trading/execution_agent.py` lines 306-318
- Strict exchange matching can cause false rejections if exchange strings inconsistent.

### L-04: Direction Type Mismatch (int on bus, string in DB)
- **File:** `app/agents/front_office/strategy/strategy_agent.py` line 126 vs 212
- Bus uses integer direction (+1/-1), DB stores string ("BUY"/"SELL"). Re-emit from DB would break.

### L-05: `orders all` Argument Silently Ignored
- **File:** `app/tui/commands.py` line 251
- Help text shows `orders [all]` but args parameter is never read.

### L-06: `backtest --strategy crisis` Runs Generic SMA Strategy
- **File:** `app/tui/commands.py` lines 346-413
- Help lists "crisis" as strategy but it falls through to generic SMA-50 else branch.

### L-07: Performance Snapshots Table Grows Unbounded
- **File:** `app/workers/performance_worker.py` lines 383-419
- 576 rows/day with no retention policy. No index on `created_at`.

### L-08: `agent_messages` Table Grows Unbounded
- **File:** `app/core/local_storage.py` lines 105-116
- Every emitted message persisted. No cleanup, no indexes on `channel`/`message_type`.

### L-09: KV Store `delete()` Leaves Stale Expiry Entries
- **File:** `app/core/kv_store.py` lines 39-40
- Key removed from `_data` but not `_expiry`. Re-set without TTL inherits old expiry.

### L-10: `retry_with_backoff` Defined But Never Used
- **File:** `app/core/resilience.py` lines 14-32
- Dead code. No file imports it.

### L-11: `CircuitBreaker` and `with_timeout` Don't Exist
- **File:** `app/core/resilience.py`
- CLAUDE.md claims they exist. Only `retry_with_backoff` is implemented. External API calls lack circuit breaker protection.

### L-12: CIOChat Class Never Wired
- **File:** `app/tui/cio_chat.py`
- `CIOChat` exists but is never instantiated. Dead code.

### L-13: AgentVisualizer Class Never Used
- **File:** `app/tui/agent_visualizer.py`
- `AgentVisualizer` never imported anywhere. Dashboard builds its own agent table.

### L-14: Auto-Generated Passwords Never Displayed
- **File:** `app/config.py` lines 48-51, 109-113
- When secrets auto-generate (blank/"changeme"), the generated value is never shown. CIO password unrecoverable.

### L-15: Redis Module Imported at Top Level (Breaks LOCAL Mode)
- **File:** `app/core/redis_client.py` lines 7-13
- Connection pool created at import time. API route files import this module, triggering Redis connection attempt even in LOCAL mode.

---

<a name="dead-config"></a>
## 6. Dead Configuration Parameters

These settings exist in `app/config.py` and are displayed in config output, but **no code enforces them**:

| Setting | Line | What It Should Do | Reality |
|---------|------|-------------------|---------|
| `risk_max_leverage` | 180 | Cap portfolio leverage at 1.0x | Never checked by any agent |
| `risk_var_limit_pct` | 181 | Alert when VaR exceeds 3% | VaR computed but never compared to limit |
| `risk_max_orders_per_minute` | 183 | Throttle order submission to 10/min | No order frequency throttle exists |
| `llm_max_calls_per_minute` | 175 | Rate limit LLM API calls to 60/min | No rate limiter implemented |

**Impact:** Users configure these thinking they're protected. They're not. False sense of security.

---

<a name="dead-code"></a>
## 7. Dead Code & Missing Modules

### Files That Exist But Are Never Used
| File | What It Does | Why Dead |
|------|-------------|----------|
| `app/tui/agent_visualizer.py` | Table-based agent state display | Dashboard builds its own; never imported |
| `app/tui/cio_chat.py` | Interactive CIO chat interface | `_cio_chat = None`, never instantiated |
| `app/core/resilience.py:retry_with_backoff` | Retry decorator with exponential backoff | Never imported by any module |

### Modules Referenced in CLAUDE.md But Don't Exist
| Module | Documented Purpose | Status |
|--------|-------------------|--------|
| `app/services/stress_testing.py` | Historical crisis scenarios (GFC, COVID) | File not found |
| `app/services/model_registry.py` | ML model versioning + Thompson Sampling | File not found |

### Features Documented But Not Implemented
| Feature | Where Documented | Reality |
|---------|-----------------|---------|
| Circuit breaker on external APIs | CLAUDE.md | Only `retry_with_backoff` exists (unused) |
| Strategy LLM wiring | MEMORY.md | `generate_signals_async()` doesn't exist; strategy is rules-only |
| `ORDER_APPROVE` / `ORDER_REJECT` MessageTypes | MEMORY.md | Not in `MessageType` enum |

---

<a name="index"></a>
## 8. Full Issue Index

| ID | Sev | Category | File | One-Line Summary |
|----|-----|----------|------|------------------|
| C-01 | CRIT | Data | runtime.py:77 | Cash reset on restart destroys P&L history |
| C-02 | CRIT | Data | local_storage.py:64 | Migration drops tables with all data |
| C-03 | CRIT | Calc | performance_worker.py:187 | Win rate ~100% (uses gross proceeds not P&L) |
| C-04 | CRIT | Data | feature_computation_worker.py:396 | Indicators computed on oldest data (ASC LIMIT) |
| C-05 | CRIT | Wiring | __main__.py:265 | CIO agent started twice = double LLM costs |
| C-06 | CRIT | Calc | performance_worker.py:129 | Annualization uses snapshot count not days |
| C-07 | CRIT | Calc | backtest_metrics.py:40 | Backtest win rate halved (counts BUYs as losses) |
| H-01 | HIGH | Risk | risk_agent.py:166 | Kill switch doesn't stop orders |
| H-02 | HIGH | Calc | risk_agent.py:263 | Daily loss limit uses all-time P&L |
| H-03 | HIGH | Risk | position_worker.py:162 | Stop-loss goes through debate (can be blocked) |
| H-04 | HIGH | Risk | position_worker.py:119 | No stop-loss for SHORT positions |
| H-05 | HIGH | Calc | position_worker.py:136 | NAV mixes USD/INR without conversion |
| H-06 | HIGH | Data | execution_agent.py:266 | Poll fills recorded but positions/cash not updated |
| H-07 | HIGH | Wiring | cio_agent.py:352 | CIO reads wrong KV keys (all None) |
| H-08 | HIGH | Display | dashboard.py:434 | Trade history shows qty=0 (wrong key) |
| H-09 | HIGH | Display | dashboard.py:93 | Portfolio panel never shows positions |
| H-10 | HIGH | Display | commands.py:610 | performance ytd/all return 30-day data |
| H-11 | HIGH | Data | commands.py:975 | Watchlist writes to wrong .env path |
| H-12 | HIGH | Wiring | alert_manager.py:164 | Kill switch alerts never reach notifications |
| H-13 | HIGH | Calc | backtest_engine.py:200 | Backtest P&L excludes commissions |
| H-14 | HIGH | Display | commands.py:200 | portfolio cmd shows 0 positions |
| H-15 | HIGH | Display | commands.py:773 | pnl shows -100% first 30 seconds |
| H-16 | HIGH | Logic | debate_engine.py:281 | Approval is simple majority, not documented 3/4 |
| M-01 | MED | Calc | compliance_agent.py:115 | Concentration uses position total, not NAV |
| M-02 | MED | Wiring | accounting_agent.py:38 | Reads wrong NAV key from payload |
| M-03 | MED | Wiring | operations_agent.py:39 | Stuck order detection broken (no order_id) |
| M-04 | MED | Wiring | risk_agent.py:123 | Signal→order traceability broken |
| M-05 | MED | Logic | strategy_agent.py:108 | Conflicting signals not resolved |
| M-06 | MED | Docs | simple_strategies.py:25 | RSI thresholds don't match docstring |
| M-07 | MED | Wiring | alert_manager.py:168 | Debate alerts subscribe wrong channel |
| M-08 | MED | Wiring | alert_manager.py:263 | Debate alerts check wrong field AND value |
| M-09 | MED | Display | commands.py:831 | `cio why` always shows no reasoning |
| M-10 | MED | Display | dashboard.py:70 | Pixel agents built but never rendered |
| M-11 | MED | Logic | commands.py:1079 | buy auto-size broken for crypto (int truncation) |
| M-12 | MED | Data | report_generator.py:313 | Invalid SQL for regime query |
| M-13 | MED | Calc | performance.py:134 | Trade pairing cross-symbol, ignores commission |
| M-14 | MED | Config | __main__.py:441 | Settings panel uses relative .env path |
| M-15 | MED | Wiring | portfolio_agent.py:68 | Debate gate works by wildcard accident |
| M-16 | MED | Infra | messaging.py:127 | Handler exceptions silently lost |
| M-17 | MED | Infra | orchestrator.py:258 | Agent restart race condition |
| L-01 | LOW | Data | portfolio_agent.py:258 | fno_value always 0 |
| L-02 | LOW | Calc | portfolio_agent.py:223 | Position sizing overcounts |
| L-03 | LOW | Logic | execution_agent.py:310 | Exchange mismatch false rejections |
| L-04 | LOW | Data | strategy_agent.py:126 | Direction int/string type mismatch |
| L-05 | LOW | Display | commands.py:251 | orders all argument ignored |
| L-06 | LOW | Display | commands.py:346 | crisis strategy runs generic SMA |
| L-07 | LOW | Data | performance_worker.py:383 | Unbounded table growth (576 rows/day) |
| L-08 | LOW | Data | local_storage.py:105 | agent_messages table unbounded |
| L-09 | LOW | Data | kv_store.py:39 | delete leaves stale expiry |
| L-10 | LOW | Dead | resilience.py:14 | retry_with_backoff never imported |
| L-11 | LOW | Missing | resilience.py | CircuitBreaker/with_timeout don't exist |
| L-12 | LOW | Dead | cio_chat.py | CIOChat never wired |
| L-13 | LOW | Dead | agent_visualizer.py | AgentVisualizer never used |
| L-14 | LOW | Config | config.py:48 | Auto-gen passwords never shown |
| L-15 | LOW | Import | redis_client.py:7 | Top-level Redis import breaks LOCAL mode |

---

## 9. Math & Logic Deep-Dive (Second Pass)

A focused second-pass audit targeting only mathematical formulas, calculation errors, state machine bugs, and control flow logic. Items already covered in sections 2-5 are not repeated — only NEW findings below.

### NEW CRITICAL

#### MC-01: VaR Calculation — Wrong Index and Wrong Sign Handling
- **File:** `app/agents/middle_office/risk/var_calculator.py` line 36
- **Formula:** `return float(abs(sorted_returns[idx]))` where `idx = int((1 - confidence) * len(sorted_returns))`
- **Bug 1 — Index:** For 10 returns at 95% confidence: `int(0.05 * 10) = 0`. Index 0 = worst return (0th percentile, not 5th). Small samples always select the absolute worst return regardless of confidence level.
- **Bug 2 — abs():** When all returns are positive (strong bull run), the 5th percentile might be +0.5%. `abs(0.005)` reports 0.5% "value at risk" when there is no actual loss risk at that confidence level.
- **Fix:** Use `np.percentile(returns, (1 - confidence) * 100)` and `return max(-var, 0.0)`.

#### MC-02: Sortino Ratio — Wrong Downside Deviation Formula
- **Files:** `app/services/performance.py` line 123, `app/workers/performance_worker.py` line 157
- **Formula:** Filters to only negative excess returns, then computes `std(ddof=1)` on that subset.
- **Bug:** Standard Sortino uses downside deviation over ALL returns: `sqrt(mean(min(excess, 0)^2))`. Current code:
  1. Ignores zero/positive returns that should contribute 0 to the sum
  2. Divides by `(count_negative - 1)` instead of `total_count`
  3. Result: downside deviation shrinks when few losses exist → Sortino ratio inflated
- **Example:** 100 returns, 5 negative. Current: `std` of 5 values. Correct: `sqrt(sum_of_5_squared_negatives / 100)`. Current denominator is ~4.5x smaller → Sortino ~4.5x inflated.
- **Fix:** `downside_diff = np.minimum(excess, 0); dd = np.sqrt(np.mean(downside_diff ** 2))`

#### MC-03: Partial Sell Corrupts buy_cost — Subsequent P&L Wildly Wrong
- **File:** `app/services/performance.py` lines 146-149
- **Bug:** After partial sell, `buy_qty` decremented but `buy_cost` NOT reduced proportionally.
- **Example:** Buy 100 @ $10 (`buy_cost=1000, buy_qty=100`). Sell 50 @ $12. `buy_qty` becomes 50 but `buy_cost` stays 1000. Next sell: `avg_entry = 1000/50 = $20` (should be $10). Sell 50 @ $11: P&L = `(11-20)*50 = -$450` (should be `+$50`).
- **Impact:** Every trade P&L after a partial sell is computed against a doubled (or worse) avg entry. Win/loss classification completely wrong.
- **Fix:** After partial sell: `buy_cost -= avg_entry * qty`

### NEW HIGH

#### MH-01: Cash Balance Race Condition (Non-Atomic Read-Modify-Write)
- **File:** `app/agents/front_office/trading/execution_agent.py` lines 333-363
- **Bug:** `_update_cash_balance` does: `read current → compute new → write new`. Two concurrent fills both read same value, both compute independently, second write overwrites first. One fill's cash impact silently lost.
- **Impact:** Cash balance drifts from reality over time. More fills = more drift.
- **Fix:** Use `asyncio.Lock` to serialize all cash mutations.

#### MH-02: Poll Loop Can Double-Fill Orders at Full Quantity
- **File:** `app/agents/front_office/trading/execution_agent.py` lines 266-304
- **Bug:** Poll sends `row.quantity` (full original qty) to broker, not `remaining_qty = row.quantity - already_filled`. A PARTIAL order gets re-filled for the FULL amount. `_get_total_filled()` exists but is never called.
- **Impact:** Position doubled. Cash deducted twice (if cash update even runs — it doesn't from this path per H-06).

#### MH-03: Cash Can Go Negative (No Sufficiency Check in Live Mode)
- **File:** `app/agents/front_office/trading/execution_agent.py` lines 333-363
- **Bug:** `_update_cash_balance` computes `new_balance = current - cost - commission` and writes unconditionally. No `new_balance < 0` check. Position sizing uses stale NAV snapshot (60s delay). Multiple BUY fills between snapshots can overdraw.
- **Impact:** System trades with phantom capital. Portfolio leverage exceeds 1x silently.
- **Note:** Backtest engine correctly checks `if cost <= cash` (line 179). Live path doesn't.

#### MH-04: SELL Quantity > Position Creates Unintended SHORT
- **File:** `app/agents/front_office/trading/order_manager.py` lines 286-326
- **Bug:** Naked-short check (`_has_open_position`) only blocks SELL when NO position exists. If position is 100 shares LONG and SELL for 150 arrives, check passes (position exists). Result: `new_qty = 100 - 150 = -50 → side = SHORT, qty = 50`. Unintended short position created.
- **Fix:** Check `sell_qty <= current_position_qty` before executing.

#### MH-05: Debate Debounce Silently Drops Stop-Loss Signals
- **File:** `app/agents/middle_office/debate_agent.py` lines 74-78
- **Bug:** If stop-loss SELL signal arrives within 120 seconds of last debate for same symbol, it's silently dropped with `continue`. No rejection message, no logging. Stop-loss never executes.
- **Impact:** Position continues bleeding past stop-loss while debounce timer runs. Combined with H-03 (stop-loss goes through debate), emergency exits face TWO blocking gates.
- **Fix:** Stop-loss signals (strategy_name="stop_loss") should bypass debounce entirely.

### NEW MEDIUM

#### MM-01: Risk Position Limit Checks CURRENT Position, Not Post-Trade
- **File:** `app/agents/middle_office/risk/risk_agent.py` lines 237-261
- **Bug:** Checks if existing position exceeds `risk_max_position_pct` of NAV. Does NOT add proposed order's value. Position at 4.9% with 5% limit: BUY approved → position jumps to 7%. First order over limit always passes.
- **Fix:** `projected_value = current_value + (signal_price * signal_qty)` before comparing.

#### MM-02: Drift Detector Uses Population Variance (Too Sensitive)
- **File:** `app/agents/front_office/research/drift_detector.py` lines 50-55
- **Formula:** `var = (sum_sq / count) - mean^2` — population variance, not sample.
- **Impact:** Control bounds ~5% too tight at small sample sizes (just above 10-observation threshold). False drift alarms.
- **Fix:** `var = (sum_sq - count * mean^2) / (count - 1)`

#### MM-03: INR Position Values Treated as USD (83x Inflation)
- **File:** `app/workers/position_worker.py` lines 95-96
- **Bug:** `total_value += current_price * pos.quantity` for ALL positions regardless of currency. INR positions (NSE/BSE stocks priced in INR) are added as-is to a USD-denominated total. An INR position worth ₹100,000 appears as $100,000 (83x overvaluation).
- **Impact:** NAV massively inflated for portfolios with Indian stocks. All risk calculations using NAV are wrong.

---

## Updated Summary

| Severity | Original (Pass 1) | New (Pass 2) | Total |
|----------|-------------------|--------------|-------|
| **CRITICAL** | 7 | 3 | **10** |
| **HIGH** | 16 | 5 | **21** |
| **MEDIUM** | 17 | 3 | **20** |
| **LOW** | 15 | 0 | **15** |
| **TOTAL** | **55** | **11** | **66** |

### Updated Full Index (New Items Only)

| ID | Sev | Category | File | One-Line Summary |
|----|-----|----------|------|------------------|
| MC-01 | CRIT | Calc | var_calculator.py:36 | VaR index wrong for small samples + abs() misreports gains as losses |
| MC-02 | CRIT | Calc | performance.py:123 | Sortino downside deviation wrong — ratio inflated ~4.5x |
| MC-03 | CRIT | Calc | performance.py:146 | Partial sell corrupts buy_cost → subsequent P&L wildly wrong |
| MH-01 | HIGH | Logic | execution_agent.py:333 | Cash race condition — concurrent fills lose one update |
| MH-02 | HIGH | Logic | execution_agent.py:266 | Poll re-fills at full qty (double fills possible) |
| MH-03 | HIGH | Logic | execution_agent.py:333 | Cash can go negative (no sufficiency check) |
| MH-04 | HIGH | Logic | order_manager.py:286 | SELL > position qty creates unintended SHORT |
| MH-05 | HIGH | Logic | debate_agent.py:74 | Debounce drops stop-loss signals silently |
| MM-01 | MED | Logic | risk_agent.py:237 | Position limit checks current, not post-trade |
| MM-02 | MED | Calc | drift_detector.py:50 | Population variance → false drift alarms |
| MM-03 | MED | Calc | position_worker.py:95 | INR positions treated as USD (83x inflation) |

---

## End of Audit

**Total unique issues: 55**
- 7 CRITICAL (data loss, wrong calculations, system-breaking)
- 16 HIGH (broken features, wrong displays, safety failures)
- 17 MEDIUM (partial failures, misleading data)
- 15 LOW (dead code, minor issues)
- 4 Dead config parameters (false sense of security)
- 2 Missing modules (documented but don't exist)
- 3 Dead code files (exist but unused)
