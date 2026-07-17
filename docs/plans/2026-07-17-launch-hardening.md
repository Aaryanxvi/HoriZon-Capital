# Launch Hardening Plan — 2026-07-17

Branch: `feat/launch-hardening` (outer repo `C:\Users\Admin\Documents\Code\Horizon capital`).
Goal today: burn down launch-blocking backlog, then run live Alpaca **paper** trading with the
validated sleeve config (breadth .40 / research .30 / trend_filter .20 / momrank .10 — do NOT
change the mix; any strategy change requires a fresh pre-registered gate pass).

App code root: `horizon-capital/backend/app/`. Tests: `horizon-capital/backend/tests/`
(`python -m pytest tests/ -q` from `horizon-capital/backend`, asyncio_mode=auto). Ruff:
`python -m ruff check app/` — line-length 100, py311 target, `X | None` not Optional.
Storage: LOCAL mode = SQLite raw SQL via `core/local_storage.py`, sessions from
`runtime.get_session_factory()`. Commit style: conventional commits, NO Co-Authored-By trailer.

---

## Task A — Hygiene batch (agent_messages retention, forex key unification, dead optimizer field)

### A1. agent_messages retention
Facts: `BaseAgent.emit()` (`app/agents/base_agent.py` ~line 107-122) INSERTs into
`agent_messages` on every bus publish. Table created in `core/local_storage.py:117`. No DELETE
anywhere → unbounded growth (confirmed by grep: only writers, no pruning).

Spec:
- Add setting `agent_messages_retention_days: int = 7` to `app/config.py` Settings (env
  `AGENT_MESSAGES_RETENTION_DAYS`), following the existing pydantic-settings field style there.
- Add pruning in the back-office ITAgent's existing periodic loop (`app/agents/back_office/` —
  find ITAgent; it runs a recurring health check). Once per hour (guard with a
  last-pruned timestamp attr, no new task/thread), run portable SQL:
  `DELETE FROM agent_messages WHERE created_at < :cutoff` with
  `cutoff = now(UTC) - retention_days`. Log `agent_messages_pruned` with rowcount.
  Use `runtime.get_session_factory()` like other agents do.
- Also prune once at startup: call the same helper during ITAgent start (its `run()` first
  iteration covers this if the hourly guard starts expired — simplest: initialize last-pruned
  to epoch so first loop prunes immediately).
- Test: one small test — insert 2 rows into agent_messages (one old, one fresh) via a session,
  call the prune helper, assert old gone / fresh kept. Put in existing test tree
  (`backend/tests/`), follow existing test style (async fixtures already exist in that tree).

### A2. Forex KV key unification
Facts: writer/persist whitelist `core/kv_store.py:78` uses `"horizon:forex:usd_inr"`, but the
single reader `app/agents/front_office/portfolio/currency.py:9` defines
`FOREX_KEY = "horizon:forex:usdinr"`. Mismatch → persisted rate never read; reader falls back
83.0 default.

Spec:
- Canonical key = `horizon:forex:usdinr` (the reader's). Grep app/ for `usd_inr` KV usages
  (KV key strings only — NOT the `usd_inr_rate` DB column or `get_usd_inr_rate` method names,
  those stay). Update `kv_store.py:78` whitelist entry and ANY writer that sets the old key to
  import and use `currency.FOREX_KEY` (import from
  `app.agents.front_office.portfolio.currency`) — single source of truth. If importing FOREX_KEY
  into kv_store would create a circular import, duplicate the literal there with a comment
  `# must match currency.FOREX_KEY`.
- Test: none needed beyond existing suite if a writer exists — but add one assert-level check in
  an existing kv/currency test file if present: whitelist contains FOREX_KEY.

### A3. Dead optimizer field
Facts: `app/agents/front_office/portfolio/portfolio_agent.py:11` imports PortfolioOptimizer,
line 56 `self.optimizer = PortfolioOptimizer()`. Verify whether `self.optimizer` is referenced
anywhere else in the file/codebase.
- If unreferenced: delete the import + field (2-line diff). Leave `optimizer.py` file itself
  alone (other scripts may import it; deleting the file is out of scope today).
- If referenced: leave everything, report back where.
Do NOT touch `debate_engine.py` — it is lazily imported by
`app/agents/debate/multi_model_debate.py:27` (alive).

### Task A acceptance
- Full suite passes (`python -m pytest tests/ -q` from backend/), ruff clean on touched files.
- One commit: `fix(core): agent_messages retention + forex KV key unification + drop dead optimizer field`

---

## Task B — Commission-correct realized P&L

Facts (verified today):
- Fill txn `app/agents/front_office/trading/execution_agent.py:326-367` is atomic and ALREADY
  debits commission from cash (line 335 `delta = -(cost + commission) if BUY else (cost - commission)`)
  and stores commission on the fill row via `order_manager.record_fill(commission=...)`.
- Gap 1: `order_manager.update_position()` (`app/agents/front_office/trading/order_manager.py:261-405`)
  computes `realized_delta` GROSS — commissions never reach `positions.realized_pnl`
  (lines 346, 351, 364, 374; new-position INSERT hardcodes realized 0.0 at line 314).
- Gap 2: `app/services/performance.py:266` computes realized P&L in SQL as
  `SUM((f.fill_price - p.avg_entry_price) * f.filled_qty)` — no commission term.
- Already correct (do not touch): `workers/performance_worker.py:222,247` subtracts
  `t.get("commission", 0)`.

Convention (chosen — keep it simple and cash-consistent): commission reduces realized_pnl at
fill time, on EVERY fill (opening and closing legs alike). So lifetime
`realized_pnl == gross trading P&L − all commissions paid`, matching cash exactly. Do NOT
capitalize buy commissions into avg_entry_price.

Spec:
1. `update_position(...)`: add keyword param `commission: float = 0.0`.
   - Existing-position branches: `new_realized = old_realized + realized_delta - commission`
     (all four branches — opening legs have realized_delta 0.0, so they become −commission).
   - New-position INSERT: realized_pnl value `-commission` instead of `0.0` (bind param).
2. Call site `execution_agent.py:357-365`: pass `commission=commission`.
3. `services/performance.py:266`: subtract fill commissions in the SQL
   (`SUM(... ) - SUM(COALESCE(f.commission, 0))` or equivalent within the same aggregate).
   Check the surrounding query for how fills table is aliased; keep the query shape.
4. Tests (extend existing order_manager/execution test file if one exists, else small new
   `tests/test_commission_pnl.py`):
   - BUY 10 @ 100 with commission 1.0 → position realized_pnl == −1.0.
   - Then SELL 10 @ 110 with commission 1.1 → realized_pnl == −1.0 + (10*10) − 1.1 == 97.9.
   - Short path sanity: SELL-open then BUY-cover with commissions → same convention.

### Task B acceptance
- Full suite passes, ruff clean on touched files.
- One commit: `fix(pnl): commission-correct realized P&L (positions + performance SQL)`

---

## Task C — Alpaca paper broker wiring + startup reconciliation

Facts (verified today):
- `AlpacaBroker` exists (`app/agents/front_office/trading/alpaca_broker.py`): `get_account()`,
  `execute(order)`, `get_order_status(broker_order_id)`, `cancel_order()`, `get_positions()`.
  Prior audit added `client_order_id` idempotency + no blind retry — READ execute() fully
  before wiring; do not degrade those properties.
- `ExecutionAgent` (`app/agents/front_office/trading/execution_agent.py`) hardwires
  `self.paper_broker = PaperBroker()` (line 58) and `"broker": "PAPER"` (lines 127, 385).
  Retry loop line 295-307 already refuses blind retry for non-PAPER. Stale-order poll
  `_poll_open_orders()` (line 401+) only handles `broker = 'PAPER'` rows (cancels >60s OPEN).
- `.env`: ALPACA_API_KEY/SECRET set, `ALPACA_BASE_URL=https://paper-api.alpaca.markets`,
  `ALPACA_PAPER_MODE=true`. Settings fields for these should already exist in config.py (verify).

Spec:
1. **Broker selection.** New Settings field `execution_broker: str = "PAPER"` (env
   `EXECUTION_BROKER`, values `PAPER` | `ALPACA`). In `ExecutionAgent.__init__`: keep
   `self.paper_broker`, add `self.alpaca_broker = AlpacaBroker()`, and resolve
   `self.broker_name` / `self.broker` once:
   - `ALPACA` selected **only if** alpaca key+secret non-empty AND `alpaca_paper_mode` is true
     AND `"paper-api"` in base_url. If any check fails: log error
     `alpaca_guard_failed_falling_back_paper` and use PAPER. This is a hard safety guard —
     live-money URL must be unreachable today regardless of env values.
2. **Order tagging.** Everywhere `"broker": "PAPER"` is hardcoded (lines 127, 385, and any
   other), use `self.broker_name`. Order dict passed to broker keeps the same shape.
3. **Execute path.** `_execute_order`: route to `self.broker.execute(order)`. Alpaca fills are
   NOT instant: if `execute()` returns an accepted-but-unfilled result (inspect its return
   shape — it may return filled data only when immediately filled, else status), then:
   - persist `broker_order_id` on the order row (check orders schema — add column via
     local_storage `_migrate_table` if missing, non-destructive),
   - leave status OPEN and let polling complete it. Only run the atomic fill txn
     (lines 326-367) once REAL fill data (qty, price) is known. Do not fabricate fill prices.
4. **Fill polling.** Extend `_poll_open_orders()`: for OPEN orders with broker == ALPACA and a
   broker_order_id, call `get_order_status()`; when filled → run the SAME atomic fill txn path
   as instant fills (factor the txn block lines 326-389 into a helper `_settle_fill(order, fill)`
   so both paths share it — this is the money path, one implementation only). When canceled /
   rejected / expired → update status + emit ORDER_CANCEL like lines 309-324. Do NOT cancel
   Alpaca orders at 60s like paper ones — market orders queue when market closed; only cancel
   after 24h stale.
5. **Commission.** Alpaca US equities commission is 0.0 (their return already says so) — the
   Task B convention handles it transparently. Nothing extra.
6. **Startup reconciliation.** In `ExecutionAgent.run()` startup (before loop), when broker is
   ALPACA:
   - `get_account()` — if None/unreachable: log + emit RISK_ALERT `alpaca_unreachable`, fall
     back to PAPER for the session (flip self.broker/broker_name).
   - Fetch `get_positions()` and compare qty per symbol vs local `positions` table (LONG only).
     Log any mismatch (symbol, local qty, broker qty) and emit one RISK_ALERT summary if any
     mismatches. DO NOT auto-mutate local positions — report only (owner decision later).
   - For local orders stuck OPEN with a broker_order_id: poll status once immediately (reuse
     the step-4 helper).
7. **Tests** (new `tests/test_alpaca_wiring.py`, mock AlpacaBroker with simple stub objects —
   no network in tests; follow existing test style):
   - guard: bad base_url or paper_mode false → falls back PAPER.
   - accepted-then-filled flow: execute returns accepted → poll returns filled → position,
     cash, fill row all updated exactly once (idempotent: second poll of same order is a no-op).
   - reconciliation mismatch → RISK_ALERT emitted, local positions untouched.
8. Do NOT set `EXECUTION_BROKER=ALPACA` in `.env` yourself — launch step does that.

### Task C acceptance
- Full suite passes, ruff clean on touched files.
- One commit: `feat(execution): Alpaca paper broker wiring, async fill settlement, startup reconciliation`

---

## Task D — Launch (orchestrator-run, not an implementer task)
After A-C merge: set `EXECUTION_BROKER=ALPACA` in backend/.env, boot `python -m app --headless`,
verify: Alpaca account reachable, reconciliation clean, first signal cycle → order → fill (or
queued if market closed), kill-switch + risk limits live. Leave running.

## Task E — momrank gate test (after launch, time permitting)
momrank top-3 PIT standalone maxDD −59.5%. Candidate fix: top-N 3→10, weight unchanged.
MUST pass pre-registered gate via existing PIT harness (`scripts/validate_fix_ab.py` pattern)
before touching live mix. If no time or gate fails: leave validated mix as-is.
