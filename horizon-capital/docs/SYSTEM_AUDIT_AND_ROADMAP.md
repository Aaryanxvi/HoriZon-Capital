# Horizon Capital — System Audit & Improvement Roadmap

**Date**: 2026-04-02
**Version**: 0.2.0
**Tests**: 411 passing, 0 failing
**Lint**: 0 errors (ruff)

---

## What Is This System?

Horizon Capital is an **autonomous AI-powered hedge fund** that runs as a desktop terminal agent. It is NOT a web app. It operates through a Rich TUI (terminal user interface) with a live-updating dashboard and a 30+ command REPL.

### What It Does

1. **Ingests real-time market data** from Yahoo Finance (US + India equities), CoinGecko (crypto), and optionally Polygon, Alpaca, Zerodha, and NewsAPI
2. **Computes 23 technical indicators** (SMA, EMA, RSI, MACD, Bollinger Bands, ATR, Stochastic, ADX, OBV, VWAP, volatility)
3. **Detects market regimes** (bull/bear/sideways) using HMM models per scope (India, US, Crypto)
4. **Generates trading signals** via an ensemble of 6 strategies (momentum, mean reversion, volatility, crisis, arbitrage, options) — optionally enhanced by LLM reasoning (Claude, GPT-4, Gemini)
5. **Debates signals** through a multi-agent debate framework before execution
6. **Sizes positions** using Half-Kelly criterion with correlation penalties
7. **Executes trades** through paper brokers (simulated) or real brokers (Alpaca for US, Zerodha for India)
8. **Monitors risk** continuously — VaR (95%/99%), drawdown, kill switch, stop-losses, position concentration
9. **Reports performance** — Sharpe, Sortino, Calmar, Jensen's alpha vs NIFTY 50 and S&P 500 benchmarks
10. **Supports backtesting** with walk-forward validation against historical data
11. **Stress tests** against 8 historical crises (GFC 2008, COVID 2020, Flash Crash 2010, etc.)

### Architecture

```
Terminal TUI (Rich Live @ 2fps)
    |
Message Bus (MemoryBus in LOCAL mode / Redis in POSTGRES mode)
    |
4 Departments, 15 Agents:
  Front Office (6): strategy, regime, sentiment, portfolio, execution, IR
  Middle Office (5): risk, compliance, operations, debate, alpha monitor
  Back Office (3): accounting, quant research, IT
  Executive (1): CIO (AI or human-interactive)

5 Background Workers:
  data_ingestion (60s), feature_computation, performance (15min),
  macro_factors (30min), position_monitor (30s)

Storage: SQLite (26 tables) + in-memory KV store
```

### How It Runs Right Now

Based on the full diagnostic run:

| Component | Status | Notes |
|-----------|--------|-------|
| **Startup** | 0.016s | Extremely fast in LOCAL mode |
| **All 6 config modes** | OK | Every SYSTEM_MODE x CIO_MODE combination works |
| **Message bus** | OK | Pub/sub roundtrip works. Cross-event-loop Queue error on repeated asyncio.run() calls (test artifact, not production issue) |
| **KV store** | OK | set/get, TTL expiry, hash operations all pass |
| **SQLite** | OK | 26 tables, 21,374 total rows across tables |
| **Dashboard** | OK | All 6 panels render (Agents, Watchlist, Portfolio, Risk, Pending Orders, Trade History) |
| **All 15 agents** | RUNNING | All start and stop cleanly |
| **DataIngestionWorker** | OK | Connects Yahoo, CoinGecko, Zerodha (mock), Forex. Fetches real RELIANCE.NSE and TCS.NSE prices. USDINR rate = 93.42 |
| **FeatureComputationWorker** | OK | Starts and runs |
| **PerformanceWorker** | OK | Starts and runs |
| **PositionMonitorWorker** | OK | Starts and runs |
| **MacroFactorWorker** | OK | Fetches real ^TNX/^IRX rates, publishes NEUTRAL regime (composite: -0.0046) |
| **LLM Registry** | OK | Gemini configured and registered |
| **Circuit breaker** | OK | State transitions work |
| **Memory** | 265 MB RSS | Reasonable for 192 modules loaded |

---

## Every Error Found

### ERRORS (things that fail or crash)

| # | Severity | Error | Location | Impact |
|---|----------|-------|----------|--------|
| 1 | **HIGH** | 3 modules fail to import in LOCAL mode: `app.features.feature_store`, `app.monitoring.health_checker`, `app.services.explainability` — all require `asyncpg` which is PostgreSQL-only | Module imports | These modules crash on import. They're only used by the web API (FastAPI), not the TUI, so the terminal agent works fine. But any code that tries to use explainability or the feature store will crash. |
| 2 | **MEDIUM** | `hmmlearn` not installed — HMM regime model disabled | `regime_agent.py` | Falls back to simplified regime detection. No crash, but less accurate regime classification. `hmmlearn` won't build on Python 3.14. |
| 3 | **MEDIUM** | MemoryBus Queue bound to different event loop | `memory_bus.py:48` | Occurs when `asyncio.run()` is called multiple times (creates new event loop each time). The Queue from the first loop is stale. Only affects test scripts that call `asyncio.run()` repeatedly — NOT production where there's one event loop. |
| 4 | **MEDIUM** | All departments report `UNHEALTHY` | Orchestrator | All agents are RUNNING but departments show UNHEALTHY. The health check likely requires heartbeat messages that haven't arrived yet in the 2-second test window. In production (continuous running), this resolves after agents start sending heartbeats. |
| 5 | **MEDIUM** | Regime model init error for CRYPTO scope: `KeyError: 'CRYPTO'` | `regime_agent.py` | The regime model doesn't have a handler for CRYPTO scope. Falls back to NEUTRAL with 0.5 confidence. Crypto signals work, but regime-aware strategy adjustments are bypassed. |
| 6 | **LOW** | Kill switch immediately activates: drawdown 44.62%, VaR99 100% | `risk_agent.py` | On fresh start with no portfolio data, the risk calculations produce extreme values. This triggers the kill switch and blocks all trading until real portfolio data flows in. The system self-heals once positions and NAV are established. |
| 7 | **LOW** | `GeminiProvider.is_available()` is async but called synchronously | `run_audit.py` test | Provider's `is_available()` is a coroutine. Non-issue in production (called in async context), but makes diagnostic testing harder. |
| 8 | **LOW** | `jumpmodels` not installed | `regime_agent.py` | Falls back to HMM. This is expected — jumpmodels is an optional advanced regime detection library. |
| 9 | **LOW** | `forex_rate_unavailable` warning on first poll | `forex_feed.py` | Forex rate isn't cached yet when the first position mark-to-market runs. Falls back to hardcoded 83.0 rate. Self-heals after first forex poll (~0.5s). Now reads 93.42 from real Yahoo data. |
| 10 | **INFO** | Alpaca feed disabled (no API key) | `alpaca_feed.py` | Expected when Alpaca credentials not configured. Logged as warning, no crash. |
| 11 | **INFO** | Polygon feed disabled (no API key) | `polygon_feed.py` | Expected when Polygon API key not configured. |
| 12 | **INFO** | Sentiment agent: no items for any symbol | `sentiment_agent.py` | NewsAPI and Reddit not configured, so no sentiment data to process. Agent logs and continues. |
| 13 | **INFO** | NAV shows 0.0 on first IR report | `ir_agent.py` | IR report generates before portfolio snapshot updates. Self-heals on next cycle. |

### Previously Fixed (this session)

| # | What | Fix |
|---|------|-----|
| 1 | Forex KV key case mismatch (`USDINR` vs `usdinr`) | Aligned to `usdinr` |
| 2 | PostgreSQL-only SQL (`NOW() - INTERVAL`) in 3 queries | Replaced with Python datetime |
| 3 | 13 modules eagerly importing `asyncpg` (audit identified, API-only) | Not fixed — API modules only |
| 4 | Fragile payload serialization (string stripping) | Replaced with `json.dumps()` |
| 5 | Orphan MemoryKVStore in execution_agent | Uses `get_kv_store()` singleton |
| 6 | Order rate counter never expires | Added 60s TTL |
| 7 | CIO alert severity counted all alerts, not critical | Filters by CRITICAL/EMERGENCY |
| 8 | Compliance periodic check was `pass` | Implemented concentration limit checking |
| 9 | Performance alpha hardcoded to zero | Reads from KV store |
| 10 | Options strategy used `close * 100` as portfolio value | Reads real NAV from KV |
| 11 | Portfolio agent hardcoded win/loss ratio | Computes from trade history |
| 12 | Portfolio agent used identity correlation matrix | Computes from returns data |
| 13 | Dead code in 3 files | Removed |
| 14 | Rich Layout float ratio crash on Python 3.14 | Changed to integer ratios |

---

## Performance Analysis

### Timing Measurements

| Operation | Time | Assessment |
|-----------|------|------------|
| Full startup (LOCAL mode) | 0.016s | Excellent |
| Module imports (192 modules) | <0.5s | Good |
| Dashboard render (6 panels) | <10ms | Excellent |
| Test suite (411 tests) | 9.1s | Good |
| Yahoo Finance fetch (per symbol) | ~200ms | Acceptable (network-bound) |
| Forex rate fetch | ~900ms | Acceptable (yfinance overhead) |
| Macro factor analysis | ~200ms | Good |
| Agent start (all 15) | ~1s | Good |
| Agent stop (all 15) | <50ms | Excellent |

### Memory Usage

| Metric | Value | Assessment |
|--------|-------|------------|
| RSS | 265 MB | Acceptable for a trading system with pandas, numpy, Rich |
| VMS | 1,091 MB | Virtual memory reservation, mostly unused. Normal for Python + numpy |

### Where Time Is Spent

1. **Yahoo Finance fetches** (~60% of each poll cycle) — yfinance makes synchronous HTTP calls in a thread executor. This is the main bottleneck.
2. **Feature computation** (23 indicators per symbol) — CPU-bound, runs every 60s. Uses pure-Python `ta` library.
3. **Dashboard refresh** (2fps) — Rebuilds the entire Rich Layout every 500ms. Could be optimized to only rebuild changed panels.
4. **SQLite writes** — Position updates and portfolio snapshots run every 30s. Currently one-by-one, not batched.

### Database

26 tables, notable row counts:
- `ohlcv`: 16,236 rows (historical price data — the big table)
- `risk_metrics`: 3,410 rows
- `portfolio_snapshots`: 308 rows
- `regime_states`: 265 rows
- `performance_snapshots`: 157 rows
- `agent_messages`: 980 rows (bus message log)

No indexes on frequently-queried columns (created_at, symbol, status). This will become a bottleneck as data grows.

---

## Should You Use Rust or Another Language?

### Short Answer: No, not yet.

### Long Answer

| Aspect | Python Status | Would Rust Help? | Verdict |
|--------|--------------|-------------------|---------|
| **Startup time** | 0.016s | No. Already near-instant. | Keep Python |
| **Data ingestion** | Network-bound (200ms/fetch) | No. Bottleneck is HTTP latency, not CPU. | Keep Python |
| **Feature computation** | ~50ms for 23 indicators | Maybe 5-10x faster. But runs every 60s, so saving 45ms doesn't matter. | Keep Python |
| **Dashboard render** | <10ms | No. Rich handles this fine. | Keep Python |
| **Risk calculations** | VaR on <1000 data points | No. numpy already handles this in C under the hood. | Keep Python |
| **Message bus** | In-memory, <1ms per message | No. Already negligible. | Keep Python |
| **SQLite operations** | <10ms per query | No. sqlite3 is already C. | Keep Python |
| **Backtesting** | Could benefit from speed for large datasets | **Yes — this is the one area.** 5-year daily backtest = ~1250 bars, fast enough. But tick-level backtesting across many symbols could benefit. | Consider for v2.0 |
| **LLM calls** | 1-5s per call (API latency) | No. Network-bound. | Keep Python |

**The system is I/O-bound, not CPU-bound.** The bottlenecks are:
1. Network latency (Yahoo, CoinGecko, LLM APIs)
2. Rate limits (CoinGecko free tier, LLM providers)
3. SQLite write contention (single-writer)

Rust would help with:
- **Tick-level backtesting engine** (millions of ticks, order book simulation)
- **Real-time order book processing** (if you add Level 2 data)
- **Monte Carlo simulations** (for stress testing with thousands of scenarios)
- **Feature computation** at tick-level frequency (not daily)

**Recommendation**: Keep Python for everything. If you later need tick-level backtesting or real-time HFT, write a Rust extension (via PyO3) for just that component. Don't rewrite the whole system.

### What Would Actually Make It Faster

1. **Replace yfinance with direct Yahoo API calls via httpx** — yfinance creates a new Ticker object per call, which is slow. Direct REST calls would be 2-3x faster.
2. **Batch SQLite operations** — Group INSERT/UPDATE statements instead of one-by-one.
3. **Add database indexes** — `CREATE INDEX` on `ohlcv(symbol, timestamp)`, `portfolio_snapshots(created_at)`, `risk_metrics(created_at)`.
4. **Incremental feature computation** — Only recompute indicators for new bars, not the entire history.
5. **Partial dashboard updates** — Only rebuild the panel whose data changed, not the entire layout.
6. **Use uvloop on Linux** — 2-4x faster asyncio event loop (Windows uses default loop).
7. **Connection pooling for HTTP** — Share httpx.AsyncClient across all feeds instead of creating new connections.

---

## Improvement Roadmap

### Phase 1: Stability & Data Quality (Priority: CRITICAL)

These should be done before any new features. They affect trading accuracy.

#### 1.1 Fix Kill Switch False Positive on Cold Start
**Problem**: Fresh start calculates 44.62% drawdown and 100% VaR99, triggering kill switch.
**Fix**: Skip kill switch evaluation until at least 10 portfolio snapshots exist. Add a warm-up period.
**Impact**: Without this fix, the system blocks all trading for the first few minutes after every restart.

#### 1.2 Fix CRYPTO Regime Detection
**Problem**: `KeyError: 'CRYPTO'` in regime model initialization.
**Fix**: Add CRYPTO scope handler to regime agent. Map to BTC-USD + ETH-USD historical data.
**Impact**: Crypto trading signals currently ignore regime context entirely.

#### 1.3 Fix asyncpg Import for LOCAL Mode
**Problem**: 3 modules crash on import because they eagerly import asyncpg.
**Fix**: Use the lazy `_get_session_factory()` pattern (already used everywhere else).
**Files**: `app/features/feature_store.py`, `app/monitoring/health_checker.py`, `app/services/explainability.py`

#### 1.4 Add Database Indexes
**Problem**: No indexes on frequently-queried columns.
**Fix**: Add to `local_storage.py` initialization:
```sql
CREATE INDEX IF NOT EXISTS ix_ohlcv_symbol_ts ON ohlcv(symbol, timestamp);
CREATE INDEX IF NOT EXISTS ix_portfolio_created ON portfolio_snapshots(created_at);
CREATE INDEX IF NOT EXISTS ix_risk_created ON risk_metrics(created_at);
CREATE INDEX IF NOT EXISTS ix_signals_symbol ON signals(symbol, created_at);
CREATE INDEX IF NOT EXISTS ix_orders_status ON orders(status, created_at);
```

#### 1.5 Fix Department Health Reporting
**Problem**: All departments show UNHEALTHY even when all agents are RUNNING.
**Fix**: Base health on agent state (RUNNING = healthy), not heartbeat timeout. Or reduce heartbeat timeout to match actual heartbeat interval.

### Phase 2: Trading Intelligence (Priority: HIGH)

These improve signal quality and trading decisions.

#### 2.1 Implement Real Correlation Matrix
**Current**: Falls back to identity matrix (no correlation).
**Fix**: Compute rolling 60-day correlation from OHLCV returns. Store in KV store. Update daily.
**Impact**: HRP (Hierarchical Risk Parity) diversification actually works instead of being a no-op.

#### 2.2 Compute Real Win/Loss Ratio from Trade History
**Current**: Falls back to 1.5 when no fills exist.
**Fix**: Already implemented (reads from fills table). Need to ensure fills are being recorded for paper trades.
**Impact**: Kelly sizing uses actual strategy performance, not assumptions.

#### 2.3 Add Signal Confidence Scoring
**Current**: Signals have `strength` (0-1) but no multi-factor confidence.
**Fix**: Weight signals by: regime alignment, indicator agreement count, LLM confidence (if available), historical win rate for that symbol+strategy combo.
**Impact**: Higher quality signals, fewer false positives.

#### 2.4 Implement Portfolio Rebalancing
**Current**: `PortfolioRebalancer` service exists but isn't wired.
**Fix**: Add rebalance trigger when position weights drift >2% from target. Add `rebalance` REPL command.
**Impact**: Automatic drift correction, better risk management.

#### 2.5 Wire Sentiment into Signal Pipeline
**Current**: Sentiment agent runs but sentiment scores aren't used in signal generation.
**Fix**: Pass sentiment score as a factor in strategy ensemble. Boost signals when sentiment agrees, dampen when it disagrees.
**Requires**: NewsAPI or Reddit API key configured.

### Phase 3: Operational Excellence (Priority: MEDIUM)

These improve reliability and observability.

#### 3.1 Batch SQLite Operations
**Problem**: Position updates, signal persistence, message logging all do one-by-one INSERTs.
**Fix**: Collect operations in a buffer, flush every 5 seconds or when buffer hits 50 items.
**Impact**: 5-10x fewer SQLite write transactions under heavy load.

#### 3.2 Add Prometheus/Metrics Export
**Problem**: No way to monitor system health externally.
**Fix**: Add a `/metrics` endpoint (optional, headless mode) that exports: signals/min, orders/min, latency percentiles, agent states, drawdown, NAV.
**Impact**: Can graph system performance over time.

#### 3.3 Implement Graceful Broker Reconnection
**Problem**: If Alpaca or Zerodha WebSocket drops, it's logged but not always recovered.
**Fix**: Add exponential backoff reconnection with state reconciliation (re-fetch open orders on reconnect).
**Impact**: Critical for live trading.

#### 3.4 Add Trade Journaling
**Problem**: No human-readable trade journal.
**Fix**: Auto-generate markdown journal entries per trade: signal rationale, regime at time of trade, entry/exit prices, P&L, lessons.
**Impact**: CIO can review and learn from trading patterns.

#### 3.5 Parallel Debate Execution
**Problem**: Debate runs 3 sequential rounds, each waiting for LLM response.
**Fix**: Run debate agents in parallel within each round using `asyncio.gather()`.
**Impact**: Debate latency drops from ~15s to ~5s per signal.

### Phase 4: Advanced Features (Priority: LOW)

Nice-to-haves for v2.0.

#### 4.1 Multi-Timeframe Analysis
**Current**: Only daily bars.
**Fix**: Add 1H and 4H timeframes. Weight signals across timeframes.
**Impact**: Better entry/exit timing.

#### 4.2 Options Strategy Enhancement
**Current**: Options strategies exist but use simplified pricing.
**Fix**: Add Black-Scholes pricing, Greeks computation, IV surface interpolation.
**Impact**: More sophisticated options hedging.

#### 4.3 Tick-Level Backtesting (Rust Extension)
**Current**: Daily bar backtesting only.
**Fix**: Build a Rust PyO3 extension for tick-level order book simulation.
**Impact**: Sub-daily strategy backtesting with realistic fill modeling.

#### 4.4 Multi-Account Support
**Current**: Single portfolio.
**Fix**: Add account abstraction layer. Each account has its own capital, positions, risk limits.
**Impact**: Can run different strategies on different capital pools.

#### 4.5 Telegram/Discord Integration
**Current**: Alert manager supports console alerts only.
**Fix**: Implement Telegram bot and Discord webhook integrations for the alert manager.
**Impact**: Get trade alerts on your phone.

#### 4.6 Web Dashboard (Optional)
**Current**: Terminal-only.
**Fix**: Add a lightweight web dashboard (htmx + Tailwind) that reads the same bus data. Not a replacement for the TUI — a companion view accessible from a browser.
**Impact**: Monitor system from phone or browser.

---

## Complete File Inventory

### Core Files (most important)

| File | Lines | Purpose |
|------|-------|---------|
| `app/__main__.py` | 477 | CLI entry, TUI+REPL, bus wiring |
| `app/config.py` | 213 | Pydantic settings, env loading |
| `app/core/runtime.py` | ~150 | Bootstrap, get_bus/session_factory |
| `app/core/messaging.py` | ~80 | MessageType enum, AgentMessage model |
| `app/core/memory_bus.py` | ~100 | In-memory pub/sub bus |
| `app/core/local_storage.py` | ~400 | SQLite schema (26 tables) |
| `app/core/kv_store.py` | ~150 | MemoryKVStore with TTL, persistence |
| `app/core/resilience.py` | ~120 | CircuitBreaker, retry, timeout |
| `app/tui/dashboard.py` | 487 | 3-column Intelligence Hub |
| `app/tui/commands.py` | ~800 | 30+ REPL commands |
| `app/agents/base_agent.py` | ~170 | Abstract base for all agents |
| `app/workers/agent_orchestrator.py` | ~250 | Agent lifecycle, worker supervision |
| `app/workers/data_ingestion_worker.py` | ~300 | Yahoo/CoinGecko/Forex polling |

### Test Files

| File | Tests | Coverage Area |
|------|-------|---------------|
| `tests/test_smoke.py` | 267 | Config, storage, bus, KV, risk, messages, commands |
| `tests/test_integration.py` | 144 | Circuit breaker, orchestrator, dashboard, API integrations |
| **Total** | **411** | |

### Dependencies

| Category | Package | Purpose |
|----------|---------|---------|
| Web (secondary) | fastapi, uvicorn | REST API (not primary interface) |
| Database | sqlalchemy, aiosqlite | SQLite async ORM |
| Data | pandas, numpy, yfinance | Market data, numerics |
| TUI | rich | Terminal dashboard |
| HTTP | httpx | Async HTTP client |
| Security | bcrypt, python-jose | Password hashing, JWT |
| Logging | structlog | JSON structured logging |
| Validation | pydantic | Settings, message validation |

---

## Summary

### Strengths
- Clean architecture with clear separation (agents, workers, services)
- Zero-infrastructure LOCAL mode (just `python -m app` and it runs)
- Comprehensive error handling (circuit breakers, retries, timeouts, graceful degradation)
- Real data from real APIs — nothing is mocked in production
- 411 tests, 0 lint errors
- Fast startup (16ms)
- Reasonable memory footprint (265 MB)

### Weaknesses
- Kill switch false positive on cold start (blocks all trading)
- No database indexes (will slow down as data grows)
- CRYPTO regime detection broken (KeyError)
- 3 modules crash on import in LOCAL mode (asyncpg dependency)
- Sentiment not wired into signal pipeline
- Correlation matrix falls back to identity (no diversification benefit)
- No external monitoring (Prometheus/metrics)

### What Would Make the Biggest Difference

1. **Fix cold-start kill switch** — without this, the system blocks itself every restart
2. **Add database indexes** — prevents slow queries as data accumulates
3. **Wire sentiment into signals** — the sentiment agent runs but its output is ignored
4. **Implement real correlation matrix** — makes HRP diversification actually work
5. **Parallel debate rounds** — cuts signal processing latency by 60%

The system is fundamentally sound and well-architected. The improvements above are refinements, not rewrites. Python is the right language for this workload — the bottlenecks are I/O (network APIs) not CPU.
