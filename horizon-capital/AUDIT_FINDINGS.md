# Horizon Capital — Audit Findings (2026-04-25)

Two-part audit: **(A)** concrete bugs & logic errors in code, **(B)** root-cause diagnosis of why the paper account is bleeding money.

Findings are ranked **CRITICAL / HIGH / MEDIUM / LOW** by impact on P&L.

---

## PART B — ROOT CAUSES OF LOSSES (read this first)

Five bugs, any one alone enough to guarantee losses. Stacked = guaranteed bleed.

### B1. CRITICAL — Paper broker half-spread is 6.25% per trade

File: [paper_broker.py:26](horizon-capital/backend/app/agents/front_office/trading/paper_broker.py:26)

```python
_TEMPORARY_IMPACT_EPSILON = 0.0625  # temporary impact half-spread
...
temporary = (
    _TEMPORARY_IMPACT_EPSILON * price          # <-- 6.25% of price, flat
    + _TEMPORARY_IMPACT_ETA * volatility * price * (participation ** _TEMPORARY_IMPACT_GAMMA)
)
```

`epsilon * price` = 6.25% of the share price added as slippage on **every** trade. On a $100 stock the fill happens at $106.25 on BUY, $93.75 on SELL. Round-trip cost = **12.5% before any market move**.

A retail stock rarely moves 12% a day. No strategy can climb out of that hole. This single line makes the system a losing machine by construction.

**Fix:** `epsilon` should be a fraction (e.g. `0.0001` = 1 bp). Almgren-Chriss literature uses the half-spread in *dollars*, not `epsilon * price`.

---

### B2. CRITICAL — Wrong currency bucket on every Indian-stock trade

Files: [portfolio_agent.py:273-290](horizon-capital/backend/app/agents/front_office/portfolio/portfolio_agent.py:273), [execution_agent.py:374](horizon-capital/backend/app/agents/front_office/trading/execution_agent.py:374)

Strategy agent's signal payload has no `exchange` field — see [strategy_agent.py:127-136](horizon-capital/backend/app/agents/front_office/strategy/strategy_agent.py:127). Downstream:

```python
available_cash = cash_inr if exchange in ("NSE", "BSE") else cash_usd
```

`exchange` is always `""`, so **every** trade drains USD cash. For `RELIANCE.NSE` priced at ₹3000, the system allocates USD, divides `allocation_usd / 3000` treating the INR price as USD, and books a 1-share position. Cash accounting diverges from position value immediately. Indian positions look "free" in INR accounting yet the USD cash register keeps paying.

**Fix:** derive `exchange` from `symbol.split(".")[1]` in strategy agent before emit. Map NSE/BSE→INR, NASDAQ/NYSE→USD, CRYPTO→USD.

---

### B3. CRITICAL — RSI thresholds emit signals nearly every bar

File: [simple_strategies.py:25-38](horizon-capital/backend/app/agents/front_office/strategy/simple_strategies.py:25)

Comment says `RSI < 30 oversold, > 70 overbought`. Code uses:

```python
if current_rsi < 45:    # BUY
...
elif current_rsi > 65:  # SELL
```

RSI spends ~80% of time in 45–65. Gap of only 20 pts means signals fire constantly. Equities trade around mean → strategy BUYS a mean-reversion dip, SELLS on next rally = churn + slippage drain. Combined with B1, every churn cycle pays 12.5%.

**Fix:** revert to 30/70 or use adaptive thresholds. Add volatility filter so mean-reversion only fires when ATR is elevated.

---

### B4. HIGH — Signals get re-emitted every 60s indefinitely

Files: [strategy_agent.py:77-87](horizon-capital/backend/app/agents/front_office/strategy/strategy_agent.py:77), [portfolio_agent.py:63](horizon-capital/backend/app/agents/front_office/portfolio/portfolio_agent.py:63)

Strategy polls every 60s on **daily** OHLCV data. The daily close doesn't change intraday until market close, so the same RSI/MACD/BB signal fires 390 times per session. Portfolio's 120-s cooldown only rate-limits — once the cooldown expires, the same stale signal becomes a new order.

Net effect: one valid signal → N orders per day → N × slippage.

**Fix:** strategy agent should key on bar timestamp and skip re-emitting for the same closed bar. Cooldown should be "one order per bar", not "one per 120s".

---

### B5. HIGH — SELL signal closes entire position; next BUY re-opens

File: [portfolio_agent.py:252-263](horizon-capital/backend/app/agents/front_office/portfolio/portfolio_agent.py:252)

```python
if direction < 0:
    held = p.get("quantity")
    ...
    return {"quantity": held, ...}
```

A tiny mean-reversion SELL (RSI=66) dumps 100% of the position. Next cycle BUYS back. Each round-trip pays B1's slippage. Classic over-trading pattern, mechanised.

**Fix:** SELL should reduce proportionally to signal strength (`qty = min(held, held * strength)`) or leave exits to stop-loss / target-price logic.

---

### Summary — why money is leaving

Pipeline each cycle: strategy fires on a meaningless 45/65 RSI → portfolio allocates USD for an INR stock (wrong bucket) → broker charges 6.25% slippage → fills at inflated price → 120s later same stale signal fires → fills again. Even without the currency bug, B1+B3+B4 alone compound into a negative-edge machine.

---

## PART A — ALL LOGIC ERRORS FOUND (by file)

### agents/front_office/strategy/

| # | Severity | File:line | Bug |
|---|---|---|---|
| 1 | CRIT | simple_strategies.py:25 | RSI thresholds 45/65 — see B3 |
| 2 | HIGH | simple_strategies.py:75-81 | MACD has two BUY branches (crossover AND trend-follow). Both fire same bar if crossed and `|diff|>0.5`. Duplicate signal. |
| 3 | HIGH | simple_strategies.py:107-119 | Bollinger asymmetric: BUY if pos<0.25, SELL if pos>0.85. Biased short. Normal convention is symmetric. |
| 4 | HIGH | strategy_agent.py:77-87 | Poll every 60s on daily data — re-emits same signal. See B4. |
| 5 | MED | strategy_agent.py:127 | Payload missing `exchange` — see B2. |
| 6 | MED | strategy_agent.py:95 | No market-hours check. Signals fire on weekends, holidays, after hours — daily bar unchanged, still emits. |
| 7 | MED | strategy_agent.py:180-193 | yfinance called inside agent loop, no rate-limit/backoff. Will hit rate limits across 12 symbols × 60s poll. |
| 8 | LOW | strategy_agent.py:50 | No volatility/regime filter. Mean-reversion (RSI, BB) runs in trending markets; trend-follow (MACD branch) runs in choppy markets. Contradictory positions. |

### agents/middle_office/risk/

| # | Severity | File:line | Bug |
|---|---|---|---|
| 9 | HIGH | risk_agent.py:285-319 | "Daily loss limit" sums `realized_pnl + unrealized_pnl` **across all time**, not today. Lifetime drawdown triggers the "daily" kill switch. |
| 10 | HIGH | risk_agent.py:258-283 | Position-limit check reads current weight, not post-order. A BUY that would push past the limit passes if current is below. Same check blocks SELLs that *reduce* over-limit exposure. |
| 11 | HIGH | risk_agent.py:242-244 | Kill switch auto-resets when drawdown recovers (`redis.set("horizon:system:halted","0")`). Should require manual reset. |
| 12 | MED | risk_agent.py:268-274 | `LIMIT 1` on `WHERE symbol = ...` — picks arbitrary row if same ticker trades on two exchanges. |
| 13 | LOW | risk_agent.py:325-360 | `_compute_var`, `_compute_max_drawdown` duplicated — dead code, real impls live in `VaRCalculator`. |

### agents/front_office/portfolio/

| # | Severity | File:line | Bug |
|---|---|---|---|
| 14 | CRIT | portfolio_agent.py:273-290 | Currency bucket bug — see B2. |
| 15 | CRIT | portfolio_agent.py:252-263 | SELL dumps entire position — see B5. |
| 16 | HIGH | portfolio_agent.py:266-271 | `num_positions = len(positions) + 1` means 1st BUY gets NAV/1 (all capital), 10th gets NAV/11. Non-equal weighting. |
| 17 | HIGH | portfolio_agent.py:120 | Cooldown set **before** sizing. Sizing returning qty=0 still locks the symbol for 120s. |
| 18 | HIGH | portfolio_agent.py:285 | `max_notional = 50_000` hardcoded and applied to both USD and INR. For NSE, 50k INR ≈ $600 — trades become too small to overcome slippage (especially at B1's 6.25%). |
| 19 | MED | portfolio_agent.py:466-474 | `_get_price` uses USD-assumption on raw cached price. For INR tickers, price is in INR but treated as USD in `qty = allocation_usd / price`. |
| 20 | MED | portfolio_agent.py:344 | `gross_leverage = (long+short)/nav`, but nav already contains position value. Divisor should be equity (cash + long - short), not nav. Understates true leverage. |
| 21 | MED | portfolio_agent.py:109-120 | Cooldown is per-symbol in-memory dict — not persisted. Restart clears cooldowns, allowing duplicate orders. |
| 22 | LOW | portfolio_agent.py:321 | `fno_value` always 0 but column exists. Dead field. |

### agents/front_office/trading/

| # | Severity | File:line | Bug |
|---|---|---|---|
| 23 | CRIT | paper_broker.py:26, 94-100 | 6.25% half-spread slippage — see B1. |
| 24 | HIGH | paper_broker.py:184 | `commission = 0.0` always. Zero commission makes paper results unrealistic (NSE STT+brokerage ~0.1%, US ~$0, crypto ~0.1-0.25%). Missing commission hides strategy cost. |
| 25 | HIGH | execution_agent.py:374 | Wrong cash bucket — see B2. |
| 26 | HIGH | order_manager.py:305-314 | SELL > LONG qty flips to SHORT silently. Bypasses naked-short check (which requires existing long qty>0). Creates unintended short positions. |
| 27 | MED | execution_agent.py:307 | `datetime('now', '-60 seconds')` is SQLite-only syntax. Breaks in Postgres mode. |
| 28 | MED | paper_broker.py:110 | Random noise `gauss(0, vol*price*0.01)` added on top of impact — already-realistic impact is further randomised, can cross-sign and flip to benefit. |
| 29 | MED | execution_agent.py:209-215 | Retry loop reruns `paper_broker.execute` up to 3× on None. Paper broker never returns None except on "no price" — retry won't help; burns 6s. |
| 30 | LOW | execution_agent.py:183-204 | Naked-short check uses `quantity > 0` — correct today because all SHORTs are blocked, but inconsistent with order_manager.py:305-314 which creates shorts anyway. |

### backtesting/

| # | Severity | File:line | Bug |
|---|---|---|---|
| 31 | HIGH | backtest_engine.py:198-214 | SELL with no position: `position_qty -= qty` goes negative then clamps to 0, but `pnl = (fill_price - avg_entry) * qty` with `avg_entry=0` books fake profit = `price * qty`. If any strategy emits SELL-first, backtest reports phantom gains. |
| 32 | HIGH | backtest_engine.py:223, 231 | `history = bars_df.iloc[:i+1]` — current bar's CLOSE is visible to strategy before the order fills at next bar's OPEN. Strategy using close=today creates look-ahead if interpreted as intraday. Fine only if strategy explicitly uses `.iloc[-1]` as "today's close" and orders fill "tomorrow open" — must be enforced by convention. |
| 33 | MED | backtest_engine.py:179-197 | BUY with `cost > cash` silently drops — no log, no metric. Strategy sees ignored orders but no feedback; win-rate inflated because unfilled losers never book. |
| 34 | MED | backtest_broker.py:97-102 | When `volume=0`, fallback is `base_slippage_pct` again — slippage just doubles the base. Should warn / skip the bar. |
| 35 | MED | backtest_metrics.py:16-27 | Sharpe uses daily returns but doesn't remove autocorrelation or handle outliers. `risk_free=0.05` annual hardcoded — fine for US but not for INR portfolios. |
| 36 | MED | backtest_metrics.py:40-46 | `win_rate` only counts SELL trades. If strategy holds a winner and never sells (or backtest ends mid-position), winners missing from numerator. |
| 37 | LOW | backtest_engine.py:144-150 | Empty bars_df returns `final_capital = initial_capital` — looks like 0% return rather than "no data" error. |

### agents/debate/

| # | Severity | File:line | Bug |
|---|---|---|---|
| 38 | MED | debate_engine.py:286 | Decision = pure FOR/AGAINST counting — ignores confidence. 3 low-conf FORs beat 1 high-conf AGAINST. |
| 39 | MED | debate_engine.py:281-286 | Ties → REJECTED but also "all abstain" → REJECTED silently. No distinct outcome, can't distinguish "debate couldn't decide" from "rejected". |

### config / infra

| # | Severity | File:line | Bug |
|---|---|---|---|
| 40 | MED | config.py:178-183 | `risk_max_drawdown_pct=10` + `risk_daily_loss_limit_pct=5` — combined with bug #9 (lifetime PnL, not daily), kill switch trips fast during normal DD. |
| 41 | MED | config.py:181 | `risk_var_limit_pct=3` defined but nothing reads it. |
| 42 | MED | config.py:183 | `risk_max_orders_per_minute=10` defined but not enforced anywhere. |

---

## PART C — "MAKE IT PROFITABLE": REALITY CHECK

Honestly: no code fix guarantees profit. Fixing all 42 bugs above gets you to **neutral expectation** (slippage realistic, signals non-degenerate, currency correct). That's the *floor*, not an edge.

**What currently prevents profitability (after bugs):**

1. **No edge.** RSI/MACD/Bollinger on daily bars for mega-cap stocks = textbook indicators that institutions arbitraged away decades ago. Retail-timeframe mean-reversion on RELIANCE/AAPL has ~0 alpha.
2. **No regime filter.** Mean-reversion loses in trends, trend-follow loses in chop. Running both concurrently on same name = guaranteed opposite trades.
3. **No transaction cost awareness.** Strategy fires without checking if expected edge > fees+slippage.
4. **Universe too broad, too correlated.** 5 Indian large-caps + 5 US mega-caps + 2 cryptos = ~2 effective bets. Correlated drawdowns.
5. **Equal weight sizing.** No Kelly/vol-targeting. All positions get same weight regardless of edge confidence.
6. **LLM debate as arbiter.** LLMs don't have trading edge. Adding debate adds latency, not alpha.

**Realistic paths forward — pick one, not all:**

- **Path 1 (Honest): make it a paper research platform.** Ship with clear "educational, expects negative returns without discovered edge" framing. Focus engineering on backtest rigor, walk-forward validation, transaction-cost modelling. No claim of profitability.
- **Path 2 (Narrow edge): pick one uncorrelated, less-efficient market.** Example: crypto funding-rate arbitrage, NIFTY options IV skew, or low-vol factor rotation on Indian mid-caps. Much smaller universe, one strategy, one timeframe, one thesis. Backtest with proper walk-forward.
- **Path 3 (Ensemble with cost-gating):** keep multiple strategies but only trade when `predicted_edge > 2× (slippage + commission)` and strategies agree. Strict regime filter (ADX for trend, VIX for vol regime). Expect low trade frequency.

My recommendation: **Path 1 as default, Path 2 as optional** — be honest that "personal hedge fund that's profitable" from retail daily OHLCV + canonical indicators is not realistic. Build the platform to be rigorous, let user plug in their own edge if they find one.

---

## PART D — SUGGESTED FIX ORDER

If you want to proceed to implementation:

1. **Stop the bleeding.** Fix B1 (slippage constant), B2 (currency bucket), B3 (RSI thresholds), B4 (bar-level dedup), B5 (partial SELL).
2. **Make backtest honest.** Fix #24 (commissions), #31 (phantom SELL profit), #33 (silent cash rejects).
3. **Tighten risk.** Fix #9 (daily vs lifetime), #10 (post-order weight), #11 (kill-switch reset).
4. **Add a minimum viable edge check.** Don't trade unless `|signal_strength| > threshold` AND `ATR > median(ATR)`.
5. **Cut the universe.** 2-3 instruments, one strategy, one timeframe until you see a genuine equity curve.

Then and only then, discuss real strategy design.
