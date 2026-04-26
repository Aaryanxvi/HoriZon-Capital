# College Project Simplification Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strip horizon-capital down to a clean, impressive college project — multi-agent AI trading with debates, sentiment, paper trading — with no traces of the advanced version.

**Architecture:** Simplify all advanced components to basic implementations. Remove regime detection, advanced risk models, ML pipeline, stress testing, and real trading. Keep the agent department structure, add multi-LLM debate, add basic sentiment, keep 3 data feeds.

**Tech Stack:** Python 3.14, Rich TUI, SQLite, ta (indicators), yfinance, alpaca-py, httpx (CoinGecko)

---

## File Structure Overview

**Files to simplify (heavy edits):**
- `app/core/messaging.py` — strip to ~15 message types
- `app/agents/front_office/strategy/ensemble_selector.py` — remove, replace with simple strategy runner
- `app/agents/front_office/strategy/base_strategy.py` — simplify Signal dataclass
- `app/agents/front_office/portfolio/optimizer.py` — replace with equal-weight
- `app/agents/front_office/portfolio/portfolio_agent.py` — simplify signal handling
- `app/agents/middle_office/risk/risk_agent.py` — basic limits only
- `app/tui/commands.py` — trim to ~15 commands
- `app/tui/dashboard.py` — simplify panels
- `app/__main__.py` — fewer workers, simpler startup
- `app/workers/data_ingestion_worker.py` — 3 feeds only
- `app/core/resilience.py` — remove circuit breakers, keep basic retry

**Files to remove entirely:**
- `app/agents/front_office/research/regime_agent.py`
- `app/agents/front_office/research/jump_model.py`
- `app/agents/front_office/research/hmm_model.py`
- `app/agents/front_office/strategy/crisis_strategy.py`
- `app/agents/front_office/strategy/volatility_strategy.py`
- `app/agents/front_office/strategy/options_strategy.py`
- `app/agents/front_office/strategy/arbitrage_detector.py`
- `app/agents/front_office/trading/paper_crypto_broker.py`
- `app/agents/front_office/trading/zerodha_broker.py`
- `app/backtesting/walk_forward.py`
- `app/backtesting/monte_carlo.py`
- `app/backtesting/multi_asset_engine.py`
- `app/backtesting/benchmark.py`
- `app/services/stress_testing.py`
- `app/services/tax_harvesting.py`
- `app/services/attribution_engine.py`
- `app/services/adaptation_engine.py`
- `app/services/explainability.py`
- `app/services/model_registry.py`
- `app/services/macro_factors.py`
- `app/services/portfolio_rebalancer.py`
- `app/services/reconciliation.py`
- `app/data_layer/zerodha_feed.py`
- `app/data_layer/forex_feed.py`
- `app/data_layer/polygon_feed.py`
- `app/workers/macro_worker.py`
- `app/workers/position_worker.py`
- `app/plugins/` (entire directory)
- `app/monitoring/` (entire directory)

**Files to create:**
- `app/agents/front_office/research/sentiment_agent.py` — basic news sentiment
- `app/agents/front_office/strategy/simple_strategies.py` — RSI, MACD, Bollinger

---

### Task 1: Strip MessageType Enum

**Files:**
- Modify: `app/core/messaging.py:24-73`
- Test: `tests/test_smoke.py` (run existing tests after)

- [ ] **Step 1: Replace MessageType enum with ~15 types**

Replace the MessageType enum (lines 24-73) with:

```python
class MessageType(str, Enum):
    """Core message types for the trading platform."""
    TICK = "tick"
    OHLCV = "ohlcv"
    FEATURE_UPDATE = "feature_update"
    SIGNAL = "signal"
    RISK_CHECK = "risk_check"
    RISK_ALERT = "risk_alert"
    DEBATE_START = "debate_start"
    DEBATE_VOTE = "debate_vote"
    DEBATE_CONCLUSION = "debate_conclusion"
    ORDER_NEW = "order_new"
    ORDER_FILL = "order_fill"
    ORDER_CANCEL = "order_cancel"
    PORTFOLIO_UPDATE = "portfolio_update"
    HEALTH_CHECK = "health_check"
    SENTIMENT_UPDATE = "sentiment_update"
    AGENT_STATUS = "agent_status"
    HEARTBEAT = "heartbeat"
```

- [ ] **Step 2: Find and fix all references to removed message types**

Search for every usage of removed MessageType values (REGIME_UPDATE, KILL_SWITCH, CIO_COMMAND, COMPLIANCE_ALERT, OPERATIONS_ALERT, ACCOUNTING_SNAPSHOT, IT_ALERT, IT_STATUS, IR_REPORT, DEPARTMENT_STATUS, CIO_DIRECTIVE, CIO_CHAT, ALPHA_DECAY, ALPHA_SNAPSHOT, REGIME_TRANSITION, ADAPTATION_ACTION, AGENT_STATE_CHANGE, MACRO_REGIME_UPDATE, SYSTEM, ALERT, HEALTH_SNAPSHOT, TRADE_EXECUTED, RISK_APPROVED, RISK_REJECTED, ORDER_CANCEL_ALL, PRICE_UPDATE, ORDER_APPROVE, ORDER_REJECT, ORDER_UPDATE, FEED_STATUS) across the entire codebase and remove or remap them.

Run: `grep -r "MessageType\." app/ --include="*.py" -l`

For each file, remove subscriptions to deleted types, remove handlers for deleted types, and remove publish calls for deleted types.

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/ -x -q`
Fix any import errors or missing references.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: strip message types to 17 core types"
```

---

### Task 2: Remove Advanced Strategy Files

**Files:**
- Delete: `app/agents/front_office/strategy/crisis_strategy.py`
- Delete: `app/agents/front_office/strategy/volatility_strategy.py`
- Delete: `app/agents/front_office/strategy/options_strategy.py`
- Delete: `app/agents/front_office/strategy/arbitrage_detector.py`
- Delete: `app/agents/front_office/strategy/ensemble_selector.py`
- Modify: `app/agents/front_office/strategy/__init__.py`

- [ ] **Step 1: Delete the files**

```bash
rm app/agents/front_office/strategy/crisis_strategy.py
rm app/agents/front_office/strategy/volatility_strategy.py
rm app/agents/front_office/strategy/options_strategy.py
rm app/agents/front_office/strategy/arbitrage_detector.py
rm app/agents/front_office/strategy/ensemble_selector.py
```

- [ ] **Step 2: Clean __init__.py imports**

Remove all imports referencing deleted files from `app/agents/front_office/strategy/__init__.py`.

- [ ] **Step 3: Find and fix references**

Run: `grep -rn "EnsembleSelector\|CrisisStrategy\|VolatilityStrategy\|OptionsStrategy\|ArbitrageDetector" app/ --include="*.py"`

Fix every reference — these will mostly be in `strategy_agent.py` and `__main__.py`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "remove: advanced strategy files"
```

---

### Task 3: Create Simple Strategies

**Files:**
- Create: `app/agents/front_office/strategy/simple_strategies.py`
- Modify: `app/agents/front_office/strategy/base_strategy.py`
- Test: `tests/test_simple_strategies.py`

- [ ] **Step 1: Simplify Signal dataclass in base_strategy.py**

Replace the Signal dataclass (lines 15-52) with a simpler version:

```python
@dataclass
class Signal:
    """A trading signal generated by a strategy."""
    symbol: str
    direction: int  # +1 buy, -1 sell, 0 hold
    strength: float  # 0.0 to 1.0
    strategy_name: str
    reasoning: str = ""
    target_price: float | None = None
    stop_loss: float | None = None
    timestamp: datetime | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
```

Remove LLM-related fields (llm_enhanced, meta, regime). Simplify BaseStrategy to remove `generate_signal_with_llm()` and `_parse_llm_response()` methods. Keep only the abstract `generate_signal()` method.

- [ ] **Step 2: Write simple_strategies.py**

```python
"""Three basic trading strategies using fixed technical indicator thresholds."""

from __future__ import annotations

import ta
import pandas as pd

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal


class RSIStrategy(BaseStrategy):
    """Buy when RSI < 30 (oversold), sell when RSI > 70 (overbought)."""

    @property
    def name(self) -> str:
        return "rsi"

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal | None:
        if df is None or len(df) < 14:
            return None

        rsi = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
        current_rsi = rsi.iloc[-1]

        if pd.isna(current_rsi):
            return None

        if current_rsi < 30:
            return Signal(
                symbol=symbol,
                direction=1,
                strength=min((30 - current_rsi) / 30, 1.0),
                strategy_name=self.name,
                reasoning=f"RSI oversold at {current_rsi:.1f}",
            )
        elif current_rsi > 70:
            return Signal(
                symbol=symbol,
                direction=-1,
                strength=min((current_rsi - 70) / 30, 1.0),
                strategy_name=self.name,
                reasoning=f"RSI overbought at {current_rsi:.1f}",
            )
        return None


class MACDStrategy(BaseStrategy):
    """Buy on MACD crossover above signal line, sell on crossover below."""

    @property
    def name(self) -> str:
        return "macd"

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal | None:
        if df is None or len(df) < 26:
            return None

        macd_ind = ta.trend.MACD(df["close"])
        macd_line = macd_ind.macd()
        signal_line = macd_ind.macd_signal()

        if len(macd_line) < 2 or pd.isna(macd_line.iloc[-1]):
            return None

        current_diff = macd_line.iloc[-1] - signal_line.iloc[-1]
        prev_diff = macd_line.iloc[-2] - signal_line.iloc[-2]

        if prev_diff <= 0 < current_diff:
            return Signal(
                symbol=symbol,
                direction=1,
                strength=min(abs(current_diff) / 2, 1.0),
                strategy_name=self.name,
                reasoning=f"MACD crossed above signal line ({current_diff:.4f})",
            )
        elif prev_diff >= 0 > current_diff:
            return Signal(
                symbol=symbol,
                direction=-1,
                strength=min(abs(current_diff) / 2, 1.0),
                strategy_name=self.name,
                reasoning=f"MACD crossed below signal line ({current_diff:.4f})",
            )
        return None


class BollingerBandStrategy(BaseStrategy):
    """Buy below lower Bollinger Band, sell above upper band."""

    @property
    def name(self) -> str:
        return "bollinger"

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal | None:
        if df is None or len(df) < 20:
            return None

        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        upper = bb.bollinger_hband().iloc[-1]
        lower = bb.bollinger_lband().iloc[-1]
        price = df["close"].iloc[-1]

        if pd.isna(upper) or pd.isna(lower):
            return None

        band_width = upper - lower
        if band_width == 0:
            return None

        if price < lower:
            return Signal(
                symbol=symbol,
                direction=1,
                strength=min((lower - price) / band_width, 1.0),
                strategy_name=self.name,
                reasoning=f"Price {price:.2f} below lower BB {lower:.2f}",
            )
        elif price > upper:
            return Signal(
                symbol=symbol,
                direction=-1,
                strength=min((price - upper) / band_width, 1.0),
                strategy_name=self.name,
                reasoning=f"Price {price:.2f} above upper BB {upper:.2f}",
            )
        return None
```

- [ ] **Step 3: Write test**

```python
"""Tests for simple trading strategies."""

import pandas as pd
import numpy as np
import pytest

from app.agents.front_office.strategy.simple_strategies import (
    RSIStrategy,
    MACDStrategy,
    BollingerBandStrategy,
)


def _make_df(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "open": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": [1000] * len(prices),
    })


class TestRSIStrategy:
    def test_returns_none_insufficient_data(self):
        strategy = RSIStrategy()
        df = _make_df([100.0] * 5)
        assert strategy.generate_signal("AAPL", df) is None

    def test_buy_signal_on_oversold(self):
        strategy = RSIStrategy()
        # Create a strong downtrend to push RSI below 30
        prices = [100.0 - i * 2 for i in range(30)]
        df = _make_df(prices)
        signal = strategy.generate_signal("AAPL", df)
        if signal is not None:
            assert signal.direction == 1
            assert signal.strategy_name == "rsi"

    def test_sell_signal_on_overbought(self):
        strategy = RSIStrategy()
        prices = [50.0 + i * 2 for i in range(30)]
        df = _make_df(prices)
        signal = strategy.generate_signal("AAPL", df)
        if signal is not None:
            assert signal.direction == -1


class TestMACDStrategy:
    def test_returns_none_insufficient_data(self):
        strategy = MACDStrategy()
        df = _make_df([100.0] * 10)
        assert strategy.generate_signal("AAPL", df) is None

    def test_generates_signal_with_enough_data(self):
        strategy = MACDStrategy()
        np.random.seed(42)
        prices = [100 + np.random.randn() * 2 for _ in range(50)]
        df = _make_df(prices)
        # May or may not generate signal depending on data
        signal = strategy.generate_signal("AAPL", df)
        if signal is not None:
            assert signal.direction in (-1, 1)
            assert signal.strategy_name == "macd"


class TestBollingerBandStrategy:
    def test_returns_none_insufficient_data(self):
        strategy = BollingerBandStrategy()
        df = _make_df([100.0] * 5)
        assert strategy.generate_signal("AAPL", df) is None

    def test_buy_signal_below_lower_band(self):
        strategy = BollingerBandStrategy()
        prices = [100.0] * 20 + [80.0]
        df = _make_df(prices)
        signal = strategy.generate_signal("AAPL", df)
        if signal is not None:
            assert signal.direction == 1
            assert signal.strategy_name == "bollinger"
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_simple_strategies.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add app/agents/front_office/strategy/simple_strategies.py tests/test_simple_strategies.py
git commit -m "feat: add three basic trading strategies (RSI, MACD, Bollinger)"
```

---

### Task 4: Create Basic Sentiment Agent

**Files:**
- Create: `app/agents/front_office/research/sentiment_agent.py`
- Test: `tests/test_sentiment.py`

- [ ] **Step 1: Write sentiment_agent.py**

```python
"""Basic sentiment analysis using free news headlines."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app.core.messaging import AgentMessage, MessageType

logger = logging.getLogger(__name__)

# Simple keyword lists for sentiment scoring
POSITIVE_WORDS = frozenset({
    "surge", "soar", "rally", "gain", "profit", "growth", "beat", "upgrade",
    "bullish", "record", "high", "strong", "boom", "breakout", "outperform",
    "up", "rise", "positive", "optimistic", "buy", "upside", "recover",
})

NEGATIVE_WORDS = frozenset({
    "crash", "plunge", "drop", "loss", "decline", "downgrade", "bearish",
    "low", "weak", "bust", "sell", "miss", "warning", "risk", "fear",
    "down", "fall", "negative", "pessimistic", "recession", "default",
})


def score_headline(headline: str) -> tuple[str, float]:
    """Score a headline as positive/negative/neutral with magnitude 0-1."""
    words = set(headline.lower().split())
    pos_count = len(words & POSITIVE_WORDS)
    neg_count = len(words & NEGATIVE_WORDS)
    total = pos_count + neg_count

    if total == 0:
        return "neutral", 0.0

    if pos_count > neg_count:
        return "positive", min(pos_count / total, 1.0)
    elif neg_count > pos_count:
        return "negative", min(neg_count / total, 1.0)
    return "neutral", 0.0


class SentimentAgent:
    """Fetches news headlines and scores sentiment per symbol."""

    def __init__(self, bus, symbols: list[str], api_key: str = ""):
        self.bus = bus
        self.symbols = symbols
        self.api_key = api_key
        self._running = False

    async def start(self):
        self._running = True
        logger.info("SentimentAgent started for %d symbols", len(self.symbols))
        while self._running:
            for symbol in self.symbols:
                try:
                    sentiment, score = await self._analyze_symbol(symbol)
                    await self.bus.publish(AgentMessage(
                        type=MessageType.SENTIMENT_UPDATE,
                        source="sentiment_agent",
                        data={
                            "symbol": symbol,
                            "sentiment": sentiment,
                            "score": score,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    ))
                except Exception:
                    logger.exception("Sentiment analysis failed for %s", symbol)
            await asyncio.sleep(300)  # Every 5 minutes

    async def stop(self):
        self._running = False

    async def _analyze_symbol(self, symbol: str) -> tuple[str, float]:
        """Fetch headlines for a symbol and return aggregate sentiment."""
        headlines = await self._fetch_headlines(symbol)
        if not headlines:
            return "neutral", 0.0

        pos_total = 0.0
        neg_total = 0.0
        for headline in headlines:
            sentiment, magnitude = score_headline(headline)
            if sentiment == "positive":
                pos_total += magnitude
            elif sentiment == "negative":
                neg_total += magnitude

        count = len(headlines)
        if pos_total > neg_total:
            return "positive", min(pos_total / count, 1.0)
        elif neg_total > pos_total:
            return "negative", min(neg_total / count, 1.0)
        return "neutral", 0.0

    async def _fetch_headlines(self, symbol: str) -> list[str]:
        """Fetch news headlines from Finnhub (free tier)."""
        if not self.api_key:
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://finnhub.io/api/v1/company-news",
                    params={
                        "symbol": symbol,
                        "from": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "to": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "token": self.api_key,
                    },
                )
                if resp.status_code == 200:
                    articles = resp.json()
                    return [a.get("headline", "") for a in articles[:20]]
        except Exception:
            logger.debug("Failed to fetch headlines for %s", symbol)
        return []
```

- [ ] **Step 2: Write test**

```python
"""Tests for sentiment analysis."""

from app.agents.front_office.research.sentiment_agent import score_headline


class TestScoreHeadline:
    def test_positive_headline(self):
        sentiment, score = score_headline("Stock prices surge on strong growth")
        assert sentiment == "positive"
        assert score > 0

    def test_negative_headline(self):
        sentiment, score = score_headline("Markets crash amid recession fear")
        assert sentiment == "negative"
        assert score > 0

    def test_neutral_headline(self):
        sentiment, score = score_headline("Company announces quarterly results")
        assert sentiment == "neutral"
        assert score == 0.0

    def test_empty_headline(self):
        sentiment, score = score_headline("")
        assert sentiment == "neutral"
```

- [ ] **Step 3: Run test**

Run: `python -m pytest tests/test_sentiment.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add app/agents/front_office/research/sentiment_agent.py tests/test_sentiment.py
git commit -m "feat: add basic keyword sentiment analysis agent"
```

---

### Task 5: Remove Regime Detection

**Files:**
- Delete: `app/agents/front_office/research/regime_agent.py`
- Delete: `app/agents/front_office/research/jump_model.py`
- Delete: `app/agents/front_office/research/hmm_model.py`

- [ ] **Step 1: Delete files**

```bash
rm app/agents/front_office/research/regime_agent.py
rm app/agents/front_office/research/jump_model.py
rm app/agents/front_office/research/hmm_model.py
```

- [ ] **Step 2: Fix all references**

Run: `grep -rn "RegimeAgent\|JumpRegimeModel\|HMMRegimeModel\|regime_agent\|jump_model\|hmm_model" app/ --include="*.py"`

Remove imports, instantiations, and subscriptions referencing these. In `__main__.py`, remove regime agent startup. In strategy files, remove regime-based logic.

- [ ] **Step 3: Run tests, fix breakage**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "remove: regime detection (Jump Model, HMM)"
```

---

### Task 6: Simplify Risk Agent

**Files:**
- Modify: `app/agents/middle_office/risk/risk_agent.py`

- [ ] **Step 1: Replace risk agent internals**

Strip out GARCH-EVT, kill switch, complex exposure calculations. Replace with:

```python
async def check_risk(self, signal_data: dict) -> bool:
    """Basic risk checks: position limit and daily loss."""
    symbol = signal_data.get("symbol", "")
    
    # Max 5% of portfolio per position
    portfolio_value = await self._get_portfolio_value()
    position_value = await self._get_position_value(symbol)
    if portfolio_value > 0 and position_value / portfolio_value > 0.05:
        return False
    
    # 10% daily loss limit
    daily_pnl = await self._get_daily_pnl()
    if portfolio_value > 0 and daily_pnl / portfolio_value < -0.10:
        return False
    
    return True
```

Keep the basic structure, remove all imports for scipy, numpy risk calculations, GARCH, EVT.

- [ ] **Step 2: Run tests, fix breakage**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "simplify: basic position limit and daily loss risk checks"
```

---

### Task 7: Simplify Portfolio to Equal-Weight

**Files:**
- Modify: `app/agents/front_office/portfolio/optimizer.py`

- [ ] **Step 1: Replace optimizer with equal-weight**

Replace the entire file with:

```python
"""Simple equal-weight portfolio allocation."""

from __future__ import annotations


class PortfolioOptimizer:
    """Allocates equal weight to each position in the portfolio."""

    @staticmethod
    def calculate_weights(symbols: list[str]) -> dict[str, float]:
        """Return equal weight for each symbol."""
        if not symbols:
            return {}
        weight = 1.0 / len(symbols)
        return {s: weight for s in symbols}

    @staticmethod
    def position_size(
        portfolio_value: float,
        num_positions: int,
        max_pct: float = 0.05,
    ) -> float:
        """Calculate position size as equal share, capped at max_pct."""
        if num_positions <= 0 or portfolio_value <= 0:
            return 0.0
        equal_share = portfolio_value / num_positions
        max_size = portfolio_value * max_pct
        return min(equal_share, max_size)
```

- [ ] **Step 2: Fix references to removed methods (hrp_weights, kelly_fraction, ledoit_wolf_shrinkage, correlation_penalty)**

Run: `grep -rn "hrp_weights\|kelly_fraction\|ledoit_wolf_shrinkage\|correlation_penalty" app/ --include="*.py"`

Replace calls with `calculate_weights()` or `position_size()`.

- [ ] **Step 3: Run tests, fix breakage**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "simplify: equal-weight portfolio allocation"
```

---

### Task 8: Strip Backtesting to Basics

**Files:**
- Delete: `app/backtesting/walk_forward.py`
- Delete: `app/backtesting/monte_carlo.py`
- Delete: `app/backtesting/multi_asset_engine.py`
- Delete: `app/backtesting/benchmark.py`
- Modify: `app/backtesting/backtest_metrics.py`

- [ ] **Step 1: Delete advanced backtesting files**

```bash
rm app/backtesting/walk_forward.py
rm app/backtesting/monte_carlo.py
rm app/backtesting/multi_asset_engine.py
rm app/backtesting/benchmark.py
```

- [ ] **Step 2: Simplify backtest_metrics.py to 3 metrics**

Keep only: Sharpe ratio, max drawdown, win rate. Remove Sortino, Calmar, Omega, information ratio, recovery factor.

- [ ] **Step 3: Fix references and commands**

Remove walk-forward and monte carlo references from `commands.py` backtest handler.

- [ ] **Step 4: Run tests, fix breakage**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "simplify: basic backtest with Sharpe, max drawdown, win rate"
```

---

### Task 9: Remove Advanced Services

**Files:**
- Delete: `app/services/stress_testing.py`
- Delete: `app/services/tax_harvesting.py`
- Delete: `app/services/attribution_engine.py`
- Delete: `app/services/adaptation_engine.py`
- Delete: `app/services/explainability.py`
- Delete: `app/services/model_registry.py`
- Delete: `app/services/macro_factors.py`
- Delete: `app/services/portfolio_rebalancer.py`
- Delete: `app/services/reconciliation.py`

- [ ] **Step 1: Delete files**

```bash
rm app/services/stress_testing.py
rm app/services/tax_harvesting.py
rm app/services/attribution_engine.py
rm app/services/adaptation_engine.py
rm app/services/explainability.py
rm app/services/model_registry.py
rm app/services/macro_factors.py
rm app/services/portfolio_rebalancer.py
rm app/services/reconciliation.py
```

- [ ] **Step 2: Fix all references**

Run: `grep -rn "stress_testing\|tax_harvesting\|attribution_engine\|adaptation_engine\|explainability\|model_registry\|macro_factors\|portfolio_rebalancer\|reconciliation" app/ --include="*.py"`

Remove imports and usages.

- [ ] **Step 3: Run tests, fix breakage**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "remove: advanced services (stress testing, attribution, ML registry, etc.)"
```

---

### Task 10: Strip Data Layer to 3 Feeds

**Files:**
- Delete: `app/data_layer/zerodha_feed.py`
- Delete: `app/data_layer/forex_feed.py`
- Delete: `app/data_layer/polygon_feed.py`
- Modify: `app/data_layer/data_manager.py`

- [ ] **Step 1: Delete feed files**

```bash
rm app/data_layer/zerodha_feed.py
rm app/data_layer/forex_feed.py
rm app/data_layer/polygon_feed.py
```

- [ ] **Step 2: Simplify data_manager.py**

Remove references to Zerodha, Forex, and Polygon feeds. Keep only Yahoo, Alpaca, and CoinGecko initialization and routing.

- [ ] **Step 3: Fix references in data_ingestion_worker.py**

Remove Zerodha/Forex/Polygon polling loops and imports.

- [ ] **Step 4: Run tests, fix breakage**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "simplify: keep Yahoo, Alpaca, CoinGecko feeds only"
```

---

### Task 11: Simplify Resilience (Remove Circuit Breakers)

**Files:**
- Modify: `app/core/resilience.py`

- [ ] **Step 1: Replace with basic retry**

Replace the entire file with:

```python
"""Basic resilience utilities."""

from __future__ import annotations

import asyncio
import logging
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
):
    """Retry a function with exponential backoff."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception:
                    if attempt == max_retries:
                        raise
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "Retry %d/%d for %s in %.1fs",
                        attempt + 1, max_retries, func.__name__, delay,
                    )
                    await asyncio.sleep(delay)
        return wrapper
    return decorator
```

- [ ] **Step 2: Fix all CircuitBreaker references**

Run: `grep -rn "CircuitBreaker\|CircuitState\|RateLimiter\|with_timeout" app/ --include="*.py"`

Remove usages or replace with simple try/except.

- [ ] **Step 3: Run tests, fix breakage**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "simplify: basic retry, remove circuit breakers"
```

---

### Task 12: Remove Extra Workers and Files

**Files:**
- Delete: `app/workers/macro_worker.py`
- Delete: `app/workers/position_worker.py`
- Delete: `app/plugins/` (entire directory)
- Delete: `app/monitoring/` (entire directory)
- Modify: `app/__main__.py`

- [ ] **Step 1: Delete files and directories**

```bash
rm app/workers/macro_worker.py
rm app/workers/position_worker.py
rm -rf app/plugins/
rm -rf app/monitoring/
```

- [ ] **Step 2: Simplify __main__.py worker startup**

In `_start_workers()` (line 146-201), keep only:
- DataIngestionWorker
- FeatureComputationWorker
- PerformanceWorker

Remove MacroFactorWorker and PositionMonitorWorker startup.

- [ ] **Step 3: Fix references**

Run: `grep -rn "macro_worker\|position_worker\|plugins\|monitoring" app/ --include="*.py"`

- [ ] **Step 4: Run tests, fix breakage**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "remove: extra workers, plugins, monitoring"
```

---

### Task 13: Simplify Debate to Majority Vote

**Files:**
- Modify: debate-related agent files (find via grep for DEBATE)

- [ ] **Step 1: Find all debate logic**

Run: `grep -rn "debate\|DEBATE" app/ --include="*.py" -l`

- [ ] **Step 2: Simplify debate scoring**

Replace any weighted scoring, conviction metrics, regime-aware vote weighting with simple majority vote logic:

```python
def tally_votes(votes: list[dict]) -> str:
    """Simple majority vote. Returns 'APPROVED' or 'REJECTED'."""
    approve_count = sum(1 for v in votes if v.get("vote") == "approve")
    reject_count = sum(1 for v in votes if v.get("vote") == "reject")
    return "APPROVED" if approve_count > reject_count else "REJECTED"
```

Remove signal buffering, debate-to-order gating complexity, and FULLY_AUTONOMOUS/HUMAN mode logic. Keep basic: signal → debate → majority vote → order.

- [ ] **Step 3: Run tests, fix breakage**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "simplify: majority vote debate system"
```

---

### Task 14: Trim REPL Commands to ~15

**Files:**
- Modify: `app/tui/commands.py`

- [ ] **Step 1: Remove command handlers**

Keep only these commands: help, status, portfolio, positions, orders, signals, backtest, risk, sentiment, debate, agents, health, performance, config, quit

Remove handlers for: stress-test, alerts, report, models, office, dashboard, approve, reject, ai-routing, connect, broker, disconnect, kill-switch, symbols, data, setup, interrupt, risk-tolerance, exposures, attribution, workers, go-live, override, toggle, execution-mode, and all compound commands that reference removed features.

- [ ] **Step 2: Update help text and command router**

Update `_cmd_help()` to list only the 15 kept commands.

- [ ] **Step 3: Update readline completions in __main__.py**

Update the completion list (line 362-399 in `__main__.py`) to only include the 15 kept commands.

- [ ] **Step 4: Run tests, fix breakage**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "simplify: trim REPL to 15 essential commands"
```

---

### Task 15: Remove Real Trading (Paper Only)

**Files:**
- Delete: `app/agents/front_office/trading/zerodha_broker.py`
- Delete: `app/agents/front_office/trading/paper_crypto_broker.py`
- Modify: execution agent to use paper broker only

- [ ] **Step 1: Delete broker files**

```bash
rm app/agents/front_office/trading/zerodha_broker.py
rm app/agents/front_office/trading/paper_crypto_broker.py
```

- [ ] **Step 2: Fix references**

Remove broker selection logic. Hardcode paper broker. Remove connect/disconnect commands.

- [ ] **Step 3: Run tests, fix breakage**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "simplify: paper trading only, remove real brokers"
```

---

### Task 16: Clean All Breadcrumbs

**Files:**
- All files in `app/`

- [ ] **Step 1: Search for any references to removed features**

```bash
grep -rn "regime\|GARCH\|EVT\|HRP\|Kelly\|Heston\|MPC\|circuit.breaker\|kill.switch\|Thompson\|walk.forward\|monte.carlo\|stress.test\|macro.factor\|drift\|plugin\|pro\|advanced\|elite\|module" app/ --include="*.py" -i
```

- [ ] **Step 2: Remove or rewrite any matches**

Remove comments, docstrings, or code referencing removed features. The code should read as if these features never existed.

- [ ] **Step 3: Search for TODO/FIXME/HACK references**

```bash
grep -rn "TODO\|FIXME\|HACK\|PLACEHOLDER\|REMOVED\|SIMPLIFIED\|was\|used to\|previously\|originally" app/ --include="*.py" -i
```

Remove anything that hints at prior complexity.

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`
All tests should pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "clean: remove all references to advanced features"
```

---

### Task 17: Update Tests

**Files:**
- Modify: `tests/test_smoke.py`
- Modify: `tests/test_integration.py`
- Delete tests referencing removed features

- [ ] **Step 1: Remove tests for deleted features**

Delete or update any tests that reference: regime detection, circuit breakers, stress testing, walk-forward, monte carlo, advanced risk, HRP, Kelly, kill switch, macro factors, model registry, etc.

- [ ] **Step 2: Add tests for new sentiment agent**

Already done in Task 4.

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Target: all pass, 0 fail, 0 error

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: update test suite for simplified college project"
```

---

### Task 18: Update Documentation and Config

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml` (remove unused dependencies)
- Delete: docs referencing advanced features

- [ ] **Step 1: Simplify pyproject.toml**

Remove dependencies: jumpmodels, hmmlearn, scipy (if only used by removed code), scikit-learn (if only used by removed code). Keep: fastapi, sqlalchemy, rich, pydantic, yfinance, httpx, ta, alpaca-py, bcrypt, structlog.

- [ ] **Step 2: Update README to describe college project**

Rewrite as a college-level AI trading platform. No mention of advanced features.

- [ ] **Step 3: Remove advanced docs**

Delete or simplify: TECHNICAL_DEEP_DIVE.md, AUDIT.md, RESEARCH_PAPERS.md, VISION.md if they reference advanced capabilities.

- [ ] **Step 4: Final full test run**

Run: `python -m pytest tests/ -v`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: update documentation for college project"
```

---

### Task 19: Wire Sentiment into Dashboard and Strategy

**Files:**
- Modify: `app/tui/dashboard.py`
- Modify: `app/__main__.py`

- [ ] **Step 1: Add sentiment panel to dashboard**

Add a `_build_sentiment_panel()` method that displays per-symbol sentiment scores (positive/negative/neutral with color coding). Wire it into `build_layout()`.

- [ ] **Step 2: Start SentimentAgent in __main__.py**

Add SentimentAgent instantiation and startup alongside other agents. Subscribe dashboard to SENTIMENT_UPDATE messages.

- [ ] **Step 3: Add 'sentiment' REPL command**

In commands.py, add a handler that displays current sentiment scores for all tracked symbols.

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: wire sentiment into dashboard and REPL"
```

---

### Task 20: Final Verification

- [ ] **Step 1: Run the application**

```bash
cd backend && python -m app
```

Verify: dashboard loads, agents start, data feeds connect, no errors.

- [ ] **Step 2: Test key flows**

- Type `portfolio` — should show empty portfolio
- Type `signals` — should show generated signals
- Type `debate history` — should show debate records
- Type `sentiment` — should show sentiment scores
- Type `backtest AAPL` — should run basic backtest
- Type `health` — should show system health
- Type `quit` — should shut down cleanly

- [ ] **Step 3: Run lint**

Run: `ruff check app/`
Expected: 0 errors

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "college project: complete simplification"
```
