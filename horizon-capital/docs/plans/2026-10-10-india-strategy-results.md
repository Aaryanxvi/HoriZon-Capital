# India (NSE) strategy gate — RESULTS

**Date:** 2026-10-10. Pre-registration: `2026-10-10-india-strategy-gate.md` (commit `060a556`).
Harness frozen at `e1f9ece` before the holdout ran. Scripts: `backend/scripts/india_data.py`,
`backend/scripts/validate_india_gate.py`. Raw outputs: `~/.horizon-capital/india/results_{A,B}.json`.

## Verdict

**FAIL.** On the untouched 2020-01 → 2026-09 holdout the India mix clears G1–G5 and G7 but
fails **G6** (robustness to 20 bps slippage: Sharpe 0.46 < 0.50). The passing gates are thin
(net Sharpe 0.57, post-tax 0.43), the edge comes almost entirely from the sleeve most exposed
to the residual survivorship gap (MomentumRank over Nifty 500), and the US "dominant alpha"
sleeve (ResearchStack) is a drag in both Indian windows. Do not fund this.

## Gate table — window B (holdout 2020-01-01 → 2026-09-30, ₹25L, 10 bps, Zerodha CNC)

| Gate | Rule | Result | Value |
|---|---|---|---|
| G1 | net-of-cost Sharpe ≥ 0.50 | PASS | 0.57 |
| G2 | max drawdown ≥ −35% | PASS | −23.5% |
| G3 | Sharpe > NIFTYBEES buy-and-hold | PASS | 0.57 vs 0.39 |
| G4 | PIT coverage ≥ 70% every year | PASS | min 96.0% (Nifty 500, 2020) |
| G5 | post-tax Sharpe > B&H post-tax | PASS | 0.43 vs 0.34 |
| G6 | G1 and G3 still hold at 20 bps slippage | **FAIL** | 0.46 (needs ≥ 0.50; bench 0.39) |
| G7 | window-A net Sharpe ≥ 0.30 | PASS | 0.86 |

All seven were required. Window A (design/debug, 2014–2019) passed G1–G6 (Sharpe 0.86 / post-tax 0.69 vs
B&H 0.47 / 0.41; maxDD −14.0%) — reported, not decisive.

## Coverage (PIT members on Jun-30 with a Yahoo close within 7 days)

| year | Nifty 50 | Nifty 100 | Nifty 500 | | year | Nifty 50 | Nifty 100 | Nifty 500 |
|---|---|---|---|---|---|---|---|---|
| 2014 | 98.0 | 95.0 | 82.0 | | 2021 | 98.0 | 97.9 | 96.2 |
| 2015 | 98.0 | 94.9 | 84.2 | | 2022 | 98.0 | 97.9 | 97.2 |
| 2016 | 98.0 | 96.9 | 88.2 | | 2023 | 98.0 | 99.0 | 98.4 |
| 2017 | 98.0 | 96.9 | 89.7 | | 2024 | 100.0 | 100.0 | 98.8 |
| 2018 | 98.0 | 98.0 | 91.1 | | 2025 | 100.0 | 100.0 | 99.4 |
| 2019 | 98.0 | 97.9 | 93.0 | | 2026 | 100.0 | 100.0 | 99.6 |
| 2020 | 98.0 | 98.0 | 96.0 | | | | | |

105 of 954 historical Nifty-500 symbols have no Yahoo history (DHFL, Bhushan Steel, Amtek Auto, Jet Airways,
Cox & Kings, Reliance Capital/Home Finance, merged PSU banks, HDFC Ltd, …). The missing set is the blow-ups,
so coverage % is a floor on the bias, not evidence of its absence.

## All arms

Columns: CAGR / vol / Sharpe / maxDD / avg gross exposure / turnover per yr / charges %NAV per yr. Capital ₹25,00,000 and
10 bps slippage unless stated. Sharpe uses the FRED interbank rate (2014 ≈ 9%, 2020–21 ≈ 4.3%, 2023–24 ≈ 6.7%).

### Window B — holdout 2020-01-01 → 2026-09-30 (1,670 days)

| arm | CAGR% | vol% | Sharpe | maxDD% | gross% | turn/yr | chg%/yr |
|---|---|---|---|---|---|---|---|
| **full-mix (pre-tax)** | 13.0 | 13.2 | **0.57** | −23.5 | 76.8 | 14.7 | 3.16 |
| full-mix post-tax (liquidation value) | 10.4 | 11.4 | 0.43 | −21.9 | 76.8 | 14.7 | 3.16 |
| full-mix 20 bps | 11.4 | 13.2 | 0.46 | −23.9 | 76.8 | 14.7 | 4.62 |
| full-mix 20 bps post-tax | 9.0 | 11.5 | 0.32 | −22.5 | 76.7 | 14.6 | 4.62 |
| full-mix 5 bps | 13.8 | 13.2 | 0.62 | −23.2 | 76.7 | 14.7 | 2.43 |
| full-mix zero cost | 16.6 | 13.2 | 0.81 | −22.5 | 76.7 | 14.8 | 0.00 |
| full-mix ₹5L | 12.9 | 13.2 | 0.57 | −23.3 | 76.6 | 14.5 | 3.34 |
| full-mix ₹1Cr | 13.1 | 13.2 | 0.57 | −23.5 | 76.8 | 14.7 | 3.13 |
| NIFTYBEES B&H (pre-tax) | 11.0 | 15.8 | 0.39 | −36.3 | | | |
| NIFTYBEES B&H (post-tax liq.) | 9.9 | 15.0 | 0.34 | −36.2 | | | |
| solo: research_stack | 4.7 | 14.3 | **0.00** | −23.7 | 70.0 | 17.6 | 3.76 |
| solo: trend_filter | 7.1 | 2.2 | 0.58 | −1.7 | 15.0 | 0.4 | 0.10 |
| solo: momentum_rank | 24.4 | 20.6 | 0.89 | −38.3 | 60.0 | 7.2 | 1.53 |
| LOO − research_stack | 18.3 | 12.4 | 0.97 | −22.2 | 48.3 | 4.4 | 0.96 |
| LOO − trend_filter | 13.0 | 17.0 | 0.48 | −32.0 | 85.2 | 19.0 | 4.07 |
| LOO − momentum_rank | 7.2 | 11.5 | 0.18 | −18.6 | 66.8 | 14.3 | 3.08 |

Regime gate: RISK_OFF on 88/334 weekly refreshes (26%), **30 flips** in 6.75 years. Trend filter long on 251/334 weeks.
Standalone return correlations: research–trend 0.50, research–momentum 0.34, trend–momentum 0.32.

Per-sleeve attribution (US rules, LOO vs full 0.57): research_stack LOO 0.97 (+0.40) **DRAGS**;
trend_filter LOO 0.48 (−0.09) CARRIES; momentum_rank LOO 0.18 (−0.39) CARRIES.

### Window A — design/debug 2014-01-01 → 2019-12-31 (1,462 days)

| arm | CAGR% | vol% | Sharpe | maxDD% | gross% | turn/yr | chg%/yr |
|---|---|---|---|---|---|---|---|
| **full-mix (pre-tax)** | 18.5 | 12.3 | **0.86** | −14.0 | 73.8 | 14.8 | 3.17 |
| full-mix post-tax (liquidation value) | 14.8 | 10.4 | 0.69 | −13.0 | 73.8 | 14.7 | 3.17 |
| full-mix 20 bps | 16.8 | 12.3 | 0.74 | −14.8 | 73.8 | 14.7 | 4.64 |
| full-mix 20 bps post-tax | 13.5 | 10.6 | 0.57 | −13.9 | 73.8 | 14.7 | 4.63 |
| full-mix 5 bps | 19.4 | 12.3 | 0.92 | −13.7 | 73.8 | 14.8 | 2.43 |
| full-mix zero cost | 22.3 | 12.3 | 1.11 | −13.4 | 73.7 | 14.8 | 0.00 |
| full-mix ₹5L | 18.3 | 12.3 | 0.84 | −14.1 | 73.7 | 14.6 | 3.35 |
| full-mix ₹1Cr | 18.6 | 12.3 | 0.86 | −14.0 | 73.8 | 14.8 | 3.13 |
| NIFTYBEES B&H (pre-tax) | 13.2 | 12.9 | 0.47 | −21.6 | | | |
| NIFTYBEES B&H (post-tax liq.) | 12.0 | 11.6 | 0.41 | −19.4 | | | |
| solo: research_stack | 13.9 | 13.1 | 0.51 | −21.9 | 65.0 | 16.6 | 3.55 |
| solo: trend_filter | 7.0 | 2.1 | −0.20 | −2.1 | 15.3 | 1.2 | 0.26 |
| solo: momentum_rank | 36.5 | 20.2 | 1.28 | −18.0 | 60.0 | 6.7 | 1.44 |
| LOO − research_stack | 23.3 | 12.2 | 1.19 | −11.7 | 48.6 | 5.0 | 1.07 |
| LOO − trend_filter | 24.7 | 15.9 | 1.02 | −17.5 | 81.1 | 18.0 | 3.84 |
| LOO − momentum_rank | 11.3 | 10.5 | 0.38 | −17.0 | 63.4 | 14.4 | 3.09 |

Regime gate: RISK_OFF 80/293 (27%), 34 flips. Trend long 224/293. Attribution vs full 0.86: research_stack LOO 1.19
(+0.33) DRAGS; trend_filter LOO 1.02 (+0.16) DRAGS; momentum_rank LOO 0.38 (−0.48) CARRIES.

(The solo trend_filter arm looks odd at 15% gross: a 1.0 signal × 1.0 sleeve weight is capped at the live 20%
per-name limit and the clipped weight is discarded — the same thing happens to it inside the live mix,
0.333 → 0.20. That is faithful to live sizing, as in the US harness.)

## Costs, turnover and tax (window B, full mix, ₹25L)

* 2,306 fills in 6.75 years (≈ 340/yr); turnover 14.7× NAV/yr. Most of it is the GMM regime gate flipping
  ~4–5×/yr and rotating ~50% of NAV between Nifty-50 stocks and gold/gilt, plus weekly HRP × Kelly re-weighting.
* Charges ₹9.76 lakh ≈ 3.16% of NAV per year: STT ₹4.54L, slippage ₹4.54L, stamp ₹0.34L, DP ₹0.17L,
  NSE txn ₹0.14L, GST+SEBI ₹0.03L. STT and slippage are 93% of it; DP charges are negligible even at ₹5L
  (Sharpe 0.57 → 0.57; ₹1Cr same). Capital size is not the problem — turnover is.
* Cost drag on Sharpe: zero-cost 0.81 → 5 bps 0.62 → 10 bps 0.57 → 20 bps 0.46. Each 5 bps of slippage
  costs ≈ 0.05 Sharpe because of the 14.7× turnover.
* Tax (pre-tax arm's liability, FY): 2020 ₹1.14L, 2021 ₹2.16L, 2022 ₹0.39L, 2023 ₹2.80L, 2024 ₹0.25L,
  2025 ₹0.18L, 2026 (partial) ₹0.19L — ₹7.1L total, essentially all STCG at 20.8% (holdings rarely reach
  12 months). Post-tax CAGR 10.4% vs NIFTYBEES post-tax 9.9%: **+0.5 pt/yr** after tax for 2,300 trades
  and annual STCG filings. FY-2024–26 liabilities are tiny because the strategy made almost nothing in the
  2024–26 correction.

## Harness bugs found and fixed (all before the holdout, disclosed in commits)

1. **Yahoo ETF bad prints:** NIFTYBEES / GOLDBEES / BANKBEES carry 2019-12-19 and -20 at 1/10 or 1/100 of
   price with no split record (−90%/+900% and −99%/+9900% days). Pre-registered rule (>50% move that reverts
   within 3 bars → NaN + ffill) removes them; verified max |daily return| after cleaning = 17% (2010).
2. **Yahoo ETF opens are junk on 1.6–3% of days** (JUNIORBEES 3.0%, LTGILTBEES 1.8%, NIFTYBEES 1.6%); stocks
   ≈ 0.06%. Open replaced by that day's close when it is >10% off the prior close and >5% off the same-day close.
3. **FRED stalls on any custom User-Agent** → `load_rf_monthly` silently fell back to a flat 6.5% in the
   first debug run (full-mix A Sharpe 0.90 flat vs 0.86 with the real series). Fixed; the holdout used the
   real series throughout.
4. pandas 3.0 removed `fillna(method=...)` (metrics crashed); cp1252 console cannot print "₹".
5. LIQUIDBEES is flat ₹1000 in Yahoo (dividend units not reflected) — unusable as a return series; cash is
   synthetic at RF − 50 bps as pre-registered.
6. **Not an India bug, but found while porting:** `validate_sleeve_attribution._targets` is called with
   `i // 5 * 5` and tests `i % rebalance_days == 0`, so the "monthly" MomentumRank sleeve refreshed only every
   105 trading days (lcm 5, 21) in the US attribution / 2008-17 holdout runs, while the live agent refreshes
   on a ≥ 21-business-day delta. The India harness uses the live semantics (67 momentum refreshes in B, not 16).
   The US validated numbers were therefore computed with ~5-monthly momentum; worth a re-run on main.

## Biggest caveats (why even the passing gates should not be trusted)

* **The edge is the survivorship-prone sleeve.** MomentumRank CARRIES in both windows (LOO −0.48 / −0.39);
  without it the mix is Sharpe 0.38 (A) / 0.18 (B). 12-1 top-3 over Nifty 500 is exactly the screen that
  would have held DHFL, Reliance Capital, Jet Airways, Manpasand, Cox & Kings into their collapses — and those
  names have no prices here. The G1/G3 passes lean on the part of the test that is least honest.
* **ResearchStack — the US dominant alpha — does not travel.** Solo Sharpe 0.51 (A) and **0.00** (B); DRAGS
  in both. The GMM regime gate flips 30–34 times per window, which is where the 14.7× turnover and 3.2%/yr of
  costs come from. In India costs are ~7× the US harness's 3 bps, so the same churn that was tolerable on
  Alpaca is fatal on Zerodha.
* **Margins are thin and one-sided.** 0.57 → 0.46 for 10 bps of extra slippage; post-tax 0.43 (below the 0.5
  bar, which G5 did not require — a tightening it would have failed). NIFTYBEES itself would fail G2 (−36.3%).
* Membership pre-2018 is best-effort (±2–13 names); Yahoo opens; whole-unit fills but no impact model;
  QMJ stubbed; dividends untaxed; one path, no PSR/DSR haircut.
* Post-hoc observation, **not a recommendation and not shippable from this run:** the LOO-research arm
  (trend .667 / momentum .333 renormalized) is 1.19 (A) / 0.97 (B) at 4–5× turnover. It would need its own
  fresh pre-registration on survivorship-free prices before anyone acts on it.

## If a future version passes — what live India needs

* **Survivorship-free prices** are the blocker, not the broker: NSE daily bhavcopy archives (free,
  `nsearchives.nseindia.com`, every traded symbol incl. later-delisted) + NSE corporate-action files to build
  adjusted series; or a paid vendor. Kite historical (₹500/mo) does **not** include delisted instruments either.
* Kite Connect: instruments dump (tradingsymbol ↔ ISIN), historical candles for `^NSEI`/ETFs, CNC order type,
  T+1 settlement and holiday calendar; a `zerodha` broker adapter (none exists in `data_layer/` today) and an
  India feed to replace the mock; INR cash accounting; FIFO lot tracking for the ITR capital-gains schedule.
* niftyindices press-release poller to keep PIT membership current.
