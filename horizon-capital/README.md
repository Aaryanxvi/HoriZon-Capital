# Horizon Capital — AI Trading Platform

A college project: an autonomous multi-agent AI trading platform that runs as a
desktop terminal application. Specialized AI agents collaborate through structured
debates to make paper-trading decisions across Indian markets (NSE/BSE), US markets
(NYSE/NASDAQ), and cryptocurrency.

## Features

- **Multi-agent architecture** — four departments (Front Office, Middle Office, Back Office,
  Executive) each staffed with specialized agents that communicate over an in-process
  message bus
- **LLM debate system** — before any trade is executed, four AI debaters (Strategy, Risk,
  Sentiment, Portfolio) argue for or against the trade; a consensus vote decides
- **Sentiment analysis** — real-time headline scoring using keyword matching and optional
  FinancialBERT neural scoring; scores are displayed live on the dashboard
- **Paper trading** — simulated broker with Almgren-Chriss market-impact model; no real
  money involved
- **Backtesting** — historical replay of strategies with equity curve and trade journal export
- **3 data feeds** — Yahoo Finance (US equities), CoinGecko (crypto), and a mock feed for
  Indian equities; switchable via `.env`
- **Rich terminal dashboard** — 2fps live dashboard showing agents, watchlist with sparklines,
  portfolio, risk metrics, sentiment, and order history
- **Interactive REPL** — 30+ commands: `backtest`, `sentiment`, `debate`, `portfolio`,
  `orders`, `approve`, `reject`, `health`, `performance`, and more

## Quick Start

```bash
cd backend

# First run: interactive setup wizard
python -m app --setup

# Run the terminal agent (TUI + agents)
python -m app

# Headless mode (log output only)
python -m app --headless

# Show configuration
python -m app config
```

No Docker required. Runs with SQLite + in-memory message bus by default.

## Desktop app

The same engine with a window instead of a terminal — agents, storage, API and UI
all run in one process. Nothing about the trading logic changes; the app's Terminal
screen is the REPL itself, over a websocket.

```bash
# Dev: build the UI once, then launch the app (it starts the backend for you)
cd frontend && npm install && npm run build
cd ../desktop && npm install && npm start

# Installer (Windows NSIS / macOS dmg / Linux AppImage)
python build_desktop.py
```

Screens: Overview, Portfolio, Trading (manual ticket + approvals), Signals (sleeve
toggles), Agents, Debates, Risk, Performance, Terminal, Settings. The title bar keeps
**Halt**, the trading-mode switch and engine start/stop one click away on every screen,
and first run opens a setup wizard that writes the same `.env` the CLI reads.

Backend alone, no window:

```bash
cd backend && HORIZON_RUN_AGENTS=1 python desktop_entry.py 8000   # http://127.0.0.1:8000
```

## Architecture

```
Data Feeds
  └─ Yahoo Finance (US equities, ETFs)
  └─ CoinGecko (crypto prices)
  └─ Mock feed (Indian equities)

Feature Engine (23 technical indicators)
  └─ Trend: SMA, EMA, MACD, Ichimoku
  └─ Momentum: RSI, Stochastic, Williams %R
  └─ Volatility: Bollinger Bands, ATR, GARCH(1,1)
  └─ Volume: OBV, VWAP

Strategy Agents
  └─ Momentum — trend-following signals
  └─ Mean Reversion — RSI/Bollinger-band reversals

AI Debate Engine
  └─ 4 debaters (Strategy / Risk / Sentiment / Portfolio)
  └─ Each argues FOR or AGAINST a proposed trade
  └─ Confidence-weighted consensus vote decides

Risk Agent
  └─ VaR (95%, 99%), drawdown limit, position limits
  └─ Emergency halt (kill switch) on drawdown breach

Execution Agent
  └─ PAPER_TRADING — simulated fills
  └─ HUMAN_APPROVAL — every trade needs CLI approval
  └─ FULLY_AUTONOMOUS — debate gate controls all trades
```

## Project Structure

```
backend/
├── app/
│   ├── __main__.py          # CLI entry point (TUI + REPL)
│   ├── config.py            # Settings (.env loading)
│   ├── agents/
│   │   ├── front_office/    # Strategy, sentiment, execution agents
│   │   ├── middle_office/   # Risk, compliance agents
│   │   ├── back_office/     # Quant, accounting, IT agents
│   │   └── executive/       # CIO agent
│   ├── core/
│   │   ├── messaging.py     # In-memory message bus
│   │   ├── local_storage.py # SQLite schema (23 tables)
│   │   └── kv_store.py      # Key-value store abstraction
│   ├── backtesting/         # Historical replay engine
│   ├── features/            # Technical indicators
│   ├── services/            # Alerts, reports, health monitor
│   ├── tui/                 # Rich terminal dashboard + REPL
│   └── workers/             # Background data + performance workers
└── tests/                   # 265 tests (pytest)
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| TUI | Rich (terminal dashboard) |
| Web API | FastAPI (optional) |
| Database | SQLite (local) / PostgreSQL |
| Messaging | In-memory bus (local) / Redis |
| LLM | Claude / GPT / Gemini (optional) |
| Data | yfinance, CoinGecko, httpx |
| ML | ta (technical analysis), arch (GARCH) |
| Brokers | Alpaca (US paper), Zerodha (India) |

## Configuration

All settings in `.env`:

```env
SYSTEM_MODE=PAPER_TRADING     # PAPER_TRADING | HUMAN_APPROVAL | FULLY_AUTONOMOUS
CIO_MODE=HUMAN                # HUMAN | AI
STORAGE_BACKEND=LOCAL         # LOCAL (SQLite) | POSTGRES

# Optional — LLM providers (for AI debate)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AI...

# Optional — real broker connections
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
```

Without any API keys, the system runs fully in rule-based / paper mode.

## Running Tests

```bash
cd backend
python -m pytest tests/ -v        # 265 tests
python -m ruff check app/          # 0 lint errors
```
