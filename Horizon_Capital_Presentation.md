# Horizon Capital: An Autonomous AI-Powered Hedge Fund Platform with Multi-Agent Debate Consensus

### Sem VI & VII Major Project
### Department of Computer Engineering

**Mentored by Dr [Your Mentor's Name]**

[Your Name]
[Team Member Names]

---

# Problem Definition

Algorithmic trading systems are increasingly dominant in financial markets, yet most retail and mid-tier institutional investors lack access to **intelligent, multi-agent decision-making frameworks** that combine quantitative analysis with AI-driven reasoning. Existing trading platforms rely on **single-strategy models** that fail to adapt to changing market regimes, leading to significant drawdowns during volatility shifts and regime transitions.

## Existing Challenges

- **No unified multi-agent collaboration** -- most systems use isolated strategies without cross-validation or debate-based consensus
- **Poor regime adaptability** -- static strategies fail during regime transitions (bull to bear, low to high volatility)
- **Fragmented data sources** -- market data from multiple brokers (India NSE/BSE, US NYSE/NASDAQ, Crypto) remains siloed and underutilized
- **Limited risk governance** -- lack of real-time kill switches, VaR monitoring, and autonomous circuit breakers
- **Opaque decision-making** -- no audit trail or explainability for why trades are executed

## Need for the Proposed Solution

- **Multi-agent AI system** where specialized agents debate and reach consensus before executing trades
- **Regime-aware strategy switching** using Hidden Markov Models (HMM) to detect market state transitions
- **Production-grade risk management** with VaR, Conditional VaR, kill switches, and pre-trade validation
- **Transparent, auditable decision pipeline** with full debate history and per-trade attribution

---

# Literature Review

| Broad Research Area | Gaps Identified from Literature | Proposed Solution in This Work |
|---|---|---|
| **1. Multi-Agent Systems in Algorithmic Trading** | - Existing multi-agent systems lack structured consensus mechanisms<br>- Limited use of LLMs for financial reasoning<br>- No debate-based decision architecture in trading platforms | Developing a **4-agent debate engine powered by Claude AI** with structured argument rounds, JSON vote parsing, and consensus calculation for trade decisions |
| **2. Market Regime Detection & Adaptive Strategies** | - Most systems use static strategy allocation<br>- HMM-based regime detection not integrated with real-time strategy switching<br>- Limited drift detection for regime transitions | Implementing **HMM regime detection + LFR drift detection** that automatically routes signals through appropriate strategies (Momentum, Mean Reversion, Volatility, Crisis Alpha) |
| **3. Risk Management & Portfolio Optimization** | - Retail platforms lack institutional-grade risk controls<br>- VaR and CVaR not commonly applied in automated systems<br>- No real-time kill switch mechanisms | Designing an **institutional-grade risk framework** with VaR (95%/99%), Conditional VaR, Kelly criterion sizing, drawdown-based kill switch, and pre-trade compliance validation |

*Table 1. Literature Review Summary*

---

# Scope of Project

## Functional Requirements

1. **Multi-Source Market Data Ingestion** - Collects real-time and historical OHLCV data from Yahoo Finance, Alpaca, Zerodha, Polygon.io, CoinGecko, and forex APIs
2. **Feature Engineering & Technical Analysis** - Computes 20+ technical indicators (RSI, MACD, Bollinger Bands, ATR, GARCH volatility) and sentiment features (FinancialBERT + NewsAPI)
3. **Multi-Agent Debate & Consensus** - 4 specialized AI agents (Strategy, Risk, Sentiment, Portfolio) debate trade decisions using Claude AI with structured voting
4. **Autonomous Trade Execution** - Supports Paper Trading, Human Approval, and Fully Autonomous execution modes across Indian equities, US equities, and cryptocurrency
5. **Rich Terminal Dashboard & REPL** - Live TUI dashboard with 30+ interactive commands for portfolio monitoring, backtesting, stress testing, and CIO governance

## Non-Functional Requirements

1. **Scalability** - Supports multiple asset classes (equities, crypto, forex), multiple brokers, and extensible strategy plugins
2. **Resilience & Fault Tolerance** - Circuit breakers on all external APIs, worker auto-restart supervision, exponential retry with jitter
3. **Security** - JWT authentication, password validation, startup secret warnings, CORS configuration, security headers (HSTS, X-Frame-Options)
4. **Performance** - Near real-time data processing with 2fps TUI refresh, in-memory message bus for low-latency agent communication
5. **Zero-Infrastructure Local Mode** - Runs entirely on SQLite + in-memory bus with no Docker, PostgreSQL, or Redis required

---

# Dataset Description

*Data sourced from multiple financial market APIs and providers*

| Name | Source | Key Parameters | Description / Purpose |
|---|---|---|---|
| **Market OHLCV Data** | Yahoo Finance, Alpaca, Polygon.io | Open, High, Low, Close, Volume, Adjusted Close, Timestamps | Historical and real-time price data for equities (NSE/BSE, NYSE/NASDAQ) used for technical analysis and backtesting |
| **Crypto Market Data** | CoinGecko API | Price, Market Cap, 24h Volume, Price Change %, Supply metrics | Cryptocurrency price feeds for BTC, ETH and other digital assets enabling cross-asset strategy execution |
| **Sentiment & News Data** | NewsAPI, Reddit (PRAW) | Article text, sentiment scores, publication timestamps, social engagement metrics | Financial news and social media data processed through FinancialBERT NLP for sentiment features and narrative lifecycle tracking |
| **Macroeconomic Data** | Public APIs / Manual feeds | Interest rates, yield curve spreads, credit spreads, VIX | Macro factor inputs for regime detection and risk assessment across market scopes (India, US, Global) |

*Table 2. Dataset Description*

---

# Technical Requirements

## Data Sources
- Yahoo Finance (Global Equities)
- Alpaca (US Paper + Live Trading)
- Zerodha Kite (India NSE/BSE F&O)
- CoinGecko (Cryptocurrency)
- Polygon.io (Premium US Data)
- NewsAPI / Reddit (Sentiment)
- Macro APIs (Rates, Yield Curve, VIX)

## Processing Pipeline
- Data Collection & Normalization
- Feature Engineering (20+ Technical Indicators)
- Regime Detection (HMM + LFR Drift)
- Agent Orchestration & Messaging
- Risk Validation & Compliance
- Debate Consensus & Trade Execution

## ML/AI Implementation
- HMM (Regime Detection)
- FinancialBERT (Sentiment NLP)
- GARCH (Volatility Modeling)
- Claude AI (Debate Reasoning)
- Thompson Sampling (Strategy Selection)
- Kelly Criterion (Position Sizing)

## Technology Stack

| Layer | Technology |
|---|---|
| **Backend** | Python, FastAPI, Uvicorn, SQLAlchemy |
| **Database** | SQLite (Local) / PostgreSQL (Production) |
| **Messaging** | Redis Pub/Sub / In-Memory Bus |
| **Terminal UI** | Rich (Live Dashboard, 2fps refresh) |
| **AI/ML** | Anthropic Claude, hmmlearn, FinancialBERT |
| **Data** | pandas, numpy, yfinance, httpx |
| **Frontend** | React 18, TypeScript, Vite, Tailwind CSS |
| **Testing** | pytest (300+ tests), Ruff linter (0 errors) |

*Fig 1. Technical Workflow and System Components*

---

# Overview of Project

## System Architecture

```
+-------------------------+   +------------------------------------------+   +---------------------------+
|    DATA INGESTION       |   |    INTELLIGENCE & PROCESSING CORE        |   |  CONSUMPTION & INSIGHTS   |
|                         |   |                                          |   |                           |
| Yahoo Finance           |   |  Feature Engineering & Preprocessing     |   |  Rich Terminal Dashboard   |
|  (Global Equities)      |   |  +--------+ +----------+ +----------+   |   |  (Live Agent Status,      |
|                         |-->|  | Clean  |>|Normalize |>| Extract  |   |-->|   Signals, Portfolio)     |
| Alpaca / Zerodha        |   |  +--------+ +----------+ +----------+   |   |                           |
|  (India & US Brokers)   |   |                                          |   |  REPL Command Interface    |
|                         |   |  Multi-Agent Debate Engine (Claude AI)   |   |  (30+ Commands: backtest,  |
| CoinGecko               |   |  +----------+ +--------+ +-----------+  |   |   stress-test, alerts,    |
|  (Cryptocurrency)       |   |  | Strategy | |  Risk  | | Sentiment |  |-->|   report, health)         |
|                         |   |  | Debater  | |Debater | |  Debater  |  |   |                           |
| NewsAPI / Reddit        |   |  +----------+ +--------+ +-----------+  |   |  Pixel Agent Visualizer    |
|  (Sentiment)            |   |         4-Agent Consensus Voting         |   |  (Animated ASCII Office)   |
|                         |   |                                          |   |                           |
| Macro Factors           |   |  Risk & Compliance Layer                 |   |  CIO Governance Chat      |
|  (Rates, Yield Curve)   |   |  VaR | CVaR | Kill Switch | Kelly Size  |-->|  (Natural Language AI)    |
+-------------------------+   +------------------------------------------+   +---------------------------+
                              |                                          |
                              |  Infrastructure                          |
                              |  SQLite/PostgreSQL | Redis/MemoryBus     |
                              |  Circuit Breakers  | Worker Supervision  |
                              |                                          |
                              |  Security & Governance                   |
                              |  JWT Auth | CORS | Security Headers      |
                              +------------------------------------------+
```

*Fig 2. Overall System Architecture*

---

# Schedule for Sem VI

| Task | Begin Date | End Date |
|---|---|---|
| **Project Planning** | **15/01/26** | **30/01/26** |
| -- Project proposal & title approval | 15/01/26 | 30/01/26 |
| -- Literature survey (multi-agent systems, regime detection, risk mgmt) | 23/01/26 | 27/01/26 |
| -- Approved project title | 30/01/26 | 30/01/26 |
| **Core Infrastructure Development** | **01/02/26** | **15/02/26** |
| -- Message bus & agent base framework | 01/02/26 | 05/02/26 |
| -- Multi-source data ingestion (Yahoo, Alpaca, CoinGecko) | 06/02/26 | 10/02/26 |
| -- Feature engineering (20+ technical indicators) | 11/02/26 | 15/02/26 |
| -- Core infrastructure complete | 15/02/26 | 15/02/26 |
| **Agent System & Debate Engine** | **16/02/26** | **28/02/26** |
| -- Strategy agents (Momentum, Mean Reversion, Volatility, Crisis) | 16/02/26 | 22/02/26 |
| -- Claude AI debate engine & consensus voting | 23/02/26 | 28/02/26 |
| -- Agent system operational | 28/02/26 | 28/02/26 |
| **Mid-Term Evaluation** | **17/03/26** | **20/03/26** |
| -- Mid-term presentation & demo | 17/03/26 | 20/03/26 |
| **Production Hardening & Advanced Features** | **21/03/26** | **10/04/26** |
| -- Risk management (VaR, kill switch, circuit breakers) | 21/03/26 | 28/03/26 |
| -- Rich TUI dashboard & REPL commands | 29/03/26 | 04/04/26 |
| -- Stress testing, alerts, reporting, health monitoring | 05/04/26 | 10/04/26 |
| -- Production-hardened system complete | 10/04/26 | 10/04/26 |

*Fig 3. Project Schedule for Semester VI*

---

# References

1. Hamilton, J.D. (1989). "A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle." *Econometrica*, 57(2), 357-384. (HMM Regime Detection)
2. Rockafellar, R.T. & Uryasev, S. (2000). "Optimization of Conditional Value-at-Risk." *Journal of Risk*, 2(3), 21-42. (VaR & CVaR)
3. MacLean, L.C., Thorp, E.O. & Ziemba, W.T. (2011). "The Kelly Capital Growth Investment Criterion." *World Scientific*. (Kelly Criterion Sizing)
4. Araci, D. (2019). "FinBERT: Financial Sentiment Analysis with Pre-trained Language Models." (FinancialBERT NLP)
5. Kirilenko, A. et al. (2017). "The Flash Crash: High-Frequency Trading in an Electronic Market." *Journal of Finance*. (Flash Crash Analysis)
6. Lu, J. et al. (2019). "Learning under Concept Drift: A Review." *IEEE TKDE*. (LFR Drift Detection)
7. Anthropic Claude API Documentation -- Multi-agent debate reasoning
8. Data Sources: Yahoo Finance, Alpaca Markets, Zerodha Kite, CoinGecko, Polygon.io, NewsAPI
