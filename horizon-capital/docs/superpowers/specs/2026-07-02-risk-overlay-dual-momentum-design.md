# Risk Overlay + Dual-Momentum Sleeve — Design

**Date:** 2026-07-02
**Goal:** raise portfolio Sharpe above SPY (0.55) and cut maxDD below −25% on honest
survivorship-free data, without manufacturing fake alpha. Current honest baseline
(PIT S&P 500, 2018–2024): Sharpe 0.30, CAGR 8.1%, maxDD −36.5%.

**Explicit non-goal:** beating SPY's 2018–24 CAGR long-only. Any change that achieves
that on this window is presumed overfit and rejected.

## Success bar

Ship a variant only if, versus the current-config baseline:

1. Sharpe strictly higher AND maxDD strictly better on PIT 2018–2024, AND
2. on the second sample (ETF universe, 2008–2017), the variant's Sharpe is not
   lower than its counterpart without the component under test (i.e., the
   component must not hurt in the out-of-window sample).

If no variant passes, nothing ships and the report says so.

## Component 1 — Risk overlay (`app/quant/risk_overlay.py`, new)

Pure functions, no state, no I/O:

```
realized_vol(port_returns, window=20) -> float          # annualized trailing vol
vol_target_scalar(port_returns, target=0.15, window=20) -> float
    # min(1.0, target / realized) — cuts exposure when vol spikes, never levers up
trend_gate(spy_closes, as_of, sma_window=200) -> float
    # 1.0 if SPY close >= 200d SMA else 0.0
overlay_scalar(port_returns, spy_closes, as_of, ...) -> float
    # vol_target_scalar * trend_gate, clamped to [0, 1]
```

Parameters are locked from published research (Moreira–Muir 2017 vol targeting at
15%; Faber 2007 200d SMA) BEFORE any test runs and are never tuned on the test
window afterward.

**Live integration point:** `StrategyAgent` — after sleeve aggregation, before the
50bps drift check: `final_weights = {s: w * scalar for s, w in agg.items()}`.
Freed weight is implicit cash. Overlay moves therefore emit rebalance signals
through the existing pipeline; no changes to Risk/Portfolio/Execution agents.

**Config:** `OVERLAY_ENABLED` (bool, default off until validation passes),
`OVERLAY_VOL_TARGET` (default 0.15). One env line reverts live behavior exactly.

## Component 2 — Dual-momentum sleeve (`sleeves/dual_momentum.py`, new)

`DualMomentumSleeve(BaseSleeve)`, monthly cadence. Universe: SPY, EFA, TLT, GLD,
DBC, BIL (cash proxy). Rule = Antonacci GEM, verbatim, no tuning:

1. Rank risk assets (SPY, EFA, TLT, GLD, DBC) by 12-1 momentum.
2. If the top asset's 12-month return > BIL's 12-month return → hold it at 100%
   of sleeve weight.
3. Else → hold TLT.

ETF prices have no survivorship bias — free data is fully honest for this sleeve.

## Component 3 — Sleeve weights

| Sleeve | Old | New |
|---|---|---|
| breadth_alpha | 40% | 30% |
| research_stack | 30% | 25% |
| dual_momentum | — | 30% |
| momentum_rank | 10% | 15% |
| trend_filter | 20% | **deleted** |

TrendFilterSleeve is removed: portfolio-level trend gate + dual momentum cover the
same mechanism. Its tests are removed/updated with it. Weights stay config-driven,
so reverting is config-only.

## Component 4 — Validation (`scripts/validate_overlay.py`, new)

One-shot protocol. Four variants, same data, same cost model (1bp commission,
2bp slippage, as in `validate_pit.py`):

| Variant | Composition |
|---|---|
| baseline | current sleeves/weights, no overlay (must reproduce ~Sharpe 0.30) |
| +overlay | current sleeves + overlay |
| +dualmom | new weights incl. dual-mom, no overlay |
| full | new weights + overlay |

Samples:

- **PIT 2018–2024** (S&P 500 point-in-time membership, ~85% price coverage) —
  primary verdict vs SPY.
- **ETF 2008–2017** (SPY/EFA/TLT/GLD/DBC/BIL) — second sample including GFC;
  guards against single-window luck. Breadth sleeve can't run here (no PIT
  pre-2018 free), so this sample validates overlay + dual-mom components.

Pass/fail per the Success bar is printed at the top of the report. No parameter
iteration on either window after first run.

## Component 5 — Tests

- `tests/test_risk_overlay.py`: scalar ∈ [0,1]; caps at 1.0 when vol below target;
  gate flips exactly at SMA cross; NaN/short-history inputs degrade to 1.0 (fail-open
  to current behavior, never crash).
- `tests/test_dual_momentum.py`: GEM picks correct asset on synthetic data; falls
  to TLT when cash beats all; monthly cadence respected; sleeve weights sum ≤ 1.
- StrategyAgent tests updated for trend_filter removal + overlay hook.
- Full suite (~400 tests) stays green.

## Known risks (accepted, eyes open)

- Trend gate whipsaw in V-recoveries (2020): exits near bottom, re-enters late.
  Saves long bears (2008, 2022); costs sharp Vs. Net positive across full cycles
  historically — evidence, not certainty.
- Dual momentum has multi-year flat spells (2015–2019).
- Overlay only de-risks (≤1.0): CAGR likely dips slightly; Sharpe/DD improve.
- Residual ~15% survivorship gap in PIT sample (delisted names lack free prices):
  absolute numbers slightly inflated; variant-vs-baseline comparison unaffected
  (same data both sides).

## Rollback

Everything behind config: `OVERLAY_ENABLED=false` + old weight values = today's
live behavior exactly. No schema changes, no data migrations.
