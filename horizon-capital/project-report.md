# Horizon Capital — Project Report

## Section One: Problem Definition

Most algorithmic trading tools available today work as single-program systems where all logic runs in one place. They don't show users how or why a particular trading decision was made. For students and researchers trying to learn about quantitative finance and AI, these tools are also difficult to set up since they often need cloud servers, Docker, and paid data subscriptions.

This project, **Horizon Capital**, is a **simulation-only paper trading platform** built as a college project. It does not connect to any real brokerage or use real money — all trades are simulated. The system is structured as multiple AI agents organized into departments (similar to how a hedge fund is organized), where each agent has a specific role. Before a simulated trade is placed, an LLM-based debate module lets multiple AI perspectives argue for or against the trade, making the decision process visible and explainable. The platform runs entirely in the terminal using a text-based dashboard and command-line interface, and can be set up locally with no external services required.

---

## Section Two: Activities and Progress

During the current reporting period, the focus was on building out the core modules and getting the system to a working state.

The **multi-agent structure** was implemented with agent files organized across 4 departments (Front Office, Middle Office, Back Office, Executive). These agents communicate through an in-memory message bus. A **feature engineering module** was built that computes technical indicators like SMA, EMA, MACD, RSI, Bollinger Bands, and others using the `ta` Python library.

The **AI debate module** was built where four LLM-powered debaters (Strategy, Risk, Sentiment, Portfolio) each receive market context and independently vote for or against a proposed trade. The system supports Claude, GPT, and Gemini as LLM providers, but also works without any API keys by falling back to rule-based logic.

A **backtesting module** was implemented that replays historical price data bar-by-bar and runs strategy logic against it to produce basic performance metrics (Sharpe ratio, max drawdown, equity curve).

The **terminal dashboard** was built using the Rich library, showing live market data, agent statuses, and portfolio state. A **REPL command interface** provides 30+ commands for interacting with the system (e.g., `backtest AAPL --days 100`, `portfolio`, `signals`, `debate history`).

Data storage uses **SQLite** with 23 tables for storing agent states, signals, orders, positions, and other records. The codebase has **302 passing tests** and zero lint errors.

---

## Section Three: Financial Statement

As this project is primarily software-based, no significant financial expenditure has been incurred during this reporting period.

| Budget Head | Allocated Budget | Expenditure (Current Period) | Total Expenditure |
|---|---|---|---|
| Software Tools | Minimal (Open-source) | 0 | 0 |
| LLM API Credits | Pay-per-use | Minimal (testing only) | Minimal |
| Cloud Services | Not yet utilized | 0 | 0 |
| Data Feeds | Free-tier APIs | 0 | 0 |
| Miscellaneous | - | 0 | 0 |

The project uses open-source libraries and free-tier APIs (Yahoo Finance for price data, CoinGecko for crypto prices). LLM provider keys (Claude, GPT, Gemini) were used during testing but are not required to run the system. No cloud services have been used.

---

## Section Four: Outputs and Deliverables

The following outputs have been completed during this phase:

- **Agent architecture** — Python modules organized into 4 departments with message bus communication
- **Feature engineering module** — Technical indicators (SMA, EMA, MACD, RSI, Bollinger Bands, etc.) computed from price data
- **AI debate module** — 4 LLM debaters evaluate trade proposals and vote with structured arguments
- **Backtesting module** — Historical replay engine that runs strategies against past price data
- **Sentiment analysis module** — Keyword-based scoring of news headlines, with optional FinancialBERT support
- **Terminal dashboard** — Rich-based TUI showing market data, agents, and portfolio
- **REPL command interface** — 30+ text commands for interacting with the system
- **SQLite storage** — 23 tables for persisting system state
- **Test suite** — 302 passing tests, zero lint errors
- **Authentication module** — JWT tokens and password hashing for the optional web API

The following are still in progress:

- Stress testing with historical crisis scenarios
- Documentation and user guide
- Additional trading strategies beyond momentum and mean reversion

---

## Section Five: Outcomes and Lessons Learned

The main outcome so far is a working paper trading simulation where agents communicate, debate trades, and produce explainable decisions — all viewable through a terminal interface.

Key lessons learned include:

- **Message bus design matters** — using typed message enums with pub/sub was easier to maintain than having agents call each other directly
- **LLM outputs need structure** — the debate system only produced useful results after adding defined roles, scoring rubrics, and consensus thresholds
- **Keeping setup simple helps** — the LOCAL mode (SQLite + in-memory bus, no Docker) made development and testing much faster
- **Library compatibility is a real issue** — some Python libraries (passlib, hmmlearn) broke on Python 3.14 and needed workarounds or replacements
- **Fallback logic is necessary** — the system needed to work without LLM API keys, so rule-based defaults were added throughout

---

## Section Six: Dissemination

No external dissemination activities such as paper presentations or competitions have been undertaken at this stage.

The team plans to:

- Present the project at internal academic seminars
- Prepare documentation suitable for use as a learning resource

---

## Section Seven: Risks, Issues, Challenges, and Constraints

### Risks and Challenges

- **Market Data Availability**: Free-tier APIs (Yahoo Finance, CoinGecko) can rate-limit, return stale data, or go down temporarily
- **LLM Output Variability**: Different LLM providers give different quality responses, and outputs can be inconsistent across runs
- **Python 3.14 Compatibility**: Several dependencies had breaking changes on Python 3.14 and needed manual fixes or replacements
- **Simulation Accuracy**: Paper trading with simulated fills does not reflect real market conditions (slippage, liquidity, order book depth)

### Mitigation Strategies

- Circuit breaker pattern falls back to cached data when APIs fail
- Consensus thresholds and structured prompts reduce LLM inconsistency
- Lazy imports for optional dependencies so the core system runs even if some libraries are missing
- System is clearly labeled as simulation-only and does not support real trading

### Constraints

- Only uses delayed price data from free APIs (not real-time)
- Free-tier API rate limits restrict how often data can be fetched
- LLM API costs limit how much the debate system can be tested
- Academic timeline limits the number of strategies and features that can be implemented
- The system is a simulation tool for learning purposes and cannot execute real trades

---

## Section Eight: Institutional & Project Partner Issues

No institutional or project partner issues have been encountered during this reporting period. The project is being developed independently within the academic environment using open-source tools and free-tier services.

---

## Section Nine: Next Steps

The following activities are planned for the next phase:

- Add more trading strategies beyond the current momentum and mean reversion
- Implement stress testing with historical market scenarios
- Improve the backtesting module with more detailed reporting
- Write user-facing documentation and a setup guide
- Optimize performance of the feature computation pipeline
- Clean up and finalize the codebase for submission
