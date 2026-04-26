# Horizon Capital — College Project Design

**Date:** 2026-04-06
**Status:** Draft

---

## Overview

A multi-agent AI trading platform that demonstrates: department-based agent hierarchy, LLM-powered debate between agents using different providers, real market data from multiple sources, sentiment analysis, paper trading, backtesting, and a live terminal dashboard.

A standalone, self-contained project. No external modules or plugins.

---

## Architecture

```
horizon-capital/backend/app/
├── agents/
│   ├── executive/              # CIO agent
│   ├── front_office/
│   │   ├── strategy/           # 3 basic strategies
│   │   ├── research/           # Basic sentiment analysis
│   │   ├── portfolio/          # Equal-weight allocation
│   │   └── trading/            # Paper broker only
│   ├── middle_office/
│   │   ├── risk/               # Position limits, daily loss cap, basic VaR
│   │   └── compliance/         # Basic rule checks
│   └── back_office/
│       └── operations/         # Settlement, reporting
├── core/
│   ├── runtime.py              # App lifecycle
│   ├── messaging.py            # ~15 message types
│   ├── database.py             # SQLite only
│   ├── config.py               # Settings
│   └── resilience.py           # Basic error handling
├── data_layer/
│   ├── yahoo_feed.py           # Yahoo Finance — Indian + US equities
│   ├── alpaca_feed.py          # Alpaca — US equities
│   └── coingecko_feed.py       # CoinGecko — crypto
├── workers/
│   ├── data_ingestion.py       # Polls feeds, publishes OHLCV
│   ├── feature_computation.py  # Basic indicators (RSI, MACD, BB, SMA, EMA)
│   └── performance.py          # Basic P&L tracking
├── services/
│   ├── alert_manager.py        # Simple console alerts
│   └── health_monitor.py       # Basic uptime checks
├── backtesting/
│   ├── backtest_engine.py      # Bar-by-bar replay
│   └── backtest_metrics.py     # Sharpe, max drawdown, win rate
└── tui/
    ├── dashboard.py            # Rich live dashboard
    └── repl.py                 # ~15 REPL commands
```

---

## Agent System

### Department Structure

- **Executive**: CIO agent reviews portfolio state, issues high-level directives
- **Front Office**: Strategy (signal generation), Research (sentiment), Portfolio (allocation), Trading (execution)
- **Middle Office**: Risk (limit checks), Compliance (rule validation)
- **Back Office**: Operations (settlement, reporting)

### Debate System

Multiple LLM providers (GPT-4, Claude, etc.) assigned to different agents. They debate trades with text reasoning. Simple majority vote (approve/reject/abstain). Debate history logged and viewable via REPL.

Example flow:
1. Strategy agent generates BUY signal for AAPL
2. DEBATE_START published to bus
3. Agent A (GPT-4) argues bullish case
4. Agent B (Claude) argues bearish case
5. Agent C casts deciding vote
6. Simple majority -> DEBATE_CONCLUSION (APPROVED/REJECTED)
7. If approved -> ORDER_NEW -> paper execution

### Sentiment Analysis

- Fetch headlines from free news API (e.g., NewsAPI, Finnhub)
- Keyword-based scoring: positive/negative/neutral per symbol
- Score displayed on dashboard
- Published as SENTIMENT_UPDATE on message bus

---

## Data Feeds

| Feed | Markets | Frequency |
|------|---------|-----------|
| Yahoo Finance | Indian + US equities | Daily bars |
| Alpaca | US equities | Daily bars |
| CoinGecko | Crypto | Every 60s |

---

## Message Types (~15)

TICK, OHLCV, FEATURE_UPDATE, SIGNAL, RISK_CHECK, RISK_ALERT, DEBATE_START, DEBATE_VOTE, DEBATE_CONCLUSION, ORDER_NEW, ORDER_FILL, ORDER_CANCEL, PORTFOLIO_UPDATE, HEALTH_CHECK, SENTIMENT_UPDATE

---

## Strategies

1. **RSI Strategy**: RSI < 30 -> BUY, RSI > 70 -> SELL
2. **MACD Crossover**: MACD crosses above signal line -> BUY, below -> SELL
3. **Bollinger Band Mean Reversion**: Price below lower band -> BUY, above upper band -> SELL

All use fixed thresholds. No regime awareness, no adaptation, no ensemble.

---

## Risk Management

- Max 5% of portfolio per position
- 10% daily loss limit
- Basic historical VaR (95% confidence)
- Reject trades that breach limits

---

## Portfolio Management

- Equal-weight allocation across positions
- Track positions, P&L, NAV
- No optimization algorithms

---

## Orchestrator

- Starts all agents and workers in correct order
- Worker supervision with auto-restart on crash
- Graceful shutdown

---

## Backtesting

- Bar-by-bar replay engine
- Metrics: Sharpe ratio, max drawdown, win rate, total return
- Single-pass (no walk-forward, no Monte Carlo)

---

## TUI

- Live Rich dashboard: portfolio, positions, signals, debates, sentiment
- ~15 REPL commands: portfolio, positions, orders, signals, backtest, debate history, sentiment, agents, health, help, risk, performance, config, status, quit

---

## LLM Integration

- Multiple providers supported (OpenAI, Anthropic, local models)
- Different agents use different providers for debate
- Used for debate reasoning text
- Configurable via settings

---

## Storage

- SQLite only (LOCAL mode)
- In-memory message bus
- No Docker required

---

## Constraints

- Python 3.14, Windows 11
- Desktop terminal agent (Rich TUI + REPL)
- Paper trading only
- `ta` pure Python library for indicators
- `bcrypt` directly for Python 3.14 compatibility
