# Horizon Capital desktop app: 2 Nov 2026 update

Dark theme, 1440 px wide, engine off. Data is the real paper-trading book: about $1M NAV, last activity 13 Oct 2026.

## New features

| # | Feature | What it does | Screenshot |
|---|---------|--------------|------------|
| 1 | **Live org chart** | The fund drawn as a firm, with 13 agents in 4 departments and 24 message links. The links come from the agents' real code. While the engine runs, each message pulses along its link. Click an agent to see who it talks to and its latest messages. | 02, 03 |
| 2 | **Trade timeline** | Click any order to trace it: signal → risk check → debate → order → fill → P&L, with the time each step took. | 04 |
| 3 | **Market regime gauge** | Risk-on/risk-off dial with confidence, from the same model the strategy uses, next to the strategy mix it drives. | 01 |
| 4 | **Morning brief** | What happened since your last visit: overnight P&L, regime, risk, pending approvals, positions near their stop, recent debates. | 01 |
| 5 | **Backtest studio** | Run a strategy on any symbols and dates. Shows equity vs SPY, drawdown, 7 key metrics and every trade. Past runs are saved and two can be compared. | 05 |
| 6 | **Analysis page (9 tabs)** | Covers everything you'd check before trusting the system with money. See below. | 08–16 |

### Analysis tabs
- **Attribution:** which positions and strategies made or lost money.
- **Exposure:** split by asset class, beta to SPY, correlation between holdings.
- **Decisions:** debate approval rate, how each role and AI model votes, whether approved trades beat rejected ones, signal hit rates.
- **Execution:** slippage per fill and per broker.
- **Risk:** stress tests (SPY −5/−10/−20%, crypto −30%, worst past day and week), loss if every stop hits, positions with no stop, days to exit, concentration.
- **Trades:** expectancy, average win vs loss, streaks, holding periods, turnover.
- **Benchmark:** alpha, beta, tracking error, information ratio, up/down capture vs SPY.
- **Costs:** fees, slippage and AI model spend ($1.36 over 326 calls, about $0.035 per debate).
- **Health:** how fresh each data feed is, AI provider failures, unread alerts.

Every number shows its sample size. Below the minimum it shows "—" and how much data is still needed, rather than a misleading figure.

## Fixes and improvements

| Area | Before | After |
|------|--------|-------|
| Engine-off warning | The only sign the engine was off was a small red dot. Old prices looked current. | A banner on every page shows how old the data is, with a **Start engine** button. |
| Debate text (06) | Some arguments showed raw JSON, and their confidence was replaced by 0.50. | The argument text, vote and confidence are recovered from the AI's malformed reply. |
| Performance (07) | "+48% annualised" and Calmar 364 from 3 days of data. | Shows "—" with "3 of 30 days needed". Win rate and profit factor need 10 trades. |
| Risk VaR | Showed "$0.0010" on a $1M book. | Shows **$1,012 (0.10% of NAV)**. The limit bar is fixed too. |
| Portfolio vs SPY chart | A noisy chart drawn from 3 points. | "Building history: 3 of 5 days". |
| Long charts | Synced chart pairs showed only the last ~190 points (a 4-year backtest showed 10 months). | The full range is shown. Only pan and zoom you do yourself sync between charts. |
| Trading blotter | Opened on the empty Pending tab. | Opens on the first tab that has entries. |
| Agents page | A red "No orchestrator" error when the engine was off. | The full org chart, with a short note. |
| Frontend build | Failed with 5 TypeScript errors. | Builds cleanly. |
| Regime (morning brief) | Used 1-minute bars by mistake, and with short history showed a fake "RISK_OFF 0%". | Uses daily bars, and says "unavailable" when there isn't enough history. |
| Debate ↔ trade link | New debates weren't saved with the id of the signal they came from. | They are now, so the trade timeline links by id. |
| Backtest strategies | The same strategies were defined twice and could drift apart. | One shared copy. An unknown strategy name now gets an error. |

Tests: all 668 backend tests pass, lint is clean, and the frontend builds.

## What the analysis found
- **Claude debaters are failing:** the Claude API key is rejected (401), so 46 of Claude's 232 debate votes were errors. Two Polymarket buys went ahead after debates where every debater failed.
- **Unprotected positions:** 3 positions have no stop-loss: DOGE, SOL and XRP ($40.6k).
- **Loss if every stop hits:** −$37.8k (3.8% of NAV).
- **Crypto isn't modelled:** there are no daily crypto prices, so the $80.7k in crypto has no volatility, beta or stress history.
- **Prices have stopped:** daily bars end on 13 Oct, so "did approved trades make money" can't be measured yet.
- **Morning brief disagrees with the Risk page:** the brief shows VaR 0.00% and drawdown 0.00%, while the Risk page shows 0.10% and −0.08%. The brief reads an older stored snapshot. Not fixed yet.

## Screenshots
| File | Shows |
|------|-------|
| 01-overview-morning-brief-regime-gauge.png | Overview: morning brief, regime gauge, strategy mix |
| 02-agents-org-chart.png | Org chart (engine off) |
| 03-agents-org-chart-node-selected.png | Execution agent selected: links and channels |
| 04-trading-trade-timeline.png | SPY buy traced from signal to P&L |
| 05-backtest-finished-run.png | Momentum backtest on AAPL/MSFT/NVDA, 2023–2026, vs SPY |
| 06-debates-clean-argument-text.png | Debate with the repaired argument text |
| 07-performance-withheld-metrics.png | Metrics withheld until there's enough history |
| 08–16-analysis-*.png | The 9 Analysis tabs |
