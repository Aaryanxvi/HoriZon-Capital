# India (NSE) strategy gate — PRE-REGISTRATION

**Date:** 2026-10-10 (written and committed BEFORE any strategy return was computed)
**Question:** does an NSE version of Horizon Capital's live mix (ResearchStack .500 /
TrendFilter .333 / MomentumRank .167) have a real, net-of-cost, after-tax edge for an
individual trading their own money through Zerodha CNC? A FAIL is a good outcome.

Scripts: `backend/scripts/india_data.py` (data, coverage) and
`backend/scripts/validate_india_gate.py` (replay, costs, tax, gates). No live code is
touched; nothing here wires India into the agent.

---

## 1. Data (free tier only — what was actually obtainable)

| Need | Source | Range / quality |
|---|---|---|
| PIT index membership | `aditya-jha/nse-historical-membership` (CC BY 4.0) — interval table per index parsed from NSE/niftyindices press releases | floor **2014-01-01**; author rates it **reliable from 2018-04**, best-effort before ("drifts ±2–13 names pre-2018"). Nifty 50 / 100 / 500 present (no Nifty 200). Cross-checked against the official `IndexInclExcl.xls` (NSE, company *names* back to 1996/1998 — not usable directly, no symbols). |
| Symbol renames | NSE official `symbolchange.csv` (1,065 rows) | chain old→new so renamed names keep their Yahoo history |
| Prices | yfinance `<SYMBOL>.NS`, `auto_adjust=True` | stocks from 1996–2002 (survivors); delisted/merged names are **absent** |
| Nifty 50 index | `^NSEI` | 2007-09 → |
| Nifty 50 ETF | `NIFTYBEES.NS` | 2009-01 → |
| Next-50 / Bank ETFs | `JUNIORBEES.NS`, `BANKBEES.NS` | 2009-01 → |
| Gold ETF | `GOLDBEES.NS` | 2009-01 → |
| Long gilt ETF | `LTGILTBEES.NS` | **2018-05 →** (SETF10GILT exists from 2016 but median volume ≈ 8.5k units/day — not tradable, not used) |
| Liquid ETF | `LIQUIDBEES.NS` | price flat at ₹1000 in Yahoo (dividend units not reflected) → **not usable as a return series**; cash is modelled synthetically (§3) |
| Risk-free | FRED `IRSTCI01INM156N` (India immediate interbank rate, monthly, OECD) | 1968 → 2026-07; 2014 ≈ 9%, 2020–21 ≈ 4.3%, 2023–24 ≈ 6.7% |

### 1.1 Coverage measured before pre-registration (Jun-30 each year; members with a Yahoo close within 7 days)

| year | NIFTY 50 | NIFTY 100 | NIFTY 500 |
|---|---|---|---|
| 2014 | 98.0 | 95.0 | 82.0 |
| 2015 | 98.0 | 94.9 | 84.2 |
| 2016 | 98.0 | 96.9 | 88.2 |
| 2017 | 98.0 | 96.9 | 89.7 |
| 2018 | 98.0 | 98.0 | 91.1 |
| 2019 | 98.0 | 97.9 | 93.0 |
| 2020 | 98.0 | 98.0 | 96.0 |
| 2021 | 98.0 | 97.9 | 96.2 |
| 2022 | 98.0 | 97.9 | 97.2 |
| 2023 | 98.0 | 99.0 | 98.4 |
| 2024 | 100.0 | 100.0 | 98.8 |
| 2025 | 100.0 | 100.0 | 99.4 |
| 2026 | 100.0 | 100.0 | 99.6 |

105 of 954 historical Nifty-500 symbols (11%) have no Yahoo history: DHFL, Bhushan Steel,
Amtek Auto, Jet Airways, Cox & Kings, Reliance Capital/Home/Power-type names, merged
banks (Andhra, Corporation, Dena, Allahabad), HDFC Ltd, etc. **These are
disproportionately the blow-ups**, so even 82–99% coverage leaves a survivorship tilt
that flatters the momentum sleeve in particular. Coverage % is therefore a floor on the
bias, not a measure of its absence. Residual gap is identical in shape to the US work.

### 1.2 Price-cleaning rules (decided from the probes above, before any strategy run)

* **Bad print:** a close that deviates >50% from the previous close and reverts to within
  25% of it within 3 bars is a bad print (Yahoo has 2019-12-19/20 at 1/10 or 1/100 price
  for NIFTYBEES, GOLDBEES, BANKBEES with no split record). The whole bar is set NaN and
  forward-filled.
* **Bad open:** if |open/prev-close − 1| > 10% **and** |open/close − 1| > 5%, the open is
  replaced by that day's close for fill purposes (Nippon ETF opens are junk on 1.6–3% of
  days; stocks ≈ 0.06%).
* Names must have ≥ 30 bars to exist at all.

---

## 2. Mapping (fewest changes from the US live mix)

| US (live) | India | Why |
|---|---|---|
| Regime gate on SPY (GMM, 252d) | `^NSEI` closes | index, longest history, same object the ETF tracks |
| ResearchStack risk universe: fixed 25-name mega-cap/sector-ETF list (not PIT in the US!) | **PIT NIFTY 50 members on the decision date + NIFTYBEES, JUNIORBEES, BANKBEES** | stricter than the US: no hindsight list; the 3 ETFs stand in for SPY/QQQ/sector ETFs |
| RISK_OFF: inverse-vol TLT / GLD | inverse-vol **LTGILTBEES / GOLDBEES** (60d vol, same code). Before LTGILTBEES has 30 returns (< ~2018-07): **50% GOLDBEES + 50% cash** (harness halves the sleeve's gold weight) | only liquid long-gilt ETF starts 2018-05 |
| TrendFilter on SPY: 200d SMA + 20d vol < 30%, long or cash | identical rule on **NIFTYBEES** | |
| MomentumRank 12-1, top-3, monthly, over PIT S&P 500 | identical, over **PIT NIFTY 500** stocks (ETFs/index excluded) | the broad-universe analog; coverage above |
| QMJ quality tilt | **stubbed to 0** | same stub as every US validation run (current-snapshot fundamentals are look-ahead) |
| Sleeve weights .500 / .333 / .167; cadences 5 / 5 / 21 days; research top-5; HRP × half-Kelly; 20% per-name cap, clipped weight discarded | **unchanged** | no parameter is re-tuned for India |
| Decision every 5th trading day at close, fills at next open | **unchanged** | |

Implementation: the real sleeve classes are run unmodified; the harness only patches the
module-level universe constants (`research_stack._RISK_UNIVERSE/_DEFENSE_UNIVERSE`,
`trend_filter._INSTRUMENT`, `MomentumRankSleeve._exclude`, `momentum_rank._TOP_N=3`)
exactly as the US validation scripts do. The `^NSEI` series is handed to ResearchStack
under the key `SPY-PROXY.^NSEI` because the sleeve finds its regime series by
`startswith("SPY")` — the alias is the whole hack and is named for what it is.

---

## 3. Costs, cash and tax (Zerodha CNC, rates from zerodha.com/charges as of 2026-10)

| Item | Buy | Sell |
|---|---|---|
| Brokerage | 0 | 0 |
| STT | 0.100% | 0.100% |
| NSE transaction charge | 0.00307% | 0.00307% |
| SEBI turnover fee | 0.0001% (₹10/cr) | 0.0001% |
| Stamp duty | 0.015% | — |
| GST 18% on (brokerage + NSE + SEBI) | yes | yes |
| DP charge | — | ₹15.34 per scrip per sell day |
| Slippage (market-ish order at open) | **10 bps base**; 5 and 20 bps reported | same |

* Capital **₹25,00,000** base; ₹5,00,000 and ₹1,00,00,000 reported (DP charge is fixed per
  scrip-day, so small accounts pay proportionally more).
* Trades smaller than 0.2% of NAV are skipped (US harness rule). Fractional shares are
  **not** allowed (whole units — India has no fractional delivery).
* **Cash** (what LIQUIDBEES would earn): accrues daily at (interbank RF − 50 bps). No
  cash drag assumption beyond that.
* **Risk-free for Sharpe:** the FRED interbank series, forward-filled daily; Sharpe =
  mean(daily excess) / std(daily) × √252. Same formula for every arm and the benchmark.
* **Tax (post-tax arm)**, FIFO lots, financial year Apr–Mar, 4% cess included:
  * equity shares & equity ETFs (NIFTYBEES/JUNIORBEES/BANKBEES): held < 12 m → STCG
    **20%** (20.8% with cess); ≥ 12 m → LTCG **12.5%** (13.0%) on the FY aggregate above
    **₹1,25,000** (sec. 112A). Rates verified unchanged for FY 2026-27 (Budget 2026 left
    capital-gains rates alone).
  * gold / gilt ETFs: < 12 m → slab, modelled at **30%** (31.2%); ≥ 12 m → 12.5% (13%)
    with no 112A exemption.
  * cash interest: 30% (31.2%).
  * STCL offsets STCG then LTCG in-year; net loss carries forward within the window.
  * Tax is deducted from cash on the last trading day of each FY; at window end the
    accrued liability on realized gains is deducted before computing final NAV.
    Unrealized gains are untaxed (this favours buy-and-hold deferral — stated, not fixed).
  * Dividend tax ignored (yfinance folds dividends into price; ≈ 0.1%/yr overstatement).
* Benchmark: **NIFTYBEES buy-and-hold** (total return), bought on day 1 with the same buy
  charges; post-tax variant taxed as LTCG at window end.

---

## 4. Windows

| Window | Dates | Role |
|---|---|---|
| **A — design/debug** | 2014-01-01 → 2019-12-31 | the only window the harness may be iterated on (bug fixes). Membership "best-effort". |
| **B — HOLDOUT** | 2020-01-01 → 2026-09-30 | run **once**, after the harness is frozen and committed. Membership "reliable". Decides the verdict. |
| full | 2014-01-01 → 2026-09-30 | reported |

No strategy parameter is tuned on either window. Warm-up history (regime 277 bars,
momentum 253 bars) comes from before each window's start.

---

## 5. Gates — ALL must pass on window B (post-cost, pre-tax unless stated)

| Gate | Rule |
|---|---|
| **G1** | net-of-cost Sharpe ≥ **0.50** |
| **G2** | max drawdown ≥ **−35%** |
| **G3** | net-of-cost Sharpe **>** NIFTYBEES buy-and-hold Sharpe, same window |
| **G4** | PIT coverage ≥ **70%** in every calendar year of B for every universe used (NIFTY 50 and NIFTY 500) — already measured: passes 2020–2026 |
| **G5** (tightening) | **post-tax** Sharpe > post-tax NIFTYBEES buy-and-hold Sharpe |
| **G6** (tightening) | G1 and G3 still hold at **20 bps** slippage |
| **G7** (tightening) | window A net-of-cost Sharpe ≥ **0.30** (not a one-window fluke) |

Verdict wording: **PASS** only if G1–G7 all pass; otherwise **FAIL**. Any result produced
on non-PIT membership would be labelled "SURVIVORSHIP-BIASED UPPER BOUND" and could not
pass — not needed here since PIT membership was obtained, but the residual price-side
gap in §1.1 is disclosed with every number.

Also reported, not gated: per-sleeve standalone and leave-one-out Sharpe (US attribution
rules: DRAGS if LOO ≥ full + 0.03, CARRIES if LOO ≤ full − 0.05), standalone-return
correlation matrix, zero-cost arm (cost drag), capital sensitivity, FY-by-FY tax bill,
and turnover.

---

## 6. What a PASS would still not prove

* Price-side survivorship (missing blow-ups) remains; a Kite-historical or paid vendor
  rerun is required before sizing real money.
* Fills at Yahoo opens with 10 bps slippage are optimistic for the Nifty-500 tail.
* The regime GMM and TSMOM parameters were chosen on US data; India just inherits them —
  that is the point of the test, but it is one sample path.
