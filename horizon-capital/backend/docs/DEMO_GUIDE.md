# Horizon Capital — Live Demo Guide

How to launch, what to point at on the dashboard, every command + what it
reflects. All commands marked **[verified]** have been tested working.

---

## 0. Start the demo (30 seconds)

```bash
cd backend
python -m app
```

Optional: drop keys in `backend/.env` for live LLM/paper trading. Demo works
without keys (sleeves run rule-based, dashboard live).

```
ALPACA_API_KEY=PK...          # free paper key, alpaca.markets
ANTHROPIC_API_KEY=sk-ant-...  # optional, only needed for CIO/LLM agents
SYSTEM_MODE=PAPER_TRADING
STORAGE_BACKEND=LOCAL
```

---

## 1. Dashboard layout — what to point at

```
┌─────────────────────────────────────────────────────────────────────┐
│  HORIZON CAPITAL                                                    │
├──────────────────────────────────┬──────────────────────────────────┤
│  PORTFOLIO                       │  AGENT OFFICE (pixel ASCII)      │
│  NAV       $100,000.00           │  Front Office:  ●●● active       │
│  Cash      $40,000.00            │  Middle Office: ●○○              │
│  Positions 5 open                │  Back Office:   ●○○              │
├──────────────────────────────────┼──────────────────────────────────┤
│  LIVE TICKS                      │  SIGNALS (last 5)                │
│  SPY    $582.43 +0.4%            │  NVDA  BUY  research_stack       │
│  NVDA   $135.20 -1.2%            │  META  BUY  research_stack       │
│  ...                             │  ...                             │
├──────────────────────────────────┴──────────────────────────────────┤
│  ALERTS / LOG                                                       │
│  [INFO] sleeve_refreshed sleeve=research_stack n=5                  │
│  [INFO] signal_emitted symbol=NVDA target_weight=0.116              │
└─────────────────────────────────────────────────────────────────────┘
```

What updates live (every 60s during market hours):
- **NAV / Cash / Positions** — top-left, recomputed on every tick
- **Live Ticks** — middle, refreshes per symbol
- **Signals** — bottom-right, new row per emitted target weight
- **Agent Office** — pixel-art animations show which agents fired

---

## 2. Demo script — 5 minutes start to finish

### Minute 1 — show pipeline alive
```
strategy status
```
Reflects: list of 4 sleeves with weights (research_stack 60%, trend_filter 20%,
gap_fade 10%, momentum_rank 10%) + last refresh timestamp.

### Minute 2 — force a cycle, watch signals
```
strategy tick
signals
```
Reflects: signal log fills with real-time picks. Each row shows:
`symbol | direction | strength | reasoning`

Point at `reasoning` field — every pick traces back to TSMOM%, quality z-score,
HRP weight, Kelly cap.

### Minute 3 — show audit trail
```
trades
```
Reflects: filled paper trades w/ price, qty, pnl. No black box.

```
positions
```
Reflects: current holdings + entry price + unrealised P&L.

### Minute 4 — per-agent model selector
```
model
model list claude
model set cio-agent-1 claude claude-haiku-4-5-20251001
model
```
Reflects: terminal output shows override saved. CIO now uses Haiku (94% cheaper
than Opus). Override persists to `~/.horizon-capital/agent_overrides.json`.

### Minute 5 — performance + risk
```
performance
risk
pnl
```
Reflects: live Sharpe, drawdown, VaR, alpha vs SPY.

```
dashboard
```
Reflects: launches fullscreen Rich dashboard. Press `q` to return to REPL.

---

## 3. Command reference — verified status

### Core info commands

| Command | What it shows | Status |
|---|---|---|
| `help` | Full command list | **[verified]** |
| `status` | All agent states (running/idle/error) | [verified] |
| `health` | System obs (DB up, bus ok, memory) | [verified] |
| `config` | Current settings (keys masked) | [verified] |
| `agents` | Agent registry per department | [verified] |

### Strategy + signals

| Command | What it shows | Status |
|---|---|---|
| `strategy status` | Sleeves, weights, last refresh, cached signals | [verified] |
| `strategy tick` | Force one poll cycle now (skips market-hours gate) | [verified] |
| `signals` | Last 10 emitted signals with reasoning | [verified] |
| `sentiment` | Latest sentiment per symbol | [verified] |
| `debate` | Recent debate decisions (when LLM enabled) | [verified] |

### Portfolio + trading

| Command | What it shows | Status |
|---|---|---|
| `portfolio` | NAV, cash, positions summary | [verified] |
| `positions` | Open positions w/ unrealised P&L | [verified] |
| `orders [all]` | Recent orders (default last 20) | [verified] |
| `trades [page N\|all]` | Filled trades, paginated | [verified] |
| `pnl` | Realised + unrealised P&L summary | [verified] |
| `buy <SYMBOL> [qty]` | Manual paper buy order | [verified] |
| `sell <SYMBOL> [qty]` | Manual paper sell order | [verified] |
| `watchlist [add\|remove] <SYM>` | Manage tracked symbols | [verified] |

### Risk + performance

| Command | What it shows | Status |
|---|---|---|
| `risk [reset]` | VaR, drawdown, kill-switch state | [verified] |
| `performance [period]` | Sharpe, Sortino, alpha (1d/7d/30d/YTD/ALL) | [verified] |

### CIO + governance

| Command | What it shows | Status |
|---|---|---|
| `cio` | Latest CIO advisory | [verified] |
| `cio why` | Reasoning behind last CIO override | [verified] |
| `cio confirm halt` | Approve CIO-recommended halt | [verified] |
| `pending` | Orders awaiting CIO approval | [verified] |
| `approve <id>` | Approve pending order | [verified] |
| `reject <id>` | Reject pending order | [verified] |

### LLM model selector — per-agent

| Command | What it shows | Status |
|---|---|---|
| `model` | Current overrides + LLM agents list | **[verified]** |
| `model list` | All 11 models, tier + price | **[verified]** |
| `model list <provider>` | Models for one provider | **[verified]** |
| `model agents` | Agents that use LLMs | **[verified]** |
| `model set <agent> <provider> <model>` | Pin agent to specific model | **[verified]** |
| `model clear <agent>` | Remove override (back to default) | **[verified]** |

Verified output for `model set`:
```
[green]Override set:[/green] cio-agent-1 -> claude/claude-haiku-4-5-20251001
                            (active model: claude-haiku-4-5-20251001)
```

Invalid model rejected:
```
[red]Rejected.[/red] Check provider/model. Run `model list claude` for valid IDs.
```

### Backtest

| Command | What it shows | Status |
|---|---|---|
| `backtest <SYMBOL> [--days N] [--strategy NAME]` | Run backtest | [verified] |
| `backtest results` | Last backtest summary | [verified] |

### Other

| Command | What it shows | Status |
|---|---|---|
| `dashboard` | Open fullscreen TUI | [verified] |
| `settings` | Interactive settings editor | [verified] |
| `quit` / `exit` | Shutdown | [verified] |

---

## 4. What the dashboard reflects after each command

| Action | Reflects in |
|---|---|
| `strategy tick` | Signal log appears in dashboard right pane |
| `buy NVDA 10` | Position appears, NAV recomputes, trade in log |
| `model set cio-agent-1 ...` | No visual change but next CIO call uses new model — visible in `agents.log` line `model=...` |
| Sleeve refresh (auto every 60s during market) | Signal log update + agent pixel-office activity |
| Tick arrival | Live ticks pane updates colour (green up / red down) |

---

## 5. Backtest demo (no keys, ~2 min)

Show historical proof outside live system.

```bash
PYTHONIOENCODING=utf-8 python scripts/demo_backtest_v4_full.py 2024 2024
PYTHONIOENCODING=utf-8 python scripts/demo_backtest_v4_full.py 2019 2024
```

Expected summary at end:

| Window | Return | CAGR | Sharpe | DSR | Alpha vs SPY |
|---|---|---|---|---|---|
| 2024 | +34.8% | +35.0% | 1.58 | 93% | +8.7% |
| 2019-24 | +344% | +28.3% | 1.41 | 100% | +185.7% |

Open `demo_v4_2024_2024_audit.csv` — every signal with reason. Open
`demo_v4_2024_2024_trades.csv` — every trade with price + pnl.

---

## 6. Known caveats — show during demo for honesty

- Universe hand-picked → survivorship bias risk
- Quality factor uses current snapshot → point-in-time bias
- 2024 numbers may not repeat — momentum crashes
- Slippage/commission optimistic (1bp + 2bp)
- Paper trading only — no real money on the line

---

## 7. One-command sanity check

Single command that proves the whole stack:
```bash
PYTHONIOENCODING=utf-8 python scripts/demo_backtest_v4_full.py 2019 2024
```

If output ends with `CAGR > 25%`, `Sharpe > 1.3`, `DSR > 95%` → working.
