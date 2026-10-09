# Profitability gate — after-tax, after-cost, for the real owner (pre-registered)

**Status:** PRE-REGISTERED. Committed before any strategy return in this program was
computed. Nothing below is edited after results exist; the results file
(`2026-10-10-profitability-results.md`) reports against this document as written.

**Question.** Does the live mix (research_stack .500 / trend_filter .333 / momentum_rank
.167, 20% cap) make an Indian tax resident trading US equities under LRS more money than
an index fund — after costs and after Indian tax — and can any of a small, pre-named set
of changes improve that without overfitting? "An index fund is better after tax" is an
acceptable answer and will be reported plainly if that is what the data says.

## 1. Owner situation and rules used (verified 2026-10-10)

| Item | Rule used | Source |
|---|---|---|
| Classification of US-listed shares/ETFs | "Unlisted" for Indian tax (not listed on a recognised Indian exchange) | [Winvesta](https://www.winvesta.in/blog/investors/capital-gains-tax-on-us-stocks-short-term-vs-long-term-for-indians), [Treelife](https://treelife.in/taxation/tax-on-sale-of-unlisted-shares/) |
| Long-term threshold | held **> 24 months** | Finance (No. 2) Act 2024 — [BCAJ](https://bcajonline.org/journal/important-amendments-by-the-finance-no-2-act-2024-capital-gains/), [BDO](https://bdo.in/en-gb/news/2024/key-changes-in-finance-bill-2024;-know-impact-on-capital-gains,-buy-backs-and-more) |
| LTCG rate | **12.5%**, no indexation, transfers on/after 23 Jul 2024 (s.112) | same |
| STCG rate | **slab rate** (not s.111A) | same |
| Surcharge | 10% (₹50L–1cr), 15% (₹1–2cr) …; **capped at 15% on s.112 LTCG** | [KPMG FPI rate card](https://www.in.kpmg.com/TaxFlashNews-INT/Foreign-Portfolio-Investors-Tax-Rate-Card.pdf), [incometaxindia.gov.in](https://incometaxindia.gov.in/Documents/Left%20Menu/TAX%20RATES_HUF.htm) |
| Cess | 4% Health & Education cess on tax + surcharge | same |
| Loss set-off / carry-forward | STCL vs any capital gain; LTCL vs LTCG only; carry forward 8 AYs (s.74) | [incometaxindia.gov.in s.74](https://www.incometaxindia.gov.in/w/section-74) |
| Lot matching | FIFO (s.45(2A), Circular 704/768) | [Circular 768](https://www.incometaxindia.gov.in/w/768-circular-no.-768-dated-24-6-1998-1) |
| FX basis | Gains computed in INR; Rule 115: SBI TTBR of the last day of the month preceding the transfer month, applied to cost and consideration | [Rule 115](https://www.incometaxindia.gov.in/w/rule-115-2), [KMG](https://kmgcollp.com/?p=92283) |
| US capital gains | **None** for a non-resident alien not present ≥183 days (IRS Pub 519) | [ClearTax](https://cleartax.in/s/tax-implications-indian-residents-investing-us-stock-markets), [Winvesta](https://www.winvesta.in/blog/dtaa-india-us-how-to-claim-tax-treaty-benefits-on-us-stocks) |
| US dividends | 25% withheld under India–US DTAA Art. 10 (W-8BEN); creditable in India (Form 67); India taxes dividends at slab | [Vested](https://vestedfinance.com/blog/us-stocks/how-are-us-dividends-taxed-for-indian-investors/), [Winvesta](https://www.winvesta.in/blog/investors/dividend-tax-on-us-stocks-understanding-the-25-withholding) |
| LRS | USD 250,000 per FY | [RBL](https://www.rbl.bank.in/static-pages/tax-collected-at-source) |
| TCS | 20% on LRS investment remittances above ₹10 lakh/FY (from 1 Apr 2025); creditable against tax → cash-flow cost, not a final cost | [ClearTax](https://cleartax.in/s/tds-and-tcs-changes-from-april-2025), [AU Bank](https://www.au.bank.in/blogs/tcs-on-foreign-remittance-union-budget-2025-updates) |

**Rate scenarios** (ST = slab × (1+surcharge) × 1.04; LT = 12.5% × (1+min(surcharge,15%)) × 1.04):

| Scenario | ST rate | LT rate | Dividend rate |
|---|---|---|---|
| **Base: 30% slab, 10% surcharge** | **34.32%** | **14.30%** | 34.32% |
| No surcharge | 31.20% | 13.00% | 31.20% |
| 15% surcharge (> ₹1 cr) | 35.88% | 14.95% | 35.88% |
| 20% slab, no surcharge | 20.80% | 13.00% | 20.80% |

Dividend tax = Indian slab on the gross dividend (the 25% US withholding is credited in
full because the Indian rate exceeds it). 2024's rates are applied to the whole history
("what the owner would pay today on this return stream"), not the historical rates.

**Modelling assumptions (fixed):**
- Taxes are paid **out of the portfolio** at each Indian FY end (31 Mar); the liability is
  accrued daily from realized FY-to-date gains so the after-tax curve has no artificial
  step. Carry-forward loss pools (ST, LT) are tracked across FYs; the 8-year expiry is not
  binding inside a ≤10-year window and is not modelled.
- **Terminal liquidation**: on the last day of each window every arm sells everything and
  pays tax on remaining lots (ST/LT by lot age). This is how a buy-and-hold investor pays
  LTCG "once at the end". Both pre- and post-liquidation after-tax numbers are reported;
  **post-liquidation is the gate metric**.
- INR basis: lot cost and proceeds are converted at the **spot USDINR on the trade date**
  (yfinance `INR=X`). Rule 115's prior-month-end TTBR is approximated by spot; the
  difference is second order and applies identically to every arm.
- Dividends: yfinance `auto_adjust=True` prices are total-return. Dividend tax is charged
  per FY as (equity market value × SPY trailing-12m yield that FY) and (TLT market value ×
  TLT yield) at the dividend rate. Single names are given SPY's yield — slightly
  conservative for the momentum legs (growth names yield less). GLD/cash: none.
- Costs: 1 bp commission + 2 bp slippage per side (existing harness), cash earns 0% (a
  bias against the strategy, which holds cash when trend/regime are off; SPY holds none).
- FX conversion: 0.5% each way (in at start, out at end), sensitivities 0.25% / 1.0%.
  Identical for all arms — reported, cannot change rankings.
- TCS: a one-time cash-flow cost outside the return stream; stated, not modelled.
- Whole-share rounding (live engine): reported as a sensitivity on the baseline at
  $100k capital, not applied to candidates.
- Capital: $100,000 (one LRS year's remittance is $250k; $100k keeps the harness
  comparable to every prior gate).

## 2. Windows

| Window | Dates | Role |
|---|---|---|
| Design | 2018-01-01 → 2024-12-31 | Where candidates are evaluated first; parameters are NOT tuned here either — each candidate has exactly one pre-fixed configuration |
| Holdout | 2008-01-01 → 2017-12-31 | Decides. Untouched by this program until all candidates are frozen. Caveat on record: the live mix itself was selected using a single pass over this window (2026-07-17 reweight gate), so it is "once-touched" for the baseline and untouched for every candidate |

Point-in-time S&P 500 membership (`app.data_layer.pit_universe`), one `period="max"`
fetch, the 2008-date hard-assert from `validate_holdout_gate.py` carried over. Coverage
(~71–85%; delisted names lack prices) inflates absolutes in **every arm equally** and is
reported.

## 3. Arms

Benchmarks (not trials):
- **SPY** buy-and-hold: one lot at window start, dividends taxed yearly, LTCG once at the end.
- **60/40 SPY/TLT**: rebalanced on the first trading day of each calendar year, same lot
  engine (FIFO, so from year 3 onward the sold lots are >24 months old).

Reference (the "current live mix"):
- **B_harness** — the existing harness convention (`validate_sleeve_attribution.run`):
  drift-trades every 5 days when |holding − target| ≥ 0.2% NAV, and the known cadence
  quirk (`i % rebalance_days` on multiples of 5 → momentum_rank actually recomputes
  every 105 trading days). Must reproduce Sharpe 0.67 (2018-24) / 0.70 (2008-17) at flat
  4% RF within ±0.02, otherwise STOP and debug before anything else runs.
- **B_live** — the same mix with two harness bugs fixed to match `StrategyAgent`:
  (i) cadence by calendar-day delta since the sleeve's last refresh
  (`_should_refresh`), so momentum_rank refreshes every 21 calendar days as live does;
  (ii) a symbol is traded only when its **target weight changes by ≥ 0.5%**
  (`MIN_WEIGHT_DELTA`) — live never re-trades price drift. **B_live is the reference for
  every gate.** Both are reported; the gap is a disclosed harness correction.

Measurement arm (cannot ship; it is an honesty check on the baseline):
- **B0 — mechanical research universe.** `ResearchStackSleeve._RISK_UNIVERSE` is a
  hard-coded list of 2024's mega-cap winners (NVDA, TSLA, AVGO, LLY, META …). Ranking
  that list by momentum in 2008–2017 is universe look-ahead inside 50% of the live mix.
  B0 replaces the 18 single names with the **top-18 PIT S&P 500 members by trailing-252d
  median dollar volume** at each decision date (mechanical, no hindsight); the 7 ETFs
  (SPY, QQQ, XLE, XLK, XLF, XLV, XLY, XLI) are kept. If B0 is materially worse than
  B_live, the live numbers are inflated by that much and the owner is told so.

Candidates (each one fixed configuration, rationale written before testing):
- **C1 — research_stack cadence weekly → 21 calendar days.** Rationale: research_stack
  is 50% of the book and re-solves HRP + top-5 momentum every week; momentum signals are
  documented at monthly horizons, weekly re-solves are mostly weight noise that realizes
  short-term gains at 34%. Fewer realizations, same signal.
- **C2 — C1 + tax-aware sell rule.** Rationale: a partial trim of a winner is a taxable
  event that buys almost nothing (the signal is still long); a sale of a loser creates a
  loss that shelters other gains. Rule: a *partial* reduction (new target > 0) whose FIFO
  lots are at an unrealized **gain** is deferred; a reduction whose lots are at a **loss**
  always executes (even below the 0.5% band); a **full exit** (target → 0) always
  executes. No other parameter.
- **C3 — real point-in-time QMJ.** Rationale: the live sleeve tilts 20% on quality but
  the backtests stub it to 0 because `app.quant.quality` reads *current* yfinance
  fundamentals (look-ahead). SEC `companyfacts` (free, probed 2026-10-10) carries every
  XBRL fact with its `filed` date from mid-2009, so quality can be computed as of each
  decision date using only facts filed by then. Definition (fixed): ROE = FY net income /
  latest equity; gross margin = FY gross profit / FY revenue; earnings growth = FY NI /
  prior-FY NI − 1; leverage = total liabilities / equity (lower better); beta = 252d OLS
  slope vs SPY from the bar data. Cross-sectional z-scores among single names, ETFs = 0
  (as live). Before 2009-07 (no XBRL) the score is 0 = the stub. If coverage is poor the
  arm is reported as "not measurable", not faked.
- **C4 — C1 + C3 combined.**

Not tested, with reasons: **volatility targeting** — the Moreira-Muir overlay already
failed its PIT 2018-24 gate (2026-07-02, Sharpe 0.24→0.0), `validate_voltarget.py` was
only ever run on a survivorship-biased 90-name list (its own docstring), leverage is
neither available nor appropriate for a retail LRS account, and vol-scaling multiplies
short-term realizations — it is tax-hostile by construction. **Stop-loss (20% trailing)**
— measured concurrently by another agent; not duplicated here. **Risk overlay, GEM/dual
momentum, breadth sleeve, momentum top-10** — previously rejected, not relitigated.

## 4. Metrics (every arm, both windows)

Pre-tax (USD): CAGR, vol, Sharpe vs realized 13-week T-bill (`scripts/validate_riskfree`,
the paper's basis; the flat-4% figure also printed for reconciliation with the
handoffs), maxDD, annual one-way turnover (Σ|notional|/2/avg NAV/years), fill count,
average gross exposure.

Tax: realized ST and LT gains per FY, % of total realized gains (incl. terminal
liquidation) that are short-term, total tax paid (base scenario), tax drag = pre-tax CAGR
− after-tax CAGR.

After-tax (base scenario unless stated): **CAGR post-liquidation** in USD-equivalent
(INR after-tax wealth ÷ spot at end; so it is directly comparable to the pre-tax USD CAGR)
and in INR; after-tax **Sharpe** (daily returns of the accrual after-tax wealth path, USD,
realized RF); after-tax maxDD. Rate and FX sensitivities as extra columns on the
after-tax CAGR only.

## 5. Multiple-testing control

N_program = number of strategy variants whose returns this program computes on the design
window = **8** (B_harness, B_live, B_live whole-share sensitivity, B0, C1, C2, C3, C4).
Benchmarks and post-processing sensitivities (tax rate, FX cost) are not trials.
N_project = N_program + the 12 trial Sharpes already on record in
`validate_deflated_sharpe.OBSERVED_TRIAL_SHARPES` = **20**.

Reported for B_live and every candidate, both windows:
- PSR(>0), PSR(>SPY), DSR at N_program and at N_project using the observed dispersion of
  Sharpes across this program's variants (per-period units, as the existing script does).
- **Deflated margin**: the expected maximum of N i.i.d. N(0, σ_Δ²) draws,
  E[max] = σ_Δ · ((1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e))), γ = 0.5772, where σ_Δ is the
  standard deviation of (after-tax Sharpe_variant − after-tax Sharpe_B_live) across
  {B0, C1, C2, C3, C4} on the design window and N = 5. This is the improvement one
  would expect from the best of five null variants.

## 6. Gates (holdout decides; all must pass for a candidate to be recommended)

- **G1 (deflated improvement):** after-tax Sharpe_candidate − after-tax Sharpe_B_live on
  the holdout ≥ max(0.05, E[max] from §5).
- **G2 (drawdown):** after-tax maxDD_candidate ≥ after-tax maxDD_B_live − 2.0 pts
  (i.e. no more than 2 points worse).
- **G3 (money):** after-tax post-liquidation CAGR_candidate ≥ CAGR_B_live on the holdout
  (a Sharpe gain bought with lower terminal wealth does not ship).
- **G4 (consistency):** the sign of the after-tax Sharpe improvement is the same on the
  design window.

Outcome vocabulary: **SHIP** (all pass), **KEEP CURRENT** (any fails), **NOT
MEASURABLE** (data coverage), and for the baseline question: **"index fund better after
tax"** if SPY's post-liquidation after-tax CAGR exceeds B_live's on a window; the verdict
is stated per window, never averaged across them.

B0 has no gate; it is reported as the look-ahead cost: ΔSharpe(B0 − B_live).

## 7. Rules of conduct

- No parameter is changed after seeing a result. If a run reveals a harness bug, the bug
  is fixed, disclosed, and every arm is re-run under the fixed harness.
- Research only: new scripts under `horizon-capital/backend/scripts/`, no edits to live
  engine code, no orders, no paid APIs, no push.
- Every number in the results file comes from one script run
  (`scripts/validate_profitability.py`), whose output is pasted verbatim.

## Addendum A — written and committed BEFORE the first strategy run (2026-10-10)

Triggered by harness findings relayed from the India-research agent. At the time of
writing, this program had computed **no strategy return** (only the no-network
self-checks of the tax engine and the SEC fetcher had run).

- **A1. Price-print cleaning**, applied identically to every arm except B_harness (which
  must reproduce the old numbers on raw data). (a) *Close spikes*: a close that moves
  > 40% against the prior close and returns to within 10% of that prior close within 3
  bars is a bad print; the spike bars are replaced by linear interpolation between the
  bracketing good closes, and their opens are set to that close. (b) *Opens*: if an open
  is > 10% away from the prior close **and** > 5% away from the same-day close, the open
  is replaced by the close. Counts of corrected bars and series are printed.
- **A2. Correction chain made explicit** (each step isolates one fix):
  B_harness (old cadence quirk, drift trading, anchor leak, raw prices) →
  **B_live_leak** (live cadence + target-change rule; anchor leak and raw prices kept) →
  **B_live_raw** (+ strict point-in-time view: a single-name anchor is visible to the
  sleeves only while it is an index member — the old harness showed today's mega-cap
  anchors on every date, including years before they joined; ticker aliases META→FB,
  GOOGL→GOOG for membership) → **B_live** (+ A1 cleaning) = the reference for all gates.
- **A3. Risk-free**: `load_riskfree()` (^IRX) is asserted to cover both windows with
  non-zero variance. No silent flat-rate fallback.
- **A4. Candidate set change.** C4 (the C1+C3 combination) is **dropped** and replaced by
  **C5 — regime-gate hysteresis** on research_stack: the sleeve flips RISK_ON/RISK_OFF
  at GMM confidence 0.50 both ways; C5 leaves RISK_ON only when confidence < 0.35 and
  re-enters only when > 0.65. Rationale: the India run found the same gate flipping
  ~30× per window, rotating ~50% of NAV each time — pure short-term realizations; a dead
  band removes flips caused by confidence hovering at 0.5 without delaying a decisive
  move. One configuration, no sweep. Regime flip counts are printed for every arm as
  measurement. Candidates remain four: C1, C2, C3, C5. N_program = **10** (B_harness,
  B_live_leak, B_live_raw, B_live, B_live_whole, B0, C1, C2, C3, C5); N_project = **22**.
  The dispersion set for the deflated margin is {B0, C1, C2, C3, C5}, N = 5.
- **A5. Count correction**: `_RISK_UNIVERSE` holds 17 single names + 8 ETFs (not 18 + 7);
  B0 replaces 17.

## Addendum B — confirmation arm, written AFTER the main results, BEFORE it is run

Status at writing: all ten arms and both benchmarks have run on both windows; the gate
report shows C2 passing G1–G4 and B0 showing a −0.22 pre-tax Sharpe look-ahead cost of the
hard-coded research universe on the holdout. This addendum adds **one** arm; it does not
alter any gate, rate, rule or parameter above, and no other arm is added.

- **Why.** C2's active rule is "do not trim a winner, always sell a loser". Applied to a
  universe that was chosen *because* its names won (NVDA, AAPL, AMZN …), that rule is the
  one most likely to be flattered by hindsight. The relative gate (C2 vs B_live, same
  universe) is fair, but the owner should not change live code on a result that might not
  survive an honest universe.
- **Arm B0C2** = B0's mechanical research universe (top-17 PIT members by trailing-252d
  median dollar volume + the 8 ETFs) with C2's two rules (research_stack cadence 21
  calendar days; tax-aware sell rule). Nothing else changes.
- **Gate.** Same G1–G4, reference = **B0** (not B_live), same deflated margin (0.112,
  frozen from the main run), on the holdout; G4 on the design window. Outcome vocabulary
  unchanged. The ship recommendation for C2 stands only if B0C2 also passes; otherwise the
  recommendation is "KEEP CURRENT; C2's edge is not separable from universe hindsight".
- **Counting.** N_program = 11, N_project = 23. The dispersion set and margin are not
  recomputed (recomputing after seeing results is the thing this document forbids).
