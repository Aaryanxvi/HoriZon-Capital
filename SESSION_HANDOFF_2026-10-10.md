# Horizon Capital — Session Handoff (2026-10-10)

Supersedes SESSION_HANDOFF_2026-07-17.md. Session paused by owner at 05:00 IST.

## Owner's #1 priority
Make Horizon Capital **profitable and a GO for real money** (own money; Zerodha India + US). Rank all work by that.

## GitHub
- **New repo: `origin` = https://github.com/Aaryanxvi/Horizon-r** — push all work here and keep it updated (owner's standing instruction).
- Old repo kept as remote `legacy` (github.com/Aaryanxvi/HoriZon-Capital) with push URL disabled — owner said leave it as it is.
- Only reviewed, test-passing code goes to `main`. Each agent's work was verified on a clean temp worktree (HEAD + only that agent's files) before commit.

## Shipped this session (all on Horizon-r `main`)
| Commit | What |
|---|---|
| 84ee8f9 | News → Alpaca/Benzinga (one multi-symbol call per sweep); FinBERT → ProsusAI/finbert, score = P(pos)−P(neg), inference off the event loop |
| 0fc4e73 | Alpaca feed: real data host for paper keys (sandbox = 401/402 → the July WS reconnect loop); WS auth reply actually checked |
| ba3993d | Startup phantom-cash fix (re-seeded INITIAL_CAPITAL whenever cash ≤ 0 while keeping positions) |
| 9ffbe7e | Tests isolated from dev .env + shared KV (15 → 0 failures) |
| 9de2386 | Real-money readiness audit: NO-GO, 5→6 blockers, proof tests |
| 1433561/38fea9a/f421bff | India gate v1: **FAIL** |
| 3be2105 | AUTHORSHIP.json re-signed (in a clean temp worktree) |
| 8e43201 | **Hardening: B1–B6, H1–H8, M1/M2/M4/M8 fixed** (20% trailing stop resting at Alpaca, exits never blocked, broker = source of truth, no silent simulator, restart can't double orders, leverage/notional/price-band guards) |
| a3b82de | Watchlist backend + REPL (catalog ~14k, search/browse, unlimited bulk add/remove, quotes, detail, recommended) |
| 880edcb…b670eec | Profitability research: **live mix loses to SPY after Indian tax** |

## Key verdicts (read before any real-money decision)
- **Profit (docs/plans/2026-10-10-profitability-results.md):** after cost + Indian tax, live mix 7.81% vs SPY 11.12% (2018-24), 6.10% vs 6.31% (2008-17); ~100% short-term gains at ~34%, turnover ~6.7×/yr. Real edge = drawdown (−17/−21% vs −34/−53%). Hindsight found: ResearchStack `_RISK_UNIVERSE` hard-codes 2024 winners (holdout Sharpe 0.60→0.39 mechanical; after-tax 4.22% vs SPY 6.31%); mega-cap anchor leak +0.10/+0.15 Sharpe; live yfinance QMJ is look-ahead. No candidate shipped.
- **India v1 (docs/plans/2026-10-10-india-strategy-results.md):** FAIL G6 (Sharpe 0.46 at 20 bps); turnover 14.7×/yr, 3.16%/yr charges; ResearchStack drags in India.
- **Stop-loss backtest (audit doc "Fixes" section):** 20% trailing stop costs Sharpe (2018-24 0.77→0.64; 2008-17 0.71→0.53) but cuts maxDD (−18→−14.4; −19.1→−10.8). Owner chose it anyway with re-entry rule A.
- **Readiness:** hardening done; independent re-audit was started then paused. Alpaca guard still makes a LIVE URL impossible by design — going live is a deliberate later step.

## Owner decisions (locked)
- 20% trailing stop held at the broker; re-entry only on a fresh sleeve BUY signal (rule A).
- Kill switch / drawdown breach = stop buying, exits keep working (no auto-flatten).
- Whole shares for real-money US equities (so stops can rest at Alpaca as GTC).
- Personal account first; multi-user service needs SEBI registration (told owner plainly).
- Real-money config = validated US mix only; crypto + Polymarket sleeves and their discovery switched OFF in `.env` (backup `~/.horizon-capital/env.backup-2026-10-10`).
- Markets = both (US first; India only if a gate passes); Indian broker = Zerodha Kite Connect.

## Local state
- Local ledger wiped 2026-10-10 00:33 (backup `~/.horizon-capital/horizon.backup-2026-10-10-prereset.db`); `.env INITIAL_CAPITAL_USD=1000000`. Owner was to reset the Alpaca paper account to $1M — unconfirmed. With hardening, the app now syncs positions/cash FROM Alpaca.
- Kite facts: order APIs free, data ₹500/mo; static IP mandatory for order endpoints since 2026-04-01; daily manual login; ≤10 orders/sec own use; two-leg GTT = broker-side stop. Alpaca live for Indian residents = invite-only beta (IBKR fallback).

## Paused agents — how to resume (same Claude Code session: SendMessage to the agent; new session: re-brief from these docs)
| Agent | State | Resume |
|---|---|---|
| ui-designer (Fable) | TradingView-inspired light/dark redesign + dataviz, mid-pass; status file `horizon-capital/docs/plans/2026-10-10-ui-redesign-status.md` (if written); **uncommitted frontend WIP in the working tree** + `backend/app/main.py` (mounts new `app/api/desktop_viz.py`) + `tests/test_desktop_viz.py` + backend CLAUDE.md watchlist notes | finish pass, build, screenshot both themes; then lead verifies + commits frontend together with `WatchlistPage.tsx`, `hooks/useWatchlist.ts`, `SymbolChart.tsx` |
| risk-auditor | re-audit of 8e43201 paused (partial notes in `tests/test_risk_reaudit.py` / audit doc "Re-audit" if saved) | finish → GO/NO-GO for (a) paper forward-test (b) real US money |
| india-v2 (Fable) | survivorship-free NSE bhavcopy gate, NO returns computed; WIP 0034b7b on worktree branch `worktree-agent-a425c7d1dccab7f36`; cache `~/.horizon-capital/india/bhav` 2003-01→2014-07 | resume download (~20 min) → build → validate → freeze pre-reg → run holdout 2005-13 once |
| profit-research, hardening, watchlist-builder, test-fixer | done | — |

## Next steps (in order)
1. Finish the UI redesign → verify → commit + push (frontend + watchlist page + desktop_viz endpoint).
2. Finish the re-audit (GO for paper forward-testing?).
3. **Next research step (owner flagged):** remove hindsight from the LIVE strategy (mechanical PIT `_RISK_UNIVERSE`, strict-PIT view, drop/replace look-ahead QMJ with `scripts/pit_quality.py`), then pre-register a low-turnover, long-holding (>24-month, LTCG) variant measured after Indian tax vs SPY/VOO and Nifty index funds with `scripts/validate_profitability.py`. A pass is not guaranteed.
4. India v2 verdict; Zerodha adapter only if an India gate passes.
5. Paper forward-test 4–8 weeks on Alpaca once re-audit says GO; real money only after a strategy beats the index after tax.

## Honest bottom line given to the owner
As built, the app is not a money-maker after Indian tax vs an index fund; its proven value is drawdown control, research rigor, and as a portfolio/thesis piece. Recommendation: long-term money in index funds (Nifty 50 index fund or VOO >24 months; confirm with a CA), keep the app in paper as a research platform, fund it only if a future pre-registered gate shows an after-tax edge.
