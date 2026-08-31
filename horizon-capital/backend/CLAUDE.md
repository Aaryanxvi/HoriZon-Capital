# Horizon Capital — Backend

Autonomous AI hedge-fund platform modeled as a firm org chart. **Primary product is the desktop terminal agent** (Rich TUI + REPL via `python -m app`). The Electron desktop app is a second front end onto the *same* engine — same agents, same commands (see "Desktop app" below).

## Quick Start

```bash
cd backend
python -m app              # Start terminal agent (TUI + agents + workers)
python -m app --headless   # Agents only (log output)
python -m app config       # Show configuration (secrets masked)
python -m app --setup      # Onboarding wizard
python -m app --reset      # Wipe LOCAL SQLite state (~/.horizon-capital)
```

Entry point: `horizon = app.__main__:main` (pyproject). FastAPI dev server: `uvicorn app.main:app` on :8000.

## Architecture

```
app/
├── __main__.py     # CLI entry: builds bus → orchestrator → workers → TUI/headless. Owns orchestration (NOT runtime.py)
├── main.py         # FastAPI app (web/desktop API), serves frontend/dist if present
├── config.py       # Pydantic-settings Settings singleton; .env; auto-gen secrets; per-dept AI routing
├── dependencies.py # FastAPI get_current_user (LOCAL bypasses auth)
├── agents/         # Org chart — agents are decoupled, coordinate ONLY via pub/sub bus
│   ├── base_agent.py        # BaseAgent: register → subscribe → heartbeat(10s) → run(); emit() publishes + persists
│   ├── departments.py       # DepartmentType: front/middle/back_office, executive
│   ├── department_manager.py, agent_registry.py, agent_bus.py
│   ├── executive/cio/       # CIOAgent (cio-agent-1): advisory(15min) / crisis / override modes. HumanCIO = chat helper
│   ├── front_office/
│   │   ├── strategy/        # StrategyAgent (signal source, 60s) + sleeves/ (see below)
│   │   ├── portfolio/       # PortfolioAgent: sizing, NAV, the debate gate, heavy idempotency
│   │   ├── trading/         # ExecutionAgent + paper_broker.py (Almgren-Chriss impact), alpaca_broker.py
│   │   ├── investor_relations/  # IRAgent (hourly reports)
│   │   └── research/        # SentimentAgent (plain class, launched in __main__), finbert/reddit/newsapi helpers
│   ├── middle_office/
│   │   ├── risk/            # RiskAgent: pre-trade gate + 30s VaR/CVaR/drawdown + kill switch. var_calculator.py
│   │   ├── compliance/      # ComplianceAgent (restricted symbols, concentration)
│   │   ├── operations/      # OperationsAgent (stuck-order detection)
│   │   ├── debate_agent.py  # DebateAgent: runs MultiModelDebateEngine or auto-approve
│   │   └── alpha_monitor.py # AlphaMonitorAgent (rolling Sharpe/win-rate decay alerts)
│   ├── back_office/         # AccountingAgent (NAV/P&L), ITAgent (psutil health), QuantAgent (feature freshness)
│   └── debate/              # DebateEngine (single-reasoner), MultiModelDebateEngine (per-role LLM + Round-2 rotation)
├── core/
│   ├── runtime.py       # get_bus(), get_session_factory(), startup/shutdown — backend switch points only
│   ├── messaging.py     # MessageType StrEnum, AgentMessage, AgentBus (Redis pub/sub, POSTGRES only)
│   ├── memory_bus.py    # MemoryBus: asyncio.Queue + fnmatch glob channels (LOCAL)
│   ├── kv_store.py      # MemoryKVStore + PersistentKVStore (whitelist persisted to SQLite); get_kv_store()
│   ├── cash.py          # DB-backed cash (cash_balances = source of truth, KV mirrors)
│   ├── local_storage.py # SQLite (aiosqlite, WAL) at ~/.horizon-capital/horizon.db; ~30 tables; non-destructive _migrate_table
│   ├── database.py / redis_client.py   # POSTGRES infra (lazy-imported)
│   ├── security.py      # JWT (python-jose) + bcrypt directly (passlib dropped for py3.14)
│   ├── rate_limiter.py  # token-bucket RateLimiter
│   ├── resilience.py    # retry_with_backoff ONLY (no CircuitBreaker/with_timeout despite old docs)
│   └── exceptions.py, logging.py
├── llm/             # base_provider + claude/openai/gemini providers; provider_registry (per-dept + per-agent routing)
│                    #   agent_config.py (15 roles), agent_model_overrides.py (persisted json), models_registry.py
├── quant/           # Research-grade primitives: hrp, kelly, quality(QMJ), regime_hmm(GaussianMixture),
│                    #   metrics_advanced(Probabilistic/Deflated Sharpe), llm_sentiment
├── features/        # technical.py (23 indicators via `ta`), volatility.py (GARCH), sentiment_features, feature_store
├── backtesting/     # backtest_engine (event-driven bar replay), backtest_broker (slippage+impact), metrics, trade_journal, report_exporter
├── workers/
│   ├── agent_orchestrator.py        # Supervisor: agents + workers, heartbeat auto-restart
│   ├── data_ingestion_worker.py     # Yahoo EOD 30s + CoinGecko 60s; 5y backfill if ohlcv empty
│   ├── performance_worker.py        # 900s; Sharpe/Sortino/Calmar + Jensen's alpha vs ^NSEI/^GSPC
│   └── position_worker.py           # 30s mark-to-market + stop-loss enforcement (does NOT write NAV)
├── services/        # alert_manager, health_monitor, report_generator, performance, backup
│                    #   (NOTE: stress_testing.py and model_registry.py do NOT exist)
├── tui/             # dashboard.py (Rich Live 3-col, 2fps), commands.py (REPL), pixel_agents.py (ASCII office),
│                    #   cio_chat.py, onboarding.py, settings_panel.py
├── data_layer/      # data_manager + yahoo_feed, alpaca_feed/quotes, crypto_feed (CoinGecko). zerodha/forex/polygon NOT present
├── models/          # SQLAlchemy ORM (POSTGRES path)
├── schemas/         # Pydantic DTOs
└── api/v1/          # 11 FastAPI routers under /api/v1 (built for POSTGRES path) + websocket.py /ws/dashboard
```

## Storage Modes

| Mode | DB | Bus | KV | Auth | Requirements |
|------|----|----|----|------|-------------|
| **LOCAL** (default) | SQLite `~/.horizon-capital/horizon.db`, raw-SQL ~30 tables | MemoryBus | PersistentKVStore | bypassed | Zero infra |
| POSTGRES | Postgres (asyncpg, ORM, Alembic 19-table schema) | Redis pub/sub | Redis | JWT | Docker |

Backend chosen by `settings.storage_backend`. `runtime.get_bus()` / `get_session_factory()` are the single switch points; Redis/asyncpg imported lazily so LOCAL has zero external deps. **Two DB schemas exist** (Alembic Postgres vs `local_storage.py` SQLite) and can drift.

## Trade Pipeline & Debate Gate

```
StrategyAgent --SIGNAL--> RiskAgent (pre-trade limits) --> horizon.risk.approved.*
   --> PortfolioAgent (sizing) + DebateAgent (LLM consensus)
   --> PortfolioAgent --ORDER_NEW--> ExecutionAgent (kill-switch/cash/naked-short guards) --ORDER_FILL--> PaperBroker
```

Trading modes (read in `PortfolioAgent._handle_signal`):
- **PAPER_TRADING** (default) — signals sized & emitted immediately; debate auto-approves.
- **HUMAN_APPROVAL** — orders go to `horizon.execution.order.pending`; human runs REPL `approve`/`reject`.
- **FULLY_AUTONOMOUS** — debate gate: PortfolioAgent buffers signals, releases order only on `DEBATE_CONCLUSION` APPROVED. DebateAgent refuses to auto-approve without an LLM here (emits REJECTED).

Three nested gates: RiskAgent → DebateAgent (binding only in FULLY_AUTONOMOUS) → ExecutionAgent. CIOAgent sits above as crisis/override authority; AgentOrchestrator keeps everything alive.

## Strategy Sleeves (`agents/front_office/strategy/sleeves/`)

`BaseSleeve.compute(bars, as_of) -> [SleeveSignal]`, fixed portfolio weight + rebalance cadence. StrategyAgent aggregates target weights, emits SIGNAL only on >50bps drift.
- **ResearchStackSleeve** — 60%, weekly. Dominant alpha: GMM/HMM regime gate on SPY; RISK_OFF→inverse-vol TLT/GLD; RISK_ON→12-1 TSMOM + QMJ quality, top-5, HRP weights × Half-Kelly caps. Uses `quant/`.
- **TrendFilterSleeve** — 20%, weekly. Faber 200d-SMA + 20d vol cap, long-or-cash.
- **GapFadeSleeve** — 10%, daily. Buy QQQ on overnight gap-down ≥0.3%, exit at close.
- **MomentumRankSleeve** — 10%, monthly. 12-1 cross-sectional momentum, top-3.

Optional, UNVALIDATED, default-off (REPL `sleeve on <name>`):
- **CryptoTrendSleeve** — Faber 200d SMA + vol damper. Universe is BTC/ETH, or top-N
  by market cap with `CRYPTO_DISCOVERY_ENABLED` (`crypto auto on N`) — stablecoins and
  wrapped/staked derivatives excluded, intersected with broker-tradable assets and with
  what the bar source can price (`data_layer/crypto_universe.py`).
- **PolymarketMomentumSleeve** — 7d probability momentum, tails filtered. Markets come from
  `POLYMARKET_MARKETS` plus, with `POLYMARKET_DISCOVERY_ENABLED` (`pm auto on N`), an hourly
  Gamma sweep of the most-traded open markets (`data_layer/polymarket_feed.refresh_discovery`).
  Real orders additionally need `POLYMARKET_REAL_TRADING` + wallet key + funder + py-clob-client;
  without them `.POLY` routes to PaperBroker.

(`base_strategy.py`, `momentum_strategy.py`, `mean_reversion_strategy.py`, `simple_strategies.py` are older standalone primitives, NOT wired into the sleeve agent.)

## Desktop app

One process: SQLite/KV storage + agents + workers + API + the built React UI.
`desktop_entry.py` picks a free port, sets `HORIZON_RUN_AGENTS=1`, and prints
`READY:<port>` once uvicorn is actually listening (Electron waits for that line).

- `main.py` lifespan starts the org chart in-process **only** when `HORIZON_RUN_AGENTS=1`,
  so plain `uvicorn app.main:app` is unchanged. It also attaches a `TerminalDashboard`
  via `tui/dashboard_feed.py` — REPL commands (`portfolio`, `signals`, `risk`) read
  dashboard state, so without it the desktop terminal would answer differently.
- `tui/dashboard_feed.py` — bus→dashboard routing + initial DB/KV load, **shared** with
  `__main__._run_with_tui` so the two front ends cannot drift.
- `api/desktop.py` (`/api/desktop/*`) — LOCAL-native reads (raw SQL + KV, no ORM/asyncpg),
  controls, and the REPL bridge:
  - reads: `overview, positions, equity-curve, orders, fills, pending, signals, agents,
    debates[/{id}], risk, performance, alerts, watchlist, config, onboarding`
  - controls: `POST control/halt` (sets `horizon:system:halted` + kill switch),
    `POST control/settings` (allow-listed env keys, coerced through the pydantic field
    type, written with `settings_panel._write_env_key`, mirrored onto live `settings`),
    `POST control/engine` (start/stop/restart agents)
  - REPL: `POST command` and `WS ws/terminal` run `CommandHandler` and return Rich output
    rendered to text **and** HTML (`render_markup`; `export_text(clear=False)` — clearing
    empties the HTML export). `dashboard`/`settings`/`quit` map to app screens.
  - `WS ws/live` fans the bus out to the UI through one process-wide subscription
    (`MemoryBus.unsubscribe` drops *all* handlers on a channel, so per-client subscribe
    would let one disconnect silence everyone).
- `api/v1` mounts **only** in POSTGRES mode — it imports asyncpg and the ORM.
- Electron (`desktop/`): frameless window + custom titlebar, tray, single-instance lock,
  window-state persistence, `sandbox: true`, external links opened in the browser,
  backend spawned via the `py -3.14`/`python3` launcher probe and killed with
  `taskkill /T` on Windows. `make_icon.py` regenerates `icons/icon.ico`.

## MessageType (`core/messaging.py`)

`TICK, OHLCV, FEATURE_UPDATE, SIGNAL, RISK_CHECK, RISK_ALERT, DEBATE_START, DEBATE_VOTE, DEBATE_CONCLUSION, ORDER_NEW, ORDER_FILL, ORDER_CANCEL, PORTFOLIO_UPDATE, HEALTH_CHECK, SENTIMENT_UPDATE, AGENT_STATUS, HEARTBEAT, SETTINGS_UPDATED, CIO_ADVISORY, CIO_OVERRIDE`. Channels are dot-namespaced `horizon.<area>.<sub>`, wildcard subscriptions.

## Key Design Decisions

- **Lazy imports** — Redis/asyncpg only in POSTGRES mode; LOCAL needs zero external deps.
- **No singletons** — `runtime.get_bus()` returns MemoryBus or AgentBus.
- **`X | None`** not `Optional[X]` (UP007); **`StrEnum`** for all enums.
- **`ta`** pure-Python lib (not `ta-lib` C library).
- **Worker + agent supervision** — orchestrator heartbeat-restarts crashed tasks.
- **DB-backed cash** is source of truth; KV is a mirror. NAV owned solely by PortfolioAgent.

## REPL Commands (`tui/commands.py`)

help, status, portfolio, positions, orders, signals, backtest (+ results/list/compare), risk, sentiment, debate (+ why), agents, health, performance, config, approve, reject, pending, trades, pnl, cio, watchlist, buy, sell, strategy, dashboard, settings, model/models (list/agents/set/clear), sleeve (on/off/weight),
pm (add/remove/auto/scan), crypto (auto/scan), quit/exit. Tab completion via readline in `__main__.py`. (No `stress-test`/`alerts`/`report` commands.)

## LLM Routing (`llm/`)

Per-department setting `ai_<dept>` = auto|claude|openai|gemini|none; per-agent overrides persisted to `~/.horizon-capital/agent_overrides.json`. Agent resolves provider via `provider_registry.get_provider_for_agent()` then `provider.complete(system, messages, temp)`. No keys → LLM roles degrade (debates auto-approve). Defaults: Claude `claude-sonnet-4-20250514`, OpenAI `gpt-4o`, Gemini `gemini-2.0-flash`.

## Testing

```bash
python run_tests.py                  # root: sets LOCAL/PAPER env, runs backend/tests/test_smoke.py
python -m pytest tests/ -v           # 48 files in backend/tests/ (asyncio_mode=auto)
```
Two test trees: `backend/tests/` (48 files: smoke, integration, e2e, 9 CIO, feeds, strategy, desktop API) and root `tests/unit/` (3 files: drift, features, VaR). `pyproject` `testpaths=["../tests"]`. Known: several tests assert factory defaults and fail against a configured developer `.env` (`test_cio_mode_default` with CIO_MODE=AI; the sleeve-mix tests with CRYPTO/POLYMARKET_SLEEVE_ENABLED=true); hmmlearn won't build on py3.14 (handled gracefully); redis-dependent smoke test skips when redis absent.

## Linting

```bash
python -m ruff check app/        # 0 errors target
```
`pyproject.toml`: line-length=100, target=py311, select=E,F,I,N,W,UP. Mypy strict (pydantic + sqlalchemy plugins).

## Environment Variables (`.env`, see `../.env.example`)

`STORAGE_BACKEND` (LOCAL), `SYSTEM_MODE` (PAPER_TRADING|HUMAN_APPROVAL|FULLY_AUTONOMOUS), `CIO_MODE` (HUMAN|AI), `ANTHROPIC/OPENAI/GOOGLE_API_KEY`, `ALPACA/ZERODHA_API_KEY+SECRET`, `AI_FRONT/MIDDLE/BACK_OFFICE` + `AI_EXECUTIVE`, `INITIAL_CAPITAL_USD/INR`, risk defaults (max DD 10%, pos 5%, VaR 3%, daily loss 5%, `RISK_FREE_RATE`), `CORS_ORIGINS`, Telegram/SMTP alerts. Secrets (APP_SECRET_KEY, JWT_SECRET_KEY, CIO_DEFAULT_PASSWORD, POSTGRES_PASSWORD) auto-generate via `secrets.token_hex(32)` when blank or "changeme".

## Version

v0.2.0 — Python >=3.11, runs on Python 3.14.
