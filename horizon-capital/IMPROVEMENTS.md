# Horizon Capital — Improvement Roadmap

> Generated: 2026-03-16. Prioritized by impact vs effort.

---

## Priority Matrix

| # | Improvement | Impact | Effort | Area |
|---|-------------|--------|--------|------|
| 1 | Fix alpha calculations | High | Low | Performance |
| 2 | Benchmark data feeds | High | Low | Data |
| 3 | Service-level tests | High | Medium | Testing |
| 4 | Zerodha real-mode | High | Medium | Execution |
| 5 | Macro factor signal wiring | High | Medium | Signals |
| 6 | Strategy plugin system | High | Medium | Architecture |
| 7 | ML training automation | Medium | High | ML |
| 8 | Crypto execution broker | Medium | High | Execution |
| 9 | Debate audit trail | Medium | Low | Observability |
| 10 | Live alert dashboard panel | Low | Low | TUI |
| 11 | REPL autocomplete | Low | Low | UX |
| 12 | Backtest persistence + comparison | Medium | Low | Backtesting |
| 13 | Signal confidence/direction split | High | Medium | Architecture |
| 14 | Walk-forward backtest validation | High | Medium | Backtesting |

---

## 1. Fix Alpha Calculations

**File:** `backend/app/services/performance.py:159`
**Status:** Placeholder — returns `alpha_india = 0.0`, `alpha_us = 0.0`

### Problem
Alpha vs benchmark is one of the most important performance metrics, but it's hardcoded to zero. Any performance report is misleading without real benchmark comparison.

### Solution
1. Add `^NSEI` (NIFTY 50) and `^GSPC` (S&P 500) as benchmark tickers to the Yahoo Finance feed.
2. Store benchmark daily returns in a `benchmark_returns` table.
3. Wire the performance service to read benchmark returns and compute Jensen's alpha properly.

### Expected Outcome
Real alpha values in all performance reports, dashboards, and REPL `perf` output.

---

## 2. Benchmark Data Feeds

**File:** `backend/app/workers/data_ingestion_worker.py`
**Depends on:** #1

### Problem
No benchmark data is collected. The data ingestion worker fetches portfolio symbols but not index benchmarks.

### Solution
Add a `BenchmarkFeed` class (or configure existing Yahoo feed) to pull daily close for:
- `^NSEI` — NIFTY 50 (India benchmark)
- `^GSPC` — S&P 500 (US benchmark)
- `BTC-USD` — Crypto benchmark (optional)

Store in a `benchmark_prices` table and expose via the performance worker.

---

## 3. Service-Level Tests

**Files:** `tests/` (currently 3 unit test files, 673 lines total)

### Problem
Zero test coverage on the most critical paths:
- Execution pipeline (order → fill → position update)
- Debate engine consensus voting
- Risk kill switch triggering
- Alert manager rule evaluation
- Stress testing scenario runs

Silent failures in any of these could cause undetected trading errors.

### Solution
Add test files for each critical service. Minimum viable coverage:

```
tests/
  test_execution_pipeline.py   — paper broker order matching, fill simulation
  test_debate_engine.py        — argument rounds, consensus calculation, JSON parsing
  test_risk_management.py      — VaR breach → kill switch, drawdown limits
  test_alert_manager.py        — rule evaluation, threshold triggering
  test_stress_testing.py       — GFC 2008 / COVID 2020 scenario runs
  test_report_generator.py     — daily/weekly report generation
```

Use mocks for Claude API calls and broker connections. Focus on logic correctness, not external I/O.

---

## 4. Zerodha Real-Mode Implementation

**File:** `backend/app/data/feeds/zerodha_feed.py:56,119`
**Status:** `_real_loop()` is a stub that sleeps 60 seconds

### Problem
All India equities trading is mock-only. Real live trading to NSE/BSE is not functional despite the infrastructure being in place.

### Solution
Implement `_real_loop()` using `kiteconnect.KiteTicker`:

```python
def _real_loop(self):
    ticker = KiteTicker(self.api_key, self.access_token)
    ticker.on_ticks = self._on_ticks
    ticker.on_connect = self._on_connect
    ticker.on_close = self._on_close
    ticker.connect(threaded=True)
    ticker.subscribe(self.instrument_tokens)
    ticker.set_mode(ticker.MODE_FULL, self.instrument_tokens)
```

Also implement real order placement in the Zerodha execution broker (currently mock-only).

### Prerequisites
- Valid Zerodha developer account
- Access token refresh flow (daily token expiry is a known Zerodha limitation)
- Instrument token mapping (symbol → Zerodha token ID)

---

## 5. Macro Factor Signal Wiring

**File:** `backend/app/services/macro_factors.py`
**Status:** PCA on macro data implemented but agents don't consume output

### Problem
432 lines of macro factor code runs but the signals it produces are not used in strategy agent decision-making. The macro regime information is silently discarded.

### Solution
1. Have the macro factors service publish a `MacroRegimeSignal` to the message bus on each update cycle.
2. Strategy agents (momentum, mean reversion, volatility) subscribe to this signal and use it as a conditioning variable — e.g., suppress mean-reversion signals in high-macro-stress regimes.
3. Add macro regime to the TUI dashboard status panel.

---

## 6. Strategy Plugin System

**Files:** `backend/app/agents/front_office/strategy/`

### Problem
Adding a new strategy requires modifying core agent code. There's no way for a user to add custom strategies without touching internals.

### Solution
Define a `BaseStrategy` protocol/ABC:

```python
class BaseStrategy(Protocol):
    name: str
    def generate_signal(self, features: FeatureSet, regime: RegimeState) -> Signal | None: ...
    def on_fill(self, fill: Fill) -> None: ...
```

Load strategies from a `strategies/` directory at startup. Existing strategies (momentum, mean reversion, etc.) become the default plugins. Users can drop a new `.py` file into `strategies/` and it's auto-registered.

---

## 7. ML Training Automation

**Directory:** `ml_training/`
**Status:** Training scripts exist but pipeline is manual

### Problem
ML models (regime detection, sentiment, volatility) are trained once and never updated. As market regimes shift, stale models degrade silently.

### Solution
1. Add a scheduled `ModelTrainingJob` that runs weekly (or on data volume triggers).
2. On completion, register the new model version via `ModelRegistry`.
3. Use Thompson Sampling (already implemented in `ModelRegistry`) to gradually shift traffic to the new model if it outperforms.
4. Alert if a model's out-of-sample accuracy drops below a threshold.

---

## 8. Crypto Execution Broker

**Files:** `backend/app/data/feeds/coingecko_feed.py`, `backend/app/brokers/`

### Problem
CoinGecko provides crypto price data but there's no crypto execution broker. Crypto trading signals are generated but cannot be acted upon.

### Solution
Add a `BinanceBroker` or `CoinbaseBroker` implementation matching the existing broker interface. At minimum, add a `PaperCryptoBroker` that simulates fills using CoinGecko prices — this requires no API keys and enables full end-to-end crypto paper trading.

---

## 9. Debate Audit Trail

**Files:** `backend/app/services/debate_engine.py`, order/signal tables

### Problem
Debates are stored in the DB but there's no link between "which debate influenced which trade." Post-hoc analysis of decision quality is not possible.

### Solution
1. Add `debate_id` (nullable foreign key) to the `signals` and `orders` tables.
2. When a debate concludes and produces a consensus, tag the resulting signal with that `debate_id`.
3. Add a `debate history <debate_id>` REPL command to show the full argument chain that led to a given trade.

---

## 10. Live Alert Dashboard Panel

**File:** `backend/app/tui/dashboard.py`

### Problem
Alerts fire to console/Telegram but don't appear in the live TUI dashboard. The operator has no at-a-glance view of recent alerts during a session.

### Solution
Add a scrolling "Recent Alerts" Rich panel to the dashboard layout showing the last 10 alerts with severity color-coding (INFO=blue, WARNING=yellow, CRITICAL=red). Subscribe to the alert message bus topic and push to a `deque`.

---

## 11. REPL Autocomplete

**File:** `backend/app/tui/commands.py`

### Problem
30+ commands with no tab completion. Users must remember exact command names and argument syntax.

### Solution
Use `prompt_toolkit` (likely already a transitive dependency via Rich) to add:
- Tab completion for command names
- Argument completion for known values (e.g., `status <agent_name>` completes agent names)
- Command history with up-arrow navigation (if not already working)

---

## 12. Backtest Persistence and Comparison

**Files:** `backend/app/tui/commands.py`, `backend/app/db/local_storage.py`

### Problem
Backtest results are printed to the terminal and lost. There's no way to track whether a strategy improved or degraded over time.

### Solution
1. Add a `backtest_runs` table to SQLite storing: strategy name, date range, parameters, Sharpe, CAGR, max drawdown, alpha, run timestamp.
2. Auto-save every backtest run.
3. Add REPL commands:
   - `backtest list` — show all saved runs
   - `backtest compare <id1> <id2>` — side-by-side metric comparison
   - `backtest best` — rank runs by Sharpe ratio

---

## 13. Signal Confidence / Direction Split

**Files:** `backend/app/models/signals.py`, all strategy agents

### Problem
If signal confidence and direction are encoded together (e.g., a single float from -1.0 to +1.0), it conflates two distinct concepts. A weak bullish signal and a strong bearish signal need different risk treatment.

### Solution
Split the signal model into explicit fields:

```python
class Signal:
    direction: Literal["LONG", "SHORT", "FLAT"]
    confidence: float          # 0.0–1.0
    conviction: Literal["LOW", "MEDIUM", "HIGH"]
    regime_aligned: bool       # does this signal agree with macro regime?
```

Use `confidence` for position sizing (higher confidence → larger position) and `regime_aligned` for filtering (suppress signals that fight the macro trend).

---

## 14. Walk-Forward Backtest Validation

**Files:** `backend/app/services/` (backtesting logic)

### Problem
If the backtester uses a single in-sample / out-of-sample split, strategies may be inadvertently overfit to a particular historical period. Results can look excellent but fail to generalize.

### Solution
Implement walk-forward validation:
1. Divide the historical period into N folds (e.g., 12 monthly folds).
2. For each fold: train on prior folds, test on the current fold.
3. Report out-of-sample metrics for each fold + aggregated statistics.
4. Flag strategies with high variance across folds as potentially overfit.

This gives a much more honest picture of expected live performance.

---

## Quick Wins Summary

If time is limited, these three changes deliver the most value for the least effort:

1. **Fix alpha calculations** (#1 + #2) — unblocks real performance measurement
2. **Backtest persistence** (#12) — immediate quality-of-life for strategy development
3. **Debate audit trail** (#9) — closes the decision provenance loop with minimal schema changes
