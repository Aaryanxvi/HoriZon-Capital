# Horizon Capital — Technical Reference
*Version 0.2.0*

---

## 1. Data Sources

### Yahoo Finance (`data_layer/yahoo_feed.py`)

**Role**: OHLCV data for US equities (NYSE/NASDAQ) and Indian equities (NSE/BSE).
**Library**: `yfinance`
**Polling interval**: 5 minutes

| Field | Type | Notes |
|-------|------|-------|
| `open`, `high`, `low`, `close` | float | OHLCV bar |
| `volume` | int | Shares traded |
| `timestamp` | datetime (UTC) | Bar timestamp |

**Symbol mapping**: Internal `RELIANCE.NSE` → Yahoo `RELIANCE.NS`; `TCS.BSE` → `TCS.BO`.

---

### CoinGecko (`data_layer/coingecko_feed.py`)

**Role**: Cryptocurrency prices (BTC-USD, ETH-USD, etc.)
**Polling interval**: 60 seconds
**Limitation**: Free tier provides only current price. OHLCV is synthesized as
`open = high = low = close = last_price`.

---

### Mock Feed (`data_layer/mock_feed.py`)

Used when no real data source is available. Generates realistic-looking OHLCV bars
via Geometric Brownian Motion around a base price.

---

## 2. Feature Engineering (`features/`)

### Technical Indicators (`features/technical.py`)

23 indicators across four categories:

| Category | Indicators |
|----------|-----------|
| Trend | SMA(20), SMA(50), EMA(12), EMA(26), MACD, MACD signal/histogram, Ichimoku cloud |
| Momentum | RSI(14), Stochastic %K/%D, Williams %R, ROC |
| Volatility | Bollinger Bands (upper/mid/lower), ATR(14), Keltner Channels |
| Volume | OBV, VWAP (cumulative proxy) |

### Volatility Features (`features/volatility.py`)

| Feature | Method |
|---------|--------|
| Realized vol | Rolling 20-day annualized std of log-returns |
| GARCH(1,1) | `arch` library; 1-day ahead variance forecast |
| VIX proxy | 30-day rolling vol × √252 × 100 |

---

## 3. Strategies (`agents/front_office/strategy/`)

### Momentum (`momentum_strategy.py`)

**Signal logic**: BUY when price > SMA(50) and RSI > 50 and MACD histogram > 0.
Sell when price crosses below SMA(50).

### Mean Reversion (`mean_reversion_strategy.py`)

**Signal logic**: BUY when RSI < 30 (oversold) and price touches lower Bollinger Band.
Sell when RSI > 70 or price returns to midline.

Both strategies inherit from `BaseStrategy` and return a `SignalPayload` with
`direction` (+1/-1/0), `confidence` (0–1), and `metadata`.

---

## 4. Sentiment Analysis (`agents/front_office/research/`)

### Keyword Scorer (`sentiment_agent.py`)

Simple lexicon-based scoring using two word sets:
- Positive: surge, rally, gain, profit, growth, beat, bullish, recover, ...
- Negative: crash, plunge, loss, decline, bearish, miss, recession, ...

Score = (positive_count − negative_count) / total_count

### FinancialBERT Scorer (`finbert_scorer.py`)

If the `transformers` library is available, uses the `ProsusAI/finbert` model
(pre-trained on financial text) to classify each headline as
`positive / negative / neutral` with a confidence score.

Falls back to keyword scoring if the model is not installed.

---

## 5. AI Debate Engine (`agents/debate/`)

Four AI debater roles argue for or against a proposed trade:

| Role | Perspective |
|------|-------------|
| STRATEGY | Aggressive growth — focus on upside and momentum |
| RISK | Conservative — identify downside risks and tail scenarios |
| SENTIMENT | Market psychology — headlines, investor mood |
| PORTFOLIO | Fit within existing positions, correlation, sizing |

Each debater receives the same market context prompt (symbol, proposed action,
price data, sentiment score, VaR) and returns `{vote: FOR/AGAINST/ABSTAIN,
confidence: 0–1, argument: str}`.

**Decision rule**: `consensus_score > 0.55` AND `for_votes / total > 60%` → APPROVED.

**Multi-model variant** (`multi_model_debate.py`): Distributes available LLM providers
(Claude, GPT, Gemini) across roles so different architectures argue different perspectives.
Runs two rounds with perspective rotation in round 2.

---

## 6. Risk Management (`agents/middle_office/risk/`)

| Check | Default | Effect |
|-------|---------|--------|
| Max position size | 5% NAV | Signal rejected if order would exceed limit |
| Max drawdown | 10% | Emergency halt (kill switch) triggered |
| Max leverage | 2× | Order rejected if leverage would exceed |
| VaR limit | 3% | Alert triggered when portfolio VaR > limit |
| Daily loss limit | 2% NAV | Trading halted for the session |

VaR is calculated using historical simulation on the last 30 days of portfolio returns.

---

## 7. Execution (`agents/front_office/trading/`)

### Paper Broker (`paper_broker.py`)

Simulates order fills with Almgren-Chriss market impact:

```
impact = temporary_impact + permanent_impact
temporary_impact = η × (order_size / daily_volume)^0.6
permanent_impact = γ × (order_size / daily_volume)
```

Adds 10 bps taker fee. No real money is ever used.

### Order Splitter (`order_splitter.py`)

Large orders are split into child orders to reduce impact:
- **TWAP**: Equal slices over N time intervals
- **VWAP**: Weighted by historical intraday volume profile
- **Almgren-Chriss optimal**: Front-loads when urgency (risk aversion) is high

---

## 8. Storage

### Local Mode (default)

- **Database**: SQLite via `aiosqlite` + SQLAlchemy async
- **Message bus**: In-memory pub/sub (`core/memory_bus.py`)
- **KV store**: In-memory dict with optional file persistence (`core/kv_store.py`)
- **No Docker required**

### Postgres Mode

Set `STORAGE_BACKEND=POSTGRES` in `.env`:
- **Database**: PostgreSQL via `asyncpg`
- **Message bus**: Redis pub/sub
- **KV store**: Redis

---

## 9. Security

- JWT authentication (HS256, configurable expiry)
- bcrypt password hashing
- Auto-generated secrets on first run (warns if using defaults)
- Password policy: min 8 chars, uppercase + lowercase + digit
- CORS origins configurable via `CORS_ORIGINS` env var
