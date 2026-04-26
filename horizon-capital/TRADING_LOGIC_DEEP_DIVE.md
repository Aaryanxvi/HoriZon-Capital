# Horizon Capital — Trading Logic Deep Dive

**Version:** 0.2.0  
**Last Updated:** 2026-04-25  
**Scope:** Complete technical specification of how trades are generated, evaluated, debated, sized, executed, and measured.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Signal Generation — How Trade Ideas Are Born](#2-signal-generation)
3. [Risk Gate — Pre-Trade Validation](#3-risk-gate)
4. [LLM Debate System — Multi-Model Decision Making](#4-llm-debate-system)
5. [Portfolio Agent — Position Sizing & Order Routing](#5-portfolio-agent)
6. [Execution — How Orders Become Trades](#6-execution)
7. [P&L Calculation — How Profit and Loss Are Tracked](#7-pnl-calculation)
8. [CIO Agent — AI Chief Investment Officer](#8-cio-agent)
9. [Risk Monitoring — Continuous Portfolio Surveillance](#9-risk-monitoring)
10. [Performance Metrics — How We Measure Success](#10-performance-metrics)
11. [Feature Computation — The Data Pipeline](#11-feature-computation)
12. [Configuration Reference](#12-configuration-reference)
13. [Complete Signal-to-Trade Flow Diagram](#13-complete-flow-diagram)

---

## 1. System Overview

Horizon Capital is an autonomous AI hedge fund that runs as a desktop terminal agent. It operates through a multi-agent architecture where specialized agents communicate via a pub/sub message bus.

### The Trading Pipeline

```
Data Ingestion (Yahoo/CoinGecko/Forex)
    ↓
Feature Computation (23 technical indicators)
    ↓
Strategy Agent (RSI, MACD, Bollinger, Momentum, Mean Reversion)
    ↓
Risk Agent (position limits, daily loss check)
    ↓
Debate Agent (multi-model LLM debate)
    ↓
Portfolio Agent (position sizing, cash check)
    ↓
Execution Agent (Almgren-Chriss market impact)
    ↓
Position & Cash Update
    ↓
Performance Monitoring (Sharpe, Alpha, Drawdown)
```

### Three Operating Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| **PAPER_TRADING** | Signals auto-approved, no real capital | Development/testing |
| **HUMAN_APPROVAL** | Orders buffered for CIO to approve/reject via REPL | Semi-automated |
| **FULLY_AUTONOMOUS** | Signals require LLM debate approval before execution | Full automation |

### Trading Universe

- **India:** RELIANCE.NSE, TCS.NSE, INFY.NSE, HDFCBANK.NSE, ICICIBANK.NSE
- **US:** AAPL.NASDAQ, MSFT.NASDAQ, GOOGL.NASDAQ, AMZN.NASDAQ, TSLA.NASDAQ
- **Crypto:** BTC-USD, ETH-USD

### Initial Capital

- **USD:** $1,000,000
- **INR:** ₹10,000,000

---

## 2. Signal Generation

### 2.1 How It Works

The Strategy Agent (`strategy_agent.py`) runs every **60 seconds**. For each symbol in the trading universe, it:

1. Fetches 60 days of daily OHLCV data from Yahoo Finance
2. Caches the latest price in KV store (`horizon:price:{symbol}`)
3. Caches the average daily volume (`horizon:volume:{symbol}`)
4. Runs each strategy against the data
5. Emits a `SIGNAL` message on `horizon.signal.{symbol}` for any non-zero signal

Each signal contains:

```python
{
    "signal_id": "uuid4",        # Unique tracking ID
    "symbol": "AAPL.NASDAQ",     # Instrument
    "direction": 1,              # +1 = BUY, -1 = SELL, 0 = HOLD
    "strength": 0.72,            # 0.0 to 1.0 confidence
    "strategy_name": "RSI",      # Which strategy produced it
    "reasoning": "RSI at 38...", # Human-readable explanation
    "target_price": 295.50,      # Optional price target
    "stop_loss": 270.00,         # Optional stop loss
}
```

### 2.2 RSI Strategy (Relative Strength Index)

**Core Idea:** RSI measures the speed and magnitude of price changes over a 14-day window. Extreme readings suggest the price has moved too far in one direction and is likely to reverse.

**Parameters:**
- Window: 14 periods
- Buy threshold: RSI < 45 (oversold)
- Sell threshold: RSI > 65 (overbought)

**Buy Signal Logic:**
```
IF current_rsi < 45:
    direction = +1 (BUY)
    strength = min((45 - current_rsi) / 45, 1.0)
    target_price = close * 1.05  (5% upside target)
    stop_loss = close * 0.97     (3% stop loss)
```

**Example:** RSI at 28 → strength = (45-28)/45 = 0.38. RSI at 10 → strength = (45-10)/45 = 0.78.

**Sell Signal Logic:**
```
IF current_rsi > 65:
    direction = -1 (SELL)
    strength = min((current_rsi - 65) / 35, 1.0)
    target_price = close * 0.95  (5% downside target)
    stop_loss = close * 1.03     (3% stop loss)
```

### 2.3 MACD Strategy (Moving Average Convergence Divergence)

**Core Idea:** MACD tracks the difference between a fast EMA (12) and slow EMA (26), compared to a signal line (9-period EMA of MACD). Crossovers indicate momentum shifts.

**Parameters:**
- Fast EMA: 12
- Slow EMA: 26
- Signal line: 9

**Buy Signal — Crossover:**
```
IF previous_macd < previous_signal AND current_macd > current_signal:
    direction = +1 (BUY)
    strength = min(abs(current_macd - current_signal) / 2, 1.0)
```

**Buy Signal — Trend Following:**
```
IF current_macd > current_signal + 0.5:
    direction = +1 (BUY)
    strength = min(abs(current_macd - current_signal) / 5, 0.5)
```

**Sell Signal — Crossover:**
```
IF previous_macd > previous_signal AND current_macd < current_signal:
    direction = -1 (SELL)
    strength = min(abs(current_macd - current_signal) / 2, 1.0)
```

### 2.4 Bollinger Band Strategy

**Core Idea:** Bollinger Bands create a volatility envelope around price. When price touches the lower band, it may be oversold; when it touches the upper band, it may be overbought.

**Parameters:**
- Window: 20 periods
- Standard deviations: 2

**Position in Band:**
```
band_width = upper_band - lower_band
position = (current_price - lower_band) / band_width
```
This gives a value from 0.0 (at lower band) to 1.0 (at upper band).

**Buy Signal:**
```
IF position_in_band < 0.25:   (price in bottom 25% of band)
    direction = +1 (BUY)
    strength = min((0.25 - position) / 0.25, 1.0)
```

**Sell Signal:**
```
IF position_in_band > 0.85:   (price in top 15% of band)
    direction = -1 (SELL)
    strength = min((position - 0.85) / 0.15, 1.0)
```

### 2.5 Momentum Strategy (Multi-Factor Fusion)

**Core Idea:** Combines 6 independent momentum signals into a single score using weighted fusion. Requires multiple indicators to agree before generating a signal.

**Components and Weights:**

| Component | Weight | What It Measures |
|-----------|--------|------------------|
| RSI | 20% | Momentum oscillator normalized to [-1, 1] |
| MACD | 20% | Trend strength via MACD spread magnitude |
| VPVMA | 20% | Volume-Price-Volatility fusion (MACD × Volume × ATR) |
| EMA Trend | 15% | Price deviation from 20-period EMA |
| Volume | 15% | Current volume vs 20-day average |
| VWAP | 10% | Price deviation from Volume Weighted Average Price |

**Fusion Score:**
```
fusion_score = sum(component_score * weight for each component)
bullish_count = count(components where score > 0)
bearish_count = count(components where score < 0)
```

**Buy Signal:**
```
IF fusion_score > 0.15 AND bullish_count >= 3:
    direction = +1 (BUY)
    confirmation = bullish_count / 6
    magnitude = min(abs(fusion_score), 1.0)
    strength = 0.6 * confirmation + 0.4 * magnitude
```

**Sell Signal:**
```
IF fusion_score < -0.15 AND bearish_count >= 3:
    direction = -1 (SELL)
    confirmation = bearish_count / 6
    magnitude = min(abs(fusion_score), 1.0)
    strength = 0.6 * confirmation + 0.4 * magnitude
```

### 2.6 Mean Reversion Strategy (Ornstein-Uhlenbeck)

**Core Idea:** Prices that deviate significantly from their statistical equilibrium tend to revert. Uses the Ornstein-Uhlenbeck process to model mean reversion mathematically.

**Primary Model — OU Process (requires ≥30 data points):**

The OU model fits: `dX = kappa * (theta - X) * dt + sigma * dW`

Where:
- `kappa` = speed of mean reversion
- `theta` = equilibrium price level
- `sigma` = volatility of the process
- `half_life = ln(2) / kappa` (how fast price reverts)

**S-Score:** Standardized deviation from equilibrium
```
s_score = (current_price - theta) / sigma
```

**Buy Signal:**
```
IF s_score < -1.25:        (price far below equilibrium)
    direction = +1 (BUY)
    strength = min(abs(s_score) / 2.0, 1.0)
    target_price = theta     (revert to equilibrium)
    stop_loss = price * 0.97 (3% stop)
```

**Sell Signal:**
```
IF s_score > 1.25:          (price far above equilibrium)
    direction = -1 (SELL)
    strength = min(s_score / 2.0, 1.0)
```

**Extreme thresholds** at ±2.0 produce stronger signals.

**Fallback — Bollinger + RSI (when <30 data points):**
```
BUY:  price <= lower_band * 1.005 AND RSI < 30
SELL: price >= upper_band * 0.995 AND RSI > 70
strength = min(0.5 + 0.3 * band_depth + 0.2 * rsi_strength, 1.0)
```

### 2.7 Why Multiple Strategies?

Each strategy captures different market conditions:

| Strategy | Best At | Weakness |
|----------|---------|----------|
| RSI | Range-bound markets, quick reversals | Whipsaws in strong trends |
| MACD | Trending markets, momentum shifts | Lags in choppy markets |
| Bollinger | Volatility breakouts, mean reversion | False signals in low vol |
| Momentum | Strong directional moves | Late entry, early exit |
| Mean Reversion | Statistical arbitrage | Regime changes break model |

All 3 basic strategies (RSI, MACD, Bollinger) run on every symbol every 60 seconds. A **per-symbol cooldown of 120 seconds** in the Portfolio Agent prevents the same symbol from generating multiple orders in rapid succession.

---

## 3. Risk Gate

### 3.1 Pre-Trade Validation

Before any signal reaches the Portfolio Agent, the Risk Agent (`risk_agent.py`) validates it. The Risk Agent subscribes to `horizon.signal.*` and applies two checks:

**Check 1 — Position Size Limit (5% of NAV):**
```
existing_position_value = abs(quantity * current_price)
weight_pct = (existing_position_value / NAV) * 100
PASS if weight_pct < 5%
FAIL if weight_pct >= 5%
```

**Check 2 — Daily Loss Limit (5% of NAV):**
```
total_pnl = sum(unrealized_pnl) + sum(realized_pnl)  [from positions table]
loss_pct = abs(total_pnl) / NAV * 100
PASS if total_pnl >= 0 OR loss_pct < 5%
FAIL if loss_pct >= 5%
```

### 3.2 Outcomes

- **APPROVED:** Signal forwarded to `horizon.risk.approved.{symbol}` → reaches Portfolio Agent and Debate Agent
- **REJECTED:** Signal forwarded to `horizon.risk.rejected.{symbol}` with violation list → discarded

### 3.3 What Gets Published on Rejection

```python
{
    "signal_id": "...",
    "symbol": "AAPL.NASDAQ",
    "violations": [
        "Position in AAPL.NASDAQ would exceed 5% limit",
        "Daily loss exceeds 5% limit"
    ],
    "action": "REJECTED",
    "timestamp": "..."
}
```

---

## 4. LLM Debate System

This is the most sophisticated component. When LLM providers are configured, every risk-approved signal goes through a structured multi-model debate before becoming an order.

### 4.1 Overview

The debate system uses multiple AI models arguing from different perspectives to decide whether a trade should proceed. Each model plays a specific role, and they vote FOR or AGAINST the trade.

### 4.2 The Four Debate Roles

**STRATEGY Debater — The Bull**
```
System Prompt:
"You are an aggressive growth-focused trader. Analyze the technical signals 
and market momentum. Focus on potential upside, trend strength, and entry/exit 
timing. Be decisive."
```

**RISK Debater — The Bear**
```
System Prompt:
"You are a conservative risk manager. Identify all potential downside risks 
and tail scenarios. Consider drawdown, volatility, liquidity risk, and 
correlation blow-ups. Err on the side of caution."
```

**SENTIMENT Debater — The Crowd Reader**
```
System Prompt:
"You are a market sentiment analyst. Evaluate news flow, social media mood, 
and narrative momentum. Assess whether the crowd is positioned correctly or 
is a contrary indicator."
```

**PORTFOLIO Debater — The Architect**
```
System Prompt:
"You are a portfolio construction expert. Consider diversification, 
correlation, and position sizing. Evaluate whether this trade improves or 
degrades the overall portfolio risk/return profile."
```

### 4.3 User Prompt (Sent to Each Debater)

Each debater receives context about the proposed trade:

```
Proposed Trade: BUY AAPL.NASDAQ
Signal Data: {
    "symbol": "AAPL.NASDAQ",
    "direction": 1,
    "strength": 0.72,
    "strategy_name": "RSI",
    "reasoning": "RSI at 38, oversold condition",
    "target_price": 295.50,
    "stop_loss": 270.00
}
Market Regime: NORMAL
Current Sentiment: {...}
Risk Metrics: {...}

Respond with ONLY: 
{"argument": "<reasoning>", "vote": "FOR|AGAINST|ABSTAIN", "confidence": <0.0-1.0>}
```

### 4.4 How the Debate Works — Round by Round

**Round 1 — Initial Arguments:**
- Each of the 4 debaters receives the trade context and their role-specific system prompt
- Each returns a structured JSON response: `{argument, vote, confidence}`
- LLM providers are assigned to roles via round-robin (or pinned via config)

**Round 2 — Perspective Rotation:**
- Debaters swap roles: STRATEGY ↔ RISK, SENTIMENT ↔ PORTFOLIO
- Each debater sees the Round 1 arguments from all participants
- They must now argue from the OPPOSITE perspective
- This forces each model to consider the other side, reducing confirmation bias
- They can change their vote based on new perspective

### 4.5 Provider Assignment

LLM providers (Claude, OpenAI, Gemini) are assigned to debate roles:

```python
# Default: round-robin assignment
# Can be pinned in config:
debate_role_strategy: "openai"    # Pin strategy debater to OpenAI
debate_role_risk: "gemini"        # Pin risk debater to Gemini
debate_role_sentiment: "auto"     # Auto-assign
debate_role_portfolio: "auto"     # Auto-assign
```

When set to `"auto"`, providers are assigned in rotation so each model gets different roles across debates.

### 4.6 Consensus Scoring — How the Final Decision Is Made

After both rounds, votes are tallied:

```python
# Count votes (Round 2 votes override Round 1 for same debater)
for_votes = [v for v in all_votes if v.vote == "FOR"]
against_votes = [v for v in all_votes if v.vote == "AGAINST"]

# Simple ratio
for_ratio = len(for_votes) / (len(for_votes) + len(against_votes))

# Confidence-weighted score
total_for_confidence = sum(v.confidence for v in for_votes)
total_confidence = sum(v.confidence for v in all_non_abstain_votes)
consensus_score = total_for_confidence / total_confidence
```

**Decision Thresholds:**
```
APPROVED if: consensus_score > 0.55 AND for_ratio >= 0.6
REJECTED if: otherwise
```

This means:
- At least 60% of voters must vote FOR
- The confidence-weighted score must exceed 55%
- A split vote (2-2) always results in REJECTION
- ABSTAIN votes don't count against approval but don't help either

### 4.7 What Happens Without LLM Providers

| Mode | No LLMs Available | Result |
|------|-------------------|--------|
| PAPER_TRADING | Auto-approve all signals | Trades execute freely |
| HUMAN_APPROVAL | Auto-approve all signals | CIO still reviews |
| FULLY_AUTONOMOUS | **Auto-REJECT all signals** | Safety: no trades without debate |

### 4.8 Debounce

To avoid debating the same symbol repeatedly:
- **Debounce window:** 120 seconds per symbol
- If a signal arrives for AAPL within 120 seconds of the last AAPL debate, it is silently dropped

### 4.9 Example Debate Output

```
Debate: BUY AAPL.NASDAQ
Round 1:
  STRATEGY (openai):  FOR   0.82  "RSI at 38 with strong volume support..."
  RISK (gemini):      AGAINST 0.71 "Earnings next week creates event risk..."
  SENTIMENT (openai): FOR   0.65  "Analyst upgrades and positive sentiment..."
  PORTFOLIO (gemini): FOR   0.58  "Low correlation with existing positions..."

Round 2 (rotated):
  RISK→STRATEGY (gemini):     FOR   0.55  "Reconsidering: risk/reward acceptable..."
  STRATEGY→RISK (openai):     FOR   0.60  "Even from risk view, 3% stop limits downside..."
  PORTFOLIO→SENTIMENT (gemini): FOR  0.70  "Crowd positioning supports the thesis..."
  SENTIMENT→PORTFOLIO (openai): FOR  0.75  "Adds diversification to tech allocation..."

Result: APPROVED (consensus: 0.68, for_ratio: 6/7 = 0.86)
```

---

## 5. Portfolio Agent

### 5.1 Signal Processing by Mode

The Portfolio Agent (`portfolio_agent.py`) receives risk-approved signals and debate conclusions:

**PAPER_TRADING mode:**
```
Signal arrives → Dedup check (120s cooldown) → Size position → Emit ORDER_NEW
```

**HUMAN_APPROVAL mode:**
```
Signal arrives → Dedup check → Size position → Emit ORDER_NEW (requires_approval=True)
→ Buffered until CIO types "approve <id>" or "reject <id>"
```

**FULLY_AUTONOMOUS mode:**
```
Signal arrives → Dedup check → Buffer signal by symbol
DEBATE_CONCLUSION arrives → If APPROVED: size and emit ORDER_NEW
                           → If REJECTED: discard buffered signals
```

### 5.2 Signal Deduplication

Three strategies fire simultaneously for the same symbol (RSI, MACD, Bollinger all process AAPL at the same time). Without dedup, this creates 3 orders.

**Solution:** Per-symbol cooldown set IMMEDIATELY when first signal is processed:

```python
# In _handle_signal():
last = self._last_order_time.get(symbol)
if last and (now - last) < 120_seconds:
    return  # Skip duplicate

self._last_order_time[symbol] = now  # Lock BEFORE any async work
# ... proceed to size and emit
```

The cooldown is set before the async sizing/emission to prevent race conditions.

### 5.3 Position Sizing

**Equal-weight allocation capped at available cash:**

```python
def _compute_position_size(symbol, direction, exchange):
    positions = load_positions()
    cash_usd, cash_inr = load_cash()
    nav = compute_unified_nav(cash_usd, cash_inr, positions)
    
    if nav <= 0:
        return 0  # No capital
    
    price = get_price(symbol)
    if price <= 0:
        return 0  # No price data
    
    # SELL: only sell what we hold
    if direction == SELL:
        held_qty = find_position(symbol).quantity
        return held_qty  # Sell entire position
    
    # BUY: equal-weight sizing
    num_positions = max(len(positions) + 1, 1)
    equal_share = nav / num_positions
    max_size = nav * 0.05  # 5% cap
    allocation = min(equal_share, max_size)
    
    # Cap at available cash (90% buffer)
    available = cash_inr if exchange in (NSE, BSE) else cash_usd
    if available <= 0:
        return 0  # No cash
    allocation = min(allocation, available * 0.9)
    
    qty = floor(allocation / price)  # Round down to whole shares
    return qty
```

**Key constraints:**
- Cannot buy more than 5% of NAV in one position
- Cannot buy more than 90% of available cash
- Cannot buy if cash is zero or negative
- Sell orders only sell existing position quantity
- Crypto can have fractional quantities; stocks are rounded down

### 5.4 NAV Unification

Portfolio spans USD and INR assets. NAV is computed in USD:

```python
def compute_unified_nav(cash_usd, cash_inr, positions):
    usd_inr_rate = get_rate()  # Default: 83.0
    total = cash_usd + (cash_inr / usd_inr_rate)
    for pos in positions:
        value = abs(pos.current_price * pos.quantity)
        if pos.currency == "INR":
            value = value / usd_inr_rate
        total += value
    return total
```

---

## 6. Execution

### 6.1 Order Lifecycle

```
ORDER_NEW received by Execution Agent
    ↓
Create order record in DB (status: PENDING)
    ↓
If HUMAN_APPROVAL mode and requires_approval:
    Buffer in _pending_approval dict → Wait for CIO → STOP
    ↓
If SELL: check for existing position (naked short block)
    No position? → REJECT order
    ↓
Set order status to OPEN
    ↓
Execute via PaperBroker (up to 3 retries)
    ↓
If fill received:
    Record fill in DB
    Update position (avg price, P&L)
    Update cash balance
    Publish ORDER_FILL
    ↓
If no fill after 3 retries:
    REJECT order
```

### 6.2 Almgren-Chriss Market Impact Model

The Paper Broker simulates realistic execution costs using the Almgren-Chriss model, which separates slippage into two components:

**Participation Rate:**
```
participation = order_quantity / average_daily_volume
```
This measures what fraction of daily volume the order represents. A 100-share order in a stock that trades 10M shares/day has negligible impact. A 100K-share order in a stock trading 500K/day has massive impact.

**Permanent Impact (Irreversible Price Move):**
```
permanent = 0.142 × volatility × price × (participation ^ 0.314)
```
This represents the information content of the trade. The market "learns" from the order and the price permanently shifts. The 0.314 exponent means impact grows sub-linearly — doubling the order doesn't double the impact.

**Temporary Impact (Transient Microstructure Cost):**
```
temporary = 0.0625 × price 
          + 0.142 × volatility × price × (participation ^ 0.600)
```
The first term (0.0625 × price) is the half-spread — the cost of crossing the bid-ask spread. The second term is the market-moving component, growing faster than permanent impact (exponent 0.600 vs 0.314).

**Total Slippage:**
```
total_impact = permanent + temporary
fill_price = mid_price + direction × total_impact + noise
slippage_amount = |fill_price - mid_price| × quantity
```

**Microstructure Noise:**
```
noise = random_gaussian(mean=0, std=volatility × price × 0.01)
```

**Model Parameters:**

| Parameter | Value | Meaning |
|-----------|-------|---------|
| Permanent η | 0.142 | Information content coefficient |
| Permanent γ | 0.314 | Permanent impact exponent |
| Temporary ε | 0.0625 | Half-spread (6.25 bps) |
| Temporary η | 0.142 | Microstructure coefficient |
| Temporary γ | 0.600 | Temporary impact exponent |
| Default volume | 1,000,000 | Fallback daily volume |
| Default volatility | 2% | Fallback daily volatility |

**Example:**
- Buy 150 shares of TSLA at $400, daily volume = 50M shares
- Participation = 150 / 50,000,000 = 0.000003
- Permanent = 0.142 × 0.02 × 400 × (0.000003^0.314) = ~$0.015
- Temporary = 0.0625 × 400 + 0.142 × 0.02 × 400 × (0.000003^0.600) = ~$25.002
- Fill price ≈ $400 + $25.017 + noise ≈ $425.02
- The dominant cost is the half-spread ($25), not the market impact

### 6.3 Cash Balance Update

After every fill:

```python
cost = filled_qty × fill_price

if side == "BUY":
    new_cash = current_cash - cost - commission
elif side == "SELL":
    new_cash = current_cash + cost - commission

# Indian symbols use INR bucket, everything else uses USD
cash_key = "horizon:cash:inr" if exchange in ("NSE", "BSE") else "horizon:cash:usd"
```

### 6.4 Retry Logic

```python
for attempt in range(3):
    fill = await paper_broker.execute(order)
    if fill is not None:
        break
    await sleep(2 ** attempt)  # 1s, 2s, 4s backoff
```

---

## 7. P&L Calculation

### 7.1 Position Tracking

Every position in the `positions` table tracks:

| Field | Description |
|-------|-------------|
| `symbol` | Instrument identifier |
| `side` | LONG or SHORT |
| `quantity` | Current held quantity |
| `avg_entry_price` | Volume-weighted average entry |
| `current_price` | Latest market price |
| `unrealized_pnl` | Paper profit/loss |
| `realized_pnl` | Locked-in profit/loss |
| `stop_loss_price` | Protective stop level |

### 7.2 How Average Entry Price Is Calculated

**Adding to a LONG position (BUY):**
```
new_avg = (old_avg × old_qty + fill_price × fill_qty) / (old_qty + fill_qty)
new_qty = old_qty + fill_qty
```

**Example:** Hold 100 AAPL at $280 avg. Buy 50 more at $290.
```
new_avg = (280 × 100 + 290 × 50) / 150 = $283.33
```

### 7.3 Unrealized P&L

Computed continuously as the market price changes:

```
unrealized_pnl = (current_price - avg_entry_price) × quantity    [for LONG]
unrealized_pnl = (avg_entry_price - current_price) × quantity    [for SHORT]
```

**Example:** Hold 100 AAPL, avg entry $280, current price $295.
```
unrealized_pnl = ($295 - $280) × 100 = +$1,500
```

### 7.4 Realized P&L

Locked in when a position is partially or fully closed:

**Selling a LONG position:**
```
realized_pnl += (fill_price - avg_entry_price) × min(sell_qty, held_qty)
remaining_qty = held_qty - sell_qty
```

**Example:** Sell 60 AAPL at $295, avg entry was $280.
```
realized_pnl = ($295 - $280) × 60 = +$900
remaining: 40 shares at $280 avg
```

**Covering a SHORT position (buying back):**
```
realized_pnl += (avg_entry_price - fill_price) × min(buy_qty, short_qty)
```

### 7.5 Total P&L

```
total_pnl = sum(realized_pnl for all positions) + sum(unrealized_pnl for all positions)
```

### 7.6 Position State Transitions

```
No position �� BUY → LONG position created (avg = fill_price)
LONG → BUY more → LONG increased (avg recalculated)
LONG → SELL partial → LONG decreased (realized P&L booked)
LONG → SELL all → Position closed (all P&L realized)
No position → SELL → BLOCKED (naked short prevention)
```

---

## 8. CIO Agent

The AI Chief Investment Officer operates in three modes, each with specific LLM prompts and decision logic.

### 8.1 Mode A — Strategic Advisory (Every 15 Minutes)

**System Prompt:**
```
You are the Chief Investment Officer (CIO) of Horizon Capital, an AI-driven 
hedge fund. Analyze the portfolio digest below and produce a strategic advisory 
in JSON format.

Return ONLY valid JSON with these fields:
- "outlook": one of "bullish", "neutral", "bearish"
- "summary": 1-3 sentence assessment of current portfolio state
- "recommended_adjustments": list of strings (specific actions, or empty list)
- "risk_flags": list of strings (concerns to watch, or empty list)

Portfolio digest:
{digest}
```

**Temperature:** 0.4 (moderately conservative — allows some variation but stays grounded)

**Portfolio Digest Contents:**
```python
{
    "nav": 1045000.50,
    "positions": [...],       # All current positions
    "regime": "NORMAL",       # Market regime label
    "open_positions": 5,      # Count of active positions
}
```

**Output Example:**
```json
{
    "outlook": "bullish",
    "summary": "Portfolio well-positioned with strong tech exposure. NAV growth of 4.5% this month driven by AAPL and MSFT momentum.",
    "recommended_adjustments": [
        "Consider reducing TSLA allocation given elevated volatility",
        "Add defensive exposure via HDFCBANK position"
    ],
    "risk_flags": [
        "Tech concentration above 60% — vulnerable to sector rotation",
        "Earnings season approaching for 3/5 US holdings"
    ]
}
```

### 8.2 Mode B — Crisis Response (On Risk Alert)

**Triggers:** Severity HIGH or CRITICAL risk alerts, or KILL_SWITCH_TRIGGERED.

**System Prompt:**
```
You are the Chief Investment Officer (CIO) of Horizon Capital responding to a 
crisis alert. A risk event has been triggered. Analyze the situation and respond 
in JSON format.

Return ONLY valid JSON with these fields:
- "stance": one of "HOLD", "REDUCE", "HALT"
- "confidence": float between 0.0 and 1.0
- "reasoning": 1-3 sentence explanation
- "specific_actions": list of strings (concrete steps to take)

Trigger: {trigger}
Alert payload: {payload}

Portfolio digest:
{digest}
```

**Temperature:** 0.2 (highly deterministic — crisis decisions should be consistent)

**Output Example:**
```json
{
    "stance": "REDUCE",
    "confidence": 0.78,
    "reasoning": "Daily drawdown at 4.2% approaching the 5% limit. Elevated VaR suggests portfolio is over-exposed to current volatility regime.",
    "specific_actions": [
        "Reduce TSLA position by 50%",
        "Close all crypto positions immediately",
        "Halt new BUY orders for 30 minutes"
    ]
}
```

### 8.3 Mode C — Override Directive

**Activation Criteria (ALL must be true):**
1. Kill switch is active (drawdown ≥ 10%)
2. Mode B produced stance = "HALT"
3. Mode B confidence ≥ 0.85

**Action:** Publishes `CIO_OVERRIDE` message that halts all trading system-wide.

**In FULLY_AUTONOMOUS mode:** Override requires human confirmation via `cio confirm halt` REPL command before taking effect.

### 8.4 LLM Provider Selection

```python
# Priority order: Claude > OpenAI > Gemini
priority = {"claude": 0, "openai": 1, "gemini": 2}

# Only uses providers routed to "executive" department
providers = registry.get_providers_for_department("executive")
```

### 8.5 Circuit Breaker

If the LLM fails 3 times consecutively:
- Circuit opens for 300 seconds (5 minutes)
- All Mode A/B calls return immediately (no advisory)
- After cooldown, circuit enters half-open state (allows one try)
- Successful call resets the counter

---

## 9. Risk Monitoring

### 9.1 Continuous Monitoring (Every 30 Seconds)

The Risk Agent continuously recomputes portfolio-wide risk metrics:

**Value at Risk (VaR) — Historical Simulation:**
```
1. Load last 253 daily portfolio returns (1 year of trading days)
2. Sort returns ascending
3. VaR-95 = |5th percentile of returns|
4. VaR-99 = |1st percentile of returns|
```

**Interpretation:** VaR-95 of 0.0200 means "There is a 5% chance the portfolio will lose more than 2% in a single day."

**Conditional VaR (CVaR-95) — Expected Shortfall:**
```
CVaR-95 = mean of all returns worse than the 5th percentile
```

**Interpretation:** CVaR answers "When we DO lose more than VaR, how bad is it on average?"

**Maximum Drawdown:**
```python
peak = equity_curve[0]
max_dd = 0.0
for value in equity_curve:
    if value > peak:
        peak = value
    dd = (peak - value) / peak
    if dd > max_dd:
        max_dd = dd
```

**Current Drawdown:**
```python
peak = max(equity_curve)
current = equity_curve[-1]
current_dd = (peak - current) / peak
```

### 9.2 Kill Switch

```
IF current_drawdown >= 10%:
    Publish KILL_SWITCH_TRIGGERED (severity: EMERGENCY)
    CIO Agent activates Mode B
    If CIO confidence >= 85%: halt all trading
```

### 9.3 Risk Metrics Published to Dashboard

Every 30 seconds, the Risk Agent publishes:
```python
{
    "var_95": 0.0189,
    "var_99": 0.0312,
    "cvar_95": 0.0245,
    "max_drawdown": 3.2,      # percentage
    "current_drawdown": 1.8,   # percentage
    "kill_switch_active": False,
}
```

---

## 10. Performance Metrics

### 10.1 Computation Schedule

The Performance Worker runs every **15 minutes** and computes metrics for 6 time periods: 1 day, 7 days, 30 days, 90 days, YTD, and ALL.

### 10.2 Return Metrics

**Total Return:**
```
total_return = (final_nav - initial_nav) / initial_nav
```

**Annualized Return:**
```
years = trading_days / 252
annualized = (1 + total_return) ^ (1/years) - 1
```

### 10.3 Risk-Adjusted Returns

**Sharpe Ratio (Risk-Adjusted Return):**
```
risk_free_daily = risk_free_rate / 252    (default risk-free: 0%)
excess_returns = daily_returns - risk_free_daily
sharpe = mean(excess_returns) / std(excess_returns) × sqrt(252)
```

**Interpretation:**
- Sharpe < 0: Losing money
- Sharpe 0-1: Returns don't justify the risk
- Sharpe 1-2: Good risk-adjusted performance
- Sharpe > 2: Excellent (hard to sustain)

**Sortino Ratio (Downside Risk Only):**
```
downside_returns = [r for r in excess_returns if r < 0]
downside_vol = sqrt(mean(downside_returns^2))
sortino = mean(excess_returns) / downside_vol × sqrt(252)
```

Sortino is like Sharpe but only penalizes downside volatility. Upside volatility is good — Sortino doesn't punish it.

**Calmar Ratio (Return vs Worst Drawdown):**
```
calmar = annualized_return / max_drawdown
```

### 10.4 Alpha Calculation (Jensen's Alpha)

Alpha measures how much the portfolio outperforms (or underperforms) a benchmark after adjusting for systematic risk (beta).

**Step 1 — Compute Beta:**
```
beta = covariance(portfolio_returns, benchmark_returns) / variance(benchmark_returns)
```

**Step 2 — Jensen's Alpha:**
```
alpha = mean(portfolio_return - beta × benchmark_return) × 252
```

**Benchmarks:**
- **India stocks:** NIFTY 50 (`^NSEI`)
- **US stocks:** S&P 500 (`^GSPC`)

**Interpretation:**
- Alpha > 0: Portfolio outperforms the benchmark on a risk-adjusted basis
- Alpha = 0: Portfolio performs exactly as expected given its beta
- Alpha < 0: Portfolio underperforms

### 10.5 Win Rate and Profit Factor

**Win Rate:**
```
Wins = count of round-trip trades where realized_pnl > 0
Total = total round-trip trades
win_rate = Wins / Total
```

**Profit Factor:**
```
gross_profit = sum of all positive realized P&L
gross_loss = abs(sum of all negative realized P&L)
profit_factor = gross_profit / gross_loss
```

A profit factor > 1.0 means the system is profitable overall.

---

## 11. Feature Computation

### 11.1 The Data Pipeline

The Feature Computation Worker runs every **2 minutes** and computes 23+ technical indicators for every symbol.

### 11.2 Indicators Computed

**Moving Averages (7):**

| Indicator | Formula | Purpose |
|-----------|---------|---------|
| SMA-20 | mean(close, 20) | Short-term trend |
| SMA-50 | mean(close, 50) | Medium-term trend |
| SMA-200 | mean(close, 200) | Long-term trend |
| EMA-12 | exp_weighted(close, 12) | MACD fast line input |
| EMA-26 | exp_weighted(close, 26) | MACD slow line input |
| EMA-50 | exp_weighted(close, 50) | Medium trend (smoothed) |
| EMA-200 | exp_weighted(close, 200) | Long trend (smoothed) |

**Momentum (5):**

| Indicator | Formula | Purpose |
|-----------|---------|---------|
| RSI-14 | 100 - 100/(1 + avg_gain/avg_loss) | Overbought/oversold |
| MACD | EMA-12 - EMA-26 | Trend momentum |
| MACD Signal | EMA(MACD, 9) | MACD smoothing |
| MACD Histogram | MACD - Signal | Momentum acceleration |
| Stochastic %K/%D | Position in 14-day range | Short-term momentum |

**Volatility (4):**

| Indicator | Formula | Purpose |
|-----------|---------|---------|
| BB Upper | SMA-20 + 2σ | Upper volatility band |
| BB Middle | SMA-20 | Center line |
| BB Lower | SMA-20 - 2σ | Lower volatility band |
| BB Width | (Upper - Lower) / Middle | Volatility measure |

**Trend (7):**

| Indicator | Formula | Purpose |
|-----------|---------|---------|
| ATR-14 | Average True Range | Volatility unit |
| ADX-14 | Directional Index | Trend strength |
| +DI | Positive directional | Uptrend strength |
| -DI | Negative directional | Downtrend strength |
| OBV | Cumulative volume direction | Volume-confirmed trend |
| VWAP | Σ(price × volume) / Σ(volume) | Fair value estimate |

**Advanced Volatility (3):**

| Indicator | Formula | Purpose |
|-----------|---------|---------|
| Realized Vol | std(log_returns) × √252 | Historical volatility |
| Parkinson Vol | √(Σlog(H/L)² / (4n·ln2)) × √252 | Range-based volatility |
| Garman-Klass | √(Σ[0.5·log(H/L)² - (2ln2-1)·log(C/O)²] × 252/n) | OHLC-efficient vol |

### 11.3 Storage

- **KV Store:** `horizon:features:{symbol}:{timeframe}` with 2-hour TTL
- **Database:** Persisted to `feature_snapshots` table for backtesting

---

## 12. Configuration Reference

### 12.1 Risk Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `risk_max_position_pct` | 5.0% | Maximum single position as % of NAV |
| `risk_daily_loss_limit_pct` | 5.0% | Daily loss threshold (blocks new trades) |
| `risk_max_drawdown_pct` | 10.0% | Kill switch threshold |
| `risk_max_leverage` | 1.0 | Maximum gross leverage |
| `risk_var_limit_pct` | 3.0% | VaR limit |
| `risk_max_orders_per_minute` | 10 | Order rate limit |

### 12.2 Timing Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| Strategy poll | 60s | How often strategies run |
| Feature computation | 120s | How often indicators recompute |
| Risk recomputation | 30s | How often VaR/DD update |
| Portfolio snapshot | 60s | How often NAV is recalculated |
| Performance metrics | 900s | How often Sharpe/Alpha update |
| CIO advisory | 900s | How often CIO publishes outlook |
| Order cooldown | 120s | Per-symbol order dedup window |
| Debate debounce | 120s | Per-symbol debate dedup window |

### 12.3 LLM Parameters

| Context | Temperature | Rationale |
|---------|-------------|-----------|
| Debate arguments | 0.7 | Creative, diverse perspectives |
| CIO Mode A (advisory) | 0.4 | Moderate consistency |
| CIO Mode B (crisis) | 0.2 | High consistency for crisis decisions |

### 12.4 Almgren-Chriss Parameters

| Parameter | Symbol | Value | Calibrated For |
|-----------|--------|-------|----------------|
| Permanent impact coeff | η | 0.142 | Liquid US equities |
| Permanent impact exp | γ | 0.314 | Sub-linear scaling |
| Temporary half-spread | ε | 0.0625 | ~6 bps half-spread |
| Temporary impact coeff | η | 0.142 | Matches permanent |
| Temporary impact exp | γ | 0.600 | Faster scaling |

---

## 13. Complete Signal-to-Trade Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     DATA INGESTION (Every 60s)                       │
│  Yahoo Finance → 60 days OHLCV per symbol                           │
│  Cache: price → horizon:price:{symbol}                              │
│  Cache: volume → horizon:volume:{symbol}                            │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│               FEATURE COMPUTATION (Every 2 min)                      │
│  23 technical indicators + 3 volatility measures                     │
│  Stored in KV (2hr TTL) + DB                                        │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  STRATEGY AGENT (Every 60s)                          │
│                                                                      │
│  For each symbol:                                                    │
│    RSI Strategy    → direction, strength (RSI < 45 buy, > 65 sell)  │
│    MACD Strategy   → direction, strength (crossover detection)      │
│    Bollinger Band  → direction, strength (band position)            │
│    Momentum        → direction, strength (6-factor fusion)          │
│    Mean Reversion  → direction, strength (OU s-score)               │
│                                                                      │
│  Emit: horizon.signal.{symbol} (MessageType.SIGNAL)                 │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
              ┌────────────┤
              ▼            ▼
┌──────────────────┐  ┌──────────────────────────────────────────────┐
│   RISK AGENT     │  │  (Signal also reaches other subscribers)      │
│                  │  └──────────────────────────────────────────────┘
│  Check 1: Position weight < 5% of NAV?                              │
│  Check 2: Daily loss < 5% of NAV?                                   │
│                                                                      │
│  PASS → horizon.risk.approved.{symbol}                              │
│  FAIL → horizon.risk.rejected.{symbol}                              │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ (approved only)
              ┌────────────┤
              ▼            ▼
┌──────────────────┐  ┌──────────────────────────────────────────────┐
│  DEBATE AGENT    │  │  PORTFOLIO AGENT                              │
│                  │  │                                                │
│  Debounce: 120s  │  │  Subscribes to: horizon.risk.approved.*      │
│  per symbol      │  │                 horizon.debate.*              │
│                  │  │                                                │
│  If LLM avail:  │  │  ┌────────────────────────��─┐                │
│   2-round debate │  │  │ PAPER_TRADING:            │                │
│   4 perspectives │  │  │  Process immediately      │                │
│   Rotate in R2   │  │  │                           │                │
│                  │  │  │ HUMAN_APPROVAL:           │                │
│  If no LLM:     │  │  │  Buffer for CIO review    │                │
│   PAPER: approve │  │  │                           │                │
│   AUTO: REJECT   │  │  │ FULLY_AUTONOMOUS:         │                │
│                  │  │  │  Wait for debate result   │                │
│  Consensus:      │  │  └──────────────────────────┘                │
│  > 0.55 score    │  │                                                │
│  >= 60% FOR      │  │  Dedup: 120s cooldown per symbol             │
│  = APPROVED      │  │  Sizing: min(equal_weight, 5% NAV, 90% cash) │
│                  │  │  SELL: only sell held quantity                 │
│  Emit:           │  │                                                │
│  horizon.debate  │  │  Emit: horizon.execution.order.new            │
│  .{symbol}       │  │        (MessageType.ORDER_NEW)                │
└──────────────────┘  └──────────────────────────┬───────────────────┘
                                                  │
                                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      EXECUTION AGENT                                 │
│                                                                      │
│  1. Create order in DB                                               │
│  2. If HUMAN_APPROVAL + requires_approval → buffer, STOP            │
│  3. Naked short check: SELL without position ��� REJECT               │
│  4. Execute via PaperBroker (Almgren-Chriss model)                  │
│     - Permanent impact: η × σ × P × (Q/V)^0.314                    │
│     - Temporary impact: ε × P + η × σ × P × (Q/V)^0.600           │
│     - Fill price = mid + direction × total_impact + noise           │
│  5. Retry up to 3 times with exponential backoff                    │
│  6. Record fill, update position, update cash                       │
│  7. Emit: horizon.execution.order.fill                              │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    POSITION & P&L UPDATE                             │
│                                                                      │
│  BUY → new_avg = weighted average of old + new                      │
│  SELL → realized_pnl = (fill_price - avg_entry) × qty              │
│  Cash: BUY deducts, SELL adds                                       │
│                                                                      │
│  Unrealized P&L = (current_price - avg_entry) × held_qty           │
│  Updated every 60s by Portfolio Agent snapshot                      │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
┌──────────────────┐ ┌──────────┐ ┌──────────────────────────────────┐
│  RISK MONITOR    │ │  CIO     │ │  PERFORMANCE WORKER              │
│  (Every 30s)     │ │  AGENT   │ │  (Every 15 min)                  │
│                  │ │(Every 15m│ │                                    │
│  VaR-95, VaR-99  │ │          │ │  Sharpe, Sortino, Calmar ratios  │
│  CVaR-95         │ │  Mode A: │ │  Jensen's Alpha vs NIFTY/SPX     │
│  Max drawdown    │ │  Advisory│ │  Win rate, profit factor          │
│  Current DD      │ │          │ │  Total/annualized returns         │
│                  │ │  Mode B: │ │                                    │
│  Kill switch:    │ │  Crisis  │ │  Periods: 1d/7d/30d/90d/YTD/ALL  │
│  DD >= 10%       │ │  response│ │                                    │
│  → HALT trading  │ │          │ │                                    │
│                  │ │  Mode C: │ │                                    │
│                  │ │  Override│ │                                    │
└──────────────────┘ └──────────┘ └──────────────────────────────────┘
```

---

## Appendix A: Message Types Reference

| MessageType | Channel Pattern | Emitter | Consumer |
|-------------|----------------|---------|----------|
| `SIGNAL` | `horizon.signal.*` | Strategy Agent | Risk Agent, Debate Agent |
| `SIGNAL` | `horizon.risk.approved.*` | Risk Agent | Portfolio Agent, Debate Agent |
| `RISK_ALERT` | `horizon.risk.*` | Risk Agent | CIO Agent, Dashboard |
| `DEBATE_START` | `horizon.debate.*` | Debate Agent | Dashboard |
| `DEBATE_CONCLUSION` | `horizon.debate.*` | Debate Agent | Portfolio Agent |
| `ORDER_NEW` | `horizon.execution.order.*` | Portfolio/Execution Agent | Execution Agent, Dashboard |
| `ORDER_FILL` | `horizon.execution.order.fill` | Execution Agent | Dashboard, Risk Agent |
| `ORDER_CANCEL` | `horizon.execution.order.update` | Execution Agent | Dashboard |
| `PORTFOLIO_UPDATE` | `horizon.portfolio.update` | Portfolio Agent | Dashboard |
| `CIO_ADVISORY` | `horizon.executive.cio` | CIO Agent | Dashboard |
| `CIO_OVERRIDE` | `horizon.executive.cio` | CIO Agent | All agents |
| `HEARTBEAT` | `horizon.agents.*` | All agents | Dashboard |

## Appendix B: Database Tables Used in Trading

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `signals` | All generated signals | signal_id, symbol, direction, strength, strategy_name |
| `orders` | Order lifecycle | id, symbol, side, quantity, status, broker |
| `fills` | Execution records | order_id, filled_qty, fill_price, slippage, commission |
| `positions` | Current holdings | symbol, side, quantity, avg_entry_price, unrealized_pnl |
| `debate_sessions` | Debate outcomes | id, symbol, final_decision, consensus_score, reason |
| `risk_metrics` | Historical risk data | var_1d_95, var_1d_99, max_drawdown, current_drawdown |
| `portfolio_snapshots` | NAV time series | total_value, cash_usd, cash_inr, leverage |
| `performance_metrics` | Return analytics | sharpe, sortino, calmar, alpha, win_rate |

---

*This document reflects the codebase as of v0.2.0. All parameter values, formulas, and system prompts are extracted directly from the source code.*
