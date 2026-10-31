<div align="center">

# 🏦 Horizon Capital

### An Autonomous, Multi-Agent AI Hedge Fund Platform for Intelligent Trading & Portfolio Management

*Front office · Middle office · Back office · Executive — consolidated into one supervised runtime.*

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-REST%20API-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-Vite%20%2B%20Tailwind-61DAFB?logo=react&logoColor=black)
![SQLite](https://img.shields.io/badge/Storage-SQLite%20%7C%20PostgreSQL%20%2B%20Redis-003B57?logo=sqlite&logoColor=white)
![LLMs](https://img.shields.io/badge/LLMs-Claude%20%7C%20GPT%20%7C%20Gemini-8A2BE2)
![Markets](https://img.shields.io/badge/Markets-Equities%20%7C%20Crypto%20%7C%20Polymarket-orange)
![Tests](https://img.shields.io/badge/tests-368%20collected-brightgreen)
![Status](https://img.shields.io/badge/mode-Paper%20Trading-blue)

</div>

---

## 📖 Table of Contents

1. [Overview](#-overview)
2. [Key Features](#-key-features)
3. [System Architecture](#-system-architecture)
4. [The 13 Agents](#-the-13-agents)
5. [Strategy Sleeves](#-strategy-sleeves)
6. [LLM Debate Engine & AI CIO](#-llm-debate-engine--ai-cio)
7. [Execution & Market Impact Model](#-execution--market-impact-model)
8. [Risk Management](#-risk-management)
9. [Operating Modes](#-operating-modes)
10. [Tech Stack](#-tech-stack)
11. [Project Structure](#-project-structure)
12. [Getting Started](#-getting-started)
13. [Configuration](#-configuration)
14. [Terminal UI & REPL Commands](#-terminal-ui--repl-commands)
15. [Web Dashboard](#-web-dashboard)
16. [Data & Persistence](#-data--persistence)
17. [Backtesting & Stress Testing](#-backtesting--stress-testing)
18. [Testing](#-testing)
19. [Results from the Demonstration Run](#-results-from-the-demonstration-run)
20. [Known Limitations & Roadmap](#-known-limitations--roadmap)
21. [Team](#-team)
22. [References](#-references)
23. [Disclaimer](#-disclaimer)

---

## 🌐 Overview

Traditional buy-side firms split their work across disconnected vendor tools: Bloomberg-style terminals for research, separate OMS/EMS systems for execution, third-party risk engines, ledger software for accounting, and BI dashboards for executives. Every cross-department decision pays a price in reconciliation, network hops and human hand-offs. Solo quants and small teams don't have this infrastructure at all, yet they face the same risk, compliance and reporting constraints.

**Horizon Capital** models an entire investment firm in software. It is a **single desktop-grade agent platform** in which thirteen autonomous agents, grouped into four departments, communicate over a publish/subscribe message bus. Together they produce signals, gate them through risk, debate them with LLMs, execute them against a realistic simulated broker, and report results, all with a full audit trail.

It runs on a laptop with **zero external infrastructure** by default (SQLite + in-memory bus), and scales to **PostgreSQL + Redis** for production-style deployments.

> Built as a B.Tech (AI & Data Science / Computer Engineering) final-year project at **K. J. Somaiya College of Engineering, Somaiya Vidyavihar University, Mumbai** (2023–27 batch).

### Problem requirements the system is designed around

| ID | Requirement | How Horizon Capital addresses it |
|----|-------------|----------------------------------|
| R1 | **Functional fidelity** | Almgren–Chriss slippage, per-exchange commissions, stale-price rejection |
| R2 | **Risk discipline** | Pre-trade gates, live VaR/CVaR, drawdown kill-switch in the same code path as live trading |
| R3 | **Multi-currency correctness** | One reconciled NAV across USD, INR and crypto baskets |
| R4 | **Reproducibility** | Runs on one laptop, fully offline by default, no containers required |
| R5 | **Auditability** | Every order, fill, risk decision and inter-agent message is persisted |
| R6 | **Operability** | Live TUI dashboard + 30+ command REPL (and web dashboard), no SQL or Python needed |

---

## ✨ Key Features

- 🤖 **13-agent hierarchy** across Front Office, Middle Office, Back Office and Executive layers
- 🧠 **Pluggable LLM registry**: Anthropic Claude, OpenAI GPT, Google Gemini, with model routing and fallback
- ⚖️ **Four-debater LLM debate engine** that gates trades in `FULLY_AUTONOMOUS` mode
- 👔 **AI Chief Investment Officer** producing strategic and crisis advisories, with halt/override authority
- 📈 **Four strategy sleeves**: HRP + Half-Kelly + GMM regime gate, Faber trend filter, gap-fade, cross-sectional momentum
- 💸 **Realistic execution**: Almgren–Chriss market impact, per-exchange commission table, clamped microstructure noise
- 🛡️ **Layered risk controls**: position cap, daily-loss limit, VaR/CVaR monitoring, 10% drawdown kill-switch
- 🌍 **Multi-asset, multi-currency**: US equities (USD), Indian equities (INR), crypto, and prediction markets
- 🧪 **Walk-forward backtesting** with Sharpe, Sortino, Calmar, Jensen's alpha vs NIFTY 50 / S&P 500
- 🌪️ **Stress testing** on historical crises (GFC 2008, COVID 2020)
- 📰 **Sentiment analysis**: keyword scorer by default, optional FinancialBERT
- 🔁 **Resilient I/O**: retry-with-backoff and per-call circuit breakers on every external dependency
- 🖥️ **Rich TUI at 2 FPS** plus a React/Vite/Tailwind web dashboard
- 🔌 **Plugin system** to add strategies, brokers and LLM providers without touching the core
- 🪄 **No-key fallback**: rule-based logic keeps the system running end-to-end with zero LLM API keys

---

## 🏗️ System Architecture

Horizon Capital is a **federation of independently-clocked agents** that communicate **exclusively through a publish/subscribe message bus**. There is no shared mutable state outside the persistence layer.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         PRESENTATION LAYER                               │
│        Rich TUI (2 FPS) + REPL   │   FastAPI REST   │   React Web UI     │
└──────────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────────────────────────────────────────────┐
│                          EXECUTIVE LAYER                                 │
│                       CIOAgent (HUMAN / AI mode)                         │
└──────────────────────────────────────────────────────────────────────────┘
                                   │
┌─────────────────────┬─────────────────────┬──────────────────────────────┐
│    FRONT OFFICE     │    MIDDLE OFFICE    │         BACK OFFICE          │
│  StrategyAgent      │  RiskAgent          │  AccountingAgent             │
│  PortfolioAgent     │  ComplianceAgent    │  QuantAgent                  │
│  ExecutionAgent     │  DebateAgent        │  ITAgent                     │
│  IRAgent            │  AlphaMonitorAgent  │                              │
│                     │  OperationsAgent    │                              │
└─────────────────────┴─────────────────────┴──────────────────────────────┘
                                   │
┌──────────────────────────────────────────────────────────────────────────┐
│          MESSAGE BUS (MemoryBus  ⇄  Redis AgentBus)  · 23 msg types      │
└──────────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────────────────────────────────────────────┐
│  WORKERS (5)  ·  SERVICES  ·  DATA LAYER  ·  FEATURE ENGINE (23 indic.)  │
└──────────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────────────────────────────────────────────┐
│     PERSISTENCE: SQLite (28 tables) / PostgreSQL  +  KV store / Redis    │
└──────────────────────────────────────────────────────────────────────────┘
```

### The signal-to-fill pipeline

```
StrategyAgent ──SIGNAL──▶ RiskAgent ──approved──▶ PortfolioAgent ──ORDER_NEW──▶ ExecutionAgent ──▶ PaperBroker
   (sleeves)             (pre-trade gate)        (target weights → size)        (guards + FSM)      (Almgren–Chriss fill)
                                                         │
                                         FULLY_AUTONOMOUS: buffered ──▶ DebateAgent ──APPROVED (≥3 of 4)──▶ order
```

### Message bus

- `MemoryBus` (LOCAL): a single `asyncio.Queue` with glob-pattern (`fnmatch`) subscriptions; each handler runs in its own task so a slow subscriber can't block dispatch.
- `AgentBus` (POSTGRES): Redis pub/sub implementing the same interface.
- Every `AgentMessage` carries a unique id, UTC timestamp, sender, optional receiver, channel (e.g. `horizon.signal.research_stack`), typed `MessageType`, an `orjson` payload and an optional `correlation_id` so a chain like *signal → risk approval → order → fill* can be reconstructed forensically.
- All routed messages are also persisted to the `agent_messages` table.

**Message types:** `TICK`, `OHLCV`, `FEATURE_UPDATE`, `SENTIMENT_UPDATE`, `SIGNAL`, `RISK_CHECK`, `RISK_ALERT`, `DEBATE_START`, `DEBATE_VOTE`, `DEBATE_CONCLUSION`, `ORDER_NEW`, `ORDER_FILL`, `ORDER_CANCEL`, `ORDER_APPROVE`, `ORDER_REJECT`, `PORTFOLIO_UPDATE`, `MACRO_REGIME_UPDATE`, `HEALTH_CHECK`, `AGENT_STATUS`, `HEARTBEAT`, `SETTINGS_UPDATED`, `CIO_ADVISORY`, `CIO_OVERRIDE`.

### Concurrency model

All agents and workers run as coroutines on **one asyncio event loop**, supervised by the `AgentOrchestrator`: dependency-ordered start, heartbeat monitoring (restart with exponential back-off if a heartbeat lapses > 30 s), and reverse-order graceful shutdown. This gives deterministic execution order, which is critical for forensic replay.

---

## 👥 The 13 Agents

| Department | Agent | Cadence | Role |
|-----------|-------|---------|------|
| **Front Office** | `StrategyAgent` | timer, 60 s | Steps the four sleeves and emits signals |
| | `PortfolioAgent` | timer, 60 s | Converts approved signals into target weights and orders; maintains NAV |
| | `ExecutionAgent` | timer, 5 s | Order state machine, guards, atomic fills |
| | `IRAgent` | message-driven | Investor-relations style reporting/communication |
| **Middle Office** | `RiskAgent` | timer, 30 s | Pre-trade gating + continuous VaR/CVaR/drawdown monitoring |
| | `ComplianceAgent` | message-driven | Rule/compliance checks |
| | `DebateAgent` | message-driven | Runs the multi-LLM debate in autonomous mode |
| | `AlphaMonitorAgent` | timer, 300 s | Tracks signal/alpha quality |
| | `OperationsAgent` | message-driven | Operational workflows |
| **Back Office** | `AccountingAgent` | timer, 3600 s | Ledger and reconciliation |
| | `QuantAgent` | message-driven | Ad-hoc quantitative queries |
| | `ITAgent` | health monitor | Infrastructure health |
| **Executive** | `CIOAgent` | timer, 900 s + crisis-driven | Strategic and crisis advisories; HUMAN or AI mode with veto authority |

All agents derive from `BaseAgent`, which standardises lifecycle (`start`/`stop`), a 10-second heartbeat, metric collection and persistence of every emitted message.

---

## 📊 Strategy Sleeves

| Sleeve | Allocation | Cadence | Idea |
|--------|-----------:|---------|------|
| **ResearchStackSleeve** | 60 % | weekly | Hierarchical Risk Parity (Ward linkage) sized by **Half-Kelly**, **regime-gated** by a two-state Gaussian Mixture Model, tilted by a **Quality** factor |
| **TrendFilterSleeve** | 20 % | daily | Faber 200-day moving-average rule on SPY (hold above, cash below) |
| **GapFadeSleeve** | 10 % | each US open | Overnight gap-reversal on QQQ |
| **MomentumRankSleeve** | 10 % | weekly | 12-minus-1 month cross-sectional momentum, long the top decile |

**Signal hygiene**

- **Market-hours gate:** US equity signals only between 09:30–16:00 ET; crypto signals run 24/7.
- **Minimum weight delta** (`MIN_WEIGHT_DELTA = 0.005`, i.e. 50 bps) suppresses jitter-driven order spam.
- Signals carry symbol, direction, normalised strength, new/previous target weight and bar timestamp.

**Why HRP?** Mean-variance is hypersensitive to covariance estimation error, equal-weight ignores risk concentration, and naïve risk parity still needs a covariance inversion. HRP avoids the inversion by recursive bisection of an asset-cluster hierarchy (O(n²)) and delivers lower out-of-sample variance on realistic universes.

---

## ⚖️ LLM Debate Engine & AI CIO

### Provider-agnostic LLM layer

A `ProviderRegistry` exposes **Anthropic Claude, OpenAI GPT and Google Gemini** behind one interface, with model routing and **fallback** between providers. Strategy, Debate, IR and CIO agents all consume it. If no API key is configured, **rule-based fallbacks** keep the system fully operational.

### Four-debater, perspective-rotated debate

In `FULLY_AUTONOMOUS` mode, any signal whose weight change exceeds the debate threshold is buffered by the `PortfolioAgent` and submitted to the `DebateAgent`. Four perspective-rotated debaters (including a **sentiment** debater fed by the sentiment module) argue the trade over a structured round-robin protocol with consensus, timeout and failure handling. An order is emitted **only if `DEBATE_CONCLUSION = APPROVED` (≥ 3 of 4 votes FOR)**. The design is grounded in multi-agent debate research (Du et al., 2023).

### AI Chief Investment Officer

The `CIOAgent` reflects every 15 minutes and on crises. It can run in **HUMAN mode** (advisory only) or **AI mode** (with crisis-response veto). A `HALT` advisory causes `ExecutionAgent` to reject all opening orders; the REPL exposes `cio`, `cio why` and `cio confirm halt`.

---

## 💸 Execution & Market Impact Model

The `PaperBroker` simulates fills using a closed-form **Almgren–Chriss** model so backtests and paper runs carry realistic cost friction rather than zero-cost mid-price fills.

```
ρ        = Q / V                                  (participation rate)
I_perm   = η_p · σ · P · ρ^γ_p                    (permanent impact)
I_temp   = ε · P + η_t · σ · P · ρ^γ_t            (half-spread + temporary impact)
F        = P + d · (I_perm + I_temp) + ν          (fill price; d = +1 buy, −1 sell)
C        = |F · Q| · κ_exchange / 10 000          (commission)
```

| Constant | Value |
|----------|-------|
| η_p (permanent coeff.) / γ_p | 0.01 / 0.5 |
| ε (half-spread) | 0.0001 (1 bp) |
| η_t (temporary coeff.) / γ_t | 0.01 / 0.5 |
| Default volume / volatility (when missing) | 1,000,000 shares / 2 % daily |
| Stale-price threshold | 300 s |

**Commission table (bps of notional)**

| Exchange | Rate |
|----------|-----:|
| NSE / BSE | 10 |
| CRYPTO | 10 |
| NYSE / NASDAQ | 1 |

**Execution Agent guards** before any fill: **(A)** kill-switch blocks BUYs when halted, **(B)** naked-short check, **(C)** CIO `HALT` override. Fills are written in a **single atomic SQL transaction** (fill + order status + position + cash). Open orders unfilled after **60 s** are auto-cancelled.

**Order state machine:** `PENDING → OPEN → PARTIAL → FILLED`, with `CANCELLED` / `REJECTED` as terminal states.

**Position accounting** uses weighted-average cost basis with correct handling for adding to / reducing / flipping long and short positions, and realised P&L tracked per position.

**Multi-currency NAV:** `N = c_USD + c_INR / r_FX + Σ|F·q|·χ`, with USD/INR sourced from the feed and a fallback rate of 83.0.

---

## 🛡️ Risk Management

| Control | Default | Behaviour |
|---------|---------|-----------|
| Max position weight | 5 % of NAV | Signal rejected: *"Position limit exceeded"* |
| Daily loss limit | 5 % of start-of-day NAV | Signal rejected: *"Daily loss limit breached"* |
| **Max drawdown kill-switch** | **10 %** | Sets `horizon:system:halted`, CRITICAL alert, blocks new buys |
| Max leverage | 1.0 | Declared; enforcement on the roadmap |
| Max orders / minute | 10 | Declared; enforcement on the roadmap |
| Stop-loss | per position | Position monitor emits a liquidating SELL signal when the price crosses |

**Continuous monitoring (every 30 s):** historical-simulation **VaR (95 / 99)** and **CVaR (95)** over the trailing 253 trading days, plus current and maximum drawdown, persisted to `risk_metrics`.

```
VaR_α  = − Q_{1−α}(r)
CVaR_α = − E[ r | r ≤ Q_{1−α}(r) ]
```

Historical simulation was chosen over parametric VaR (Gaussian fits understate 99th-percentile losses in stressed regimes) and Monte-Carlo VaR (extra cost, little benefit with a long window).

---

## 🎛️ Operating Modes

| Mode | Authority | Description |
|------|-----------|-------------|
| `PAPER_TRADING` | Automatic | Signals that survive risk are executed automatically with no human in the loop |
| `HUMAN_APPROVAL` | Operator | Orders wait in `PENDING_APPROVAL`; operator uses `orders pending`, `approve <id>`, `reject <id>` |
| `FULLY_AUTONOMOUS` | LLM debate | Significant signals must win a ≥ 3-of-4 debate before an order is emitted |

Select via `HORIZON_MODE` or `--mode`.

---

## 🧰 Tech Stack

| Layer | Technology |
|-------|-----------|
| Language / runtime | Python 3.11+ (verified on 3.14), `asyncio` |
| API | FastAPI, Uvicorn (12 routers) |
| ORM / DB | SQLAlchemy 2.0 (async), `aiosqlite`, `asyncpg` |
| Messaging / KV | In-memory bus, Redis (≥ 5) |
| Validation / config | Pydantic v2, `pydantic-settings` |
| Serialization | `orjson` |
| Terminal UI | Rich |
| Market data | `yfinance`, CoinGecko, Forex feeds, Alpaca, Zerodha (KiteTicker), Polymarket |
| LLM SDKs | `anthropic`, `openai`, `google-generativeai` |
| Sentiment | Keyword lexicon; optional HuggingFace FinancialBERT |
| ML (experimental) | HMM regime trainer, DRL strategy trainer (`ml_training/`) |
| Web front-end | React + Vite + Tailwind CSS |
| Testing / lint | pytest, ruff |
| Deployment | Dockerfiles for backend & frontend (`infrastructure/`) |

---

## 🗂️ Project Structure

```
HoriZon-Capital/
├── backend/
│   ├── pyproject.toml
│   └── app/
│       ├── agents/          # 13 agents in 4 departments (+ paper_broker, order_manager)
│       ├── core/            # message bus, DB session factory, KV store, config, logging
│       ├── workers/         # 5 background workers + AgentOrchestrator
│       ├── data_layer/      # Yahoo, Crypto, Alpaca, Forex, (Polymarket) feeds
│       ├── services/        # stress testing, alerts, model registry, reports, health
│       ├── features/        # 23-indicator feature engine + sentiment
│       ├── llm/             # ProviderRegistry, LLMInterface
│       ├── quant/           # portfolio optimiser (HRP), regime detector (GMM)
│       ├── backtesting/     # walk-forward BacktestEngine / BacktestRunner
│       ├── models/          # SQLAlchemy ORM models
│       ├── schemas/         # Pydantic schemas
│       ├── api/v1/          # FastAPI routers
│       └── tui/             # Rich dashboard, REPL commands, onboarding wizard
├── frontend/                # React + Vite + Tailwind dashboard
├── landing-page/            # Separate React landing page
├── ml_training/             # train_hmm_regime.py, train_drl_strategies.py
├── infrastructure/          # Dockerfiles
└── README.md
```

> ⚠️ Adjust folder names above to match the repo exactly if anything differs.

**Code metrics (at thesis audit):** 180 Python modules · ~26.8k lines (~22.6k non-blank) · 13 agents · 5 workers · 23 message types · 28 DB tables · 23 technical indicators · 30+ REPL commands.

---

## 🚀 Getting Started

### Prerequisites

- Python **3.11+**
- Node.js 18+ (only for the web front-end)
- *(Optional)* PostgreSQL and Redis for production mode
- *(Optional)* API keys for Anthropic / OpenAI / Gemini, Alpaca, Zerodha

### 1. Clone

```bash
git clone https://github.com/Aaryanxvi/HoriZon-Capital.git
cd HoriZon-Capital
```

### 2. Backend setup

```bash
cd backend
python -m venv .venv

# macOS / Linux
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -e .
```

### 3. First-run setup wizard

```bash
python -m app --setup
```

The interactive wizard asks for initial capital (USD/INR), default mode, optional LLM and broker keys, and dashboard refresh rate, then writes a `.env` file. Re-run `--setup` any time to reconfigure.

### 4. Run

```bash
# Default: launches the TUI dashboard + REPL
python -m app

# Choose a mode explicitly
python -m app --mode PAPER_TRADING
python -m app --mode HUMAN_APPROVAL
python -m app --mode FULLY_AUTONOMOUS
```

The terminal dashboard appears within about five seconds on first boot.

### 5. (Optional) REST API

```bash
uvicorn app.main:app --reload     # adjust the module path to your entry point
```

### 6. (Optional) Web dashboard

```bash
cd frontend
npm install
npm run dev
```

---

## ⚙️ Configuration

Configuration is loaded from `.env` through `pydantic-settings`. Typical variables:

```ini
# --- Core ---
HORIZON_MODE=PAPER_TRADING          # PAPER_TRADING | HUMAN_APPROVAL | FULLY_AUTONOMOUS
HORIZON_STORAGE=LOCAL               # LOCAL (SQLite + in-memory) | POSTGRES (PostgreSQL + Redis)

# --- LLM providers (all optional; rule-based fallback if none set) ---
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=

# --- Brokers / feeds (optional) ---
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
ZERODHA_API_KEY=
ZERODHA_API_SECRET=

# --- Risk ---
RISK_MAX_POSITION_PCT=5.0
RISK_DAILY_LOSS_LIMIT_PCT=5.0
RISK_MAX_DRAWDOWN_PCT=10.0
RISK_MAX_LEVERAGE=1.0
RISK_MAX_ORDERS_PER_MINUTE=10

# --- Sentiment ---
SENTIMENT_USE_BERT=false
```

> ⚠️ Variable names are indicative; confirm against `backend/app/config.py`. **Never commit your `.env` file.**

### Storage modes

| Mode | Database | Bus | KV store | Infrastructure needed |
|------|----------|-----|----------|-----------------------|
| `LOCAL` | SQLite (28 tables) | In-memory `MemoryBus` | In-memory (`kv_cache`) | **None** |
| `POSTGRES` | PostgreSQL | Redis pub/sub `AgentBus` | Redis | PostgreSQL + Redis |

---

## 🖥️ Terminal UI & REPL Commands

The **Rich-based dashboard** refreshes at **2 FPS** with a multi-panel layout:

- **Left:** NAV, USD/INR cash balances, gross/net leverage
- **Centre:** recent fills and open positions with mark-to-market P&L
- **Right:** risk panel, live alerts, and the debate transcript when a debate is running

The **REPL** (30+ commands, tab-completion) is organised into families:

| Family | Commands |
|--------|----------|
| **Trading** | `buy`, `sell`, `orders`, `positions`, `trades`, `pnl` |
| **Portfolio** | `portfolio`, `cash`, `nav` |
| **Backtest** | `backtest`, `backtest list`, `backtest compare` |
| **Risk** | `risk`, `var`, `drawdown` |
| **Debate** | `debate history`, `debate active` |
| **CIO** | `cio`, `cio why`, `cio confirm halt` |
| **System** | `agents`, `health`, `config`, `quit` |
| **Approval** | `orders pending`, `approve <id>`, `reject <id>` |
| **Testing** | `inject signal …` (push a synthetic signal through the pipeline) |

---

## 🌐 Web Dashboard

A React + Vite + Tailwind single-page app in `frontend/` consumes the FastAPI REST layer to present portfolio, positions, orders, risk, agent health and CIO insights in the browser. It has been redesigned with an improved GUI since the original thesis.

<!-- Add screenshots here -->
<!--
![Dashboard](docs/images/dashboard.png)
![Portfolio](docs/images/portfolio.png)
![Polymarket](docs/images/polymarket.png)
-->

---

## 💾 Data & Persistence

**28 tables in 7 clusters**

| Cluster | Tables |
|---------|--------|
| Trading | `orders`, `fills`, `positions`, `trades` |
| Portfolio & risk | `portfolio_snapshots`, `cash_balances`, `risk_metrics`, `performance_snapshots` |
| Signals & debate | `signals`, `debate_sessions`, `debate_arguments` |
| Market data | `ohlcv`, `feature_snapshots`, `narratives`, `sentiment_aggregates` |
| Macro & regime | `regime_states` |
| System & audit | `agent_states`, `agent_messages`, `kv_cache`, `health_snapshots`, `alert_history`, `model_versions`, `strategy_selections` |
| Analytics & reporting | `stress_test_results`, `reports`, `backtest_runs`, `cio_advisories`, `cio_overrides` |

**Key-value conventions:** `horizon:price:{SYMBOL}`, `horizon:portfolio:nav`, `horizon:system:halted`, `horizon:system:mode`, `horizon:forex:usdinr`, `horizon:volume:{SYMBOL}`.

**Data resilience:** every external dependency (Yahoo Finance, CoinGecko, Forex, Alpaca, Zerodha, Polymarket, LLM providers) is wrapped with **retry-with-backoff** and a **per-call circuit breaker**.

**Feature engine (23 indicators):**

| Family | Indicators |
|--------|-----------|
| Trend | SMA(20/50/200), EMA(12/26), MACD (+signal, hist), Ichimoku |
| Momentum | RSI(14), Stochastic %K/%D, Williams %R, ROC |
| Volatility | Bollinger Bands, ATR(14), GARCH(1,1) σ̂ |
| Volume | OBV, VWAP, volume SMA, volume ratio |

---

## 🔬 Backtesting & Stress Testing

- **Walk-forward backtest engine** reporting Sharpe, Sortino, Calmar, Jensen's alpha (vs **NIFTY 50** and **S&P 500**), win rate and profit factor across six time horizons.
- **Stress-testing service** replays historical crises (**GFC 2008**, **COVID 2020**) and counterfactual price paths to validate behaviour under tail conditions.
- Results persist to `backtest_runs` and `stress_test_results`; compare runs with `backtest compare`.

---

## 🧪 Testing

```bash
cd backend
pytest                 # full suite
ruff check .           # lint
```

Four verification layers: **unit** (Almgren–Chriss, cost-basis, NAV, VaR/CVaR, order FSM) → **integration** (multi-agent signal-to-fill) → **smoke** (headless boot) → **manual live demonstration**.

At the thesis audit, **368 test functions** were collected across 22 files, with all collected tests passing. Five test files failed *collection* because of configuration/import-path drift (a stale `ai_front_office='openai'` value and pre-refactor `app.agents.*` imports). These were tracked as P1 fixes.

---

## 📈 Results from the Demonstration Run

A four-hour live paper-trading session (USD 100,000 seed, four sleeves, live Yahoo/CoinGecko feeds, Windows 11 laptop):

| Metric | Value |
|--------|------:|
| Signals emitted | 87 |
| Passed Risk Agent → orders | 63 |
| Orders filled | 61 (2 rejected for stale price during a Yahoo rate-limit window) |
| Final NAV | $99,807.42 |
| Day P&L | −$192.58 (−0.19 %) |
| Max drawdown | 3.06 % (kill-switch threshold 10 %) |
| VaR₉₅ / VaR₉₉ / CVaR₉₅ (1-day) | 1.42 % / 2.31 % / 1.94 % * |
| Gross / net leverage | 0.94 / 0.94 |
| Open positions | 9 |

\* Computed over the 4-hour window only; these stabilise as the 253-day history accumulates.

**Observed slippage:** ~0.4–1.2 bps on liquid US large-caps vs ~3–6 bps on crypto and Indian equities, consistent with Almgren–Chriss participation-rate scaling.

### Worked example (AAPL buy)

667 shares @ $150.00 reference, σ = 2 %, ADV = 50 M → ρ = 1.334×10⁻⁵ → fill ≈ **$150.0152**, commission ≈ **$10.01**, total round-trip cost ≈ **2.02 bps** of notional.

---

## 🚧 Known Limitations & Roadmap

The thesis included a formal engineering audit of the paper-trading path: **46 gaps** (14 P0, 26 P1, 6 P2) and a composite production-readiness score of **6.5 / 10**.

**Most important known items**

- 🔴 **Restart safety:** signal-dedup state is in-memory, so a restart can re-emit duplicate orders
- 🔴 **Realised P&L** is not yet summed into the NAV shown on the dashboard
- 🔴 **Slippage bias:** the clamped noise term introduces a small systematic drag
- 🔴 **No partial fills** are simulated; the `PARTIAL` state path is effectively dormant
- 🔴 **Kill-switch** blocks BUYs but not short-opening orders
- 🔴 **No market-hours gate** in the broker; injected or replayed weekend orders can fill against a stale close
- 🟠 `risk_max_leverage` and `risk_max_orders_per_minute` are declared but not enforced
- 🟠 Live-money broker routing (Zerodha / Alpaca) is **not certified**; paper-with-real-feed only

**Roadmap**

- [ ] Fix all P0 items, then the P1 set
- [ ] Persist dedup / cooldown state across restarts
- [ ] Partial fills + latency simulation
- [ ] Enforce leverage and order-rate limits
- [ ] Feed-health badge and tighter NAV refresh on the dashboard
- [ ] Production deployment (Docker Compose, CI)
- [ ] Expand Polymarket and crypto strategies and risk models
- [ ] Train and integrate HMM regime and DRL strategy models

---

## 👨‍💻 Team

**Group 40** — B.Tech, K. J. Somaiya College of Engineering, Somaiya Vidyavihar University (2023–27)

| Name | Branch | Roll No. |
|------|--------|----------|
| Aditya Manoj | AI & Data Science | 16014223005 |
| Krutarth Ashar | AI & Data Science | 16014223047 |
| Aaryan Baadkar | Computer Engineering | 16010123010 |
| Aditya Singh | Computer Engineering | 16010123025 |

**Guides:** Dr. Anushree Deshmukh · Prof. Kalpita Wagaskar

---

## 📚 References

1. Almgren & Chriss, *Optimal Execution of Portfolio Transactions*
2. Markowitz, *Portfolio Selection*
3. López de Prado, *Building Diversified Portfolios that Outperform Out-of-Sample* (Hierarchical Risk Parity)
4. Kelly, *A New Interpretation of Information Rate* (Kelly criterion)
5. Jorion, *Value at Risk*
6. Faber, *A Quantitative Approach to Tactical Asset Allocation*
7. Jegadeesh & Titman, *Returns to Buying Winners and Selling Losers*
8. Wooldridge, *An Introduction to MultiAgent Systems*
9. LeBaron, Santa Fe Artificial Stock Market
10. Aldridge, *High-Frequency Trading*
11. Bertsimas & Lo, *Optimal Control of Execution Costs*
12. Ramírez, FastAPI documentation
13. Du et al., *Improving Factuality and Reasoning in Language Models through Multiagent Debate* (2023)

Full bibliography is in the project report.

---

## ⚠️ Disclaimer

Horizon Capital is an **educational and research project**. It runs in **paper-trading mode** with simulated execution and is **not financial advice**. Live-broker integrations are experimental and **not certified for real-money trading**. Markets, including crypto and prediction markets, involve substantial risk of loss. Use at your own risk, and never trade money you cannot afford to lose.

---

<div align="center">

**Built with ❤️ at K. J. Somaiya College of Engineering**

⭐ If you find this project useful, consider giving it a star!

</div>
