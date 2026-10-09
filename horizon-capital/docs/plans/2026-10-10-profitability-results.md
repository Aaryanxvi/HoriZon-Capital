# Profitability gate — results (after cost, after Indian tax)

> **STATUS 2026-10-10 (paused on owner request):** program COMPLETE. All 11 arms and both
> benchmarks ran on both windows; `--report` regenerated after the final lint pass with
> identical verdicts; no background computation is running; everything is committed on
> `worktree-agent-aa57ee4d0fb2bdf72` (not pushed). Stopped before delivering the summary to
> the coordinator. Next: hand back this report; then, only if the owner wants, the
> follow-up gates listed in §5.4 (each needs its own pre-registration first).

Reports against `2026-10-10-profitability-gate.md` exactly as pre-registered (commits
`df23d26`, `4f6990d` addendum A, `f09f696` addendum B — all committed before the runs they
govern). Every number below is pasted from `scripts/validate_profitability.py` output
(`own research paper/profitability_{design,holdout}.log`, `profitability_report.log`).

## 0. Verdict in one line

**As it actually runs, the live mix does not beat an index fund after Indian tax on either
window** (post-liquidation after-tax CAGR 7.81% vs SPY 11.12% on 2018-24; 6.10% vs 6.31%
on 2008-17) because 96–100% of its gains are short-term and taxed at 34%; its real edge is
drawdown (−17/−21% vs −34/−53%). Of four pre-registered candidates, three fail outright and
the fourth (C2: hold winners, harvest losers, monthly research cadence) passes the primary
gates but **fails its pre-registered confirmation on a hindsight-free universe** (§4), so
**nothing ships**; the honest answer to the owner is "an index fund is better after tax".

## 1. What ran

- Data: 643 price series = PIT S&P 500 union 2008-24 + anchors, `period=max` (the paper's
  own cache). Coverage of the PIT union: 85% (2018-24), 70% (2008-17), 73% overall; the
  missing names are delisted — inflates absolutes in every arm equally.
- Risk-free: realized 13-week bill, asserted to span both windows (mean 2.33% on 2018-24,
  **0.31%** on 2008-17 — the flat 4% the handoffs used was a wrong hurdle there).
- Cleaning (addendum A1): 126 spike close bars and 5,055 junk opens corrected across 545
  series. Effect on results: none measurable (B_live_raw ≡ B_live).
- FX: USDINR 39.38 → 64.06 over 2008-17; gains taxed in INR as the law requires.
- Taxes: base 30% slab + 10% surcharge + 4% cess → ST 34.32%, LT 14.30%, dividends 34.32%
  (25% US withholding credited); FIFO; 24-month line; s.74 set-off; tax paid from the
  portfolio each 31 March; terminal liquidation taxed for every arm.
- Reproduction: B_harness (old harness semantics, raw data) = Sharpe **0.77** (2018-24) and
  **0.70** (2008-17) at flat 4%, matching the recorded LOO-breadth and holdout-candidate
  figures. Note: the 0.67 quoted in the brief is the OLD 4-sleeve mix; the live 3-sleeve
  mix on 2018-24 was always 0.77.

### Harness corrections and what each one was worth (flat-4% Sharpe, design / holdout)

| Step | What changed | Sharpe | Comment |
|---|---|---|---|
| B_harness | as published | 0.77 / 0.70 | cadence quirk (momrank every 105d), weekly drift re-trading, anchors always visible |
| B_live_leak | live cadence (calendar-day) + trade only on ≥0.5% target change | 0.77 / 0.75 | the two bugs the India agent flagged were roughly neutral here |
| B_live_raw | + strict point-in-time view (today's mega-caps hidden before they joined the index) | 0.67 / 0.60 | **the anchor leak was worth +0.10 / +0.15** |
| **B_live** | + price cleaning = the honest "current live mix" | **0.67 / 0.60** | realized-RF Sharpe 0.78 / 0.89 |
| B_live_whole | + whole-share rounding ($100k book) | 0.68 / 0.60 | immaterial |
| B0_mech_univ | research_stack universe chosen mechanically (top-17 by $ volume) | 0.66 / 0.39 | **−0.22 Sharpe of universe hindsight on the holdout**; none on 2018-24 |

## 2. Baseline: live mix vs SPY vs 60/40 (verbatim)

```
=== design 2018-01-01..2024-12-31 -- pre-tax (USD) ===
arm                 CAGR%   vol%  Sh4%  ShRF  maxDD  turn fills  gross flips defer qmjcov
SPY_bh               13.6   19.5  0.55  0.64  -33.7  0.05     1  100.0     0     0      -
6040_annual           7.3   12.0  0.32  0.46  -27.6  0.09    14  100.0     0     0      -
B_harness            15.8   15.3  0.77  0.89  -18.0  6.37  1915   78.0    44     0      -
B_live_leak          16.2   16.0  0.77  0.88  -18.9  6.72  1167   78.7    44     0      -
B_live_raw           14.1   15.5  0.67  0.78  -17.2  6.85  1206   79.3    44     0      -
B_live               14.1   15.5  0.67  0.78  -17.2  6.85  1206   79.2    44     0      -
B_live_whole         14.1   15.4  0.68  0.79  -17.2  6.79  1205   78.9    44     0      -
B0_mech_univ         14.4   16.5  0.66  0.76  -18.7  6.99  1241   78.0    44     0      -
C1_rs21              17.7   15.5  0.87  0.98  -13.3  4.42   714   78.9    30     0      -
C2_rs21_taxaware     20.3   17.5  0.92  1.02  -16.3  4.16   631   83.8    30   333      -
C3_pit_qmj           15.5   15.4  0.75  0.86  -17.2  6.81  1207   79.1    44     0   100%
C5_regime_hyst       15.3   15.5  0.74  0.85  -17.2  6.26  1167   79.2    36     0      -

=== design -- after Indian tax (base 30%+10%sc, FX 0.50% each way) ===
arm                  %ST tax/yr  ATpre ATpost  ATinr  ATsh   ATdd  drag nreal
SPY_bh               0.0   2.75  12.81  11.12  15.91  0.61  -33.9  2.48     0
6040_annual          1.2   2.07   6.13   5.09   9.62  0.38  -28.5  2.21     6
B_harness          100.0   5.64   9.37    8.9   13.6  0.51  -17.2   6.9  1596
B_live_leak        100.0   5.73   9.68   9.25  13.96  0.51  -18.2  6.95   803
B_live_raw         100.0   5.37   8.24   7.81  12.46  0.44  -16.9  6.29   833
B_live             100.0   5.37   8.24   7.81  12.46  0.44  -16.9  6.29   833
B_live_whole       100.0   5.36   8.26   7.84  12.49  0.44  -16.9  6.26   831
B0_mech_univ       100.0   5.31   8.35   7.95   12.6  0.43  -18.2  6.45   862
C1_rs21            100.0   6.11  10.74  10.32  15.07  0.57  -13.8  7.38   443
C2_rs21_taxaware   100.0   6.98  13.51  12.24  17.08  0.67  -17.1  8.06   355
C3_pit_qmj         100.0   5.71   9.14   8.76  13.45  0.49  -17.0  6.74   836
C5_regime_hyst     100.0   5.65    9.1   8.69  13.38  0.48  -16.9  6.61   815

=== holdout 2008-01-01..2017-12-31 -- pre-tax (USD) ===
arm                 CAGR%   vol%  Sh4%  ShRF  maxDD  turn fills  gross flips defer qmjcov
SPY_bh                8.5   20.3  0.31  0.49  -51.9  0.04     1  100.0     0     0      -
6040_annual           9.1   10.0  0.52  0.88  -26.8  0.08    18  100.0     0     0      -
B_harness            13.0   12.9   0.7  0.99  -19.1   6.3  2748   75.4    57     0      -
B_live_leak          14.1   13.5  0.75  1.02  -17.1  6.65  1801   76.0    57     0      -
B_live_raw           11.5   12.9   0.6  0.88  -20.2   6.6  1802   75.7    57     0      -
B_live               11.5   12.8   0.6  0.89  -20.2   6.6  1802   75.7    57     0      -
B_live_whole         11.5   12.8   0.6  0.89  -20.2  6.59  1802   75.6    57     0      -
B0_mech_univ          8.6   13.1  0.39  0.67  -18.5  6.94  1865   76.5    57     0      -
C1_rs21              10.6   13.2  0.53  0.81  -20.3  4.27  1039   75.5    38     0      -
C2_rs21_taxaware     14.0   15.6  0.66   0.9  -20.6  3.76   885   80.9    38   497      -
C3_pit_qmj           10.8   12.5  0.57  0.86  -20.2  7.06  1879   75.6    57     0   100%
C5_regime_hyst       12.7   12.9  0.68  0.97  -20.2  6.07  1747   75.5    47     0      -

=== holdout -- after Indian tax (base 30%+10%sc, FX 0.50% each way) ===
arm                  %ST tax/yr  ATpre ATpost  ATinr  ATsh   ATdd  drag nreal
SPY_bh               0.0   2.57    7.5   6.31  11.62  0.45  -52.7  2.19     0
6040_annual          2.9   2.62   7.21   6.18  11.48  0.72  -30.4  2.92     8
B_harness           96.6   4.68   7.19   7.06   12.4  0.57  -18.7  5.94  2299
B_live_leak         96.1   4.81   7.97   7.86  13.24   0.6  -17.2  6.24  1280
B_live_raw          95.7   4.55   6.22    6.1   11.4   0.5  -20.6   5.4  1279
B_live              95.7   4.55   6.22    6.1  11.39   0.5  -20.6   5.4  1279
B_live_whole        95.7   4.55   6.22    6.1  11.39   0.5  -20.6   5.4  1279
B0_mech_univ        94.7   3.75   4.39   4.22   9.42  0.37  -18.6  4.38  1306
C1_rs21             95.4   4.49   5.71   5.54   10.8  0.46  -21.0  5.06   664
C2_rs21_taxaware    96.5   6.05   9.78   7.96  13.35  0.65  -21.3  6.04   519
C3_pit_qmj          95.6   4.44   5.84   5.67  10.95  0.49  -20.6  5.13  1329
C5_regime_hyst      95.9   4.84   7.01   6.89  12.23  0.56  -20.6  5.81  1255
```
Columns: Sh4% = Sharpe vs flat 4%; ShRF = vs realized bill; turn = one-way turnover × NAV/yr;
%ST = share of realized gains that were short-term; tax/yr = tax paid as % of avg NAV per
year; ATpre/ATpost = after-tax CAGR before/after terminal liquidation (USD-equivalent);
ATinr = post-liquidation CAGR in INR; ATsh/ATdd = Sharpe/maxDD of the accrual after-tax
curve; drag = pre-tax CAGR − ATpost; flips = research_stack regime flips; defer = C2
deferred trims; qmjcov = share of composite scores ≠ 0 (beta alone makes this 100%; the real
SEC coverage is in §3).

### Baseline, read plainly (B_live = the current live mix)

| | 2018-24 live | 2018-24 SPY | 2018-24 60/40 | 2008-17 live | 2008-17 SPY | 2008-17 60/40 |
|---|---|---|---|---|---|---|
| Pre-tax CAGR | 14.1 | 13.6 | 7.3 | 11.5 | 8.5 | 9.1 |
| Pre-tax Sharpe (realized RF) | 0.78 | 0.64 | 0.46 | 0.89 | 0.49 | 0.88 |
| maxDD | −17.2 | −33.7 | −27.6 | −20.2 | −51.9 | −26.8 |
| % gains short-term | 100 | 0 | 1.2 | 95.7 | 0 | 2.9 |
| Tax drag (pts/yr) | 6.29 | 2.48 | 2.21 | 5.40 | 2.19 | 2.92 |
| **After-tax CAGR, post-liquidation** | **7.81** | **11.12** | 5.09 | **6.10** | **6.31** | 6.18 |
| After-tax Sharpe | 0.44 | 0.61 | 0.38 | 0.50 | 0.45 | 0.72 |
| After-tax maxDD | −16.9 | −33.9 | −28.5 | −20.6 | −52.7 | −30.4 |

- Pre-tax the live mix beats SPY on both windows (+0.5 and +3.0 CAGR points, far better
  drawdowns). After tax it loses on both: the strategy pays 5.4–6.3 points of CAGR a year
  in tax, SPY pays 2.2–2.5 (dividends yearly, 14.3% once at the end).
- On 2008-17 SPY buy-and-hold ends with slightly more money (6.31% vs 6.10%) **and** a
  −53% drawdown versus −21%. 60/40 has the best after-tax Sharpe there (0.72). On 2018-24
  SPY wins outright (11.12% vs 7.81%, higher after-tax Sharpe).
- The 24-month long-term line is unreachable for this strategy (weekly/monthly momentum:
  96–100% short-term). The lever is not "become long-term", it is "realize less".
- Rate sensitivity does not change any ranking: at a 20% slab the live mix is 10.24% vs SPY
  11.53% (design) and 8.13% vs 6.79% (holdout — only here does a lower slab flip it). FX
  cost 0.25–1% moves every arm by ±0.1–0.15 points equally.
- Rupee depreciation is taxed: 2008-17 USDINR rose 63%, so SPY's INR gain (and tax) was far
  larger than its USD gain — SPY's 2.57%-of-NAV yearly tax bill is mostly that.

## 3. Candidates and gates (verbatim from `--report`)

```
=== Deflated margin: sigma_delta 0.094 over 5 variants, E[max] 0.112, margin 0.112 ===

=== Gates on the holdout (after-tax, base rates) ===
C1_rs21            dATsharpe -0.040 (G1 F) | ATdd -21.0 vs -20.6 (G2 P) | ATpost 5.54 vs 6.1 (G3 F) | design d +0.13 (G4 F) -> KEEP CURRENT
C2_rs21_taxaware   dATsharpe +0.150 (G1 P) | ATdd -21.3 vs -20.6 (G2 P) | ATpost 7.96 vs 6.1 (G3 P) | design d +0.23 (G4 P) -> SHIP
C3_pit_qmj         dATsharpe -0.010 (G1 F) | ATdd -20.6 vs -20.6 (G2 P) | ATpost 5.67 vs 6.1 (G3 F) | design d +0.05 (G4 F) -> KEEP CURRENT
C5_regime_hyst     dATsharpe +0.060 (G1 F) | ATdd -20.6 vs -20.6 (G2 P) | ATpost 6.89 vs 6.1 (G3 P) | design d +0.04 (G4 P) -> KEEP CURRENT

=== C3 data coverage: names (of 17) with SEC point-in-time ROE on 2 Jan ===
2008:0 2009:0 2010:3 2011:12 2012:12 2013:12 2014:14 2015:14 2016:14 2017:15 2018:15 2019:16 2020:16 2021:16 2022:15 2023:15 2024:16

=== PSR / DSR (pre-tax excess returns; N_program=10, N_project=22) ===
design: program Sharpe range 0.76..1.02, SPY 0.64
  B_live             pre  PSR>0 0.980  PSR>SPY 0.646  DSR(N=10) 0.954  DSR(N=22) 0.946
  B_live             post PSR>0 0.875  PSR>SPY 0.297  DSR(N=10) 0.784  DSR(N=22) 0.758
  C2_rs21_taxaware   pre  PSR>0 0.996  PSR>SPY 0.838  DSR(N=10) 0.989  DSR(N=22) 0.987
  C2_rs21_taxaware   post PSR>0 0.960  PSR>SPY 0.527  DSR(N=10) 0.917  DSR(N=22) 0.903
holdout: program Sharpe range 0.67..1.02, SPY 0.49
  B_live             pre  PSR>0 0.997  PSR>SPY 0.893  DSR(N=10) 0.989  DSR(N=22) 0.985
  B_live             post PSR>0 0.943  PSR>SPY 0.518  DSR(N=10) 0.862  DSR(N=22) 0.836
  C2_rs21_taxaware   pre  PSR>0 0.998  PSR>SPY 0.902  DSR(N=10) 0.991  DSR(N=22) 0.987
  C2_rs21_taxaware   post PSR>0 0.980  PSR>SPY 0.695  DSR(N=10) 0.941  DSR(N=22) 0.926
```
(C1/C3/C5 PSR/DSR rows are in `profitability_report.log`.)

Per candidate:
- **C1 — research_stack weekly → 21 days.** Better on 2018-24 (+0.13 after-tax Sharpe,
  turnover 6.85 → 4.42), worse on 2008-17 (−0.04, CAGR 5.54 vs 6.10). Sign flips between
  windows → KEEP CURRENT. Less churn alone is not enough.
- **C2 — C1 + tax-aware sells** (defer partial trims of winners; always sell losers; full
  exits always). Passes G1–G4: holdout after-tax Sharpe +0.15 (> 0.112 deflated margin),
  CAGR 7.96 vs 6.10, maxDD −21.3 vs −20.6; design +0.23, 12.24 vs 7.81. Fills fall 1206 →
  631 and 1802 → 885. **Beats SPY after tax on both windows** (12.24 vs 11.12; 7.96 vs 6.31)
  with roughly half SPY's drawdown. Honest mechanics: average gross exposure rises
  (79 → 84%, 76 → 81%) and vol with it (15.5 → 17.5, 12.8 → 15.6); on the holdout the
  pre-tax Sharpe is unchanged (0.90 vs 0.89) — there the whole gain is "fewer taxable
  trims + more exposure", on 2018-24 the pre-tax Sharpe also improves (1.02 vs 0.78). The
  after-tax DSR at N=22 is 0.90 / 0.93; PSR(>SPY) after tax 0.53 / 0.70 — better than the
  live mix's 0.30 / 0.52, still far from certainty.
- **C3 — real point-in-time QMJ (SEC companyfacts).** Feasible for free: 17/17 names
  mapped, coverage 12–16 of 17 from 2011 on, zero before mid-2009 (no XBRL), so the
  holdout test is partial. Result: ≈ neutral (+0.05 design, −0.01 holdout after-tax Sharpe;
  CAGR 8.76 vs 7.81 and 5.67 vs 6.10) → KEEP CURRENT. Implication for live: the quality
  tilt neither helps nor hurts measurably; the look-ahead in the live yfinance snapshot is
  therefore a correctness problem, not a hidden return source.
- **C5 — regime-gate hysteresis (leave RISK_ON < 0.35, re-enter > 0.65).** Flips 44 → 36
  and 57 → 47; after-tax CAGR +0.9 / +0.8 points; after-tax Sharpe +0.04 / +0.06 — right
  direction on both windows but under the 0.112 deflated margin → KEEP CURRENT ("promising,
  not proven"). Flips are a real cost: 5.7–6.3 flips a year each rotating the 50% sleeve ≈
  3 NAV-turns of the 6.6–6.9 yearly total, all short-term.
- **Not tested** (pre-registered reasons): volatility targeting, stop-loss (other agent),
  previously rejected ideas.

## 4. Addendum B — does C2 survive an honest universe? **No.**

```
=== Addendum B confirmation on the holdout (after-tax, base rates; margin 0.112, reference B0_mech_univ) ===
B0C2_mech_rs21_tax dATsharpe -0.030 (G1 F) | ATdd -22.7 vs -18.6 (G2 F) | ATpost 3.34 vs 4.22 (G3 F) | design d +0.22 (G4 F) -> KEEP CURRENT
design   B0C2 vs SPY after tax: CAGR 12.56 vs 11.12, Sharpe 0.65 vs 0.61, maxDD -19.8 vs -33.9
holdout  B0C2 vs SPY after tax: CAGR 3.34 vs 6.31, Sharpe 0.34 vs 0.45, maxDD -22.7 vs -52.7

arm (window)                 CAGR%   vol%  Sh4%  ShRF  maxDD  turn fills  gross flips defer | ATpost  ATsh   ATdd
B0_mech_univ (holdout)         8.6   13.1  0.39  0.67  -18.5  6.94  1865   76.5    57     0 |   4.22  0.37  -18.6
B0C2_mech_rs21_tax (holdout)   7.5   14.8  0.29  0.54  -22.2  4.14   969   80.8    38   433 |   3.34  0.34  -22.7
B0_mech_univ (design)         14.4   16.5  0.66  0.76  -18.7  6.99  1241   78.0    44     0 |   7.95  0.43  -18.2
B0C2_mech_rs21_tax (design)   20.9   18.8  0.89  0.98  -18.9  4.25   641   83.4    30   375 |  12.56  0.65  -19.8
```

With the research universe chosen mechanically (no knowledge of who later won), C2's two
rules lose on 2008-17 on every gate — Sharpe, drawdown (4 points worse) and terminal wealth
— and keep their large 2018-24 gain. The +1.86 CAGR points C2 added over B_live on the
holdout therefore came from *not trimming names that were in the list because they later
won*. "Let winners run" is only reliably profitable when the winners are known in advance.
The 2018-24 result (beats SPY after tax by 1.4 points with 60% of its drawdown) is real for
that window but is one mega-cap regime, and the whole point of the holdout was to catch
exactly this.

## 5. Recommendation

1. **Ship nothing.** C1, C3 and C5 fail the primary gates; C2 passes them but fails the
   pre-registered confirmation on a hindsight-free universe. Per the gate document the
   outcome is KEEP CURRENT.
2. **Tell the owner the baseline answer plainly:** after Indian tax the live mix makes less
   money than SPY buy-and-hold on both windows (−3.3 points/yr in 2018-24, −0.2 in 2008-17)
   because 96–100% of its gains are short-term at 34%. What it buys for that is drawdown:
   −17/−21% against −34/−53%. If the objective is after-tax wealth, a US index ETF held
   past 24 months (12.5% once) is the better instrument; if the objective is a shallower
   worst year, the mix delivers that and the owner should know its price.
3. **Fix the measurement before the next strategy idea** (these are live-code changes and
   need their own gates, not done here): (a) replace `ResearchStackSleeve._RISK_UNIVERSE`
   with a mechanical rule — the hard-coded list is worth −0.22 Sharpe / −2.9 CAGR points
   of hindsight on 2008-17 and every prior holdout number carried it; (b) adopt the
   strict point-in-time view and live-semantics cadence/trading rule in all harnesses
   (`validate_profitability.replay` is the reference implementation); (c) the live
   yfinance quality snapshot is look-ahead with no measurable value (C3 ≈ 0) — switch it to
   `scripts/pit_quality.PITQuality` or drop the tilt.
4. **Hypotheses for a future pre-registered gate** (not tested, not evidence): C5
   hysteresis plus C2's loss-harvest leg only (no winner deferral) on the mechanical
   universe; interaction of the 20% trailing stop with tax (a stop is a loss harvest);
   earning the bill rate on the 21–25% average cash. Each should be one configuration,
   gated on the holdout against B0 with the frozen 0.112 margin.
5. **Structural fact for an LRS investor:** anything that turns over monthly pays the slab
   rate. To beat SPY after tax the engine needs either consistent pre-tax alpha of roughly
   3–4 points a year over SPY, or holding periods past 24 months. On honest data it has
   neither today.

## 6. Caveats (carry these with every number)

1. **Universe hindsight inside research_stack.** `_RISK_UNIVERSE` is a hard-coded list of
   2024's winners; replacing it mechanically costs −0.22 Sharpe and −2.9 CAGR points on
   2008-17 (nothing on 2018-24, where the list ≈ the biggest names anyway). The 2026-07-17
   holdout gate that selected the live mix (0.70) contained this. The honest holdout
   baseline is B0: after-tax 4.22% vs SPY 6.31%.
2. **Anchor leak** in all prior harness numbers (+0.10 / +0.15 Sharpe). Fixed here; the
   published 0.77 / 0.70 should be read as 0.67 / 0.60.
3. Delisted-price gap (15–30%) inflates every arm; one holdout; N_program 11 variants,
   margin deflated accordingly; the holdout was already touched once by the July reweight.
4. Tax model: current (post-July-2024) rates applied to history; spot FX instead of Rule
   115's prior-month-end TTBR; all equity given SPY's dividend yield (overstates the
   strategy's dividend tax slightly); 8-year loss expiry not modelled; tax paid pro-rata
   from the portfolio with the second-order tax on that sale ignored; TCS (20% above ₹10L,
   creditable) is a cash-flow cost not in these numbers; the owner's actual slab, surcharge
   and residency must be confirmed with a CA.
5. Cash earns 0% in the harness while the strategy holds ~21–25% cash (SPY holds none): in
   2018-24 that is ≈ +0.5 pre-tax / +0.3 after-tax points the strategy would plausibly earn
   in a swept account — not enough to change any verdict.
6. QMJ coverage before 2011 is partial; C3 on the holdout is a weak test.
7. Live-faithfulness: B_live reproduces StrategyAgent's cadence and target-change rule, but
   not fills at Alpaca, partial fills, the stop-loss, or the LLM debate gate.

## 7. Files

- Gate (pre-registered): `docs/plans/2026-10-10-profitability-gate.md`
- Harness: `backend/scripts/validate_profitability.py` (`--window`, `--report`,
  `--selfcheck`), `backend/scripts/pit_quality.py` (SEC point-in-time QMJ, `--selfcheck`)
- Logs (gitignored, regenerable): `own research paper/profitability_*.log|json|pkl`
