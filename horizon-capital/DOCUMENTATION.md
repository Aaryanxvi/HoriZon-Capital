# Horizon Capital -- Comprehensive System Documentation

> **Version 0.2.0** | Autonomous AI Hedge Fund Terminal Agent
>
> A multi-agent, department-structured hedge fund platform that runs entirely from your terminal.
> Zero infrastructure required in LOCAL mode -- just Python + SQLite.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Organizational Structure (Departments)](#3-organizational-structure-departments)
4. [Agent System](#4-agent-system)
5. [Front Office -- Investment & Revenue](#5-front-office----investment--revenue)
6. [Middle Office -- Risk & Control](#6-middle-office----risk--control)
7. [Back Office -- Support & Finance](#7-back-office----support--finance)
8. [Executive -- Management](#8-executive----management)
9. [Debate Engine -- Multi-Agent Consensus](#9-debate-engine----multi-agent-consensus)
10. [Multi-LLM Provider Layer](#10-multi-llm-provider-layer)
11. [Messaging & Communication](#11-messaging--communication)
12. [Data Storage & Persistence](#12-data-storage--persistence)
13. [Terminal UI & Commands](#13-terminal-ui--commands)
14. [CIO Dual Mode](#14-cio-dual-mode)
15. [Risk Management Deep Dive](#15-risk-management-deep-dive)
16. [Trading Execution Pipeline](#16-trading-execution-pipeline)
17. [Data Flow & Signal Lifecycle](#17-data-flow--signal-lifecycle)
18. [Configuration Reference](#18-configuration-reference)
19. [CLI Reference](#19-cli-reference)
20. [Testing](#20-testing)
21. [Dependencies](#21-dependencies)
22. [Glossary](#22-glossary)

---

## 1. System Overview

Horizon Capital is an **autonomous AI hedge fund** that operates as a **desktop terminal agent**. It is NOT a web application -- it runs in your terminal using Rich for the TUI and a REPL for interactive commands.

### What It Does

- **Monitors global markets** across India (NSE), US (NASDAQ), and Crypto (BTC, ETH)
- **Detects market regimes** (Bull, Bear, Neutral, Crisis, High Volatility) using Hidden Markov Models
- **Analyzes sentiment** from news and Reddit using FinBERT
- **Generates trading signals** through an ensemble of four strategies
- **Debates trade decisions** using a multi-agent AI debate with four specialist perspectives
- **Manages risk** in real-time with VaR, drawdown monitoring, and an automatic kill switch
- **Executes trades** across multiple brokers (Alpaca for US, Zerodha for India, paper trading)
- **Reports to the CIO** (you) through an interactive chat interface or runs autonomously as an AI CIO

### Design Principles

1. **Zero Infrastructure** -- LOCAL mode uses SQLite + in-memory message bus. No Docker, no PostgreSQL, no Redis needed.
2. **Agent Autonomy** -- Each agent runs independently as an asyncio task with its own lifecycle, heartbeat, and error recovery.
3. **Department Structure** -- Agents are organized into four departments mirroring a real hedge fund: Front Office, Middle Office, Back Office, and Executive.
4. **Human Oversight** -- Default mode keeps a human CIO in the loop. AI CIO is opt-in.
5. **Multi-LLM** -- Each agent role can use Claude, GPT-4, or Gemini. Multiple instances per role produce diverse perspectives.
6. **Defensive Risk** -- Multiple layers of risk control: pre-trade validation, post-trade monitoring, kill switch, compliance checks.

---

## 2. Architecture

### High-Level Architecture

```
                          ┌─────────────────────┐
                          │   Terminal (TUI)     │
                          │  Dashboard + REPL    │
                          │  CIO Chat Interface  │
                          └──────────┬──────────┘
                                     │
                          ┌──────────▼──────────┐
                          │  Agent Orchestrator  │
                          │  (Health Monitor)    │
                          └──────────┬──────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
   ┌──────────▼──────────┐ ┌────────▼────────┐ ┌──────────▼──────────┐
   │    Front Office     │ │  Middle Office   │ │    Back Office      │
   │ Research, Strategy, │ │ Risk, Compliance,│ │ Accounting, IT,     │
   │ Trading, Portfolio, │ │ Operations       │ │ Quant               │
   │ Investor Relations  │ │                  │ │                     │
   └──────────┬──────────┘ └────────┬────────┘ └──────────┬──────────┘
              │                      │                      │
              └──────────────────────┼──────────────────────┘
                                     │
                          ┌──────────▼──────────┐
                          │    Message Bus      │
                          │ (MemoryBus / Redis) │
                          └──────────┬──────────┘
                                     │
                          ┌──────────▼──────────┐
                          │    Storage Layer     │
                          │ (SQLite / PostgreSQL)│
                          └─────────────────────┘
```

### Storage Backends

| Mode | Database | Message Bus | Infrastructure |
|------|----------|-------------|----------------|
| LOCAL (default) | SQLite (`~/.horizon-capital/horizon.db`) | In-memory asyncio Queue | None |
| POSTGRES | PostgreSQL + asyncpg | Redis pub/sub | Docker or hosted |

### System Modes

| Mode | Behavior |
|------|----------|
| PAPER_TRADING (default) | All orders go to the paper broker. No real money at risk. |
| HUMAN_APPROVAL | Orders queue as PENDING. CIO must approve each trade. |
| FULLY_AUTONOMOUS | Orders route directly to real brokers. Full auto-trading. |

### Boot Sequence

```
main() → parse CLI args
  └→ _run_system()
       ├→ startup()                    # Init logging, create DB tables, start bus
       ├→ provider_registry.auto_register_from_settings()  # Register LLMs
       ├→ AgentOrchestrator(bus)
       └→ _run_with_tui(orchestrator)
            ├→ TerminalDashboard()
            ├→ CommandHandler()
            ├→ Wire bus → dashboard listeners
            ├→ orchestrator.start_all()
            │    ├→ Create department managers
            │    ├→ Each manager creates its agents
            │    ├→ Each agent launched as asyncio.Task
            │    └→ Health monitor loop started
            └→ REPL loop: input() → handle() → output
```

---

## 3. Organizational Structure (Departments)

The system mirrors a real hedge fund's organizational structure with four departments:

```
Horizon Capital
│
├── Executive (Management)
│   └── CIO Agent (AI mode) / Human CIO (interactive mode)
│
├── Front Office (Investment & Revenue)
│   ├── Research
│   │   ├── Regime Detection Agent (HMM-based)
│   │   └── Sentiment Agent (FinBERT + news/Reddit)
│   ├── Strategy
│   │   └── Ensemble Selector (4 strategies)
│   ├── Trading
│   │   └── Execution Agent (multi-broker)
│   ├── Portfolio
│   │   └── Portfolio Agent (Kelly sizing, NAV)
│   └── Investor Relations
│       └── IR Agent (performance reports)
│
├── Middle Office (Risk & Control)
│   ├── Risk
│   │   └── Risk Agent (VaR, kill switch)
│   ├── Compliance
│   │   └── Compliance Agent (rules engine)
│   └── Operations
│       └── Operations Agent (stuck orders)
│
└── Back Office (Support & Finance)
    ├── Accounting
    │   └── Accounting Agent (NAV snapshots)
    ├── IT
    │   └── IT Agent (infrastructure monitoring)
    └── Quant
        └── Quant Agent (feature pipelines)
```

### Department Manager

Each department has a manager class (NOT an agent) that:
- Creates all agents for its department
- Provides start/stop lifecycle management
- Reports department health status
- Handles agent failures gracefully via try/except imports

---

## 4. Agent System

### BaseAgent

Every agent in the system inherits from `BaseAgent`, which provides:

```python
class BaseAgent(abc.ABC):
    agent_id: str           # Unique identifier ("risk-agent-1")
    agent_type: str         # Category ("risk", "regime", etc.)
    department: str         # Department ("middle_office")
    llm_provider: str       # LLM backend ("claude", "", etc.)

    async def start()       # Boot: register → subscribe → heartbeat → run()
    async def stop()        # Graceful shutdown
    async def run()         # Abstract: main agent loop
    async def on_message()  # Abstract: handle subscribed messages
    async def emit()        # Publish message + persist to DB
```

### Agent Lifecycle

```
1. start() is called by orchestrator
   ├─ _register()            # Upsert into agent_states table (status=RUNNING)
   ├─ _subscribe()           # Subscribe to bus channels (override in subclass)
   ├─ _heartbeat_loop()      # Publish heartbeat every 10s on horizon.system.health
   └─ run()                  # Main loop (must respect self._running flag)

2. Running...
   ├─ Heartbeats published every 10 seconds
   ├─ Messages received via on_message()
   └─ Messages sent via emit() (publishes + persists)

3. stop() is called
   ├─ Set _running = False
   ├─ Cancel heartbeat task
   └─ Set status = STOPPED in DB
```

### Health Monitoring (Orchestrator)

The orchestrator continuously monitors all agents:

- **Heartbeat Timeout**: If no heartbeat received for 60 seconds → mark UNRESPONSIVE → restart
- **Crash Detection**: If asyncio task exits with exception → mark CRASHED → restart
- **Retry Limit**: Max 3 restarts per agent with exponential backoff (2s, 4s, 8s)
- **Status Values**: INIT → RUNNING → CRASHED/UNRESPONSIVE → (restart) → RUNNING → ... → DEAD (max retries exceeded)

---

## 5. Front Office -- Investment & Revenue

### 5.1 Regime Detection Agent

**File**: `app/agents/front_office/research/regime_agent.py`

Classifies the current market regime for each geographic scope using a Hidden Markov Model (HMM) with concept drift detection.

**Market Scopes**: INDIA, US, CRYPTO

**Regime Classifications**:
| Regime | Description | Indicator |
|--------|-------------|-----------|
| BULL | Sustained uptrend | Highest mean return state |
| BEAR | Sustained downtrend | Lowest mean return state |
| NEUTRAL | Sideways / range-bound | Middle mean, low variance |
| HIGH_VOLATILITY | Large swings, no clear direction | Highest variance state |
| CRISIS | Sharp decline + high volatility | Low mean AND high variance |

**How It Works**:

1. **Feature Extraction** (every 60 seconds):
   - Fetches last 60 OHLCV records for a representative symbol per scope
   - Computes log-returns: `returns = diff(log(closes))`
   - Computes 20-period rolling volatility: `rolling_vol = std(returns[-20:])`
   - Feature matrix: `[returns, rolling_vol]` (Nx2)

2. **HMM Classification**:
   - `GaussianHMM` from hmmlearn with 4 hidden states
   - States are mapped to regime labels based on learned means/covariances
   - Confidence = posterior probability of the predicted state

3. **Drift Detection** (LFR Detector):
   - Tracks whether regime predictions remain accurate over time
   - If drift detected → clamp confidence to 0.4, reset detector
   - If drift warning → clamp confidence to 0.6

4. **Publishing**:
   - Only publishes `REGIME_UPDATE` when regime changes (delta detection)
   - Persists every evaluation to `regime_states` table

**Representative Symbols**:
- INDIA → RELIANCE.NSE
- US → AAPL.NASDAQ
- CRYPTO → BTC-USD

---

### 5.2 Sentiment Agent

**File**: `app/agents/front_office/research/sentiment_agent.py`

Fetches news and Reddit posts, scores them with FinBERT, tracks narrative lifecycles, and detects cross-asset sentiment spillover.

**Pipeline** (runs every 15 minutes per symbol):

```
1. Fetch Sources
   ├─ NewsAPI → articles with headlines
   └─ Reddit → posts from relevant subreddits

2. Score with FinBERT
   └─ Each article/post → sentiment_score [-1.0, +1.0]

3. Store Narratives
   └─ Persist to narratives table (title, score, source, symbols)

4. Classify Lifecycle Stage
   ├─ EMERGING     → <5 articles, trend forming
   ├─ ACCELERATING → Growing coverage, strengthening sentiment
   ├─ PEAK         → Maximum coverage/engagement
   ├─ DECLINING    → Fading coverage
   └─ FADING       → Minimal relevance

5. Compute Aggregates (multiple windows)
   ├─ 1 hour
   ├─ 4 hours
   ├─ 24 hours
   └─ 14 days
   Each: avg_sentiment, article_count, bull_pct, bear_pct, neutral_pct

6. Detect Spillover
   └─ If related symbols have correlated sentiment shifts → flag

7. Publish FEATURE_UPDATE
   └─ Channel: horizon.features.{symbol}.sentiment
```

**Related Symbol Groups** (for spillover detection):
- US Tech: AAPL, MSFT, GOOGL, AMZN, TSLA
- India IT: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK
- Crypto: BTC-USD, ETH-USD

---

### 5.3 Strategy System

**File**: `app/agents/front_office/strategy/`

Four specialized strategies, each active in specific market regimes, coordinated by an ensemble selector.

#### Signal Data Structure

```python
@dataclass
class Signal:
    symbol: str              # "AAPL.NASDAQ"
    direction: int           # +1 BUY, -1 SELL, 0 NEUTRAL
    strength: float          # Confidence [0.0, 1.0]
    strategy_name: str       # "momentum", "mean_reversion", etc.
    regime: str              # Current regime when signal was generated
    reasoning: str           # Human-readable explanation
    meta: dict               # Raw indicator values (RSI, MACD, etc.)
    target_price: float      # Optional price target
    stop_loss: float         # Optional stop-loss level
```

#### Strategy Implementations

| Strategy | Active Regimes | Logic |
|----------|---------------|-------|
| **MomentumStrategy** | BULL | Trend-following. BUY when RSI > 60 and MACD positive, SELL when RSI < 40 and MACD negative. |
| **MeanReversionStrategy** | NEUTRAL | Counter-trend. BUY when oversold (RSI < 30, price below lower Bollinger), SELL when overbought. |
| **VolatilityStrategy** | HIGH_VOLATILITY | Range-bound. BUY near support, SELL near resistance. Uses ATR for range detection. |
| **CrisisStrategy** | CRISIS | Defensive. Reduce exposure, favor safe havens. SELL risky assets, BUY defensive. |

#### Ensemble Selector

```python
class EnsembleSelector:
    strategies = [MomentumStrategy, MeanReversionStrategy,
                  VolatilityStrategy, CrisisStrategy]

    def get_active_strategies(regime: str) → list[BaseStrategy]
        # Returns only strategies active in the current regime

    def generate_signals(symbol, features, regime) → list[Signal]
        # Runs all active strategies and collects signals
```

When multiple strategies produce signals for the same symbol, the system can:
- Take the highest-strength signal
- Average strengths (ensemble vote)
- Route to the debate engine for consensus

---

### 5.4 Execution Agent

**File**: `app/agents/front_office/trading/execution_agent.py`

Routes orders to the appropriate broker based on system mode and symbol exchange.

**Order Flow**:

```
Signal arrives via ORDER_NEW message
│
├─ Check kill switch
│  └─ If active → override to PAPER_TRADING
│
├─ Create order record in DB
│
├─ Route based on SystemMode:
│  ├─ PAPER_TRADING → PaperBroker (mock fills, random slippage)
│  ├─ HUMAN_APPROVAL → Queue as PENDING (CIO must approve)
│  └─ FULLY_AUTONOMOUS → Real broker
│
├─ Broker selection (for real/paper):
│  ├─ Symbol ends in .NSE/.BSE → ZerodhaBroker
│  ├─ Symbol ends in .NASDAQ/.NYSE → AlpacaBroker
│  └─ Everything else → PaperBroker
│
└─ On fill:
   ├─ Update order status → FILLED
   ├─ Update/create position record
   └─ Publish ORDER_FILL message
```

**Order Status Lifecycle**:
```
PENDING → OPEN → FILLED
                → PARTIAL (partially filled)
                → REJECTED
                → CANCELLED
```

**Brokers**:
- **PaperBroker** -- Mock execution with simulated slippage and commission
- **AlpacaBroker** -- Alpaca API for US equities (paper or live)
- **ZerodhaBroker** -- Zerodha Kite API for Indian equities (mock by default)

---

### 5.5 Portfolio Agent

**File**: `app/agents/front_office/portfolio/portfolio_agent.py`

Manages capital allocation, position sizing, and NAV tracking.

**Position Sizing (Kelly Criterion)**:

```
1. Load current NAV and positions
2. Convert all values to base currency (USD) via CurrencyConverter
3. For each incoming signal:
   a. win_rate = clamp(signal.strength, 0.51, 0.85)
   b. win_loss_ratio = 2.0  (assumes 2:1 reward-to-risk)
   c. kelly_fraction = (win_rate - (1 - win_rate) / win_loss_ratio) / win_loss_ratio
   d. Apply correlation penalty:
      - If holding correlated positions, reduce kelly_fraction
   e. position_value = kelly_fraction * NAV * max_position_pct
   f. quantity = floor(position_value / current_price)
```

**NAV Snapshot** (every 60 seconds):
```
1. Load all positions from DB
2. Compute:
   - equity_value (stocks)
   - crypto_value (crypto positions)
   - total_value = cash + equity_value + crypto_value
   - gross_leverage = (long_value + short_value) / total_value
   - net_leverage = (long_value - short_value) / total_value
3. Persist to portfolio_snapshots table
4. Cache in Redis: horizon:portfolio:latest, horizon:portfolio:nav
5. Publish PORTFOLIO_UPDATE
```

---

### 5.6 Investor Relations Agent

**File**: `app/agents/front_office/investor_relations/ir_agent.py`

Generates periodic performance reports (every hour). LLM-powered when an LLM provider is available.

**Report Contents**:
- Current NAV
- Portfolio composition snapshot
- Risk metrics summary
- Period performance

---

## 6. Middle Office -- Risk & Control

### 6.1 Risk Agent

**File**: `app/agents/middle_office/risk/risk_agent.py`

The most critical agent in the system. Performs continuous risk monitoring and pre-trade validation.

**Pre-Trade Validation** (triggered on every signal):

| Check | Condition | Action |
|-------|-----------|--------|
| Position Limit | Symbol weight > max_position_pct (5%) | REJECT signal |
| Exposure Ceiling | Gross leverage > max_leverage (1.0x) | REJECT signal |
| Correlation Guard | Same-direction position > 3% weight | REJECT signal |
| Kill Switch | Kill switch active | REJECT all signals |

**Continuous Risk Recomputation** (every 30 seconds):

```
1. Load last 253 portfolio snapshots (1 year of daily data)
2. Compute daily returns from NAV values

3. Value at Risk (Historical):
   - VaR 95% = -percentile(returns, 5)     # 5th percentile loss
   - VaR 99% = -percentile(returns, 1)     # 1st percentile loss
   - CVaR 95% = -mean(returns[returns <= -VaR95])  # Expected loss beyond VaR

4. Drawdown:
   - Max Drawdown = max((peak - trough) / peak) over all time
   - Current Drawdown = (all-time-high - current) / all-time-high

5. Kill Switch Check:
   - If drawdown >= risk_max_drawdown_pct → ACTIVATE
   - If VaR95 >= max_var_95_pct → ACTIVATE
   - If VaR99 >= max_var_99_pct → ACTIVATE

6. Persist metrics to risk_metrics table
7. Cache in Redis for dashboard access
```

### 6.2 Kill Switch

**File**: `app/agents/middle_office/risk/kill_switch.py`

Emergency circuit breaker that immediately halts all real trading.

**When Activated**:
1. Sets `horizon:system:kill_switch = "1"` in Redis/KV store
2. Overrides system mode to PAPER_TRADING
3. Publishes `KILL_SWITCH` message on `horizon.risk.kill_switch`
4. All agents check the kill switch before any order execution
5. Remains active until manually deactivated by the CIO

**Trigger Conditions**:
- Current drawdown exceeds configured max (default: 10%)
- VaR (95%) exceeds configured limit (default: 3%)
- VaR (99%) exceeds configured limit (default: 5%)
- Manual activation by CIO

### 6.3 Compliance Agent

**File**: `app/agents/middle_office/compliance/compliance_agent.py`

Rule-based compliance monitoring (no LLM needed).

**Checks**:
- **Restricted Symbols**: Maintains a set of symbols that cannot be traded (regulatory, sanctions)
- **Signal Compliance**: Blocks signals targeting restricted symbols
- **Order Compliance**: Blocks orders for restricted symbols
- **Periodic Sweep**: Checks existing positions against compliance rules every 30 seconds

**Publishes**: `horizon.compliance.alert` (COMPLIANCE_ALERT)

### 6.4 Operations Agent

**File**: `app/agents/middle_office/operations/operations_agent.py`

Monitors order lifecycle for operational issues.

**Stuck Order Detection**:
- Tracks all pending orders with their creation timestamp
- If an order remains pending for > 5 minutes → flag as stuck
- Publishes `OPERATIONS_ALERT` with stuck order IDs
- Removes orders from tracking when they reach terminal state (FILLED, CANCELLED, REJECTED)

---

## 7. Back Office -- Support & Finance

### 7.1 Accounting Agent

**File**: `app/agents/back_office/accounting/accounting_agent.py`

Computes and records NAV and P&L snapshots every 2 minutes.

- Subscribes to `horizon.portfolio.*` to track latest NAV
- Publishes `ACCOUNTING_SNAPSHOT` with current NAV and timestamp
- Rule-based (no LLM)

### 7.2 IT Agent

**File**: `app/agents/back_office/it/it_agent.py`

Monitors infrastructure health every 60 seconds.

**Metrics Collected**:
- Platform and Python version
- Memory usage (percent, available GB) -- requires `psutil`
- CPU usage percent
- Alerts if memory usage > 90%

**Publishes**:
- `horizon.it.status` (IT_STATUS) -- routine health report
- `horizon.it.alert` (IT_ALERT) -- when memory/CPU critical

### 7.3 Quant Agent

**File**: `app/agents/back_office/quant/quant_agent.py`

Monitors feature pipeline health and model drift.

- Tracks timestamp of last feature update per scope
- Flags scopes where features are > 5 minutes stale
- Subscribes to `horizon.features.*`
- Rule-based (no LLM)

---

## 8. Executive -- Management

### 8.1 AI CIO Agent

**File**: `app/agents/executive/cio/cio_agent.py`

Only active when `CIO_MODE=AI`. Provides autonomous governance.

**Monitoring** (every 60 seconds):
- Aggregates alerts from risk, compliance, and IT
- If >= 5 critical alerts in recent window → issue `HALT_TRADING` directive
- If kill switch triggered → issue `EMERGENCY_HALT` directive

**Subscribes to**:
- `horizon.risk.*` -- Risk alerts
- `horizon.compliance.*` -- Compliance violations
- `horizon.department.*` -- Department status
- `horizon.it.*` -- IT alerts

**Publishes**: `horizon.cio.directive` (CIO_DIRECTIVE)

### 8.2 Human CIO Interface

**File**: `app/agents/executive/cio/human_cio.py`

A helper class (NOT an agent) that aggregates system state for the human CIO chat interface.

**Methods**:
- `get_system_summary()` -- Mode, storage, department statuses, agent count
- `get_department_overview()` -- Status per department
- `get_pending_approvals()` -- Items awaiting CIO approval

---

## 9. Debate Engine -- Multi-Agent Consensus

**Files**: `app/agents/debate/debate_engine.py`, `app/agents/debate/claude_reasoner.py`

A multi-perspective AI debate system for intelligent trade approval. Four specialist debaters argue FOR or AGAINST a proposed trade, and the system reaches consensus.

### Debater Roles

| Role | Personality | Focus |
|------|------------|-------|
| **STRATEGY** | Aggressive growth trader | Upside potential, trend alignment |
| **RISK** | Conservative risk manager | Downside risk, portfolio impact |
| **SENTIMENT** | Market sentiment analyst | News flow, social sentiment, momentum |
| **PORTFOLIO** | Portfolio construction expert | Diversification, position sizing, correlation |

### Debate Flow

```
1. TRIGGER
   └─ A trade is proposed (symbol + BUY/SELL)

2. CONTEXT ASSEMBLY
   ├─ Current signal data (direction, strength, strategy)
   ├─ Market regime (BULL/BEAR/etc.)
   ├─ Sentiment data (FinBERT scores, article count)
   ├─ Risk metrics (VaR, drawdown, leverage)
   └─ Existing positions

3. DEBATE (4 rounds, one per debater)
   ├─ Each debater gets:
   │   ├─ System prompt with their personality
   │   └─ Shared context + proposed trade details
   │
   └─ Each debater returns:
       ├─ argument: str       # Detailed reasoning
       ├─ vote: str           # FOR, AGAINST, or ABSTAIN
       └─ confidence: float   # [0.0, 1.0]

4. TALLY
   ├─ Count FOR, AGAINST, ABSTAIN votes
   ├─ consensus_score = weighted average of FOR confidences
   └─ Decision:
       ├─ APPROVED if consensus_score > 0.6 AND >= 3 FOR votes
       └─ REJECTED otherwise

5. PERSIST
   ├─ Save debate session to debate_sessions table
   ├─ Save each argument to debate arguments
   └─ Publish DEBATE_CONCLUSION

6. ACT
   └─ If APPROVED → forward to Execution Agent
```

### Approval Thresholds

- **Minimum consensus score**: 0.6 (60%)
- **Minimum FOR votes**: 3 out of 4 debaters
- Both conditions must be met for approval

### Claude Reasoner

The AI backend for debate agents. Uses Claude (or configured LLM) to generate arguments.

- **Model**: claude-sonnet-4-20250514 (configurable)
- **Retry Logic**: 3 retries with exponential backoff (1s, 2s, 4s)
- **Response Parsing**: Tries JSON first, falls back to keyword heuristics
- **Temperature**: 0.7 for creative reasoning

---

## 10. Multi-LLM Provider Layer

**Directory**: `app/llm/`

### Provider Architecture

```python
BaseLLMProvider (abstract)
├── ClaudeProvider     # Anthropic Claude API
├── OpenAIProvider     # OpenAI GPT-4o API
└── GeminiProvider     # Google Gemini API
```

### Uniform Interface

```python
class BaseLLMProvider(abc.ABC):
    provider_name: str      # "claude", "openai", "gemini"

    async def complete(
        system_prompt: str,       # System-level instructions
        messages: list[dict],     # Conversation history
        temperature: float = 0.7  # Creativity level
    ) -> str:
        """Returns the model's text response."""

    async def is_available() -> bool:
        """Checks if API key is configured and client can be created."""
```

### Provider Registry

```python
# Singleton instance
from app.llm.provider_registry import provider_registry

# Auto-register from .env config
provider_registry.auto_register_from_settings()

# Manual registration
provider_registry.register("claude", "sk-ant-...")
provider_registry.register("openai", "sk-...")
provider_registry.register("gemini", "AIza...")

# Query
available = provider_registry.list_available()  # ["claude", "openai"]
provider = provider_registry.get_provider("claude")
response = await provider.complete("You are helpful.", [{"role": "user", "content": "Hi"}])
```

### Multi-Agent Per Role

Each role can have multiple agent instances, each using a different LLM:

```python
@dataclass
class AgentInstanceConfig:
    role: str           # "risk_analyst"
    instance_id: str    # "risk-analyst-claude"
    llm_provider: str   # "claude" | "openai" | "gemini" | "" (rule-based)
    department: str     # "middle_office"
    enabled: bool       # True
```

Default configuration provides one instance per role using Claude (or rule-based for deterministic agents). Users can configure additional instances via environment variables to get diverse perspectives from multiple LLMs.

### Which Agents Use LLMs

| Agent | LLM-Powered? | Why |
|-------|:---:|-----|
| Regime Agent | No (uses HMM) | Statistical model, not language |
| Sentiment Agent | Yes (FinBERT) | Sentiment scoring (transformer model, not LLM API) |
| Strategy Agents | No | Mathematical/indicator-based |
| Execution Agent | No | Order routing logic |
| Portfolio Agent | No | Mathematical (Kelly criterion) |
| Risk Agent | No | Statistical (VaR, drawdown) |
| Compliance Agent | No | Rule-based |
| Operations Agent | No | Rule-based |
| Accounting Agent | No | Rule-based |
| IT Agent | No | System metrics |
| Quant Agent | No | Pipeline monitoring |
| CIO Agent | Yes | Natural language reasoning |
| IR Agent | Yes | Report generation |
| Debate Engine | Yes | Multi-perspective reasoning |
| CIO Chat | Yes | Natural language understanding |

---

## 11. Messaging & Communication

### Message Protocol

Every message in the system uses the `AgentMessage` format:

```python
class AgentMessage:
    message_id: str         # UUID, auto-generated
    timestamp: datetime     # UTC, auto-set
    sender_id: str          # Agent identifier ("risk-agent-1")
    receiver_id: str        # Target agent or "*" for broadcast
    channel: str            # Topic path ("horizon.risk.alert")
    message_type: MessageType  # Enum value
    payload: dict           # Flexible data dictionary
    correlation_id: str     # Optional, for request-reply patterns
```

### Message Types

**Market Data**:
- `TICK` -- Real-time price ticks
- `OHLCV` -- Candlestick data
- `FEATURE_UPDATE` -- Computed features (sentiment, technical indicators)
- `REGIME_UPDATE` -- Market regime changes

**Trading**:
- `SIGNAL` -- Trading signals from strategies
- `ORDER_NEW` -- New order request
- `ORDER_UPDATE` -- Order status change
- `ORDER_FILL` -- Order executed
- `PORTFOLIO_UPDATE` -- Portfolio state change

**Risk & Control**:
- `RISK_ALERT` -- Risk limit breach or pre-trade rejection
- `KILL_SWITCH` -- Emergency halt activation/deactivation
- `COMPLIANCE_ALERT` -- Compliance violation
- `OPERATIONS_ALERT` -- Operational issue (stuck orders)

**Debate**:
- `DEBATE_START` -- New debate initiated
- `DEBATE_ARGUMENT` -- Individual debater's argument
- `DEBATE_CONCLUSION` -- Final consensus decision

**System**:
- `HEARTBEAT` -- Agent liveness signal (every 10s)
- `AGENT_STATUS` -- Agent state change
- `FEED_STATUS` -- Data feed status
- `DEPARTMENT_STATUS` -- Department health report

**Executive**:
- `CIO_COMMAND` -- Command from CIO
- `CIO_DIRECTIVE` -- AI CIO directive (halt, resume)
- `CIO_CHAT` -- Chat message in CIO interface

**Back Office**:
- `ACCOUNTING_SNAPSHOT` -- NAV/P&L snapshot
- `IT_ALERT` -- Infrastructure warning
- `IT_STATUS` -- Infrastructure health report
- `IR_REPORT` -- Investor relations report

### Channel Naming Convention

Channels follow a hierarchical dot-notation pattern:

```
horizon.{domain}.{subdomain}
horizon.{domain}.{subdomain}.{specific}

Examples:
  horizon.system.health           # Heartbeats
  horizon.signal.AAPL.NASDAQ      # Signal for AAPL
  horizon.risk.alert              # Risk alerts
  horizon.risk.kill_switch        # Kill switch events
  horizon.execution.order.new     # New orders
  horizon.execution.order.fill    # Order fills
  horizon.regime.update           # Regime changes
  horizon.features.BTC-USD.sentiment  # Sentiment features
  horizon.portfolio.update        # Portfolio changes
  horizon.debate.{id}.conclusion  # Debate results
  horizon.cio.directive           # CIO directives
  horizon.compliance.alert        # Compliance violations
  horizon.operations.alert        # Operational alerts
  horizon.accounting.snapshot     # Accounting data
  horizon.it.status               # IT health
  horizon.ir.report               # IR reports
```

### Subscription Patterns

Agents can subscribe to specific channels or use wildcards:

```python
# Exact channel
await bus.subscribe("horizon.risk.alert", handler)

# Wildcard (glob pattern)
await bus.subscribe("horizon.signal.*", handler)        # All signals
await bus.subscribe("horizon.execution.order.*", handler)  # All order events
await bus.subscribe("horizon.*", handler)               # Everything
```

### Message Bus Implementations

**MemoryBus** (LOCAL mode):
- Uses `asyncio.Queue` for message buffering
- `fnmatch` for glob pattern matching
- Zero infrastructure, runs in-process
- Fully async, non-blocking dispatch

**AgentBus** (POSTGRES mode):
- Redis pub/sub for cross-process communication
- Native Redis pattern matching
- Requires Redis server running

Both implement the same interface:
```python
async def publish(message: AgentMessage) -> int
async def subscribe(channel: str, handler: Callable) -> None
async def unsubscribe(channel: str) -> None
async def start_listening() -> None
async def stop() -> None
```

---

## 12. Data Storage & Persistence

### Database Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `agent_states` | Agent registration & status | agent_id, agent_type, status, last_heartbeat, config, metrics |
| `agent_messages` | Message audit trail | message_id, sender_id, receiver_id, channel, message_type, payload |
| `signals` | Trading signal records | signal_id, agent_id, symbol, direction, strength, confidence, strategy_name, regime |
| `trades` | Executed trades | trade_id, symbol, side, quantity, price, status, pnl_realized |
| `portfolio_snapshots` | NAV history | total_value, cash, equity_value, crypto_value, gross_leverage, allocations |
| `risk_metrics` | Risk measurements | var_1d_95, var_1d_99, cvar_1d_95, max_drawdown, current_drawdown, kill_switch_active |
| `debate_sessions` | Debate records | symbol, signal_id, status, consensus, consensus_confidence, rounds, arguments_json |
| `regime_states` | Regime classifications | regime, confidence, method, market_scope, drift_detected, features_json |
| `performance_snapshots` | Daily performance | daily_return, cumulative_return, sharpe_ratio, max_drawdown, win_rate |
| `narratives` | News/sentiment data | title, sentiment_score, source, symbols_json, lifecycle_stage, engagement_score |

### Data Path

- **LOCAL mode**: `~/.horizon-capital/horizon.db` (SQLite)
- **Override**: Set `HORIZON_DATA_DIR` environment variable
- **POSTGRES mode**: Connection string from config

### Persistence Pattern

Every `emit()` call does TWO things:
1. Publishes to the message bus (real-time)
2. Persists to the `agent_messages` table (audit trail)

This ensures complete traceability and enables replay/recovery.

---

## 13. Terminal UI & Commands

### Dashboard Layout

```
┌──────────────────────────────────────────────────────────────┐
│ HORIZON CAPITAL v0.2.0 | Mode: PAPER | CIO: HUMAN | ...     │  ← Header (3 lines)
├────────────────────────────┬─────────────────────────────────┤
│ Agents (by department)     │ Market Regimes                  │  ← Body
│ ┌─────────────────────┐   │   INDIA   NEUTRAL  conf=50.0%   │
│ │ Front Office        │   │   US      BULL     conf=72.3%   │
│ │   regime-agent-1  ● │   │   CRYPTO  HIGH_VOL conf=61.1%   │
│ │   sentiment-agt   ● │   ├─────────────────────────────────┤
│ │   ensemble-sel    ● │   │ Risk Metrics                    │
│ │   execution-agt   ● │   │   VaR (95%):    0.0234          │
│ │   portfolio-agt   ● │   │   VaR (99%):    0.0412          │
│ │ Middle Office       │   │   Max Drawdown: 3.21%           │
│ │   risk-agent-1    ● │   │   Curr Drawdown: 1.05%          │
│ │   compliance-agt  ● │   │   Kill Switch:  OFF             │
│ │   operations-agt  ● │   ├─────────────────────────────────┤
│ │ Back Office         │   │ Debates                         │
│ │   accounting-agt  ● │   │   AAPL  BUY   conf=78% rds=4   │
│ │   it-agent-1      ● │   │   TSLA  SELL  conf=62% rds=4   │
│ │   quant-agent-1   ● │   │                                 │
│ │ Executive           │   │                                 │
│ │   (Human CIO)       │   │                                 │
│ ├─────────────────────┤   │                                 │
│ │ Recent Signals      │   │                                 │
│ │ Time  Symbol Dir Str│   │                                 │
│ │ 14:23 AAPL  BUY 0.75│  │                                 │
│ │ 14:21 TSLA SELL 0.62│  │                                 │
│ └─────────────────────┘   │                                 │
├──────────────────────────────────────────────────────────────┤
│ Log (last 12 lines)                                          │  ← Logs (14 lines)
│ 2026-03-14T14:23:01 regime_change scope=US new=BULL          │
│ 2026-03-14T14:23:05 signal_generated symbol=AAPL dir=BUY    │
└──────────────────────────────────────────────────────────────┘
```

### Department Colors in Dashboard

| Department | Color |
|-----------|-------|
| Front Office | Bright Blue |
| Middle Office | Bright Yellow |
| Back Office | Bright Magenta |
| Executive | Bright Red |

### REPL Commands

```
horizon> help

  status         Show all agent statuses (grouped by department)
  signals        Show recent trading signals
  risk           Show current risk metrics
  regime         Show market regime per scope
  debate         Show recent debate summaries
  portfolio      Show current portfolio
  departments    Show department-level overview
  cio            Enter CIO chat mode (natural language)
  agents config  Show agent-per-role configuration
  mode <MODE>    Switch system mode
  kill-switch    Toggle kill switch
  symbols        Show trading universe
  config         Show current configuration
  help           Show this help
  quit / exit    Shutdown Horizon Capital
```

### Example Command Output

```
horizon> departments

Department Overview:
  Front Office (Investment & Revenue)     6/6 agents  HEALTHY
  Middle Office (Risk & Control)          3/3 agents  HEALTHY
  Back Office (Support & Finance)         3/3 agents  HEALTHY
  Executive (Management)                  0/0 agents  HEALTHY

horizon> config

Configuration:
  Mode:            PAPER_TRADING
  CIO Mode:        HUMAN
  Storage:         LOCAL
  Max Drawdown:    10.0%
  Max Position:    5.0%
  Max Leverage:    1.0x
  VaR Limit:       3.0%
  LLM Providers:   claude
  Anthropic Key:   ***-abc1
  OpenAI Key:      NOT SET
  Google Key:      NOT SET
  Symbols:         12 total
```

---

## 14. CIO Dual Mode

The CIO (Chief Investment Officer) interface supports two modes:

### Human CIO Mode (Default)

The user acts as CIO through an interactive natural language chat interface.

**Entering CIO Chat**:
```
horizon> cio

CIO Chat Mode
Type your questions in natural language. Type 'exit' to return.

cio> How are we doing today?

System Status: 12/12 agents running
  regime-agent-1:    RUNNING (front_office)
  risk-agent-1:      RUNNING (middle_office)
  ...

cio> What does risk say about our exposure?

Risk Metrics:
  VaR (95%):     0.0234
  VaR (99%):     0.0412
  Max Drawdown:  3.21%
  Curr Drawdown: 1.05%
  Kill Switch:   OFF

cio> exit
Returned to command mode.
```

**How CIO Chat Works**:

1. User types a natural language question
2. System checks if an LLM provider is available
3. If LLM available:
   - Gathers system context (departments, risk, portfolio)
   - Sends to LLM with a CIO-assistant system prompt
   - Returns natural language response
4. If no LLM:
   - Falls back to keyword matching
   - Maps keywords to system queries
   - Returns formatted data

### AI CIO Mode (Opt-in)

Enable with `--cio-mode AI` or `CIO_MODE=AI` in `.env`.

The AI CIO agent runs autonomously:
- Monitors all departments every 60 seconds
- Aggregates alerts from risk, compliance, IT
- Issues directives when critical conditions detected:
  - `HALT_TRADING` -- 5+ critical alerts in recent window
  - `EMERGENCY_HALT` -- Kill switch triggered

---

## 15. Risk Management Deep Dive

### Defense Layers

Horizon Capital implements defense-in-depth with multiple risk layers:

```
Layer 1: Pre-Trade Validation (Risk Agent)
├─ Position size limit (max 5% of portfolio per symbol)
├─ Leverage ceiling (max 1.0x gross leverage)
├─ Correlation guard (no concentrated same-direction bets)
└─ Kill switch check (reject all if active)

Layer 2: Debate Engine
├─ 4 specialist debaters evaluate the trade
├─ Requires 60%+ consensus AND 3/4 FOR votes
└─ Risk debater specifically focuses on downside

Layer 3: Continuous Monitoring (Risk Agent)
├─ VaR (95%, 99%) recomputed every 30 seconds
├─ Drawdown tracking (max and current)
├─ Automatic kill switch if thresholds breached
└─ Post-trade risk re-evaluation on every fill

Layer 4: Kill Switch
├─ Automatic activation on threshold breach
├─ Overrides system to PAPER_TRADING
├─ Broadcasts to all agents immediately
└─ Requires manual deactivation by CIO

Layer 5: Compliance
├─ Restricted symbol enforcement
├─ Position limit compliance sweeps
└─ Periodic audit checks

Layer 6: Operations
├─ Stuck order detection (>5 min pending)
└─ Reconciliation monitoring

Layer 7: CIO Oversight
├─ Human mode: CIO reviews all activity
└─ AI mode: Autonomous halt on critical alerts
```

### VaR Calculation

The system uses **Historical VaR** (non-parametric):

```python
def compute_var(returns, confidence=0.95):
    """Historical Value at Risk.

    VaR at 95% = the loss that is exceeded only 5% of the time.
    """
    if len(returns) == 0:
        return 0.0
    percentile = (1 - confidence) * 100  # e.g., 5.0 for 95%
    return -np.percentile(returns, percentile)

def compute_cvar(returns, confidence=0.95):
    """Conditional VaR (Expected Shortfall).

    Average loss in the worst (1-confidence)% of cases.
    """
    var = compute_var(returns, confidence)
    tail = returns[returns <= -var]
    return -np.mean(tail) if len(tail) > 0 else var
```

### Drawdown Calculation

```python
def compute_max_drawdown(equity_curve):
    """Maximum peak-to-trough decline as a fraction."""
    peak = np.maximum.accumulate(equity_curve)
    drawdown = (peak - equity_curve) / peak
    return np.max(drawdown)

def compute_current_drawdown(equity_curve):
    """Current distance from the all-time high."""
    peak = np.max(equity_curve)
    current = equity_curve[-1]
    return (peak - current) / peak
```

---

## 16. Trading Execution Pipeline

### Complete Order Lifecycle

```
                    Signal Generated
                          │
                    ┌─────▼─────┐
                    │ Pre-Trade  │──── REJECT ──→ RISK_ALERT published
                    │ Validation │
                    └─────┬─────┘
                          │ PASS
                    ┌─────▼─────┐
                    │  Debate    │──── REJECT ──→ DEBATE_CONCLUSION (REJECTED)
                    │  Engine    │
                    └─────┬─────┘
                          │ APPROVED
                    ┌─────▼─────┐
                    │ Position   │
                    │  Sizing    │──→ Kelly fraction → quantity
                    └─────┬─────┘
                          │
                    ┌─────▼─────┐
                    │  Execution │
                    │   Agent    │
                    └─────┬─────┘
                          │
              ┌───────────┼───────────┐
              │           │           │
        ┌─────▼─────┐ ┌──▼──┐ ┌─────▼─────┐
        │   Paper   │ │Queue│ │   Real    │
        │  Broker   │ │(CIO)│ │  Broker   │
        └─────┬─────┘ └──┬──┘ └─────┬─────┘
              │           │           │
              └───────────┼───────────┘
                          │
                    ┌─────▼─────┐
                    │  ORDER    │
                    │  FILLED   │
                    └─────┬─────┘
                          │
              ┌───────────┼───────────┐
              │           │           │
        ┌─────▼─────┐ ┌──▼──────┐ ┌──▼──────────┐
        │ Position  │ │ Risk    │ │ Operations  │
        │ Update    │ │ Re-eval │ │ Tracking    │
        └───────────┘ └─────────┘ └─────────────┘
```

---

## 17. Data Flow & Signal Lifecycle

### End-to-End Example: AAPL Buy Signal

```
Step 1: REGIME DETECTION
  RegimeAgent evaluates US market
  └─ HMM predicts BULL regime (confidence 72%)
  └─ Publishes REGIME_UPDATE on horizon.regime.update

Step 2: SENTIMENT ANALYSIS
  SentimentAgent processes AAPL news
  ├─ NewsAPI: 15 articles, avg sentiment +0.18
  ├─ Reddit: 42 posts, avg sentiment +0.22
  ├─ FinBERT scores: 70% bullish, 15% neutral, 15% bearish
  └─ Publishes FEATURE_UPDATE on horizon.features.AAPL.NASDAQ.sentiment

Step 3: SIGNAL GENERATION
  EnsembleSelector gets active strategies for BULL regime
  └─ MomentumStrategy generates:
     Signal(AAPL.NASDAQ, BUY, strength=0.75, strategy="momentum", regime="BULL")

Step 4: PRE-TRADE VALIDATION
  RiskAgent checks signal:
  ├─ Position limit: AAPL weight 0% < 5% limit ✓
  ├─ Leverage: 0.3x < 1.0x limit ✓
  ├─ Correlation: no existing position ✓
  └─ Kill switch: OFF ✓
  Result: APPROVED

Step 5: DEBATE
  DebateEngine initiates 4-way debate:
  ├─ STRATEGY: FOR (conf=0.82) "Strong momentum, RSI breakout"
  ├─ RISK:     FOR (conf=0.65) "Acceptable risk, good R:R ratio"
  ├─ SENTIMENT: FOR (conf=0.78) "Bullish news flow, positive Reddit"
  └─ PORTFOLIO: FOR (conf=0.71) "Good diversification benefit"
  Consensus: 0.74 (>0.6), 4 FOR votes (>=3)
  Result: APPROVED

Step 6: POSITION SIZING
  PortfolioAgent computes:
  ├─ NAV = $1,000,000
  ├─ win_rate = clamp(0.75, 0.51, 0.85) = 0.75
  ├─ kelly_f = 0.167
  ├─ position_value = 0.167 * $1M * 5% = $8,350
  ├─ AAPL price = $175
  └─ quantity = floor($8,350 / $175) = 47 shares
  Publishes ORDER_NEW

Step 7: EXECUTION
  ExecutionAgent (PAPER_TRADING mode):
  ├─ Routes to PaperBroker
  ├─ Simulated fill: 47 shares @ $175.12 (0.07% slippage)
  └─ Publishes ORDER_FILL

Step 8: POST-TRADE
  ├─ PortfolioAgent updates positions, recalculates NAV
  ├─ RiskAgent recomputes VaR, drawdown
  ├─ AccountingAgent records snapshot
  └─ Dashboard updates in real-time
```

---

## 18. Configuration Reference

### Environment Variables (.env)

```bash
# ─── Application ──────────────────────────────────────────
APP_ENV=development              # development | production
APP_SECRET_KEY=changeme          # Random 32-byte hex
APP_DEBUG=true                   # Enable debug logging
APP_HOST=0.0.0.0                 # API host (if web mode)
APP_PORT=8000                    # API port (if web mode)

# ─── System Modes ─────────────────────────────────────────
SYSTEM_MODE=PAPER_TRADING        # PAPER_TRADING | HUMAN_APPROVAL | FULLY_AUTONOMOUS
STORAGE_BACKEND=LOCAL            # LOCAL (SQLite) | POSTGRES
CIO_MODE=HUMAN                   # HUMAN (interactive) | AI (autonomous)

# ─── Database (POSTGRES mode only) ────────────────────────
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=horizon
POSTGRES_USER=horizon
POSTGRES_PASSWORD=changeme

# ─── Redis (POSTGRES mode only) ──────────────────────────
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

# ─── LLM Providers (user-provided API keys) ──────────────
ANTHROPIC_API_KEY=sk-ant-...     # Anthropic Claude
OPENAI_API_KEY=sk-...            # OpenAI GPT-4
GOOGLE_API_KEY=AIza...           # Google Gemini

# ─── Brokers ──────────────────────────────────────────────
ZERODHA_API_KEY=                 # Zerodha Kite (India)
ZERODHA_API_SECRET=
ZERODHA_ACCESS_TOKEN=
ZERODHA_MOCK_MODE=true           # Use mock broker

ALPACA_API_KEY=                  # Alpaca (US)
ALPACA_API_SECRET=
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_PAPER_MODE=true

# ─── Data Providers ──────────────────────────────────────
POLYGON_API_KEY=                 # Market data
NEWSAPI_API_KEY=                 # News articles

# ─── Social ──────────────────────────────────────────────
REDDIT_CLIENT_ID=                # Reddit API
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=horizon-capital:v1.0

# ─── Risk Parameters ─────────────────────────────────────
RISK_MAX_DRAWDOWN_PCT=10.0       # Kill switch trigger: max drawdown %
RISK_MAX_POSITION_PCT=5.0        # Max portfolio % per position
RISK_MAX_LEVERAGE=1.0            # Max gross leverage multiplier
RISK_VAR_LIMIT_PCT=3.0           # Max VaR (95%) percentage

# ─── Trading Universe ────────────────────────────────────
INDIA_SYMBOLS=RELIANCE.NSE,TCS.NSE,INFY.NSE,HDFCBANK.NSE,ICICIBANK.NSE
US_SYMBOLS=AAPL.NASDAQ,MSFT.NASDAQ,GOOGL.NASDAQ,AMZN.NASDAQ,TSLA.NASDAQ
CRYPTO_SYMBOLS=BTC-USD,ETH-USD

# ─── Alerts (optional) ───────────────────────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ALERT_EMAIL_SMTP_HOST=
ALERT_EMAIL_SMTP_PORT=587
ALERT_EMAIL_FROM=
ALERT_EMAIL_TO=
ALERT_EMAIL_PASSWORD=

# ─── JWT (if web API enabled) ────────────────────────────
JWT_SECRET_KEY=changeme
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# ─── CIO Credentials ─────────────────────────────────────
CIO_DEFAULT_USERNAME=admin
CIO_DEFAULT_PASSWORD=changeme
```

### Risk Parameter Defaults

| Parameter | Default | Description |
|-----------|---------|-------------|
| `risk_max_drawdown_pct` | 10.0% | Max portfolio drawdown before kill switch |
| `risk_max_position_pct` | 5.0% | Max portfolio weight for any single position |
| `risk_max_leverage` | 1.0x | Max gross leverage (long + short / NAV) |
| `risk_var_limit_pct` | 3.0% | Max VaR (95%) before kill switch |

---

## 19. CLI Reference

### Starting the System

```bash
# Navigate to the backend directory
cd horizon-capital/backend

# Default: Run with TUI (PAPER_TRADING, LOCAL storage, HUMAN CIO)
python -m app

# Run headless (log output only, no TUI)
python -m app --headless

# Override system mode
python -m app --mode FULLY_AUTONOMOUS

# Override storage backend
python -m app --storage POSTGRES

# Override CIO mode
python -m app --cio-mode AI

# Show configuration
python -m app config

# Show version
python -m app version
```

### Terminal REPL Commands

| Command | Description |
|---------|-------------|
| `help` | Show all commands |
| `status` | Agent statuses grouped by department |
| `signals` | Last 10 trading signals |
| `risk` | VaR, drawdown, kill switch status |
| `regime` | Market regime per scope (India, US, Crypto) |
| `debate` | Last 5 debate summaries |
| `portfolio` | NAV, cash, position count |
| `departments` | Department health overview |
| `cio` | Enter natural language CIO chat mode |
| `agents config` | Show agent-per-role LLM configuration |
| `mode <MODE>` | Switch system mode at runtime |
| `kill-switch` | Toggle kill switch |
| `symbols` | Show trading universe |
| `config` | Show full configuration |
| `quit` / `exit` | Graceful shutdown |

---

## 20. Testing

### Running Tests

```bash
cd horizon-capital/backend
python -m pytest tests/test_smoke.py -v
```

### Test Coverage

The smoke test suite validates 50+ test cases:

- **TestConfig** -- Settings loading, defaults, new fields (CIO mode, LLM keys)
- **TestLocalStorage** -- SQLite table creation, CRUD operations
- **TestMemoryBus** -- Publish/subscribe, wildcard patterns
- **TestKVStore** -- In-memory key-value operations
- **TestVaRCalculator** -- VaR computation (empty, normal, drawdown)
- **TestMessaging** -- Serialization, deserialization, all MessageTypes
- **TestDepartments** -- Department enum values, manager imports
- **TestLLMProviderRegistry** -- Empty registry, key validation, agent configs
- **TestNewAgentImports** -- All 7 new agents importable
- **TestDepartmentManagers** -- All 4 managers importable
- **TestMovedAgentImports** -- Existing agents work from new locations
- **TestEnsembleSelector** -- Strategy creation, regime activation
- **TestRuntime** -- Full startup/shutdown cycle
- **TestTerminalCommands** -- All REPL commands
- **TestCIOChat** -- Keyword-based responses

---

## 21. Dependencies

### Core Runtime
- `pydantic` + `pydantic-settings` -- Configuration, data validation
- `sqlalchemy[asyncio]` + `aiosqlite` -- Database ORM (async)
- `rich` -- Terminal UI (dashboard, tables, panels)
- `structlog` -- Structured JSON logging
- `orjson` -- Fast JSON serialization

### Data & Analysis
- `numpy`, `pandas` -- Numerical computation
- `ta` -- Technical analysis (pure Python, replaces ta-lib)
- `yfinance` -- Market data fetching

### Machine Learning
- `hmmlearn` -- Hidden Markov Models (regime detection)
- `scikit-learn` -- ML utilities
- `transformers` + `torch` -- FinBERT sentiment scoring
- `arch` -- ARCH/GARCH volatility models

### LLM Providers
- `anthropic` -- Claude API
- `openai` -- GPT-4 API (optional)
- `google-generativeai` -- Gemini API (optional)

### Brokers
- `alpaca-py` -- Alpaca trading API (US equities)

### Social Data
- `praw` -- Reddit API client

### HTTP
- `httpx` -- Async HTTP client
- `websockets` -- WebSocket support

### Production Only (POSTGRES mode)
- `asyncpg` -- PostgreSQL async driver
- `redis[hiredis]` -- Redis client

### Development
- `pytest` + `pytest-asyncio` + `pytest-cov` -- Testing
- `ruff` -- Linting + formatting
- `mypy` -- Type checking

---

## 22. Glossary

| Term | Definition |
|------|-----------|
| **Agent** | An autonomous asyncio task with its own lifecycle, heartbeat, and message handling |
| **Bus** | The message bus (MemoryBus or AgentBus) that routes messages between agents |
| **Channel** | A topic path for message routing (e.g., `horizon.risk.alert`) |
| **CIO** | Chief Investment Officer -- the human (or AI) in charge of the system |
| **CVaR** | Conditional Value at Risk -- expected loss beyond VaR threshold |
| **Debate** | Multi-agent consensus process with 4 specialist AI debaters |
| **Department** | Organizational grouping of agents (Front Office, Middle Office, etc.) |
| **Drawdown** | Peak-to-trough decline in portfolio value |
| **Ensemble** | Collection of multiple strategies that vote on trades |
| **FinBERT** | Financial BERT model for sentiment analysis of financial text |
| **HMM** | Hidden Markov Model -- statistical model for regime classification |
| **Kelly Criterion** | Optimal position sizing formula based on win rate and payoff ratio |
| **Kill Switch** | Emergency circuit breaker that halts all real trading |
| **NAV** | Net Asset Value -- total portfolio value |
| **Regime** | Market state classification (Bull, Bear, Neutral, Crisis, High Vol) |
| **REPL** | Read-Eval-Print Loop -- the interactive command interface |
| **Signal** | A trading recommendation with symbol, direction, and strength |
| **Slot** | Orchestrator's bookkeeping record for each agent (task, retries, status) |
| **TUI** | Terminal User Interface -- Rich-based dashboard |
| **VaR** | Value at Risk -- maximum expected loss at a given confidence level |

---

## Directory Structure

```
horizon-capital/backend/
├── app/
│   ├── __init__.py
│   ├── __main__.py                          # CLI entry point
│   ├── config.py                            # Settings (pydantic-settings)
│   ├── main.py                              # FastAPI entry (web mode)
│   ├── dependencies.py                      # DI container
│   │
│   ├── agents/
│   │   ├── __init__.py                      # Re-exports
│   │   ├── base_agent.py                    # Abstract base agent
│   │   ├── agent_bus.py                     # Bus re-export
│   │   ├── agent_registry.py               # Agent CRUD
│   │   ├── departments.py                   # DepartmentType enum
│   │   ├── department_manager.py            # Base department manager
│   │   │
│   │   ├── front_office/                    # Investment & Revenue
│   │   │   ├── manager.py                   # FrontOfficeManager
│   │   │   ├── research/                    # RegimeAgent + SentimentAgent
│   │   │   ├── strategy/                    # EnsembleSelector + 4 strategies
│   │   │   ├── trading/                     # ExecutionAgent + brokers
│   │   │   ├── portfolio/                   # PortfolioAgent + optimizer
│   │   │   └── investor_relations/          # IRAgent
│   │   │
│   │   ├── middle_office/                   # Risk & Control
│   │   │   ├── manager.py                   # MiddleOfficeManager
│   │   │   ├── risk/                        # RiskAgent + VaR + KillSwitch
│   │   │   ├── compliance/                  # ComplianceAgent
│   │   │   └── operations/                  # OperationsAgent
│   │   │
│   │   ├── back_office/                     # Support & Finance
│   │   │   ├── manager.py                   # BackOfficeManager
│   │   │   ├── accounting/                  # AccountingAgent
│   │   │   ├── it/                          # ITAgent
│   │   │   └── quant/                       # QuantAgent
│   │   │
│   │   ├── executive/                       # Management
│   │   │   ├── manager.py                   # ExecutiveManager
│   │   │   └── cio/                         # CIOAgent + HumanCIO
│   │   │
│   │   └── debate/                          # Shared: debate engine
│   │       ├── debate_engine.py
│   │       └── claude_reasoner.py
│   │
│   ├── llm/                                 # Multi-LLM provider layer
│   │   ├── base_provider.py                 # Abstract provider
│   │   ├── claude_provider.py               # Anthropic Claude
│   │   ├── openai_provider.py               # OpenAI GPT-4
│   │   ├── gemini_provider.py               # Google Gemini
│   │   ├── provider_registry.py             # Registry + factory
│   │   └── agent_config.py                  # Per-agent LLM config
│   │
│   ├── core/                                # Infrastructure
│   │   ├── runtime.py                       # Bootstrap + lifecycle
│   │   ├── messaging.py                     # AgentMessage + AgentBus
│   │   ├── memory_bus.py                    # In-memory pub/sub
│   │   ├── local_storage.py                 # SQLite setup
│   │   ├── database.py                      # PostgreSQL setup
│   │   ├── kv_store.py                      # In-memory KV store
│   │   ├── redis_client.py                  # Redis client
│   │   ├── logging.py                       # Structured logging
│   │   ├── security.py                      # Auth utilities
│   │   └── exceptions.py                    # Custom exceptions
│   │
│   ├── tui/                                 # Terminal interface
│   │   ├── dashboard.py                     # Rich live dashboard
│   │   ├── commands.py                      # REPL command handler
│   │   └── cio_chat.py                      # CIO chat interface
│   │
│   ├── workers/                             # Orchestration
│   │   ├── agent_orchestrator.py            # Central controller
│   │   ├── data_ingestion_worker.py         # Data feed worker
│   │   ├── feature_computation_worker.py    # Feature pipeline
│   │   └── performance_worker.py            # Performance tracking
│   │
│   ├── services/                            # Business logic
│   ├── data_layer/                          # Data access
│   ├── features/                            # Feature engineering
│   ├── models/                              # SQLAlchemy models
│   ├── schemas/                             # Pydantic schemas
│   ├── api/                                 # REST API (optional)
│   ├── backtesting/                         # Backtesting engine
│   └── monitoring/                          # Monitoring utilities
│
├── tests/
│   └── test_smoke.py                        # 51 smoke tests
│
├── pyproject.toml                           # Project config
├── requirements.txt                         # Dependencies
└── .env                                     # Configuration (user-provided)
```

---

*Horizon Capital v0.2.0 -- Built with Python, Rich, and multi-agent AI.*
