# Horizon Capital — Autonomous AI Hedge Fund Platform

An autonomous AI hedge fund platform that replaces traditional hedge fund departments with specialized AI agents. Targets Indian markets (NSE/BSE) and US markets (NYSE/NASDAQ), supporting equities, F&O, and crypto.

## Architecture

```
Data Feeds → Feature Engine → Regime Detection → Strategy Agents → Debate Engine → Risk Check → Portfolio Sizing → Execution
```

### AI Agents
- **Regime Agent** — HMM + LFR drift detection (Bull/Bear/HighVol/Crisis)
- **Strategy Agents** — Momentum, Mean Reversion, Volatility, Crisis Defense
- **Risk Agent** — VaR calculation, drawdown monitoring, kill switch
- **Portfolio Agent** — Kelly sizing, correlation penalty, unified NAV
- **Sentiment Agent** — FinancialBERT scoring, narrative lifecycle tracking
- **Debate Engine** — Claude-powered investment committee (4 agents debate each trade)
- **Execution Agent** — Paper/Human Approval/Autonomous modes

### Execution Modes
```
PAPER_TRADING → HUMAN_APPROVAL → FULLY_AUTONOMOUS
```

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env with your API keys

# 2. Start infrastructure
cd infrastructure
docker compose up -d

# 3. Run migrations
cd ../backend
alembic upgrade head

# 4. Backfill historical data
python ../scripts/backfill_historical.py

# 5. Start backend
uvicorn app.main:app --reload

# 6. Start frontend
cd ../frontend
npm install && npm run dev
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + SQLAlchemy 2.x async + asyncpg |
| Database | PostgreSQL 16 |
| Cache/Messaging | Redis 7 (pub/sub) |
| Frontend | React 18 + TypeScript + Vite + Zustand + Tailwind |
| ML | hmmlearn, FinancialBERT (HuggingFace), stable-baselines3 |
| LLM | Claude API (debate engine) |
| Brokers | Zerodha Kite (India) + Alpaca (US) |
| Data | Yahoo Finance, Polygon.io, CoinGecko, NewsAPI, Reddit |

## Brokers
- **Zerodha Kite** — Indian equities and F&O (mock mode available)
- **Alpaca** — US equities (paper trading by default)

## Key Features
- Multi-agent institutional debate architecture
- Regime-specific dynamic strategy switching
- Narrative momentum modeling with cross-asset spillover detection
- Visual pixel agent layer for AI transparency
- CIO-controlled governance framework
- Institutional-grade explainability per trade
- Continuous learning and drift adaptation

## Project Structure

```
horizon-capital/
├── infrastructure/     # Docker, Postgres, Redis, Nginx
├── backend/           # FastAPI application
│   ├── app/
│   │   ├── agents/    # All AI agents
│   │   ├── api/       # REST + WebSocket endpoints
│   │   ├── core/      # DB, Redis, messaging, auth
│   │   ├── data_layer/# Market data feeds
│   │   ├── features/  # Technical indicators, feature store
│   │   ├── models/    # SQLAlchemy ORM
│   │   └── workers/   # Background workers
│   └── alembic/       # DB migrations
├── frontend/          # React dashboard
├── ml_training/       # Offline model training
├── tests/             # Unit + integration tests
└── scripts/           # Bootstrap, backfill, smoke test
```

## License

Proprietary — Horizon Capital
