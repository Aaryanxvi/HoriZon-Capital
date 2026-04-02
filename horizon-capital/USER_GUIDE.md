# Horizon Capital — User Guide

**Version 0.2.0 | March 2025**

Horizon Capital is an autonomous AI hedge fund platform that runs entirely in your terminal. It employs a multi-agent architecture -- strategy analysts, risk managers, compliance officers, and an AI CIO -- debating and collaborating to generate, validate, and execute trading signals across Indian, US, and crypto markets. This guide walks you through every feature, from first launch to advanced CIO governance.

---

## 1. User Personas

Horizon Capital serves different roles. Find yours below to understand which commands and workflows matter most to you.

### Paper Trader

**Who you are:** You are learning the platform, testing strategies, or evaluating Horizon Capital before committing real capital. Everything runs in simulation -- no broker connections needed.

**Your daily workflow:**

1. Launch the platform: `python -m app`
2. Check agent status: `status`
3. Watch incoming signals: `signals`
4. Review portfolio NAV: `portfolio`
5. Monitor data feeds: `data`
6. Explore the agent office: `office`

**Key commands:** `status`, `signals`, `portfolio`, `data`, `symbols`, `office`

### Quantitative Analyst

**Who you are:** You focus on backtesting strategies, tuning models, and analyzing performance attribution. You want to know which strategies are generating alpha and why.

**Your daily workflow:**

1. Run backtests on target symbols: `backtest AAPL.NASDAQ --days 90`
2. Compare strategy results: `backtest results`
3. Review model registry: `models`
4. Check Thompson Sampling rotation: `model stats`
5. Analyze performance metrics: `performance 30d`
6. Drill into attribution: `attribution AAPL.NASDAQ`

**Key commands:** `backtest`, `performance`, `models`, `model stats`, `attribution`, `backtest results`

### Risk Manager

**Who you are:** You monitor Value-at-Risk, run stress tests against historical crises, and have the authority to halt trading via the kill switch.

**Your daily workflow:**

1. Check risk dashboard: `risk`
2. Review market regime: `regime`
3. Run stress tests: `stress-test`
4. Monitor alerts: `alerts`
5. Review alert rules: `alert rules`
6. Emergency halt if needed: `kill-switch`

**Key commands:** `risk`, `stress-test`, `kill-switch`, `alerts`, `alert rules`, `regime`

### CIO (Human Mode)

**Who you are:** You are the Chief Investment Officer operating in HUMAN mode. You approve or reject agent recommendations, override regime classifications, and adjust risk tolerance in real time.

**Your daily workflow:**

1. Review agent debates: `debate`
2. Enter CIO chat for natural language control: `cio`
3. Override market regime if needed: `override regime INDIA BULL`
4. Adjust risk tolerance: `risk-tolerance 5.0`
5. Interrupt misbehaving agents: `interrupt <agent_id>`
6. Generate daily report: `report daily`

**Key commands:** `cio`, `override regime`, `risk-tolerance`, `interrupt`, `debate`, `toggle sentiment`

### Fund Manager (AI Mode)

**Who you are:** You have set CIO_MODE=AI and the system runs fully autonomously. You monitor performance and generate reports but do not intervene in trading decisions.

**Your daily workflow:**

1. Check system health: `health`
2. Review overall status: `status`
3. Monitor performance: `performance YTD`
4. Generate reports: `report weekly`
5. Export for stakeholders: `report export csv`

**Key commands:** `status`, `performance`, `report`, `health`, `workers`

---

## 2. Getting Started

### Prerequisites

- Python 3.11 or newer (tested up to Python 3.14)
- pip (Python package manager)
- 4 GB RAM minimum (8 GB recommended)
- Internet connection for market data feeds

### Installation

```bash
# Clone or download the repository
cd horizon-capital/backend

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate    # Linux/macOS
.venv\Scripts\activate       # Windows

# Install dependencies
pip install -e .
```

### First Launch

```bash
python -m app
```

On first run, the onboarding wizard will guide you through initial setup.

### Onboarding Wizard

The wizard presents two paths:

**Quick Start (recommended for beginners)**

- Sets PAPER_TRADING mode
- Uses LOCAL storage (SQLite, no Docker needed)
- Configures default trading universe (NIFTY 50, S&P 500, top crypto)
- Skips API key configuration (uses free Yahoo Finance data)
- You can start exploring immediately

**Advanced Setup**

- Choose your system mode (Paper Trading / Human Approval / Fully Autonomous)
- Configure LLM API keys (Claude, GPT, Gemini)
- Set up broker connections (Alpaca, Zerodha)
- Customize trading universe
- Configure alert channels (Telegram, email)
- Set risk parameters

You can re-run the wizard at any time with `setup` from the REPL or `python -m app --setup` from the command line.

---

## 3. Platform Modes

### Trading Modes

| Mode | Description | Who Decides |
|------|-------------|-------------|
| **PAPER_TRADING** | Simulated trades, no real money | Agents auto-execute (paper) |
| **HUMAN_APPROVAL** | Agents propose, human approves | CIO (you) approves each trade |
| **FULLY_AUTONOMOUS** | Agents trade without approval | AI CIO governs |

Switch modes at runtime:

```
mode PAPER_TRADING
mode HUMAN_APPROVAL
mode FULLY_AUTONOMOUS
```

### CIO Mode

| Mode | Behavior |
|------|----------|
| **HUMAN** | You act as CIO -- approve trades, override regimes, adjust risk |
| **AI** | AI CIO agent makes all governance decisions autonomously |

Set via environment variable `CIO_MODE=HUMAN` or `CIO_MODE=AI` in your `.env` file.

### Storage Backends

| Backend | Database | Message Bus | Requirements |
|---------|----------|-------------|-------------|
| **LOCAL** (default) | SQLite | In-memory bus | Nothing -- works out of the box |
| **POSTGRES** | PostgreSQL | Redis pub/sub | Docker or managed services |

LOCAL mode is recommended for individual use. POSTGRES mode is for multi-instance deployments.

---

## 4. Step-by-Step Workflows

### Workflow 1: First Launch and Paper Trading

**Goal:** Get the platform running and see agents in action.

```
Step 1:  python -m app
         -> Onboarding wizard runs (choose Quick Start)

Step 2:  status
         -> See all agents grouped by department:
            Front Office:  Strategy, Regime, Sentiment agents
            Middle Office: Risk, Compliance, VaR agents
            Back Office:   Operations, Accounting, IT agents
            Executive:     CIO agent

Step 3:  data
         -> See live market data, OHLCV counts, feed health

Step 4:  signals
         -> Watch trading signals as agents generate them

Step 5:  portfolio
         -> Check NAV, cash balance, and positions

Step 6:  office
         -> Watch the animated ASCII art agent office
```

### Workflow 2: Monitoring Market Data

**Goal:** Understand what data the platform is ingesting.

```
Step 1:  symbols
         -> View trading universe:
            India:  RELIANCE.NSE, TCS.NSE, INFY.NSE, ...
            US:     AAPL.NASDAQ, MSFT.NASDAQ, GOOGL.NASDAQ, ...
            Crypto: BTC-USD, ETH-USD, SOL-USD, ...

Step 2:  data
         -> View latest prices, OHLCV bar counts,
            feature cache status, forex rates (INR/USD),
            feed health, circuit breaker states

Step 3:  workers
         -> Check background worker status:
            Data Ingestion:        polling Yahoo/CoinGecko/Forex
            Feature Computation:   23 technical indicators
            Performance Analytics: Sharpe, alpha calculations
```

### Workflow 3: Analyzing Signals and Debates

**Goal:** Understand why agents are recommending specific trades.

```
Step 1:  signals
         -> See recent signals with direction (BUY/SELL/HOLD)
            and strength (0.0 to 1.0)

Step 2:  debate
         -> Read agent debate summaries:
            Strategy Agent argues for momentum entry
            Risk Agent raises VaR concerns
            Compliance Agent checks position limits
            CIO Agent makes final decision

Step 3:  regime
         -> See market regime per scope:
            INDIA:  BULL (confidence: 0.82)
            US:     NEUTRAL (confidence: 0.65)
            CRYPTO: HIGH_VOL (confidence: 0.91)
```

### Workflow 4: Running a Backtest

**Goal:** Test a strategy on historical data.

```
Step 1:  backtest AAPL.NASDAQ --days 90
         -> Runs walk-forward backtest on AAPL with 90 days of data
            Tests all strategies: momentum, mean_reversion,
            volatility, crisis

Step 2:  backtest AAPL.NASDAQ --days 252 --strategy momentum
         -> Run a specific strategy over 1 year

Step 3:  backtest results
         -> View comprehensive results:
            Total Return, Sharpe Ratio, Max Drawdown,
            Win Rate, Profit Factor, Calmar Ratio
```

### Workflow 5: Managing Risk

**Goal:** Monitor and control portfolio risk.

```
Step 1:  risk
         -> View risk dashboard:
            VaR 95%:        -2.3%
            VaR 99%:        -3.8%
            Max Drawdown:   -5.1%
            Current DD:     -1.2%
            Kill Switch:    INACTIVE

Step 2:  stress-test
         -> Run all historical scenarios:
            GFC_2008, COVID_2020, TAPER_TANTRUM_2013,
            FLASH_CRASH_2010, CRYPTO_WINTER_2022

Step 3:  stress-test COVID_2020
         -> Detailed impact analysis for a specific scenario

Step 4:  risk-tolerance 3.0
         -> Tighten max drawdown to 3% (range: 1.0-50.0%)

Step 5:  kill-switch
         -> ACTIVATE to halt all trading immediately
         -> DEACTIVATE to resume trading
```

### Workflow 6: Generating Reports

**Goal:** Create portfolio reports for review or export.

```
Step 1:  report daily
         -> Generate daily portfolio report:
            P&L summary, top winners/losers,
            risk metrics, signal summary

Step 2:  report weekly
         -> Weekly aggregate report

Step 3:  report monthly
         -> Monthly performance review

Step 4:  report export csv
         -> Export last report as CSV file

Step 5:  report export json
         -> Export last report as JSON
```

### Workflow 7: Using CIO Chat Mode

**Goal:** Interact with the system using natural language.

```
Step 1:  cio
         -> Enter CIO chat mode

Step 2:  Type natural language queries:
         "What is our current risk exposure?"
         "Why did the strategy agent recommend buying AAPL?"
         "Show me the top performing strategies this month"
         "Reduce exposure to crypto markets"

Step 3:  Type 'exit' to leave CIO chat mode
```

---

## 5. Command Reference

### System Commands

| Command | Description | Example |
|---------|-------------|---------|
| `help` | Show all available commands | `help` |
| `status` | Show all agent statuses by department | `status` |
| `departments` | Department-level overview | `departments` |
| `workers` | Background worker status | `workers` |
| `config` | Show current configuration | `config` |
| `setup` | Re-run onboarding wizard | `setup` |
| `office` | Show animated agent office (ASCII art) | `office` |
| `quit` / `exit` | Shutdown Horizon Capital | `quit` |

### Portfolio and Trading

| Command | Description | Example |
|---------|-------------|---------|
| `portfolio` | Current portfolio (NAV, cash, positions) | `portfolio` |
| `signals` | Recent trading signals | `signals` |
| `exposures` | Current exposures by symbol | `exposures` |
| `symbols` | Trading universe (India, US, Crypto) | `symbols` |
| `data` | Live market data and feed health | `data` |

### Risk Management

| Command | Description | Example |
|---------|-------------|---------|
| `risk` | Risk dashboard (VaR, drawdown, kill switch) | `risk` |
| `regime` | Market regime per scope with confidence | `regime` |
| `stress-test` | Run all crisis scenarios | `stress-test` |
| `stress-test <SCENARIO>` | Run specific scenario | `stress-test COVID_2020` |
| `kill-switch` | Toggle emergency trading halt | `kill-switch` |
| `risk-tolerance <N>` | Set max drawdown % (1.0-50.0) | `risk-tolerance 5.0` |

### Strategy and Analysis

| Command | Description | Example |
|---------|-------------|---------|
| `backtest <SYMBOL>` | Run walk-forward backtest | `backtest AAPL.NASDAQ --days 90` |
| `backtest results` | Show last backtest results | `backtest results` |
| `debate` | Recent agent debate summaries | `debate` |
| `performance [period]` | Performance metrics (1d/7d/30d/90d/YTD/ALL) | `performance 30d` |
| `attribution [symbol]` | Per-trade attribution breakdown | `attribution AAPL.NASDAQ` |

### Models and ML

| Command | Description | Example |
|---------|-------------|---------|
| `models` | Registered ML models with status and Sharpe | `models` |
| `model stats` | Thompson Sampling rotation statistics | `model stats` |

### Reports and Alerts

| Command | Description | Example |
|---------|-------------|---------|
| `report [period]` | Generate report (daily/weekly/monthly) | `report daily` |
| `report export [fmt]` | Export report (csv/json) | `report export csv` |
| `alerts [severity]` | Show alerts (INFO/WARNING/CRITICAL/EMERGENCY) | `alerts CRITICAL` |
| `alert rules` | Show alert rules and channel status | `alert rules` |
| `health` | System health dashboard | `health` |

### CIO and Governance

| Command | Description | Example |
|---------|-------------|---------|
| `cio` | Enter CIO natural language chat | `cio` |
| `override regime <SCOPE> <REGIME>` | Manually set market regime | `override regime INDIA BULL` |
| `interrupt <agent_id>` | Pause a specific agent | `interrupt strategy_agent` |
| `toggle sentiment` | Enable/disable sentiment agent | `toggle sentiment` |
| `mode <MODE>` | Switch trading mode | `mode HUMAN_APPROVAL` |
| `agents config` | Show agent LLM configuration | `agents config` |

---

## 6. Configuration Guide

### API Keys

Configure in your `.env` file in the backend directory:

```bash
# LLM Providers (optional -- agents work with any one provider)
ANTHROPIC_API_KEY=sk-ant-...     # Claude (recommended)
OPENAI_API_KEY=sk-...            # GPT-4
GOOGLE_API_KEY=AI...             # Gemini

# Brokers (optional -- not needed for paper trading)
ALPACA_API_KEY=PK...
ALPACA_API_SECRET=...
ZERODHA_API_KEY=...
ZERODHA_API_SECRET=...

# Data Providers (optional -- Yahoo Finance is free and default)
POLYGON_API_KEY=...
```

### Risk Parameters

Adjustable at runtime or via `.env`:

```bash
# Maximum portfolio drawdown before kill switch activates
MAX_DRAWDOWN_PCT=5.0

# Position sizing limits
MAX_POSITION_PCT=10.0        # Max % of NAV in a single position
MAX_SECTOR_PCT=30.0          # Max % of NAV in a single sector

# VaR confidence levels
VAR_CONFIDENCE_95=0.95
VAR_CONFIDENCE_99=0.99
```

### Trading Universe

The default universe includes:

- **India:** RELIANCE.NSE, TCS.NSE, INFY.NSE, HDFCBANK.NSE, and more
- **US:** AAPL.NASDAQ, MSFT.NASDAQ, GOOGL.NASDAQ, AMZN.NASDAQ, and more
- **Crypto:** BTC-USD, ETH-USD, SOL-USD, and more

Customize via the onboarding wizard (`setup`) or by editing the configuration.

### Alert Channels

```bash
# Telegram notifications
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Email notifications
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
ALERT_EMAIL_TO=you@example.com
```

---

## 7. Troubleshooting

### Platform will not start

**Symptom:** Error on `python -m app`

- Ensure you are in the `backend/` directory
- Check Python version: `python --version` (must be 3.11+)
- Install dependencies: `pip install -e .`
- Check for port conflicts if using POSTGRES mode

### No market data appearing

**Symptom:** `data` command shows empty or stale values

- Check internet connection
- Run `workers` to verify Data Ingestion worker is running
- Yahoo Finance has rate limits -- wait a few minutes and retry
- Check circuit breaker states in `data` output (CLOSED = healthy)

### Agents stuck or not responding

**Symptom:** `status` shows agents in ERROR state

- Run `workers` to check if orchestrator is running
- Workers auto-restart on crash (check logs for details)
- Use `interrupt <agent_id>` then wait for auto-restart
- As a last resort, restart the platform

### Kill switch activated unexpectedly

**Symptom:** Trading halted, `risk` shows kill switch ACTIVE

- Check `risk` for current drawdown vs max drawdown threshold
- Use `risk-tolerance <N>` to adjust if threshold is too tight
- Use `kill-switch` to deactivate when ready to resume

### Backtest returns no results

**Symptom:** `backtest results` shows nothing

- Ensure you ran a backtest first: `backtest AAPL.NASDAQ --days 90`
- Check that market data exists for the symbol: `data`
- Try a shorter period: `--days 30`

### LLM agents not working

**Symptom:** Agents produce generic or empty responses

- Verify API key is set: `config` (keys are masked but shown)
- At least one LLM provider key is needed for full agent functionality
- The platform works without LLM keys but with reduced agent intelligence
- Re-run `setup` to configure API keys

### High memory usage

**Symptom:** Platform consuming excessive RAM

- LOCAL mode with SQLite is the most efficient
- Reduce trading universe size via `setup`
- Close other applications
- Consider running in headless mode: `python -m app --headless`

### Common error messages

| Error | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError` | Missing dependency | `pip install -e .` |
| `Address already in use` | Port conflict (POSTGRES mode) | Stop other services or change port |
| `Connection refused` | Redis/Postgres not running | Start Docker services or use LOCAL mode |
| `Rate limit exceeded` | Too many API calls | Wait and retry; circuit breaker will handle it |
| `Invalid API key` | Wrong or expired key | Check `.env` file, re-run `setup` |
