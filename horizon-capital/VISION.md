# Horizon Capital — Project Vision & Development Roadmap

## What Is Horizon Capital?

Horizon Capital is an **autonomous AI hedge fund platform** that runs as a desktop terminal agent. It uses multiple AI agents that collaborate through structured debates to make trading decisions across Indian equities (NSE/BSE), US equities (NYSE/NASDAQ), and cryptocurrency markets.

Unlike traditional algorithmic trading systems that rely on a single strategy, Horizon Capital deploys a **multi-agent architecture** where specialized agents (regime detection, strategy selection, sentiment analysis, risk management, portfolio optimization) communicate through a message bus and must reach **consensus via AI-powered debates** before any trade is executed.

The system is designed to run locally on your machine with zero infrastructure in paper trading mode, and can scale to production with PostgreSQL + Redis when ready for live trading.

---

## Core Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    TERMINAL AGENT (TUI / REPL)                  │
│  Status Dashboard  │  Command Interface  │  Live Logs           │
├─────────────────────────────────────────────────────────────────┤
│                     AGENT ORCHESTRATOR                          │
│  Lifecycle management  │  Health monitoring  │  Auto-restart    │
├──────────┬──────────┬──────────┬──────────┬─────────────────────┤
│  Regime  │ Strategy │Sentiment │   Risk   │  Portfolio  │ Exec  │
│  Agent   │ Ensemble │  Agent   │  Agent   │   Agent     │ Agent │
│  (HMM)   │ (4 strats)│(FinBERT)│  (VaR)  │  (Kelly)    │(Broker│
├──────────┴──────────┴──────────┴──────────┴─────────────┴───────┤
│                    DEBATE ENGINE (Claude AI)                     │
│  4 debaters argue each trade → consensus vote → execute/reject  │
├─────────────────────────────────────────────────────────────────┤
│                      MESSAGE BUS                                │
│  In-Memory (local) or Redis Pub/Sub (production)                │
├─────────────────────────────────────────────────────────────────┤
│                      DATA LAYER                                 │
│  SQLite (local) or PostgreSQL (production)                      │
│  Yahoo Finance │ Alpaca │ Polygon │ Zerodha │ CoinGecko         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Complete Feature List

### Multi-Agent System
- [x] BaseAgent framework with lifecycle management, heartbeats, and message bus integration
- [x] Agent orchestrator with health monitoring and automatic restart (up to 3 retries)
- [x] Agent registry for discovery and status tracking
- [x] Inter-agent pub/sub communication via message bus

### Regime Detection Agent
- [x] Hidden Markov Model (HMM) for market regime classification (BULL, BEAR, NEUTRAL, CRISIS, HIGH_VOLATILITY)
- [x] Per-scope regime tracking (INDIA, US, CRYPTO)
- [x] LFR drift detector for concept drift monitoring
- [x] Automatic confidence adjustment when drift is detected

### Strategy Agents (Rule-Based MVP)
- [x] Momentum strategy (trend-following signals)
- [x] Mean reversion strategy (contrarian signals)
- [x] Volatility strategy (vol-adjusted positioning)
- [x] Crisis defense strategy (risk-off signals during drawdowns)
- [x] Ensemble selector — routes signals through regime-appropriate strategies

### Sentiment Analysis Agent
- [x] FinancialBERT (HuggingFace transformers) for financial text scoring
- [x] NewsAPI integration for real-time news sentiment
- [x] Reddit (PRAW) integration for social sentiment
- [x] Narrative lifecycle tracker (EMERGING → GROWING → PEAK → FADING → DEAD)

### Debate Engine (Claude-Powered)
- [x] Multi-agent debate with 4 roles: Strategy, Risk, Sentiment, Portfolio
- [x] Structured argument rounds with evidence citing
- [x] Consensus voting with confidence scoring
- [x] Full debate history persistence and audit trail
- [x] Anthropic Claude API integration with retry logic

### Risk Management Agent
- [x] Historical VaR (Value at Risk) at 95% and 99% confidence
- [x] Conditional VaR (Expected Shortfall)
- [x] Max drawdown and current drawdown tracking
- [x] Pre-trade validation (position limits, exposure ceiling, correlation check)
- [x] Kill switch — automatic circuit breaker when risk limits are breached

### Portfolio Optimization Agent
- [x] Kelly criterion for position sizing
- [x] Correlation-aware portfolio weighting
- [x] Multi-currency support (INR, USD, crypto)

### Execution Agent
- [x] Order routing to correct broker based on symbol/market
- [x] Paper trading simulator (no real money)
- [x] Alpaca integration (US equities)
- [x] Zerodha Kite integration (Indian equities)
- [x] Order lifecycle tracking (NEW → FILLED → CANCELLED)
- [x] Three modes: PAPER_TRADING, HUMAN_APPROVAL, FULLY_AUTONOMOUS

### Data Layer
- [x] Yahoo Finance feed
- [x] Alpaca Markets feed
- [x] Polygon.io feed
- [x] Zerodha market data feed
- [x] CoinGecko crypto data feed
- [x] Forex data feed
- [x] Data normalization layer
- [x] Feature store with caching

### Technical Indicators & Features
- [x] 20+ technical indicators (RSI, MACD, Bollinger Bands, ATR, etc.)
- [x] Regime-specific features (HMM inputs)
- [x] Sentiment features (NLP-derived)
- [x] Volatility measures (GARCH, realized vol)

### Terminal Agent (Desktop Interface)
- [x] Rich-based terminal dashboard with live panels
- [x] Interactive REPL command interface
- [x] Agent status monitoring
- [x] Signal visualization
- [x] Regime display per market scope
- [x] Risk metrics display
- [x] Debate history viewer
- [x] CIO governance commands (mode switch, config)
- [x] Headless mode (log-only, no TUI)

### Infrastructure
- [x] SQLite local storage (zero-infrastructure development)
- [x] In-memory message bus for local mode
- [x] PostgreSQL + Redis for production
- [x] Docker Compose for deployment
- [x] Structured JSON logging (structlog)
- [x] JWT authentication for API access
- [x] REST API (50+ endpoints) for programmatic access
- [x] WebSocket support for real-time updates

### Testing
- [x] Smoke test suite (23 tests, all passing)
- [x] VaR calculator unit tests
- [x] Drift detector unit tests
- [x] Feature engineering unit tests
- [x] No Docker/Redis/PostgreSQL needed to run tests

---

## Development Phases

### Phase 1 — MVP Foundation (CURRENT)
**Goal:** Build the core multi-agent trading system with rule-based strategies that can run locally as a terminal agent in paper trading mode.

**What it achieves:**
- Complete agent framework with orchestration, health monitoring, and message bus
- 6 core agents: Regime, Strategy (4 rule-based), Sentiment, Risk, Portfolio, Execution
- Claude-powered debate engine for trade consensus
- Paper trading simulator with no real money risk
- Terminal agent interface (Rich TUI + REPL commands)
- SQLite + in-memory bus for zero-infrastructure local development
- Full test suite that runs without Docker
- Multi-market support: India, US, Crypto

**Status:** ~85% complete. Core agents built, terminal UI built, testing infrastructure complete.

---

### Phase 2 — Deep Reinforcement Learning Strategies
**Goal:** Replace rule-based strategies with DRL models that learn optimal trading policies from data.

**What it achieves:**
- PPO (Proximal Policy Optimization) strategy agent
- A2C (Advantage Actor-Critic) strategy agent
- DDPG (Deep Deterministic Policy Gradient) for continuous action spaces
- Offline training pipeline using stable-baselines3
- Model artifact management (versioning, rollback)
- A/B testing framework: DRL vs rule-based strategy comparison
- Walk-forward validation for strategy evaluation
- Automatic strategy switching based on live performance

**Key technologies:** stable-baselines3, gymnasium, PyTorch

---

### Phase 3 — Advanced Backtesting & Performance Analytics
**Goal:** Build a production-grade backtesting engine with comprehensive performance analytics.

**What it achieves:**
- Event-driven backtesting engine with realistic simulation
- Slippage and transaction cost modeling
- Multi-asset portfolio backtesting across markets
- Walk-forward optimization with out-of-sample testing
- Performance dashboards: Sharpe, Sortino, Calmar, max drawdown, win rate
- Strategy attribution analysis (which agent contributed what P&L)
- Monte Carlo simulation for risk scenario analysis
- Benchmark comparison (vs Nifty 50, S&P 500, BTC)
- Trade journal with full explainability (why each trade was made)
- Export to PDF/CSV for reporting

---

### Phase 4 — Live Trading & Production Hardening
**Goal:** Transition from paper trading to live trading with production-grade reliability.

**What it achieves:**
- Live trading mode with real broker connections (Alpaca, Zerodha)
- Real-time order execution with fill tracking
- Multi-account support
- CIO governance panel with manual override at every stage
- Alert system: Telegram, email, SMS notifications
- Automatic position reconciliation with broker
- Rate limiting and API quota management
- Disaster recovery and data backup
- Deployment to cloud (AWS/GCP) with monitoring
- Prometheus metrics + Grafana dashboards
- Log aggregation and alerting
- Kill switch with manual reset (requires CIO confirmation)

---

### Phase 5 — Advanced AI & Expansion
**Goal:** Push the intelligence frontier with advanced AI capabilities and expand market coverage.

**What it achieves:**
- Multi-model debate: GPT-4, Claude, Gemini debating alongside each other
- Fine-tuned FinBERT on Indian financial news (Hindi + English)
- Options and futures strategy agents
- Cross-market arbitrage detection
- Macro-economic factor integration (Fed rates, RBI policy, CPI)
- Alternative data sources (satellite imagery, supply chain data)
- Portfolio rebalancing automation
- Tax-loss harvesting (India + US tax rules)
- Multi-user support with role-based access (CIO, Analyst, Viewer)
- Mobile companion app (React Native) for monitoring on the go
- Plugin architecture for custom strategy development

---

## Trading Universe

| Market | Exchange | Symbols (Default) | Broker |
|--------|----------|-------------------|--------|
| India  | NSE/BSE  | RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK | Zerodha Kite |
| US     | NASDAQ   | AAPL, MSFT, GOOGL, AMZN, TSLA | Alpaca |
| Crypto | —        | BTC-USD, ETH-USD | CoinGecko (data) |

---

## System Modes

| Mode | Description | Risk Level |
|------|-------------|------------|
| **PAPER_TRADING** | Simulated orders, no real money. Default for development. | None |
| **HUMAN_APPROVAL** | Every trade requires CIO confirmation before execution. | Low |
| **FULLY_AUTONOMOUS** | System executes trades automatically within risk limits. | High |

---

## How to Run

```bash
# Install dependencies
cd horizon-capital/backend
pip install -r requirements.txt

# Start terminal agent (LOCAL mode, paper trading)
python -m app

# Start in headless mode (log output only)
python -m app --headless

# Show configuration
python -m app config

# Run tests
python -m pytest tests/test_smoke.py -v
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11+ |
| Agent Framework | Custom (BaseAgent + AsyncIO) |
| ML - Regime | hmmlearn (HMM), scikit-learn |
| ML - Sentiment | HuggingFace Transformers (FinBERT) |
| ML - Strategy (Phase 2) | stable-baselines3, PyTorch |
| LLM - Debate | Anthropic Claude API |
| Data | pandas, numpy, ta (technical analysis) |
| Storage (Local) | SQLite + aiosqlite |
| Storage (Prod) | PostgreSQL + asyncpg |
| Messaging (Local) | In-memory async queue |
| Messaging (Prod) | Redis pub/sub |
| Terminal UI | Rich |
| Web API | FastAPI (optional, for production) |
| Testing | pytest + pytest-asyncio |
