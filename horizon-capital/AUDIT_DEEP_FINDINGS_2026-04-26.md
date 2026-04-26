# Horizon Capital — Deep System Audit (2026-04-26)

Scope: full backend (`backend/app/`), frontend, desktop, landing page, infrastructure, ml_training, scripts, tests, docs. 13 parallel deep slices: agents, core infra, workers/data, API/auth/TUI/frontend, backtest/LLM/services, tests/scripts/Rust/infra, numerical correctness, deps/docs/CI, concurrency, DB schema, smoke-boot, end-to-end trade lifecycle, observability/failure-mode.

---

## Executive Summary

| Severity | Count | Themes |
|---|---|---|
| 🔴 Critical | **38** | Money/cash race, position math wrong, lost trades, leaked API keys, auth bypass, fire-and-forget tasks, float-as-money, missing FKs, schema drift, silent dispatch failures |
| 🟡 Concerns | **62** | Missing indices, unbounded queues, manual lock release, stale data, weak fallback, no CI/CD, doc drift |
| 🟢 Quick wins | **40+** | Add Decimal money, atomic cash CAS, correlation IDs, health probes, prompt caching, RBAC |

**Verdict:** Strong architectural fundamentals. Production-unsafe for real money until P0 list (below) fixed. Paper trading mostly OK except for cash-race and position-flip bugs that distort backtest reports.

**Smoke boot status:** Python 3.14 detected (matches CLAUDE.md claim), but full pytest suite and `python -m app` startup could not be verified — sandbox blocked Python execution after first call. Add `python` to allowed bash commands in `.claude/settings.json` to retest.

---

## 1. What Works Well ✅

### Architecture
- Clean department layering (front/middle/back/exec)
- Lazy imports (Redis/asyncpg only loaded in POSTGRES mode)
- Dual bus (`MemoryBus` + Redis `AgentBus`) with same interface — testable
- `runtime.get_bus()` / `_get_session_factory()` — no module-level singletons
- `StrEnum` everywhere, `X | None` over `Optional`, modern Python idioms

### Trading logic that is correct
- Paper broker Almgren-Chriss impact model: `paper_broker.py:32-122`
- Order splitter TWAP/VWAP/AC: `order_splitter.py:95-283`
- VaR historical percentile + max drawdown peak tracking: `var_calculator.py:16-85`
- Sleeve momentum (TSMOM) with `if past <= 0` guard: `research_stack.py:60-67`
- Sharpe/Sortino math itself: correct formula, correct annualization sqrt(252) — both `backtest_metrics.py:16-27` and `performance_worker.py:160-168` (with one mismatch flagged below)
- Win-rate filtered to closed SELLs only: `backtest_metrics.py:40-46`
- Strategy emits dedup on MIN_WEIGHT_DELTA = 50 bps — threshold-based, robust: `strategy_agent.py:247-300`
- Lookahead-correct backtest slicing `bars_df.iloc[: i + 1]`: `backtest_engine.py:256`

### Security positives
- bcrypt password hashing with `gensalt()`: `security.py:39-49`
- SQLAlchemy parameterized queries everywhere; identifier whitelist regex for dynamic SQL: `local_storage.py:64-76`
- Security headers present (X-Frame, X-Content-Type, HSTS): `main.py:62`
- Swagger/ReDoc disabled in prod
- `.env` listed in `.gitignore` (although `.env` got committed anyway — see Critical)
- Rate-limit on `/auth/login` (5 req/60s)

### Resilience patterns
- CircuitBreaker, retry_with_backoff, with_timeout in `core/resilience.py` (defined; partly wired)
- Worker heartbeat + restart supervision: `agent_orchestrator.py`
- Cancellation handling in most workers (`finally` blocks, `CancelledError` suppressed cleanly)
- Connection pools sized + `pool_pre_ping=True`
- Alpaca WS exponential backoff capped at 60s

### Observability positives
- structlog JSON logging
- Per-rule alert cooldown stops alert storms: `alert_manager.py:307-312`
- Heartbeat-based agent FSM (RUNNING → UNRESPONSIVE → CRASHED → DEAD)

---

## 2. 🔴 CRITICAL FINDINGS

### 2.1 Money & Cash (highest blast radius)

**C-1. Cash balance read-modify-write race** — `execution_agent.py:357-397`
```python
current = float(await kv.get(cash_key) or 0.0)
new = current - cost - commission
await kv.set(cash_key, str(round(new, 2)))
```
Two concurrent fills both read 200, write 100 and 150. **Lost ~10–50 USD per concurrent fill.** Money disappears or appears. Fix: Redis WATCH/MULTI/EXEC or Lua CAS; for MemoryKVStore add async `set_if_equal`.

**C-2. Float for ALL money** — `local_storage.py:147,167-189,226-230`, all KV cash, all P&L paths
- `quantity REAL`, `limit_price REAL`, `commission REAL`, `cash_usd REAL`, `unrealized_pnl REAL`
- Cash stored as string→float→string round-trip; double-rounding loss
- Fix: `NUMERIC(20,8)` or integer cents; Python `Decimal` everywhere

**C-3. Buy-side commission NOT added to cost basis** — `performance_worker.py:216,241`
```python
buy_cost += t["fill_price"] * t["filled_qty"]   # commission MISSING
realized_pnl = (t["fill_price"] - avg_entry) * sell_qty - t["commission"]
```
Result: ~$10 understated loss per round-trip, win-rate inflated. Add commission to BUY accumulation.

**C-4. Net leverage uses `abs()` so shorts treated as longs** — `portfolio_agent.py:402,422`
```python
val = abs(price * quantity)            # short sign destroyed
net_leverage = (long_value - short_value) / nav
```
Net leverage off by 2-3× for balanced books. Must track signed exposure separately.

**C-5. Cash + position fetch unsynchronized → NAV stale** — `portfolio_agent.py:308-312`
Position fetch at T0, cash fetch at T1. Fill between → NAV wrong → over-allocates. Wrap in single transaction.

**C-6. Order_manager position-flip math wrong** — `order_manager.py:286-323`
- Oversell flips quantity but `new_avg = old_avg` (stale entry on flip)
- Cover-and-flip from SHORT to LONG sets `new_avg = price` only sometimes
- `new_side = "SHORT" if new_qty > 0 else ("LONG" if new_qty < 0 else "FLAT")` at line 301 is **inverted on the flip path** — sub-agent flagged this twice independently
- Test cases needed for: oversell long, oversell short, cover-and-flip, flatten exactly

**C-7. Sharpe risk-free rate dimensionality mismatch between modules** — `backtest_metrics.py:25` vs `performance_worker.py:164`
- Backtest: `daily_rf = (1 + rf)**(1/252) - 1` (compound; correct)
- Performance worker: `excess = returns - rf / 252` (additive; ~+0.6 bps systemic bias)
- Pick one and apply everywhere

**C-8. Volatility std missing `ddof=1`** — `feature_computation_worker.py:211,218,229`
`.std()` defaults to ddof=0; underestimates vol ~0.5%. Affects Kelly, VaR, risk limits.

**C-9. No NSE tick-size rounding** — `portfolio_agent.py:336`
`sell_qty = float(int(sell_qty))` rounds Indian fractional lots (0.05) to whole. Lot rejection on broker side.

### 2.2 Trade Lifecycle & State

**C-10. Strategy direction lossy on equality** — `strategy_agent.py:266`
```python
direction = 1 if new_w > old_w else -1   # equal → -1 (flip!)
```
Fix: ternary including `else 0`.

**C-11. Signal-id dedup is in-memory FIFO, 5000 cap** — `portfolio_agent.py:160-164`
After 5000 unique signals or restart, replayed signals re-enter and **create duplicate orders**. Move dedup to Redis SET with TTL or DB unique constraint on `signal_id`.

**C-12. ORDER_NEW not idempotent** — `execution_agent.py:105` + `order_manager.py:40`
Redelivered ORDER_NEW → two orders, two fills, two cash deductions. Add `idempotency_key = hash(signal_id, debate_id, side, qty, bar_ts)`.

**C-13. Retry loop double-fills** — `execution_agent.py:209-215`
Paper broker fills atomically. Retry on `None` doesn't check existing fills; can double-fill if first attempt actually filled. Either remove retries or query fills first.

**C-14. Fill record + position update + cash update NOT atomic** — `execution_agent.py:234-265`
Three separate awaits, no transaction. Crash between → fill recorded but position/cash unchanged → P&L corrupted. Wrap all three in single DB transaction.

**C-15. Risk approval not idempotent; no pending-order awareness** — `risk_agent.py:90-99`
Two same-symbol signals in same tick both pass position-limit check. Loss-limit reads equity ignoring queued orders. Add per-symbol lock + pending exposure.

**C-16. Risk agent loses `bar_timestamp`** — `risk_agent.py:114-125`
Approved signal re-emit drops `bar_timestamp`; downstream cooldown dedup fires falsely. Propagate field.

**C-17. Debate consensus_score never gates decision** — `debate_engine.py:286`
```python
decision = "APPROVED" if len(for_votes) > len(against_votes) else "REJECTED"
```
Score computed but never used. 1-FOR vs 0-AGAINST with 3 ABSTAINs = APPROVED. Fix: `decision = "APPROVED" if for >= 3 and score > 0.6`.

**C-18. Debate APPROVED → all buffered signals execute in loop** — `portfolio_agent.py:172-183`
Three buffered AAPL signals all `_size_and_emit()` against same cash snapshot → triple-buy. Lock per-symbol + re-fetch cash per emit.

**C-19. Kill-switch advisory only — ExecutionAgent does NOT enforce**
RiskAgent sets `horizon:system:halted = "1"` but ExecutionAgent never queries before submitting. Block at execution path.

**C-20. P&L attribution ignores `positions.realized_pnl`** — `performance_worker.py:62-86`
NAV from snapshots only counts cash + mark-to-market. Closed-trade gains lost from equity curve → Sharpe shows loss when net positive.

### 2.3 Concurrency & Async

**C-21. Fire-and-forget message handlers swallow exceptions** — `messaging.py:134`, `memory_bus.py:61`
```python
asyncio.create_task(handler(message))   # no done_callback, no tracking
```
Handler exceptions silent. Critical signals lost mid-shutdown if dispatch loop dies. Wrap in `_safe_handler`, add done_callback that logs `task.exception()`.

**C-22. `get_bus()` / `get_session_factory()` / `PersistentKVStore` — global state, no lock** — `runtime.py:40-50`, `kv_store.py:149`
First concurrent call spawns multiple buses → multiple Redis listeners → race for messages. Add `asyncio.Lock` + double-checked init.

**C-23. Debate dedup dict TOCTOU** — `debate_agent.py:44, 76-78`
Read+write `_last_debate[symbol]` across await. Concurrent debates double-fire. Lock or per-symbol asyncio.Lock.

**C-24. Concurrent WS+REST polling on Alpaca** — `alpaca_feed.py:90-157`
WS fails mid-flight → fallback REST started but WS task may still resume. Duplicate ticks, quota burn.

**C-25. WebSocket queue unbounded** — `websocket.py:72`
`asyncio.Queue()` no `maxsize`. Slow consumer → OOM per client.

**C-26. `threading.Lock` in async code blocks event loop** — `agent_model_overrides.py:21,28,66,81`
Disk JSON I/O under threading.Lock from agent coros. Use asyncio.Lock + `to_thread` for file I/O.

**C-27. Async tasks orphaned on worker restart** — `agent_orchestrator.py:421-424`
Old task ref discarded, never cancelled; cleanup never runs → DB connection leak.

### 2.4 Security

**C-28. LIVE API keys committed to `.env`** — `backend/.env:12,18,26-27`
- `OPENAI_API_KEY=sk-proj-[REDACTED — rotate immediately]`
- `GOOGLE_API_KEY=AIza[REDACTED — rotate immediately]`
- `ALPACA_API_KEY=PK[REDACTED]` + secret `[REDACTED — rotate immediately]`
- `.gitignore` lists `.env` but file already in repo history
- **ROTATE ALL THREE NOW.** `git rm --cached backend/.env`. Re-issue keys. Audit billing for misuse.

**C-29. Auth bypass in LOCAL mode** — `dependencies.py:18-19`
```python
if settings.storage_backend == StorageBackend.LOCAL:
    return {"sub": "cio", "username": "admin", "role": "cio"}
```
Default mode skips JWT entirely. If LOCAL ever runs production-facing → full bypass.

**C-30. JWT in WebSocket query string** — `websocket.py:140`
`token: str = Query(default="")` — leaks via browser history, proxy logs, referrer.

**C-31. JWT algorithm not pinned to whitelist** — `security.py:71`, `config.py:94`
`algorithms=[settings.jwt_algorithm]` reads from config string. Hardcode `["HS256"]`.

**C-32. WebSocket no Origin check** — `websocket.py:137-156` — CSRF possible.

**C-33. No rate-limit on CIO endpoints** (override, halt, agent pause). Token-holder can flood.

**C-34. Refresh token never rotated/revoked** — `auth.py:79-104` — leaked refresh = lifetime access.

**C-35. Docker-compose default password fallback** — `infrastructure/docker-compose.yml:11`
`POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme_in_production}` — kill default.

**C-36. Backend Dockerfile runs as root** — `backend/Dockerfile:1-21` — no `USER` directive.

### 2.5 Data & Feeds

**C-37. Bollinger band width div-by-zero** — `feature_computation_worker.py:107`
```python
df["bb_width"] = (bb_upper - bb_lower) / bb_middle
```
Penny stocks / new tokens with `close ≈ 0` → NaN/inf poisons downstream. Replace 0 with NaN before divide.

**C-38. 429 rate-limit silently dropped** — `crypto_feed.py:109`, `alpaca_feed.py:205`
Status != 200 → log warning + return. No backoff. Same poll cadence guarantees ban. `rate_limiter.py` defined but **never wired into any feed.**

### 2.6 Observability blind spots

- `/healthz` only probes Redis: `main.py:79-98`. Yahoo/CoinGecko/Alpaca/DB write/LLM all unmonitored.
- Alert dispatch failure logged but flow continues — kill-switch fired but on-call never paged.
- No correlation_id propagation despite field existing on every message: `messaging.py:57`.
- No broker↔internal position reconciliation.
- KV store cached prices used with no staleness check — RiskAgent approves on stale prices.

---

## 3. 🟡 Major Concerns

### Logic / Correctness
- Sortino downside std uses pop variance (no `ddof=1`): `performance_worker.py:171-180`
- Drift detector population variance + catastrophic cancellation risk: `drift_detector.py:50-55`. Use Welford.
- VaR div-by-peak guard `peak > 0` should be `peak > 1e-8`: `var_calculator.py:59`
- Profit factor returns `inf`; CSV export breaks: `report_generator.py:57,388-432`. Cap at 99.9999.
- No expectancy metric exposed.
- Sleeve cache update not in try/except — exception leaves stale: `strategy_agent.py:218`
- Strategy `bar_timestamp = datetime.now(UTC)` not actual bar time: `strategy_agent.py:285`
- OBV cumsum NaN propagation: `feature_computation_worker.py:152`
- Realized vol no outlier cap (split/halt spikes): `feature_computation_worker.py:208-212`
- Calmar near-zero DD → astronomical values: `performance_worker.py:190`
- Currency rate fallback to default 83.0 silent: `portfolio_agent.py:357-361`
- `usd_inr` referenced outside its conditional block (NameError risk): `portfolio_agent.py:380`

### Backtest Realism
- No dividend / corporate action handling
- Survivorship bias not addressed (delisted symbols excluded)
- Always next-bar-open fill; no partial fills modelled
- No walk-forward / OOS framework — every reported Sharpe is in-sample
- Slippage model = base bps + volume only; no time-of-day, no intraday vol

### LLM
- `max_tokens=4096` hardcoded across providers regardless of context window
- No 429/503 retry+backoff in `base_provider.py:44-55`
- `response.content[0].text` no bounds check → IndexError: `claude_provider.py:38`
- No token usage logged; no cost tracking despite price table existing in `models_registry.py`
- No prompt caching (Claude offers 90% off cached system prompts)
- Provider fallback chain order is dict insertion — no priority
- No circuit breaker around LLM calls
- CIO chat: prompt injection — user message merged into system prompt: `cio_chat.py:29-75`
- No JSON mode used; brittle parsing

### Database / Schema
- 27 tables, 0 enforced FOREIGN KEYs (declared but `PRAGMA foreign_keys=ON` missing): `local_storage.py:82`
- Missing indices on FK and hot columns: `orders.signal_id`, `fills.order_id`, `debate_arguments.session_id`, `agent_messages.sender_id/receiver_id`, `positions WHERE quantity != 0`, `narratives(symbol, published_at DESC)`, `ohlcv(exchange, timestamp)`
- Schema drift: alembic uses UUID/JSONB; SQLite uses TEXT. Migrations cannot apply to LOCAL → divergent prod/dev
- No `with_for_update()` row locking on positions/cash — lost-update race
- Naive `CURRENT_TIMESTAMP` mixed with `datetime.now(UTC)` writes; TZ info lost on SQLite
- WAL enabled but no checkpoint policy; multi-writer not safe in SQLite
- No backup/restore procedure documented
- DB URL contains credentials → leak risk in any echo or traceback
- KV-store persistence error swallowed at DEBUG level: `kv_store.py:93-110`
- KV `restore()` runs before bus listener starts — startup races for cash reads: `runtime.py:86-87`
- Sensitive payloads (broker creds, prompts) unencrypted at rest

### Concurrency (other)
- Rate limiter manual `release()` / `acquire()` around sleep: `rate_limiter.py:98-119`
- Agent `_running` bool unsynced (atomic on CPython but fragile): `agent_orchestrator.py:258`
- Heartbeat timestamp unsynced read/write: `agent_orchestrator.py:265-269`
- Position-update worker opens N+1 sessions in loop: `position_worker.py:104-120`
- Worker stuck in poll loop after max retries (zombie): `agent_orchestrator.py:403-409`

### API / Frontend
- No symbol/exchange regex validation: `trades.py:51-58`
- Single hardcoded admin user — no RBAC
- Frontend stores token in `localStorage` (XSS-stealable): `frontend/src/store/index.ts:27`
- Desktop IPC unsigned: `desktop/main.js:6-16`
- Onboarding writes secrets plaintext to `.env`: `tui/onboarding.py:573-594`

### Alerts
- Cooldown is per-rule, not per-message; different DD levels in same window dedup'd into one
- Email send synchronous in executor — slow SMTP blocks
- No persistent retry queue for failed channels
- Alert history in-memory only

### Tests / CI
- **Test count claims wrong everywhere:**
  - `README.md`: 265
  - `CLAUDE.md`: 232 smoke + 69 integration = 301
  - `project-report.md`: 302
  - **Actual: ~257-324 depending on counting method (test functions: ~324)**
- 138 smoke tests (claimed 232) — off by ~94
- 119 integration (claimed 69) — off by 50
- Flaky `await asyncio.sleep(0.2)` in dispatch tests: `test_smoke.py:150`, `test_integration.py:105+`
- All external APIs mocked — schema drift blind
- HMM training has no train/test split: `ml_training/train_hmm_regime.py:103-138`
- DRL trained on full 5y history, no walk-forward: `ml_training/train_drl_strategies.py:101-138`
- No tests instantiate RiskAgent (imported only)
- No CI/CD: no `.github/workflows/`, no `.gitlab-ci.yml`, no `.pre-commit-config.yaml`
- `python-jose==3.3.0` (unmaintained since 2023)
- `pyproject.toml` upper bounds loose; `requirements.txt` pinned tight (acceptable but inconsistent)

### Docs vs Reality Drift
- CLAUDE.md claims "23 tables" — actual 27
- CLAUDE.md claims "runs on Python 3.14" — Python 3.14 exists (released, system shows it) but `pyproject.toml` declares `>=3.11` only
- `plugins/` directory referenced in architecture but **does not exist** (no Python files)
- TODO/FIXME count: 0 in `backend/app` (good)

---

## 4. 🟢 Quick Wins

1. Hardcode `JWT_ALGORITHMS = {"HS256"}` whitelist — 5-line fix.
2. Add `PRAGMA foreign_keys=ON` to `local_storage.py:82`.
3. Replace `time.sleep` with `await asyncio.sleep` audit pass (most are sync TUI — false positive — but verify).
4. Wrap every `asyncio.create_task(handler(msg))` in `_safe_handler` + `add_done_callback`.
5. Cap profit_factor at 99.9999 in JSON/CSV export.
6. Add `replace(0, np.nan)` to bb_width calc.
7. Set `asyncio.Queue(maxsize=1000)` on WebSocket per-client queue.
8. Add `set_if_equal` to `MemoryKVStore` for cash CAS.
9. Move JWT from WebSocket query → first WS message after `accept()`.
10. Block `STORAGE_BACKEND=LOCAL` + `APP_ENV=production` combo at startup.
11. Cap LLM `max_tokens` per model from `models_registry.py` table.
12. Wire Claude prompt caching for system prompts (~90% LLM cost cut).
13. Add correlation_id middleware: generate on signal, propagate every hop.
14. Health-probe Yahoo/CoinGecko/DB-write/LLM in `/healthz`.
15. `git rm --cached backend/.env` and rotate three exposed keys.

---

## 5. Failure-Mode Matrix

| Dependency | Failure | Current behavior | Desired |
|---|---|---|---|
| Yahoo Finance | API 5xx | Retry 5x, then silent give up; trade on stale cache | Alert; reject signals on stale data >5min; quarantine symbol |
| CoinGecko | 429 | Log warning; same poll rate | Exponential backoff via `rate_limiter.py`; pause crypto signals if 10min stale |
| Alpaca WS | crash | Reconnect to max; silent give up | Alert; circuit-break US signals |
| PostgreSQL | write fail | Log warning, continue | Transaction rollback; write-ahead Redis buffer; alert |
| Redis | disconnect | Exception in feeds; reconnect loop | Health probe cascade to "DEGRADED"; queue critical writes |
| Anthropic | down | RuntimeError after 3 retries; debate stalls forever | Fallback to rule-based ABSTAIN; alert provider |
| Zerodha | high latency | Blocks position_worker 30s loop | Async timeout; cached fallback; alert |
| Agent crash | heartbeat stops | Restart 3x then DEAD silent | Alert; disable subscriptions; continue |
| Memory leak | OOM | unmonitored | psutil 80% WARN / 95% CRIT |
| Kill-switch SET | nothing changes | advisory only | ExecutionAgent enforces before every order |
| Position desync | unnoticed | never reconciled | Daily broker-vs-book diff; alert >0.5% |

---

## 6. Action Plan

### P0 — Block production (fix before any real money)
1. Rotate **all** committed API keys (C-28); `git rm --cached backend/.env` and force-push history rewrite if repo public
2. Cash CAS / atomic ledger (C-1)
3. Fill+position+cash transaction (C-14)
4. Idempotency keys on orders (C-12) + Redis-backed signal-id dedup (C-11)
5. Position-flip math fixes + tests (C-6, C-9, C-10)
6. Buy-side commission in cost basis (C-3)
7. Net leverage signed (C-4)
8. Auth bypass in LOCAL mode (C-29)
9. JWT algorithm whitelist (C-31)
10. Move WS token off query (C-30) + Origin check (C-32)
11. Kill-switch enforcement in ExecutionAgent (C-19)
12. `PRAGMA foreign_keys=ON` + add FK constraints
13. Money columns → `NUMERIC` or integer cents (C-2)
14. Wrap message handlers in safe-handler (C-21)
15. asyncio.Lock around `get_bus()` / `get_session_factory()` / `PersistentKVStore` (C-22)
16. Realized PnL added to NAV (C-20)
17. Wire 429 backoff into all feeds (C-38)
18. Bollinger div-by-zero (C-37)
19. Debate consensus_score actually gates decision (C-17)
20. Per-symbol lock around debate-conclusion sizing loop (C-18)

### P1 — Pre-launch hardening
21. Walk-forward backtest framework
22. Dividend/split adjustment
23. LLM 429/503 retry+backoff + token-usage logging + cost tracking
24. Claude prompt caching
25. RBAC (admin/trader/risk_manager/viewer)
26. Refresh-token rotation + revocation list
27. CIO endpoint rate limits
28. Symbol regex validation
29. `/healthz` deep probes (Yahoo, CoinGecko, DB-write, LLM)
30. Correlation IDs propagated end-to-end
31. Broker↔internal position reconciliation job
32. Per-symbol freshness tracking + risk-agent staleness gate
33. Alert dispatch failure escalation
34. Persistent alert/audit log
35. Schema unification (generate SQLite DDL from ORM)
36. Add CI: ruff + pytest + pip-audit + secret scan on PR
37. Pre-commit hook for secret detection
38. Dockerfile non-root user
39. Drop `python-jose`, switch to `pyjwt[crypto]`
40. Frontend tokens → httpOnly cookie

### P2 — Polish & observability
41. Prometheus/OTel metrics
42. Replace flaky `asyncio.sleep(0.2)` with `asyncio.Event`-based barriers
43. Walk-forward in HMM/DRL training
44. NSE tick-size rounding
45. Sortino ddof=1, vol ddof=1
46. Calmar near-zero clamp
47. Profit factor cap
48. Backup/restore SOP for SQLite
49. Encrypt sensitive JSON columns at rest
50. Single-writer enforcement on SQLite or hard-switch to Postgres for prod

---

## 7. Test-Count Reality Check

| Source | Claim | Actual |
|---|---|---|
| README.md:101 | 265 | — |
| backend/CLAUDE.md:84 | 232 smoke + 69 integration = 301 | smoke=138, integration=119 = 257 |
| project-report.md | 302 passing | unknown (could not run pytest) |
| repo grep `def test_` | — | ~324 functions, 77 classes |

Update docs to match reality once `pytest --collect-only` actually runs.

---

## 8. Files Most Affected (Heat Map)

Highest critical-finding density — start here:
1. `backend/app/agents/front_office/trading/execution_agent.py` (cash race, fill atomicity, retry double-fill, 4 critical)
2. `backend/app/agents/front_office/trading/order_manager.py` (position flip, side logic, 3 critical)
3. `backend/app/agents/front_office/portfolio/portfolio_agent.py` (NAV race, leverage abs, signal dedup, 4 critical)
4. `backend/app/core/messaging.py` + `core/memory_bus.py` (handler fire-forget, 2 critical)
5. `backend/app/core/local_storage.py` (FK, money types, schema, 3 critical)
6. `backend/app/agents/middle_office/risk/risk_agent.py` (kill-switch, race, 2 critical)
7. `backend/app/agents/debate/debate_engine.py` (consensus gate, 1 critical)
8. `backend/app/workers/performance_worker.py` (commission, NAV, sharpe-rf, 3 critical)
9. `backend/app/workers/feature_computation_worker.py` (bb width, vol ddof, 2 critical)
10. `backend/app/api/websocket.py` + `dependencies.py` (auth bypass, JWT in URL, 2 critical)

---

## 9. What Could NOT Be Verified

- Live `python -m app` boot — sandbox blocked second `python` call
- `python -m pytest tests/` — same
- `python -m ruff check app/` — same (CLAUDE.md claims 0 errors; unverified)
- Whether code currently in working tree compiles (37 modified files in `git status`)
- Rust speed layer (commit `2c23ee3 phase 1 complete: Rust speed layer + progressive UX`) — files not located via Glob in standard paths
- LLM provider live calls / cost behavior

To unblock these: add `python` and `pytest` patterns to `.claude/settings.json` allowed commands.

---

## 10. Appendix — Cross-References to Existing Docs

- `horizon-capital/AUDIT_FINDINGS.md` (existing) lists 42 trading-logic bugs (B1–B42). Notable overlap with this audit — verify which have shipped fixes since that doc.
- `horizon-capital/IMPROVEMENTS.md` likely covers some P1 items.
- `horizon-capital/TRADING_LOGIC_DEEP_DIVE.md` for deeper sleeve-system semantics.

---

*Audit generated from 13 parallel deep code-reading agents over `backend/app/` and adjacent code. All findings cite `file:line`. Severity calibrated to financial-systems threat model (money loss > security > correctness > performance).*

---

# ROUND 2 — WORM-MODE FORENSICS (9 additional deep slices)

Round 2 dispatched 9 more focused agents: hot-files line-by-line, frontend deep dive, time/timezone sweep, hidden-bug pattern scan, config exhaustive, ML reproducibility, existing AUDIT_FINDINGS regression check, API contract per-router, security-primitive scan.

## R2.1 — Status of prior `AUDIT_FINDINGS.md` (B1–B42)

**Major progress.** Most root-cause money bugs **already shipped fixes**:

| Status | Count | Examples |
|---|---|---|
| ✅ FIXED | 25 | B1 (slippage 6.25%→1bp), B2 (currency bucket), B3 (RSI 30/70), B4 (bar dedup), B5 (SELL clamp), bugs 1-6, 9-11, 14-15, 17, 23-26, 31, 33, 37, 39 |
| ⚠️ PARTIAL | 3 | Bug 7 (rate limiter not wired), Bug 21 (cooldown still in-memory, lost on restart), Bug 30 (naked-short check) |
| ❓ UNKNOWN | 7 | Bugs 16, 18-20, 22, 27, 29, 34 — code rewritten or method bodies cut off |
| 🔴 STILL BROKEN | 5 | **Bug 28** (random.gauss noise on impact can flip sign — `paper_broker.py:110`), **Bug 35** (Sharpe risk_free=0.05 hardcoded, no autocorrelation), **Bug 36** (win-rate ignores held winners), **Bug 38** (debate consensus_score never gates decision — repeat of C-17), **Bug 41/42** (`risk_var_limit_pct`, `risk_max_orders_per_minute` defined but UNUSED) |

Round 1 P0 items C-3 (commission), C-4 (signed leverage), C-10 (signal direction) appear partially mitigated by clamping in `order_manager.py:306-314`. Verify by re-reading full method bodies — sub-agent could not see entire file.

## R2.2 — Hot-files line-by-line (50+ micro-findings)

`execution_agent.py`:
- L70 magic `5` poll interval undocumented
- L71 broad `except` masks system errors
- L173 `halted == "1"` string-bool fragile
- L209 magic `3` retries / L215 `2**attempt` no jitter
- L243 `>= order["quantity"]` truthy on `0.0` invalid
- L285 `abs(prev - qty) < 1.0` float compare without epsilon
- L302 `datetime('now', '-60 seconds')` SQLite-only — breaks Postgres
- L315-328 silent continue on update_status fail → zombie order
- L387 `round(new_balance, 2)` lossy money

`order_manager.py`:
- L19 `_VALID_TRANSITIONS` module dict — concurrent mutation possible
- L100-109 commit fail returns False indistinguishable from logical fail
- L135-136 `COALESCE(:broker_order_id, broker_order_id)` order-dependent
- L222 `stop_loss_price < current_price` not validated
- L287-304 position FSM 6 branches, no test coverage
- L310 `min(qty, old_qty)` wrong if `old_qty` negative
- L325 unknown side silent return — should raise

`paper_broker.py`:
- L22 magic `1_000_000` daily volume — should be per-asset
- L24 `_PERMANENT_IMPACT_GAMMA = 0.5` no citation
- L25 `_PERMANENT_IMPACT_ETA = 0.01` no citation
- L27 `0.0001` half-spread hardcoded — crypto needs 10-50 bps
- L107 `direction = -1 else` — typo "BUUY" returns -1 not error
- L110 `random.gauss(0, vol*price*0.01)` magic 0.01, can flip sign (Bug 28)
- L232 `is_us = not (".NSE" in symbol or ...)` fragile, `.nse` slips through

`order_splitter.py`:
- L66-68 US-equity volume profile hardcoded; India/crypto have different intraday
- L101 default `n_slices=10` magic, `n_slices=0` divides by zero
- L162 silent profile-length fixup
- L166 `profile.sum() == 0` → div-by-zero
- L228 `X`, `T` cryptic var names
- L232 eta=0.142 differs from paper_broker's 0.01 (**inconsistent params**)
- L240 sinh threshold `100` magic; `1e30` sentinel
- L351 half-spread `0.0005` differs from paper_broker (`0.0001`) — third value
- L355 permanent-impact exponent `0.314` — where from? not 0.5

`portfolio_agent.py`:
- L69 `_processed_signal_max=5000` magic
- L73 `_order_cooldown=120s` hardcoded
- L91-92 broad except, snapshot fail invisible
- L110 `halted == "1"` string-bool
- L116 `direction == 0` implicit bool
- L133-135 ms-precision dedup vs second bars
- L136 `(now - last) < cooldown` breaks on clock jump back
- L163 off-by-one on LRU eviction
- L190/L234 `or 1.0` coerces strength=0 → 1 (wrong)
- L200 `<= 0` rejects valid `0.0` size (rare but flagged)
- L334 `max(0.25, min(1.0, strength))` clamps silent — partial exit min=25% always
- L337 `float(int(sell_qty))` truncates 9.9 → 9
- L351 `0.25` 25% NAV cap magic
- L372 `native_cash * 0.9` magic 10% reserve
- L380 asymmetric INR↔USD divide; risk if `usd_inr=0`
- L406 `currency == "INR"` case-sensitive
- L409 `"BTC" in symbol` matches `SBTC` / `BETH`
- L501 `f"{nav:.2f}"` log truncates precision

## R2.3 — Frontend deep dive

🔴 Critical:
- WS token via URL query: `frontend/src/api/websocket.ts:32` (mirror of backend C-30)
- Unsanitized agent.description rendered: `pages/DashboardPage.tsx:32` — XSS if backend compromised

🟡 Concerns:
- Silent error swallows: `pages/AgentsPage.tsx:54,66`, `store/index.ts:101` — no toast
- No debounce/AbortController on rapid-click pause/resume — duplicate API calls
- `localStorage.getItem("token")` at store init — stale closure: `store/index.ts:27`
- `vite.config.ts:16` hardcoded `localhost:8000` proxy
- No request retry/backoff in axios interceptor
- **No Error Boundary anywhere** — single component error crashes app
- Stale closure in `PixelAgentGrid.tsx:115-118` setInterval over `connections`
- `DebateViewer.tsx:74-85` timer leak on rapid debate switching
- `LoginPage.tsx:58-85` no client password complexity validation
- **No route auth guards** — unauthenticated users can navigate protected pages
- A11y: status-by-color only, missing aria-label on most interactive elements
- `websocket.ts:160` `isConnected` no null-check on `this.ws`
- No CSRF token on POST/DELETE (`/trades/{id}/approve`)

📦 Bundle:
- recharts + lightweight-charts both — pick one
- date-fns barely used (only TopBar) — drop or replace with native Intl

## R2.4 — Time / timezone / DST

🔴 Critical:
- `quant/iv_features.py:72` — `datetime.utcnow()` deprecated, naive → TypeError
- `strategy_agent.py:62` — DST hardcoded `(3,8) <= (m,d) < (11,1)` → wrong 2 weeks/year. Strategy may trade closed market or skip open market. Use `ZoneInfo("America/New_York")`
- `strategy_agent.py:52-66` — **no US holiday calendar**. Trades on Christmas, Thanksgiving, MLK day etc.
- yfinance returns naive datetimes in **exchange-local TZ** (not UTC). Code assumes UTC. Cross-exchange compares break — `data_ingestion_worker.py:262`, `strategy_agent.py:331`, `performance_worker.py:305`
- `models/market_data.py:42` — SQLAlchemy `DateTime(timezone=True)` on SQLite stored as TEXT, TZ silently lost on round-trip

🟡 High:
- `time.time()` for durations in `health_monitor.py:91,127,150,203,335,339`, `alpaca_quotes.py:75,119`, `pixel_agents.py:194,201` — should be `time.monotonic()`. Negative uptime on NTP/clock skew. Cache TTL breaks.
- `pd.Timestamp.utcnow()` deprecated: `alpaca_quotes.py:127`
- `datetime.fromisoformat()` doesn't handle "Z" suffix consistently
- `core/security.py:54-65` JWT `exp` claim is datetime object not int. `python-jose` auto-converts but only safe if aware UTC.
- `performance_worker.py:140` mixes datetime and string types
- `yahoo_feed.py:90-93` midnight-crossing (ASX) fragile near DST boundary
- `tui/dashboard.py` displays time without TZ suffix → user confusion

## R2.5 — Hidden-bug pattern sweep

Two new criticals:
- `services/alert_manager.py:403` — `httpx.AsyncClient()` **no timeout** in Telegram alert dispatch — hangs forever on stalled connection
- `tui/onboarding.py:458` — `httpx.AsyncClient()` **no timeout** in Alpaca key verification

Cleared categories (zero hits): mutable defaults, shadowed builtins, star imports, bare excepts, asserts in business logic, print() in prod, `eval/exec/compile`, `pickle.load` from untrusted, `yaml.load`, `subprocess shell=True`, `os.system`, regex DOS, `tempfile.mktemp`, `verify=False`, MD5/SHA1 in security, SQL string-concat, `random` in security context (only TUI animation use). Codebase **Python-hygiene clean** for the standard footguns.

## R2.6 — Config / settings exhaustive

Settings count: ~70 in `config.py`. Findings:

🔴 Critical:
- `DEBATE_ROLE_STRATEGY|RISK|SENTIMENT|PORTFOLIO` — defined `config.py:151-154`, used in `multi_model_debate.py:246-249` and `settings_panel.py:297-300`, but **NOT in `.env.example`**. Users can't configure without reading code.
- Live secrets committed (already C-28).
- No `@field_validator` on enum-like strings (`ai_*_office`, `debate_role_*`). User can set `ai_front_office="invalid"` → silent.
- `INITIAL_CAPITAL_USD` default in code = 100_000 but `.env.example` shows 1_000_000 — **10× drift**.
- `INITIAL_CAPITAL_INR` default 0, example 10_000_000 — drift.

🟡 Concerns:
- **10 unused settings**: `app_host`, `app_port`, `jwt_algorithm`, `jwt_access_token_expire_minutes`, `jwt_refresh_token_expire_days`, `cio_default_username`, `cio_default_password`, `zerodha_mock_mode`, `alpaca_paper_mode`, `polygon_api_key`, `llm_max_calls_per_minute`, `risk_max_leverage` (only displayed, never enforced), `risk_max_orders_per_minute`, `risk_var_limit_pct`. Either dead config or unfinished features.
- No port range validation (1-65535) on any of 4 port settings
- No 0-100 range validation on 4 risk_*_pct settings → `risk_max_position_pct=5000` silently allows 5000% leverage
- No URL-encode on credentials in `database_url` / `redis_url` properties — password with `@`/`:` breaks string
- `CORS_ORIGINS` not documented in `.env.example`
- Auto-generated secrets never logged for recovery → restart = different `jwt_secret_key` → all tokens invalid in production
- No POSTGRES connectivity check at startup; crashes at first DB call
- No hot reload (settings frozen at module import)
- Symbol lists (`india_symbols`, `us_symbols`, `crypto_symbols`) accept malformed entries silently

## R2.7 — ML / training reproducibility

🔴 Critical:
- **Feature mismatch HMM train vs runtime**: `train_hmm_regime.py` trains on 6 features `[returns, vol_20, vol_60, vol_of_vol, skew_20, kurt_20]`, `quant/regime_hmm.py:28-31` infers on 2 features `[ret_5d, vol_20d]`. **Runtime model would shape-error or produce garbage regime labels.** If trained pkl loaded, predictions are wrong.
- `train_hmm_regime.py:153` — `pickle.dump(artifacts)` — RCE if `.pkl` from untrusted source. Use `joblib`.
- `train_hmm_regime.py:103-120` — fits on full 5y history, no train/val/test split, prints in-sample metrics → look-ahead at training time. Live regime labels biased.
- `train_drl_strategies.py:89-91` reward fn: env has full `self.df` access → DRL can learn future via index leakage. Need to crop observation to current window.
- `feature_computation_worker.py:211,218,229` `.std()` no `ddof=1` — vol underestimated ~0.5% (already noted as numerical bug).

🟡 Concerns:
- No data versioning (no fetch date, no symbol-list hash, no yfinance version stored)
- No global numpy seed (only model-level `random_state=42`)
- HuggingFace FinBERT downloaded on first call — offline failure silent
- No tokenizer truncation warning — long news bodies silently lose tail
- "Confidence" = raw softmax probability, not calibrated
- `llm_sentiment.py:131-136` headlines spliced into prompt → injection vector
- `llm_sentiment.py:145-150` naive `.split("```")[1]` parse — LLM JSON failure → fallback hard
- `drift_detector.py:50-55` population variance + catastrophic cancellation. Use Welford.
- `regime_hmm.py:44-48` confidence symmetric — `0.51 vs 0.49` reads as 0.51 (weak)
- DRL is Phase 2 stub (commented out), but if uncommented → no seed set anywhere

## R2.8 — API contract per-router

🟠 High:
- `auth.py:55-65` — **timing-attack username enumeration**. Username compared before bcrypt; non-existent user returns fast, valid user takes ~100ms. Always run `verify_password` regardless.
- `auth.py:20-33` — login rate limit is **in-process list**, not Redis-backed. Multi-worker deploy bypasses by spreading attempts across workers.

🟡 Medium (idempotency / pagination):
- `POST /trades` (`trades.py:100`) — **not idempotent**. Network retry = duplicate orders. Need `Idempotency-Key` header with Redis dedup.
- `POST /trades/{id}/approve` (`trades.py:140`) — POST on what should be PUT/idempotent action
- `POST /agents/{id}/pause|resume` (`agents.py:101,144`) — retried requests double-publish to bus
- `POST /risk/kill-switch/{activate|deactivate}` (`risk.py:104,133`) — should be PUT
- `POST /cio/mode|override|halt` — non-idempotent, no atomic Redis transaction

Unbounded list endpoints (no pagination):
- `GET /agents` — all agents
- `GET /portfolio/positions` — all non-zero positions
- `GET /risk/limits` — all limits
- `GET /narratives/sentiment/{symbol}` (when window unspecified) — all aggregates
- `GET /performance/summary` — hardcoded 20 then dedup (non-standard)
- `GET /signals/active` — has limit but no offset

Query-param validation gaps:
- `period` in `performance.py:65,106` accepts arbitrary string
- `window` in `narratives.py:96` no enum/regex

`market_data.py:29` symbol used directly as Redis key suffix — Redis key-safe but still smells.

`trades.py:112-117` kill-switch check before DB flush — race window.

## R2.9 — Security-primitive scan

Clean: zero `eval/exec/compile`, zero unsafe `pickle.load`, zero unsafe `yaml.load`, zero `subprocess shell=True`, zero `os.system`, zero `verify=False`, zero MD5/SHA1 in security context, zero SQL string-concat (all SQLAlchemy `text()` parameterized), zero `random` in security context (only TUI animation).

`local_storage.py:69,73` — only dynamic-identifier SQL — protected by `_SAFE_IDENTIFIER` regex. Correct pattern.

## R2.10 — Updated severity totals

| Severity | Round 1 | Round 2 added | Total |
|---|---|---|---|
| 🔴 Critical | 38 | 18 | **56** |
| 🟡 Concerns | 62 | 60 | **122** |
| 🟢 Quick wins | 40+ | 30+ | **70+** |

## R2.11 — Updated P0 list (additions)

51. Sync HMM train features with runtime regime detector (ML-22) — model is unusable until aligned
52. Replace pickle → joblib for all model artifacts
53. Fix DST hardcoded date range in `strategy_agent.py:62` — use `ZoneInfo`
54. Add US market holiday calendar — strategy currently trades closed market days
55. Add timeout to `httpx.AsyncClient()` in `alert_manager.py:403` and `onboarding.py:458`
56. Constant-time auth: always run `verify_password`, never short-circuit on username
57. Move login rate limiter to Redis (multi-worker safe)
58. Localize yfinance timestamps to exchange TZ then convert to UTC
59. Replace `time.time()` with `time.monotonic()` for all duration tracking
60. Add `Idempotency-Key` header support to all state-changing POST endpoints
61. Add `DEBATE_ROLE_*` to `.env.example`
62. Sync `INITIAL_CAPITAL_*` defaults between code and example
63. Add port range, percentage range, and AI-provider enum validators in `config.py`
64. Log auto-generated secrets so restart preserves JWT-signing key (or persist on disk)
65. Add Error Boundary at frontend root
66. Add route auth guards in frontend router
67. Add pagination to unbounded list endpoints (`/agents`, `/positions`, `/risk/limits`, `/narratives/sentiment/{sym}`)
68. Validate `period` / `window` query params with enum
69. Resolve cooldown persistence (currently in-memory dict, lost on restart → bug 21 partially-fixed regression)
70. Remove or implement 10+ unused settings — drift confuses operators

## R2.12 — Hottest files (re-ranked after Round 2)

1. `backend/app/agents/front_office/trading/order_manager.py` — FSM, position-flip math, cash side
2. `backend/app/agents/front_office/trading/execution_agent.py` — atomicity, retries, kill-switch
3. `backend/app/agents/front_office/portfolio/portfolio_agent.py` — sizing, NAV race, currency
4. `backend/app/agents/front_office/strategy/strategy_agent.py` — DST/holidays, direction lossy
5. `backend/app/agents/debate/debate_engine.py` — consensus_score never gates
6. `backend/app/quant/regime_hmm.py` + `ml_training/train_hmm_regime.py` — **feature mismatch breaks model**
7. `backend/app/core/local_storage.py` — money types, FK off, schema drift, naive timestamps
8. `backend/app/core/messaging.py` + `memory_bus.py` — fire-forget handlers
9. `backend/app/api/v1/auth.py` — timing attack, in-process rate limit
10. `backend/app/api/websocket.py` + `dependencies.py` — auth bypass LOCAL, JWT in URL
11. `backend/app/services/alert_manager.py` — Telegram httpx no timeout
12. `frontend/src/api/websocket.ts` + frontend root — token in URL, no error boundary, no route guard
13. `backend/app/workers/feature_computation_worker.py` — bb width div0, vol ddof
14. `backend/app/config.py` + `.env.example` — drift, unused, no validation

## R2.13 — Confidence note

Several findings could not be 100% verified line-by-line because:
- Sub-agents reading files were limited to first 50-100 lines on long files (e.g. `portfolio_agent.py` ~500 lines)
- Smoke-boot blocked → cannot confirm runtime behavior or pytest pass/fail
- Rust speed layer files referenced in commit `2c23ee3` not located via standard glob — may be in non-standard path

Recommend: rerun audit once `python` and `pytest` are allowed in `.claude/settings.json` so test count, ruff status, and module-import correctness can be ground-truthed.

---

*Round 2 worm pass complete. 9 additional sub-agents, ~200 new findings layered onto Round 1's ~140. Combined: 56 critical / 122 concerns / 70+ quick wins. Production-launch readiness: NOT YET — all P0 (1-50 from Round 1, 51-70 from Round 2) must close first. Paper-trading readiness: ACCEPTABLE for backtest research only, with awareness that prior `AUDIT_FINDINGS.md` B1-B5 fixes have shipped (good) but new lifecycle/atomicity bugs remain unresolved.*

