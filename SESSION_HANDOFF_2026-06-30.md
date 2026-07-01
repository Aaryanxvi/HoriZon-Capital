# Horizon Capital — Session Handoff (2026-06-30)

Give this file to a new session to restore context. Written after a long build +
honest-validation session. Read it fully before acting — it carries hard truths
so you don't relitigate them.

---

## 0. One-liner
Autonomous AI hedge-fund desktop terminal agent (Python, Rich TUI). Real app =
`horizon-capital/backend/app/`. LOCAL mode = SQLite + in-memory bus, zero infra.
Paper-trading. Owner is in **India**, market choice (US vs India) **undecided** —
engine is now market-agnostic so it ports.

## 1. THE decisive result (read first)
Ran the breadth engine on **point-in-time S&P 500 membership** (survivorship-free
universe), 2018–2024, 85% price coverage:

| | CAGR | Sharpe | maxDD |
|---|---|---|---|
| **Strategy (honest data)** | 8.1% | **0.30** | −36.5% |
| **S&P 500** | 13.6% | **0.55** | −33.7% |

**On honest data, the strategy UNDERPERFORMS the S&P 500.** The prior "edge"
(biased Sharpe ~1.0) was **survivorship + look-ahead bias, not alpha.** As built,
there is **no real edge.** This is the truth — do not let inflated backtests
(`demo_*.csv`, old summaries) convince you otherwise.

Caveats (don't use them to dodge the verdict): 85% coverage (delisted names lack
yfinance prices — paid vendor closes that gap); 2018–24 was a mega-cap-concentration
era brutal for diversified strategies (most pros also lost to SPX); value/beta
signals hurt in that momentum era.

## 2. Critical architecture truth
The AI agents currently **VET trades, they don't GENERATE them.** Flow:
`quant sleeves → signals → RiskAgent → DebateAgent (AI votes APPROVE/REJECT) →
Portfolio → Execution`. The quant engine is the *source*; the AI is a *filter*.
The AI's ceiling is bounded by the engine. "Users use the AI not the engine" is
NOT possible as built — the engine feeds the AI its choices.

## 3. Open strategic fork (UNRESOLVED — owner deciding)
Three product models discussed; owner undecided, leaning toward thinking it through:
- **A — AI generates trades** (rebuild; full untestable AI-alpha bet; high cost/risk; can't backtest — look-ahead trap; months to validate).
- **B — AI vets quant trades** (current; capped by the underperforming engine; weakest standalone).
- **C — AI is the experience, returns ~index** (honest/shippable; engine just matches market, AI = explainability/UX moat; smaller claim, competes with robo-advisors).

**My recommendation:** build **C now**, run **A as a cheap background experiment**
(forward-test AI-generated paper picks for months; graduate only if it shows edge).
B alone is a trap. Open question to owner: is the dream *to beat the market* (→A,
eyes open about low odds) or *give regular people a smart honest automated way to
invest* (→C, closer than you think)?

## 4. What was BUILT this session (all lint-clean, 400 tests pass)
**6 CRITICAL safety fixes** (verified real, fixed): kill-switch persists across
restart; stop-loss bypasses cooldown/debate gate; debate debounce clears buffer +
latest-only; risk VaR from daily NAV not 60s snapshots; Alpaca client_order_id
idempotency + no blind retry; per-symbol lock on fills. Test: `tests/test_critical_audit_fixes.py`.

**Breadth engine (the new strategy core):**
- `app/quant/multi_signal.py` — cheap cross-sectional scorer, 7 price-only signals
  (mom_12_1, mom_6_1, reversal, low_vol, trend, beta/BAB, ltr/long-term-reversal).
  `select_for_llm()` = the cost gate (top-K only). `build_llm_brief()` = compact.
- `app/agents/front_office/strategy/sleeves/breadth_alpha.py` — `BreadthAlphaSleeve`,
  wraps the scorer. Wired LIVE in StrategyAgent at 40% (dropped broken gap_fade;
  research 30 / trend 20 / momentum 10).

**Dynamic universe + batched data:**
- `app/data_layer/universe.py` — dynamic S&P 500 (Wikipedia, anchors + fallback ~100).
- `app/data_layer/batch_bars.py` — one batched cached fetch (not N sequential).
- `app/data_layer/pit_universe.py` — free point-in-time membership (fja05680/sp500),
  cached to `~/.horizon-capital/sp500_pit_membership.csv`.
- StrategyAgent: lazy universe + batched fetch. `universe_source` config (default
  "config" — respects .env US_SYMBOLS; set "sp500" for full ~500 breadth).

**LLM debate cost-gate:** `app/agents/middle_office/debate_agent.py` — caps debates
to `DEBATE_MAX_PER_DAY` (default 15) rolling 24h; strongest signals first (StrategyAgent
emits biggest-delta first); over-budget/weak signals pass through APPROVED (trade on
quant, no LLM). Tunable: `DEBATE_MIN_STRENGTH`.

**Test isolation fix:** `tests/conftest.py` now forces PAPER/HUMAN so the suite is
independent of the owner's live `.env`. Full suite: **400 passed**.

**Validation scripts** (in `backend/scripts/`): `validate_sleeves_oos.py`,
`validate_breadth.py`, `validate_voltarget.py`, `strategy_scorecard.py`,
`validate_pit.py`. Run from `backend/` as `python -m scripts.<name>`.

## 5. Owner's LIVE .env state (backend/.env — has REAL keys, keep gitignored)
- `SYSTEM_MODE=FULLY_AUTONOMOUS` (debate gates trades), `CIO_MODE=AI`
- OpenAI + Google keys SET; AI routing = openai all departments
- Alpaca paper keys SET (realtime IEX + paper fills); `INITIAL_CAPITAL_USD=1,000,000`
- `US_SYMBOLS` = 27 names; `UNIVERSE_SOURCE` not set → defaults to "config" (27 names)
- So a live run DOES exercise the AI agents (GPT debate). Cost-gate bounds token spend.

## 6. How to run the live paper test
```
cd horizon-capital/backend
python -m app            # runs with the .env above (FULLY_AUTONOMOUS + AI + Alpaca paper)
```
Knobs in `.env`:
- `UNIVERSE_SOURCE=sp500` → trade full ~500-name breadth (else 27 from US_SYMBOLS)
- `DEBATE_MAX_PER_DAY=15` → lower to cut OpenAI spend
- `DEBATE_MIN_STRENGTH=0.0` → raise to skip debating weak signals
US market opens 9:30 ET ≈ 7:00pm IST. System runs unattended.

## 7. When live results come back — what to look at
- Did trades fire? Check `signals`, `orders`, `fills` tables (SQLite at
  `~/.horizon-capital/horizon.db`) + the trade journal.
- **The key question (Model A signal):** did AI-approved trades differ from / beat
  what the raw engine would've done? (Compare debate APPROVE/REJECT vs outcomes.)
- Forward P&L vs SPY over the SAME period. (Weeks = noise; need months.)
- Paper-vs-model fill slippage (Alpaca real fills vs the sim assumptions).
- Don't over-read a few days. A weekly-rebalance system needs months for signal.

## 8. The binding blockers (in priority)
1. **Data** — full survivorship-free PRICE data (paid Sharadar/Norgate ~$50/mo)
   closes the 15% delisted gap. Cheapest fix on the board; unblocks all backtesting.
2. **No proven edge** — engine underperforms; needs genuinely new/decorrelated
   signals + honest re-test, OR accept the C pivot.
3. **Regulation** — self-directed tool (user runs own broker) is the legal mass-market
   path; still needs a securities lawyer (India SEBI algo rules tightening). NOT a
   managed-money fund (PMS ₹50L / AIF ₹1Cr minimums exclude the masses).
4. **Can't backtest AI decisions** — look-ahead trap; AI-alpha only forward-testable.

## 9. Memory
Durable facts saved to auto-memory: `project_horizon_capital.md` (in the user's
`memory/` dir). Honest verdicts recorded there too.

## 10. Tone the owner wants
Brutally honest, no yes-man. They're investing a lot and explicitly asked to be told
the truth, including when the answer is "this doesn't work yet." Keep it that way.
