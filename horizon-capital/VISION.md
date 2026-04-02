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
  - _Ref: Hamilton 1989, Econometrica (~14,000 citations) — foundational Markov-Switching Model_
- [x] Per-scope regime tracking (INDIA, US, CRYPTO)
- [x] LFR drift detector for concept drift monitoring
  - _Ref: Lu et al. 2019, IEEE TKDE (~1,500 citations) — concept drift detection survey_
- [x] Automatic confidence adjustment when drift is detected

### Strategy Agents (Rule-Based + LLM-Enhanced)
- [x] Momentum strategy (trend-following signals, optional LLM reasoning)
- [x] Mean reversion strategy (contrarian signals, optional LLM reasoning)
- [x] Volatility strategy (vol-adjusted positioning, optional LLM reasoning)
- [x] Crisis defense strategy (risk-off signals during drawdowns, optional LLM reasoning)
- [x] Ensemble selector — routes signals through regime-appropriate strategies
- [x] LLM reasoning path — when API key available, strategies use LLM for enhanced signal analysis

### Sentiment Analysis Agent
- [x] FinancialBERT (HuggingFace transformers) for financial text scoring
  - _Ref: Araci 2019, "FinBERT: Financial Sentiment Analysis with Pre-trained Language Models" (~778 citations)_
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
  - _Ref: Rockafellar & Uryasev 2000, J. Risk (~7,000 citations) — CVaR as coherent risk measure_
- [x] Conditional VaR (Expected Shortfall)
- [x] Max drawdown and current drawdown tracking
- [x] Pre-trade validation (position limits, exposure ceiling, correlation check)
- [x] Kill switch — automatic circuit breaker when risk limits are breached

### Portfolio Optimization Agent
- [x] Kelly criterion for position sizing
  - _Ref: MacLean, Thorp & Ziemba 2011, World Scientific (~1,000 citations) — Kelly Capital Growth Criterion_
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

### Phase 2: Advanced Agent Intelligence
- [x] LLM-powered strategy agents (optional reasoning path, falls back to rule-based)
- [x] Alpha monitor agent (per-strategy Sharpe, win rate, decay detection)
- [x] Regime transition detection (volatility shifts, structural breaks, oscillation)
- [x] Adaptation engine (strategy weight adjustment, signal threshold tuning)
- [x] Per-trade attribution engine (strategy/sentiment/regime/risk/debate breakdown)
- [x] Enhanced CIO terminal commands (interrupt, override regime, risk-tolerance, exposures, attribution)
- [x] Visual agent layer (color-coded activity states in TUI)
- [x] Parallel debate engine (asyncio.gather for ~75% latency reduction)
- [x] First-run onboarding wizard (OpenClaw-style interactive setup)

### Testing
- [x] Smoke test suite (207 tests, all passing)
- [x] VaR calculator unit tests
- [x] Drift detector unit tests
- [x] Feature engineering unit tests
- [x] Phase 3 backtesting tests (30 tests)
- [x] Phase 4 production hardening tests (20 tests)
- [x] Phase 5 advanced AI tests (65 tests)
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

**Status:** Complete. All Phase 1 features implemented and verified.

---

### Phase 2 — Advanced Agent Intelligence & Adaptive Systems
**Goal:** Elevate the LLM-powered agent layer from rule-based signal generation to adaptive, self-monitoring intelligence that explains its decisions, detects its own decay, and adapts in real time.

**What it achieves:**

**LLM-Powered Strategy Agents:**
- Each strategy agent gains an optional LLM reasoning path — when an API key is available, the LLM receives technical indicators + regime context and produces a reasoned signal with natural-language justification
- Falls back gracefully to rule-based math when no LLM is configured
- Specialized quant personas via system prompts (momentum trader, mean-reversion specialist, volatility arbitrageur, crisis manager)

**Continuous Learning & Adaptation:**
- Alpha decay monitoring — per-strategy rolling returns and Sharpe ratio tracking, with automatic alerts when a strategy's edge erodes
- Prediction confidence monitoring — track whether signal strengths are declining over time
- Structural regime detection — identify volatility regime shifts (low-vol → high-vol transitions) and sudden correlation breaks
- Automatic adaptation — strategy switching (disable underperforming, boost performing), correlation matrix recalibration, position sizing adjustment based on new regime conditions
- All adaptation decisions logged to DB for full audit trail

**Explainability & Per-Trade Attribution:**
- For every executed trade, compute and store: strategy alpha contribution, sentiment alpha contribution, regime influence, risk scaling adjustment, debate consensus details
- Agent decision traceability — full audit trail from signal generation through debate to execution
- Attribution breakdown accessible via terminal commands

**Enhanced CIO Terminal Mode:**
- Interrupt specific agents, override regime classification, adjust risk tolerance at runtime
- Enable/disable sentiment module, inspect current exposures by market/symbol
- View per-trade attribution, modify execution modes
- Full command set for real-time system control

**Visual Agent Layer:**
- Each agent rendered as a color-coded status indicator in the TUI (analyzing/debating/executing/idle)
- Real-time agent activity visualization showing what every agent is doing at any moment
- Green = analyzing, Blue = debating, Orange = executing, Dim = idle

**Execution Speed:**
- Parallel debater API calls via asyncio.gather() (~75% latency reduction)
- Parallel strategy execution across symbols

**Narrative Momentum & Cross-Asset Detection:**
- Narrative momentum modeling for sentiment lifecycle tracking
- Cross-asset sentiment spillover detection between correlated instruments

**Key technologies:** Anthropic Claude API, OpenAI API, Google Gemini API, asyncio, Rich TUI

---

### Phase 2.5 — Research-Backed Algorithm Upgrades
**Goal:** Replace placeholder and basic algorithms with academically validated, production-grade models grounded in peer-reviewed research. See [RESEARCH_PAPERS.md](RESEARCH_PAPERS.md) for full citations.

**What it achieves:**

**Risk Agent — GARCH-EVT VaR (Priority 1):**
- [x] Replace Historical VaR (`np.percentile`) with **GJR-GARCH(1,1) + Extreme Value Theory** (McNeil & Frey 2000; Kuester et al. 2006 — won 14-method comparison)
- [x] Step 1: Fit GJR-GARCH to capture time-varying volatility and leverage effects
- [x] Step 2: Apply Generalized Pareto Distribution (GPD) to standardized residuals for proper tail modeling
- [x] Provides both VaR and Expected Shortfall (CVaR) with heavy-tail awareness
- [x] Libraries: `arch` (GARCH), `scipy.stats.genpareto` (GPD/EVT)

**Portfolio Agent — HRP + Ledoit-Wolf (Priority 2):**
- [x] Replace identity-matrix correlation placeholder with **Ledoit-Wolf shrinkage estimator** (Ledoit & Wolf 2004 — 3,500 citations)
- [x] Replace correlation-aware weighting with **Hierarchical Risk Parity (HRP)** (Lopez de Prado 2016 — 31.3% Sharpe improvement over Markowitz, no matrix inversion needed)
- [x] Keep Half-Kelly position sizing (already implemented, matches MacLean, Thorp & Ziemba 2011)
- [x] Custom HRP implementation (no external portfolio optimization library needed)

**Regime Agent — Statistical Jump Model (Priority 3):**
- [x] Add **Statistical Jump Model** as primary regime detector alongside existing HMM (Shu, Yu & Mulvey 2024, *J. Asset Management*)
- [x] More persistent regime sequences, less sensitive to initialization, outperforms HMM across S&P 500, DAX, Nikkei (1990-2023)
- [x] Continuous Jump Model (CJM) + Sparse Jump Model (SJM) variants (Aydinhan et al. 2024)
- [x] Keep HMM as fallback when `jumpmodels` not installed
- [x] Library: `jumpmodels` (scikit-learn-style API with `.fit()`, `.predict()`, `.predict_online()`)

**Mean Reversion Strategy — Cointegration + OU Process (Priority 4):**
- [x] Replace Bollinger Bands with **Ornstein-Uhlenbeck process** as primary signal (Bollinger as fallback)
- [x] Model spread dynamics with **OU process** for calibrated entry/exit thresholds (arXiv 2412.12458, 2024)
- [x] Implement **s-score** signal from Avellaneda-Lee framework (Sharpe 1.44 in original paper, 2010)
- [x] Pure numpy implementation (OLS-based OU calibration, no statsmodels dependency)

**Volatility Strategy — GJR-GARCH Forecasting (Priority 5):**
- [x] Replace ATR ratio with **GJR-GARCH(1,1) with Student-t innovations** (Hansen & Lunde 2005 — compared 330 models, asymmetric GARCH wins for equities)
- [x] ATR measures past range; GARCH provides forward-looking conditional volatility forecast
- [x] Captures leverage effect (negative returns increase volatility more than positive returns)
- [x] Library: `arch` (with ATR fallback when `arch` unavailable)

**Execution Agent — Almgren-Chriss Market Impact (Priority 6):**
- [x] Replace random uniform slippage with **Almgren-Chriss optimal execution model** (Almgren & Chriss 2000 — 1,610 citations)
- [x] Separates permanent and temporary market impact
- [x] Provides closed-form execution impact based on order size, volume, and volatility
- [x] Computationally trivial — no ML needed

**Sentiment Agent — Loughran-McDonald Enhancement (Priority 7):**
- [x] Add **Loughran-McDonald financial dictionary** as secondary signal alongside FinBERT (Loughran & McDonald 2011 — 6,000 citations, the standard in financial NLP)
- [x] Combined scoring: 70% FinBERT + 30% L-M dictionary → enhanced accuracy
- [x] Dictionary includes positive, negative, uncertainty, and litigious word lists

**Momentum Strategy — Multi-Indicator Fusion (Priority 8):**
- [x] Add **VPVMA (Volume-Price-Volatility Modified MACD)** incorporating volume + volatility (arXiv 2206.12282)
- [x] Multi-indicator fusion: RSI, MACD, VPVMA, EMA trend, volume, VWAP (6 indicators)
- [x] Weighted confluence scoring (0.84-0.86 win-rate when MACD+RSI combined vs <0.50 alone)

**Crisis Strategy — Trend-Following Overlay (Priority 9):**
- [x] Add **trend-following overlay** as crisis alpha source (Taylor & Francis 2025)
- [x] Hedge first 10-15% of drawdown rather than full defensive positioning (LongTail Alpha 2021)
- [x] Dynamic trailing stop-losses (3x ATR) instead of hard VIX threshold
- [x] Multi-signal combination: trend-following + drawdown hedge + VIX + trailing stop

**New Python dependencies:** `arch`, `scipy`, `statsmodels`, `jumpmodels` (optional)

**Status:** Complete. All 9 algorithm upgrades implemented and verified (112 tests passing). See [RESEARCH_PAPERS.md](RESEARCH_PAPERS.md) for full citations.

---

### Phase 3 — Advanced Backtesting & Performance Analytics
**Goal:** Build a production-grade backtesting engine with comprehensive performance analytics.

**What it achieves:**
- [x] Event-driven backtesting engine with realistic simulation
  - _Ref: de Prado 2018, "Advances in Financial Machine Learning" (Cambridge Univ. Press) — triple barrier method, combinatorial purged cross-validation_
- [x] Slippage and transaction cost modeling (Almgren-Chriss from Phase 2.5)
  - _Ref: Almgren & Chriss 2000, J. Risk (~1,610 citations) — permanent + temporary market impact decomposition_
- [x] Multi-asset portfolio backtesting across markets
  - _Ref: DeMiguel et al. 2009 — out-of-sample portfolio evaluation_
- [x] Walk-forward optimization with out-of-sample testing
  - _Ref: Pardo 2008, "The Evaluation and Optimization of Trading Strategies" (Wiley) — the definitive walk-forward reference_
  - _Ref: DeMiguel, Garlappi & Uppal 2009, Review of Financial Studies (~6,000 citations) — none of 14 methods reliably beat 1/N in-sample_
- [x] Advanced performance metrics: Sharpe, Sortino, Calmar, Omega, Information Ratio, Tail Ratio, Recovery Factor
  - _Ref: Sharpe 1994, "The Sharpe Ratio", J. Portfolio Management — the standard risk-adjusted metric_
  - _Ref: Keating & Shadwick 2002, "A Universal Performance Measure", J. Performance Measurement — Omega ratio_
  - _Ref: Bacon 2008, "Practical Portfolio Performance Measurement and Attribution" (Wiley) — IR, tail ratio, recovery factor_
- [x] Strategy attribution analysis (which agent contributed what P&L)
  - _Ref: Brinson, Hood & Beebower 1986, Financial Analysts Journal (~2,000 citations) — performance attribution framework_
- [x] Monte Carlo simulation for risk scenario analysis (bootstrap + GBM)
  - _Ref: Glasserman 2003, "Monte Carlo Methods in Financial Engineering" (Springer) — the finance-specific MC standard_
  - _Ref: Efron & Tibshirani 1993, "An Introduction to the Bootstrap" — bootstrap confidence intervals_
- [x] Benchmark comparison (vs Nifty 50, S&P 500, BTC) with capture ratios
  - _Ref: Brinson, Hood & Beebower 1986 — BHB attribution model for benchmark decomposition_
- [x] Trade journal with full explainability (why each trade was made)
- [x] Export to CSV for reporting

**Status:** Complete. All Phase 3 components implemented and verified (142 tests passing). See [RESEARCH_PAPERS.md](RESEARCH_PAPERS.md) for full citations.

---

### Phase 4 — Live Trading & Production Hardening
**Goal:** Transition from paper trading to live trading with production-grade reliability.

**What it achieves:**
- [x] Live trading mode with real broker connections (Alpaca, Zerodha)
- [x] Real-time order execution with TWAP/VWAP/Almgren-Chriss order splitting
  - _Ref: Almgren & Chriss 2000, J. Risk (~1,610 citations) — optimal execution trajectory: x_j = X·sinh(κ(T−t_j))/sinh(κT)_
  - _Ref: Cartea & Jaimungal 2015, Quantitative Finance (~400 citations) — adaptive limit/market order mix_
  - _Ref: Bertsimas & Lo 1998, J. Financial Markets (~1,200 citations) — dynamic programming for optimal execution_
- [x] Full Zerodha Kite Connect API integration (NSE/BSE live trading)
- [x] Automatic position reconciliation with broker
  - _Ref: ISDA 2013, "Portfolio Reconciliation in Practice" — three-pass matching: exact, quantity tolerance, price tolerance_
- [x] Rate limiting and API quota management (token bucket algorithm)
  - _Ref: Turner 1986, RFC 970 — token bucket as traffic shaping mechanism_
- [x] Disaster recovery and data backup (SQLite copy, position snapshots, rotation)
- [x] Prometheus-compatible metrics exporter (portfolio value, PnL, agent health, latency)
- [x] Multi-model debate engine with perspective rotation
  - _Ref: Du et al. ICML 2024, "Improving Factuality and Reasoning through Multiagent Debate" — multi-round debate improves factual accuracy_
  - _Ref: Estornell et al. NeurIPS 2024 — perspective rotation reduces groupthink and improves calibration_
  - _Ref: Liang et al. 2023 — model architecture diversity produces better-calibrated confidence scores_

**Status:** Complete. All Phase 4 components implemented and verified (207 tests passing).

---

### Phase 5 — Advanced AI & Expansion
**Goal:** Push the intelligence frontier with advanced AI capabilities and expand market coverage.

**What it achieves:**
- [x] Options and futures strategy agent with full pricing engine
  - _Ref: Black & Scholes 1973, J. Political Economy (~40,000 citations) — closed-form Greeks: Δ=N(d₁), Γ=N'(d₁)/(Sσ√T)_
  - _Ref: Heston 1993, Review of Financial Studies (~9,400 citations) — stochastic volatility: dv = κ(θ−v)dt + σ√v dW_
  - _Ref: Gatheral & Jacquier 2012, Quantitative Finance — SVI implied vol surface: σ²(k) = a + b[ρ(k−m) + √((k−m)²+σ²)]_
  - _Ref: Hull 2021, "Options, Futures, and Other Derivatives" (11th ed) — hedging strategy selection framework_
- [x] Cross-market arbitrage detection (PCA eigenportfolios + pairs trading)
  - _Ref: Avellaneda & Lee 2010, Quantitative Finance (~800 citations) — PCA eigenportfolios, s-score = (r−r̄)/σ_eq, Sharpe 1.44_
  - _Ref: Gatev, Goetzmann & Rouwenhorst 2006, Review of Financial Studies (~2,000 citations) — distance method, 11% annualized excess return_
  - _Ref: Vidyamurthy 2004, "Pairs Trading" (Wiley) — cointegration-based pair identification_
- [x] Macro-economic factor integration
  - _Ref: Chen, Roll & Ross 1986, J. Business (~5,000 citations) — five macro factors: industrial production, inflation, credit spread, term spread, consumption_
  - _Ref: Ang & Piazzesi 2003, J. Monetary Economics (~2,500 citations) — affine term structure with macro variables, 85% yield variance explained_
  - _Ref: Ludvigson & Ng 2009, Review of Financial Studies (~1,500 citations) — PCA on 100+ macro indicators for latent factor extraction_
- [x] Tax-loss harvesting engine (US + India tax rules)
  - _Ref: Israelov & Lu 2022, AQR Capital (SSRN 4152425) — optimal harvesting cadence, tax alpha 20-80 bps/year, degradation: y(t)=B₀·e^(-λt)_
  - _Ref: Berkin & Ye 2003, J. Wealth Management (~300 citations) — HIFO lot selection maximizes harvested losses_
  - _Ref: Stein et al. 2010, Parametric Portfolio Associates — wash-sale rule, substitute correlation ρ > 0.90_
- [x] Portfolio rebalancing automation with drawdown constraints
  - _Ref: Boyd et al. 2017, Stanford — MPC framework: cushion C_t = (d_max−d_t)/(1+d_max), risk aversion γ_t = γ₀/C_t_
  - _Ref: Ledoit & Wolf 2004, J. Multivariate Analysis (~3,500 citations) — shrinkage: Σ_shrunk = α·F + (1−α)·S_
  - _Ref: DeMiguel et al. 2009, Rev. Financial Studies (~6,000 citations) — 1/N benchmark, regularized optimization_
  - _Ref: Duchi et al. 2008 — efficient O(n log n) simplex projection for portfolio constraints_
- [x] Plugin architecture for custom strategy development
  - _Ref: Gamma et al. 1994, "Design Patterns" (GoF) — Strategy Pattern for interchangeable algorithms_
  - _Ref: Fowler 2002, "Patterns of Enterprise Application Architecture" — Plugin pattern with runtime discovery_

**Status:** Complete. All Phase 5 components implemented and verified (207 tests passing).

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

| Layer | Technology | Research Basis |
|-------|------------|----------------|
| Language | Python 3.11+ | — |
| Agent Framework | Custom (BaseAgent + AsyncIO) | — |
| ML - Regime | hmmlearn (HMM) → `jumpmodels` (Statistical Jump Model) | Hamilton 1989; Shu & Mulvey 2024 |
| ML - Volatility | `arch` (GJR-GARCH) | Hansen & Lunde 2005 (330-model comparison) |
| ML - Risk | `arch` + `scipy.stats.genpareto` (GARCH-EVT) | McNeil & Frey 2000; Kuester et al. 2006 |
| ML - Portfolio | `riskfolio-lib` (HRP + Ledoit-Wolf) | Lopez de Prado 2016; Ledoit & Wolf 2004 |
| ML - Sentiment | HuggingFace Transformers (FinBERT) | Araci 2019; Loughran & McDonald 2011 |
| ML - Mean Reversion | `statsmodels` (cointegration + OU process) | Avellaneda & Lee 2010; Gatev et al. 2006 |
| ML - Execution | Almgren-Chriss (closed-form) | Almgren & Chriss 2000 |
| ML - Position Sizing | Half-Kelly criterion | MacLean, Thorp & Ziemba 2011 |
| LLM - Strategy (Phase 2) | Anthropic Claude, OpenAI, Gemini (adaptive reasoning) | — |
| LLM - Debate | Anthropic Claude API | — |
| Data | pandas, numpy, ta (technical analysis) | — |
| Storage (Local) | SQLite + aiosqlite | — |
| Storage (Prod) | PostgreSQL + asyncpg | — |
| Messaging (Local) | In-memory async queue | — |
| Messaging (Prod) | Redis pub/sub | — |
| Terminal UI | Rich | — |
| Web API | FastAPI (optional, for production) | — |
| Testing | pytest + pytest-asyncio | — |

> **All ML/algorithmic components are grounded in peer-reviewed research.**
> See [RESEARCH_PAPERS.md](RESEARCH_PAPERS.md) for full citations (40+ papers).
