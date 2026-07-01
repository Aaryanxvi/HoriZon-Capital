# Horizon Capital — Session Handoff (2026-07-02)

Supersedes SESSION_HANDOFF_2026-06-30.md. Branch: `feat/overlay-dualmom` (NOT merged
to main yet). All work committed; tree clean at handoff.

## Git facts (read first)
- **Canonical repo root: `C:\Users\Admin\Documents\Code\Horizon capital`** (outer).
- **TRAP: nested stale git repo at `horizon-capital/.git`** (branch
  feat/full-system-completion). Bare `git` from inside horizon-capital/ hits the
  WRONG repo. Always `git -C "<outer root>"`. Consider deleting the nested .git
  (ask owner first).
- Prior session's 8.9k-line breadth-engine work was UNCOMMITTED; rescued in
  baseline commit `958021f` on main.

## What shipped this session (on feat/overlay-dualmom)
1. **Risk overlay** `app/quant/risk_overlay.py` — Moreira-Muir 15% vol targeting ×
   Faber 200d trend gate, pure functions, fail-open 1.0. Wired in
   `StrategyAgent._apply_overlay`, behind `OVERLAY_ENABLED` (default **false**).
2. **DualMomentumSleeve** — Antonacci GEM, canonical menu (SPY/EFA risk, TLT
   defense, BIL cash). First cut wrongly had GLD/DBC in risk menu → bought 2008
   commodity top in backtest (−55% DD). Also fixed: TLT missing from emission set
   (RISK_OFF decided TLT but emitted nothing → 30% NAV in cash during crashes).
   `_demo()` self-check guards both.
3. **Live sleeve mix**: breadth .30 / dual_mom .30 / research .25 / momrank .15.
   trend_filter unwired (file kept — old scripts import it).
4. **9 audit fixes** (from Fable ROI audit, all verified in code):
   - risk window `ORDER BY DESC` (was ASC = frozen oldest-253d window forever)
   - `risk_max_drawdown_pct` 10→25, `risk_max_position_pct` 5→20 (10%/5% froze
     the book / stranded 15-30% NAV)
   - `universe_source` default → "sp500" (36-name config = unvalidated cousin)
   - `fetch_batch` default 400d→1200d (revives ltr signal + regime gate — both
     silently dead live)
   - breadth K12/conv0.3 → K25/conv0.5 (the validated config)
   - PortfolioAgent `_reconcile()` — 15min loop re-emits dropped orders
     (PAPER_TRADING only, halt-aware)
   - sells-first signal emission (buys before funding sells got dropped)
   - sleeve cache-on-exception (was liquidating sleeve on transient error)
   - fractional US shares (int() flooring stranded 2-5% NAV)
5. **Harnesses**: `scripts/validate_overlay.py` (ship-gate: overlay+GEM vs
   baseline, PIT 2018-24 + ETF 2008-17) and `scripts/validate_fix_ab.py` (4-way
   attribution OLD/NEW × config/PIT).
6. Tests: 418 pass (400 baseline + 18 new). Ruff clean on touched files.

## Validation verdicts (honest numbers)
- **A/B attribution (validate_fix_ab, PIT 2018-24)**: audit fixes VALIDATED.
  OLD-PIT Sharpe 0.41 → NEW 0.67 (CAGR 8.4→14.5, deployment 62→95%). vs SPY 0.55.
  Hand-picked 36-name universe = +0.5 Sharpe hindsight bias under BOTH param sets
  (0.95/1.21 columns discarded as bias). Caveats: quality tilt stubbed, ~14%
  delisted price gap (inflates absolute numbers), single window, momrank cadence
  ~105d in harness (both arms, controlled).
- **Overlay ship-gate**: PIT 2018-24 leg FAILED pre-registered gate (Sharpe
  0.24→0.0; maxDD −37→−20 ✓) — 2020/2022 V-recovery whipsaw. ETF 2008-17 leg
  PASSED brilliantly (SPY+ovl Sharpe 0.48 vs 0.30, maxDD −17 vs −50). Verdict:
  **OVERLAY_ENABLED stays false.** Open question: retest overlay on top of NEW
  config; owner may deliberately re-weigh gate toward DD-control (product thesis)
  — that's a product decision, flag overfit risk.
- **GEM**: first backtest invalid (wrong menu). Final rerun with canonical menu
  was IN FLIGHT at session close — rerun: `cd horizon-capital/backend &&
  python -m scripts.validate_overlay` (~4 min). Gate: gem 08-17 Sharpe > 0 AND
  blend beats baseline on Sharpe+maxDD.
- Run 1 harness bug (fixed): fetch_batch caches per-symbol ignoring period → ETF
  20y fetch after PIT 10y fetch returned 10y frames → 2008-16 empty. ETFs now
  fetched first.
- momrank top-3 on PIT: −59.5% maxDD — bad sleeve leg, revisit (reduce weight or
  top-N up).

## Next steps
1. Rerun `scripts.validate_overlay` → GEM verdict → dual-mom sleeve stays/goes.
2. Update spec (`docs/superpowers/specs/2026-07-02-...-design.md`) with final
   validation results section.
3. Merge feat/overlay-dualmom → main (no push — owner rule).
4. Decide overlay: keep off / retest on NEW config / re-weigh gate to DD-control.
5. Speculative (needs backtest): signal leave-one-out + IC-weighting, conviction
   weighting, REBAL=10, GMM hysteresis, debate-veto logging (Model A signal).
6. Live paper test with NEW config (owner's .env: FULLY_AUTONOMOUS + AI + Alpaca).

## Owner tone
Brutally honest, no yes-man. Gates pre-registered, no retuning on test windows;
harness bugs get fixed and disclosed, verdicts reported even when adverse.
