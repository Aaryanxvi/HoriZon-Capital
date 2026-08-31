# Horizon Capital — Autonomous AI Trading Simulator

**Python · Rich TUI · Multi-agent LLM system · SQLite · FastAPI · React**

## What it is

Horizon Capital is a paper-trading platform I built as a full desktop terminal
application, structured the way an actual hedge fund is — as an org chart of
specialized agents rather than one monolithic script. Front Office, Middle
Office, Back Office, and Executive "departments" each run their own agents that
talk to one another over an in-memory message bus, so a trade decision moves
through the firm the same way it would through real desks.

The part I'm most proud of is the debate layer: before any simulated trade is
placed, four LLM debaters — Strategy, Risk, Sentiment, and Portfolio — each get
the market context independently and argue for or against the position. The
system reaches a consensus with defined scoring thresholds, and every decision
is fully explainable after the fact. It runs against Claude, GPT, or Gemini, and
degrades cleanly to rule-based logic when no API keys are present, so the whole
thing works offline.

## What I built

- **Multi-agent architecture** — agents across four departments coordinating
  through a typed pub/sub message bus instead of direct calls, which kept the
  system decoupled as it grew.
- **LLM debate engine** — four-perspective adversarial evaluation of every trade
  with structured arguments, role-specific prompts, and consensus voting.
- **Feature engineering** — SMA, EMA, MACD, RSI, Bollinger Bands and other
  indicators computed from live price data (Yahoo Finance, CoinGecko).
- **Backtesting engine** — bar-by-bar historical replay producing Sharpe ratio,
  max drawdown, and equity curves.
- **Terminal dashboard + REPL** — a Rich-based live TUI plus a command interface
  with 30+ commands (`backtest AAPL --days 100`, `portfolio`, `debate history`).
- **Three trading modes** — paper trading, human-in-the-loop approval, and a
  fully autonomous mode gated behind the debate consensus.
- **Persistence** — SQLite with 23 tables backing agent state, signals, orders,
  and positions; a zero-infra LOCAL mode and an optional Postgres/Redis path.
- **Optional web stack** — FastAPI backend, React/TypeScript dashboard, and an
  Electron wrapper for a native desktop app.

Engineered for correctness — 302 passing tests, zero lint errors — and for
honesty about its own results: I ran a validation gate that showed the strategy's
real edge is in drawdown control, not headline returns, and wrote the reporting
to reflect that rather than a cherry-picked backtest.

## In progress / roadmap

*Designed and partially scaffolded, not yet complete:*

- **Stress testing** against historical crisis scenarios (2008, 2020, flash
  crashes) to pressure-test risk limits.
- **Deep reinforcement learning** — a DRL layer (stable-baselines3) and an HMM
  market-regime detector to move beyond the current rule-based signals.
- **Expanded strategy library** beyond momentum and mean reversion.
- **Richer backtest reporting** — per-agent attribution and trade-level analytics.

## What I learned

Getting useful output from LLMs took real structure — defined roles, scoring
rubrics, and consensus thresholds — not just good prompts. Designing the message
bus around typed events instead of direct agent calls made the system far easier
to extend. And building everything to run with no external services (SQLite,
in-memory bus, rule-based fallbacks) meant I could iterate fast and anyone can
run it in one command.
