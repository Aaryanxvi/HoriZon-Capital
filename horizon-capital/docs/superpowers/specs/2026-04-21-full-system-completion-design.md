# Horizon Capital — Full System Completion Design

**Date:** 2026-04-21
**Status:** Approved
**Scope:** Settings panel, real-time data, CIO agent intelligence, debate engine hardening

---

## 0. Backward Compatibility Contract

**Nothing in this spec is allowed to break existing functionality.** Every change is additive or a drop-in replacement. The following rules apply to every step of the implementation:

- **Existing tests must continue to pass.** Run the full test suite after every step. If a step causes a test failure it must be fixed before moving on.
- **Existing REPL commands are unchanged.** New commands are added; no existing command is removed or has its behaviour altered.
- **Existing dashboard panels are unchanged.** The settings overlay is additive. No existing panel is removed or resized.
- **All existing config fields are preserved.** New fields are added with sensible defaults. No field is renamed or removed.
- **The paper trading pipeline is not touched.** `paper_broker.py`, `execution_agent.py`, `portfolio_agent.py`, and `order_manager.py` receive no logic changes — only the KV store price source improves beneath them.
- **Graceful degradation on every new dependency.** No Alpaca key → Yahoo covers it. No LLM key → debate auto-approves as before. CIO silent → system trades normally. Settings panel unavailable → `.env` editing still works.
- **LOCAL mode (SQLite + MemoryBus) remains the default** and must work without any external infrastructure.
- **New DB tables use `CREATE TABLE IF NOT EXISTS`** and `_migrate_table()` pattern so existing databases are upgraded without data loss.

---

## 1. Overview

This spec covers four interconnected improvements built in dependency order (Approach B):

1. **Settings Panel + API Key Management** — live TUI overlay + extended wizard
2. **Real-Time Data** — Alpaca WebSocket (US equities) + Yahoo 1-minute bars (everything else)
3. **CIO Agent Intelligence** — strategic oversight, crisis response, last-resort override
4. **Debate Engine Hardening** — single-provider support, debate role pinning via settings

The goal is a fully functional paper trading system where real prices flow through a properly governed AI debate pipeline, the user has runtime control over all configuration, and an intelligent CIO provides strategic oversight.

---

## 2. Settings Panel + API Key Management

### 2.1 TUI Overlay

A full-screen settings overlay, triggered by pressing `S` from anywhere in the TUI. Three tabs, navigable by left/right arrow keys:

**Tab 1 — API Keys**
- Rows for each key: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `ALPACA_API_KEY`, `ALPACA_API_SECRET`, `NEWSAPI_API_KEY`, `POLYGON_API_KEY`
- Each row shows: label, masked value (`***4a3f`), status indicator (green = valid, red = invalid, grey = not set)
- Select a row and press Enter to edit inline
- On save: validate immediately with a test call to the provider; if valid, write to `.env` and publish `SETTINGS_UPDATED`; if invalid, show error inline, do not update `.env`

**Tab 2 — AI Allocation (Department Level)**
- 4 rows: Front Office, Middle Office, Back Office, Executive
- Each row has a selector: `auto / claude / openai / gemini / none`
- `auto` = all registered providers, round-robin in debates
- Specific provider = only that provider for all agents in the department; if unavailable, falls back to `auto`
- `none` = agents in this department run rule-based only (no LLM calls)
- Changes take effect on next agent message cycle (no restart)

**Tab 3 — Debate Roles**
- 4 rows: Strategy, Risk, Sentiment, Portfolio
- Each row has a selector: `auto / claude / openai / gemini`
- `auto` = existing round-robin assignment
- Pinned = that provider always argues that role
- Single-provider handling: if only one provider is configured, all unresolved roles fall back to that provider regardless of pinning
- Changes take effect on next debate session start

### 2.2 Extended Setup Wizard

`python -m app --setup` detects an existing `.env` and enters "update" mode:
- Shows current values pre-filled (keys masked)
- User steps through screens, skipping unchanged fields by pressing Enter
- Same screens as first-time setup: LLM keys → broker credentials → system mode → risk parameters → AI allocation → debate roles
- Writes only changed fields back to `.env`

### 2.3 Hot Reload Contract

1. Settings panel writes updated values to `.env`
2. `settings` singleton is mutated in-place (Pydantic model fields updated)
3. `SETTINGS_UPDATED` message published on the bus with `{"changed_fields": [...]}`
4. `ProviderRegistry` subscribes to `SETTINGS_UPDATED`: re-registers providers based on new keys, re-reads department routing
5. Agents call `get_providers_for_department()` dynamically on each LLM call — no restart needed
6. Debate role pinning is read fresh at the start of each debate session

---

## 3. Real-Time Data

### 3.1 Alpaca WebSocket Feed (US Equities — Free Tier)

**Implementation:** Full replacement of the existing `AlpacaFeed` stub.

- Connects to Alpaca's free-tier WebSocket (`wss://stream.data.alpaca.markets/v2/iex`)
- On connect: subscribes to trades for all US symbols in the watchlist
- Each incoming trade: writes `{"price": float, "volume": int, "timestamp": str}` to KV store at `horizon:price:{symbol}`, publishes `TICK` message on bus
- No API key configured: feed skips silently, Yahoo polling covers US symbols

**Lifecycle (managed by `DataIngestionWorker`):**
- Connect on worker start
- Reconnect with exponential backoff: 1s, 2s, 4s, 8s, max 60s
- Circuit breaker: 5 consecutive failures → open for 10 minutes, log clearly
- On circuit open: fall back to Yahoo 1-minute polling for US symbols
- Graceful shutdown: close WebSocket cleanly on worker stop

### 3.2 Yahoo Finance 1-Minute Bars (All Markets)

**Changes to existing `YahooFeed` and `DataIngestionWorker`:**

- Change polling interval from 60s to 30s
- Fetch `interval="1m"`, `period="1d"` (last trading day, gets all intraday bars)
- Take the most recent completed bar's close as the live price
- Write to KV store at `horizon:price:{symbol}` (same key Alpaca uses)
- Market hours awareness: skip polling if exchange is closed (use `exchange_calendars` or a simple hardcoded schedule per exchange suffix: `.NS` = NSE, `.L` = LSE, etc.)
- If Alpaca has already written a more recent price for a symbol, Yahoo does not overwrite it (compare timestamps before writing)

### 3.3 Price Priority

Alpaca tick > Yahoo 1-min bar. The KV store write includes a timestamp; whichever source wrote most recently wins. Paper broker reads `horizon:price:{symbol}` unchanged — no modifications needed to `paper_broker.py`.

### 3.4 Impact on Paper Trading

No changes to the paper broker or execution pipeline. Once real prices flow into the KV store, fills automatically reflect current market prices. The Almgren-Chriss impact model remains unchanged.

---

## 4. CIO Agent Intelligence

### 4.1 Mode A — Strategic Oversight (Continuous)

**Trigger:** Timer, every 15 minutes while market is open.

**Input digest sent to LLM:**
- Current NAV and 24h change
- Top 5 positions by weight
- Last 5 debate outcomes (symbol, decision, confidence score)
- Current regime state per scope (India, US)
- Most recent macro factor reading (term spread)
- Any active risk alerts

**LLM prompt:** Structured prompt asking for a concise strategic view. Response schema:
```json
{
  "outlook": "bullish|neutral|bearish",
  "summary": "2-3 sentence plain English view",
  "recommended_adjustments": [
    {"symbol": "AAPL", "action": "reduce|increase|close|hold", "reason": "..."}
  ],
  "risk_flags": ["string", ...]
}
```

**Output:** `CIO_ADVISORY` message published on bus. Dashboard shows a "CIO View" section with the latest advisory. Advisories are advisory only — no automatic order generation. Logged to `cio_advisories` table (new SQLite table).

**Provider selection:** Uses `ai_executive` setting. If `auto` and multiple providers available: Claude > OpenAI > Gemini preference order. If `none`: Mode A disabled.

### 4.2 Mode B — Crisis Response (Event-Driven)

**Triggers:**
- `RISK_ALERT` message with severity `HIGH` or `CRITICAL`
- Portfolio drawdown exceeds configured threshold (default: 10%)
- Kill switch activates

**Input:** Same digest as Mode A, plus the specific trigger event and its context.

**LLM prompt:** Asks for a crisis assessment. Response schema:
```json
{
  "stance": "HOLD|REDUCE|HALT",
  "confidence": 0.0,
  "reasoning": "...",
  "specific_actions": [
    {"symbol": "...", "action": "reduce_by_pct|close", "urgency": "immediate|next_bar"}
  ]
}
```

**Execution by system mode:**
- `HUMAN_APPROVAL`: recommendation shown prominently in TUI, user decides
- `FULLY_AUTONOMOUS`: `REDUCE` actions execute automatically; `HALT` requires one explicit confirmation via REPL (`cio confirm halt`)
- `PAPER_TRADING`: recommendation shown for visibility, no automatic execution

**Circuit breaker:** 3 LLM failures → CIO goes silent for 5 minutes, logs clearly. System continues without CIO input.

### 4.3 Mode C — Override (Last Resort)

**Activation conditions (both must be true simultaneously):**
1. Kill switch has tripped
2. CIO crisis assessment returns `HALT` with confidence ≥ configured threshold (default: 0.85)

**Available override actions:**
- Cancel all pending orders
- Force-close a specific position (synthetic SELL signal at market)
- Lock a symbol from trading for N hours (written to KV store, checked by StrategyAgent before emitting signals)

**Audit trail:** Every override writes a full record to `cio_overrides` table: timestamp, LLM provider used, full prompt, full response, portfolio state snapshot, actions taken.

**User query:** `cio why` REPL command retrieves the most recent override record and displays the full reasoning.

### 4.4 CIO Chat Integration

The existing `cio_chat.py` interface is wired to the CIO agent. Natural language queries from the user are sent to the CIO's LLM provider with full portfolio context. Responses displayed in the chat panel. The CIO can answer questions about its most recent advisory, current positions, or the last override.

---

## 5. Debate Engine Hardening

### 5.1 Single-Provider Support

When only one AI provider is configured:
- All 4 roles assigned to the same provider
- Both debate rounds still execute (round 1: assigned perspectives, round 2: rotated perspectives)
- The single model argues the bull case in round 1 and the bear case in round 2 for the relevant roles
- This is intentional — forced perspective rotation from a single model produces better signal than a unanimous vote
- Minimum viable debate: 1 provider. If 0 providers: auto-approve in PAPER_TRADING, hold signal (do not trade) in FULLY_AUTONOMOUS

### 5.2 Debate Role Pinning

New config fields added to `Settings`:
```python
debate_role_strategy: str = "auto"    # "auto" | "claude" | "openai" | "gemini"
debate_role_risk: str = "auto"
debate_role_sentiment: str = "auto"
debate_role_portfolio: str = "auto"
```

`MultiModelDebateEngine` reads these at the start of each session:
- `auto`: existing round-robin logic
- Specific provider: assign that provider to the role; if that provider is unavailable, fall back to any available provider (log the fallback)
- Single-provider scenario: all unresolved `auto` roles collapse to the one available provider

### 5.3 No Changes to Debate Logic

Consensus scoring, perspective rotation matrix, approval threshold (0.55 consensus, 0.60 for-ratio), and argument persistence are unchanged.

---

## 6. New Database Tables

Three new SQLite tables added to `local_storage.py`:

```sql
CREATE TABLE cio_advisories (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    outlook TEXT NOT NULL,
    summary TEXT NOT NULL,
    recommended_adjustments TEXT NOT NULL,  -- JSON
    risk_flags TEXT NOT NULL,               -- JSON
    provider TEXT NOT NULL,
    trigger TEXT NOT NULL                   -- "timer" | "manual"
);

CREATE TABLE cio_overrides (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    trigger TEXT NOT NULL,
    confidence REAL NOT NULL,
    actions TEXT NOT NULL,                  -- JSON
    full_prompt TEXT NOT NULL,
    full_response TEXT NOT NULL,
    portfolio_snapshot TEXT NOT NULL,       -- JSON
    provider TEXT NOT NULL
);
```

The existing `debate_sessions` and `debate_arguments` tables are unchanged.

---

## 7. New Message Types

Added to `MessageType` enum in `messaging.py`:

```python
SETTINGS_UPDATED = "settings_updated"   # triggers ProviderRegistry hot-reload
CIO_ADVISORY = "cio_advisory"           # CIO's 15-min strategic view
CIO_OVERRIDE = "cio_override"           # last-resort override directive
```

---

## 8. New REPL Commands

| Command | Description |
|---------|-------------|
| `cio` | Show latest CIO advisory |
| `cio why` | Show reasoning behind most recent override |
| `cio confirm halt` | Confirm a CIO-recommended HALT in FULLY_AUTONOMOUS mode |
| `settings` | Open settings overlay (same as pressing `S`) |

---

## 9. Error Handling Summary

| Failure | Handling |
|---------|---------|
| Alpaca WebSocket disconnect | Exponential backoff reconnect, fall back to Yahoo polling during outage |
| Alpaca circuit open (5 failures) | Open for 10 min, Yahoo covers US symbols, log clearly |
| Invalid API key in settings panel | Validate on save, show inline error, do not write to `.env` |
| CIO LLM failure | Circuit breaker (3 failures → 5 min silence), system continues |
| Debate LLM failure | Existing fallback unchanged (auto-approve PAPER_TRADING, hold FULLY_AUTONOMOUS) |
| Single debate provider | All roles assigned to that provider, perspective rotation still runs |
| Zero debate providers | Auto-approve PAPER_TRADING, hold FULLY_AUTONOMOUS |
| Pinned provider unavailable | Fall back to any available provider, log fallback |

---

## 10. Testing Plan

| Area | Tests |
|------|-------|
| Alpaca feed | Unit tests with mock WebSocket server; reconnect logic; circuit breaker |
| Yahoo 1-min polling | Market hours awareness; timestamp priority over Alpaca |
| Settings hot-reload | `SETTINGS_UPDATED` triggers ProviderRegistry re-registration |
| Settings panel validation | Invalid key shows error, `.env` unchanged |
| CIO Mode A | Mock LLM response, advisory published and stored |
| CIO Mode B | Crisis trigger → correct stance execution per system mode |
| CIO Mode C | Override fires only when both conditions met; audit trail written |
| Debate single-provider | All 4 roles use same provider; both rounds execute |
| Debate role pinning | Pinned roles ignore round-robin; unavailable provider falls back |
| End-to-end pipeline | Alpaca tick → signal → debate → CIO advisory → fill (all mocked externals) |

---

## 11. Build Order

1. New `MessageType` values + `Settings` fields + DB tables (foundation for everything)
2. Settings panel TUI overlay + extended wizard
3. Hot-reload contract (`SETTINGS_UPDATED` → `ProviderRegistry`)
4. Alpaca WebSocket feed implementation
5. Yahoo 1-minute bar polling upgrade
6. Debate engine: single-provider support + role pinning
7. CIO agent: Mode A (strategic oversight)
8. CIO agent: Mode B (crisis response)
9. CIO agent: Mode C (override) + `cio_overrides` table
10. CIO chat wiring
11. New REPL commands
12. Tests
