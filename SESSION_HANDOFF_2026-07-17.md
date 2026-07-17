# Horizon Capital — Session Handoff (2026-07-17)

Supersedes SESSION_HANDOFF_2026-07-02.md. Branch work on `feat/launch-hardening`,
**merged to main `c6ead80`** (fast-forward, not pushed — owner rule). Suite: **432 passed**, ruff clean.

## Git facts
- Canonical repo root: `C:\Users\Admin\Documents\Code\Horizon capital` (outer). Nested stale
  repo trap at `horizon-capital/.git` still exists — always `git -C` the outer root.
- Research worktree: `.worktrees/momrank-topn` (branch `exp/momrank-topn`, commit `c3c7e1d`) —
  contains the momrank gate harness only; NOT merged, verdict was negative.
- Untracked leftovers (pre-existing, deliberately not committed): `PROJECT_SUMMARY.md`,
  `horizon-capital/backend/scripts/monte_carlo_forward.py`, `scripts/.mc_equity_new.csv`.

## What shipped today (all reviewed, on main)
1. `0e17881` — **hygiene**: agent_messages retention (ITAgent hourly prune, first-loop immediate,
   `AGENT_MESSAGES_RETENTION_DAYS` default 7; live boot pruned 401 rows), forex KV key unified to
   `horizon:forex:usdinr` (kv_store whitelist matched reader; note: nothing WRITES this key yet —
   reader still falls back 83.0), dead `PortfolioOptimizer` field removed from PortfolioAgent.
2. `fcf1228` — **commission-correct realized P&L**: `update_position(commission=)` subtracts
   commission from `positions.realized_pnl` on EVERY fill (opening legs → −commission; new-position
   INSERT binds −commission). Convention: lifetime realized_pnl == gross P&L − all commissions ==
   matches cash exactly. `services/performance.py` attribution SQL subtracts `COALESCE(f.commission,0)`.
   Cash path was already commission-correct (execution_agent fill txn) — untouched.
3. `0c6eb2b` — **Alpaca paper wiring**: `EXECUTION_BROKER=PAPER|ALPACA` setting; hard guard
   `_alpaca_guard_ok()` (key+secret+paper_mode+"paper-api" in URL, else loud PAPER fallback — live
   URL unreachable by construction); async fill settlement (`_settle_fill()` shared by instant +
   polling paths, idempotent via terminal-status re-check under per-symbol lock);
   `_poll_open_orders` polls ALPACA rows via `get_order_status` (24h stale-cancel, not 60s);
   startup reconciliation: account reachability (fallback PAPER + RISK_ALERT), broker-vs-local
   position diff (report-only, never mutates), immediate poll of stuck OPEN orders.
   `OrderManager.set_broker_order_id()` added (OPEN→OPEN isn't a valid status transition — TDD
   caught update_status silently no-oping and dropping the broker id).
4. `6b668b8` — **review fixes**: instant path settles ONLY complete fills (`filled_qty >= quantity`;
   0 and partials defer to polling — prevents double-count vs Alpaca's cumulative filled_qty);
   zero-price guard (`alpaca_filled_without_price` → retry next cycle, never settle at 0).
5. `51d2d4c` — **equity-sync guard** (born from live incident, below): startup compares broker
   equity vs local NAV (`horizon:portfolio:nav`, fallback initial_capital_usd); >2% mismatch →
   CRITICAL RISK_ALERT + PAPER fallback. Plus conftest fix: tests now pin `execution_broker=PAPER`
   (with EXECUTION_BROKER=ALPACA in .env, 5 tests were silently hitting the REAL Alpaca API).
6. `c6ead80` — docs: the plan (`docs/plans/2026-07-17-launch-hardening.md`).

## LATE-SESSION: attribution + holdout gate → LIVE MIX REWEIGHTED (`a3091c0` on main)
Owner asked "which engines aren't good enough" — measured properly:
- Per-sleeve attribution (worktree `8e5e5a4`, PIT 2018-24, pre-registered LOO rules): breadth_alpha
  DRAGS (LOO Sharpe 0.77 vs mix 0.67; worst solo 0.33, corr 0.63 to momrank); research_stack
  CARRIES hardest (LOO 0.51, best diversifier); momrank CARRIES; trend NEUTRAL (insurance).
- Pre-registered holdout gate (worktree `fb4939c`, PIT 2008-17, window untouched by selection,
  71% coverage GFC-era): candidate research .500/trend .333/momrank .167 → Sharpe 0.70 vs
  current 0.63, maxDD −19.1 vs −26.9, same CAGR. G1+G2 PASS.
- **SHIPPED `a3091c0`**: StrategyAgent live mix now research .500 / trend_filter .333 /
  momentum_rank .167; BreadthAlphaSleeve dropped from live set (class kept, research artifact,
  same convention as DualMomentum/GapFade). Composition test updated. 432 tests green.
- Caveats on record: QMJ still stubbed both arms (candidate leans harder on research — live may
  differ); 71%/85% coverage flatters absolutes both arms; one candidate, one holdout.
- Note: sleeves/__init__.py docstring pre-existing stale ("trend_filter NOT used live" — wrong).

## momrank verdict (gate test, worktree, NOT shipped)
Pre-registered gates on PIT 2018-24, live config (cap 20%/K25/conv.5): top-10 full-mix Sharpe
0.63 vs top-3's 0.67 → **G1 FAIL** (G2 passed, −37.6% vs −49% bar). **Keep `_TOP_N=3`.**
KEY RECONCILIATION: top-3 standalone maxDD measured **−25.4%**, not the −59.5% in older notes —
the live 20% position cap already does the concentration control; −59.5% came from an uncapped
harness. momrank backlog item is CLOSED (cap is the fix; widening makes the blend worse).
Coverage 85% (568/667), same delisted gap as before.

## LIVE LAUNCH (the big event) — ran, found real bugs, currently STOPPED
Launched `py -3.14 -m app --headless`, SYSTEM_MODE=PAPER_TRADING, EXECUTION_BROKER=ALPACA,
CIO_MODE=HUMAN (temp — see LLM section). Bash `python` lacks deps; use `py -3.14`.
Boot needs piped blank lines through the onboarding wizard (`yes "" | py -3.14 -m app --headless`).

**What worked (verified live):** 9 signals → risk-approved → sized → orders; Alpaca accepted →
`alpaca_order_accepted_pending_fill` (broker_order_id persisted, no fabricated fill) → poll →
settled ~5s later with real fills (INTC 1602.35@93.73, SPY 200.87@744.88, LLY 44.99@1183.68 —
fractional shares work); atomic cash txn correct.

**Live incident:** local NAV $1M (INITIAL_CAPITAL_USD) vs real Alpaca paper account ~$100k equity.
First 3 orders consumed all real buying power INTO MARGIN (account ended equity $99k, cash −$253k,
BP 0 = accidental 3.5× leverage); remaining 6 orders 403 "insufficient buying power". Root cause:
sizing uses local NAV; no capital sync existed. Fixed by `51d2d4c` (guard). App killed.

**Relaunch checklist (pending owner):**
1. Owner resets Alpaca paper account to $1,000,000 (app.alpaca.markets → Paper → Reset, custom
   amount) — also clears the margin positions. ← WAITING HERE
2. `py -3.14 -m app --reset` (wipe local SQLite so cash/NAV/positions start clean).
3. Relaunch headless; verify log shows `alpaca_equity_ok` then clean reconciliation, then fills.

## LLM status (blocks the AI product story, not the rule-based trading)
- OpenAI key in .env: INVALID (401s) — owner to rotate.
- Gemini key (replaced today, also pasted in chat — advise rotation): authenticates, lists models,
  but ZERO inference quota (2.0-flash 429 quota=0; 2.5-flash 404; flash-latest 503×3). Project
  needs billing / a standard AIza key from a billed project (aistudio.google.com).
- .env currently: all `AI_*=gemini`, `CIO_MODE=HUMAN`, `SYSTEM_MODE=PAPER_TRADING`.
- Owner's stated product core: AI debates + autonomous execution → once a key works, flip
  `SYSTEM_MODE=FULLY_AUTONOMOUS` + `CIO_MODE=AI`. PAPER_TRADING mode needs no LLM (validated
  Sharpe-0.67 config is fully rule-based; debates run advisory and auto-approve).

## Open (next session)
- Relaunch after Alpaca reset (checklist above) + leave running; watch first full market day.
- Working LLM key → FULLY_AUTONOMOUS + CIO_MODE=AI; re-verify debate gate approves/rejects live.
- Alpaca partial fills: intermediate partials are deliberately NOT booked (settle-once-at-terminal);
  fine for liquid market orders, revisit if limit orders / illiquid names arrive.
- Forex KV key has no writer (reader falls back 83.0) — only matters for INR reporting.
- Universe: live boot fell back to 100-name list (Wikipedia 403) — pre-existing; PIT membership
  unaffected (used only in backtests).
- Rotate both API keys (OpenAI invalid; Gemini was pasted into a chat).

## Owner tone (unchanged)
Brutally honest; pre-registered gates; harness bugs fixed + disclosed; adverse verdicts reported.
