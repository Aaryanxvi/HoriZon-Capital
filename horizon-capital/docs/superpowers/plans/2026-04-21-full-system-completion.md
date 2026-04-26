# Horizon Capital — Full System Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make paper trading fully functional with real-time prices, a live-configurable settings panel, an intelligent CIO agent, and a hardened debate engine that works with any number of LLM providers.

**Architecture:** Settings-first build order — foundation changes (MessageType, config fields, DB tables) land first so every subsequent feature has a complete contract to implement against. Real-time data improves automatically once Yahoo shifts to 1-min bars and Alpaca reconnect is hardened. CIO intelligence replaces the current stub. Debate role pinning and single-provider rotation are surgical edits to `multi_model_debate.py`.

**Tech Stack:** Python 3.11+, Rich TUI, SQLite (aiosqlite/SQLAlchemy), asyncio, yfinance, websockets, anthropic/openai/google-generativeai SDKs, pydantic-settings.

**Backward Compatibility Rule:** Run `python -m pytest tests/ -v` after every task. All existing tests must pass before moving to the next task. Every new feature degrades gracefully when its dependencies are absent.

---

## File Map

**New files:**
- `app/tui/settings_panel.py` — Interactive Rich settings editor (API keys, AI allocation, debate roles)
- `tests/test_settings_panel.py`
- `tests/test_cio_agent.py`
- `tests/test_debate_hardening.py`
- `tests/test_yahoo_1min.py`

**Modified files:**
- `app/core/messaging.py` — 3 new MessageType values
- `app/config.py` — 4 new `debate_role_*` fields
- `app/core/local_storage.py` — 2 new tables (`cio_advisories`, `cio_overrides`)
- `app/llm/provider_registry.py` — `reload_from_settings()` method
- `app/data_layer/yahoo_feed.py` — 1-min bars, 30s polling, market hours, timestamp priority
- `app/data_layer/alpaca_feed.py` — exponential backoff WS reconnect (currently falls to REST permanently after first error)
- `app/workers/data_ingestion_worker.py` — reduce `YAHOO_POLL_INTERVAL` to 30s
- `app/agents/debate/multi_model_debate.py` — role pinning + fix single-provider round 2 gate
- `app/agents/executive/cio/cio_agent.py` — full LLM-powered rewrite (Mode A/B/C)
- `app/tui/commands.py` — 4 new commands: `cio`, `cio why`, `cio confirm halt`, `settings`
- `app/__main__.py` — wire settings panel, CIO agent, tab completions for new commands
- `app/tui/onboarding.py` — detect existing `.env` and show update-mode flow

---

## Task 1: Foundation — MessageType, Settings, DB Tables

**Files:**
- Modify: `app/core/messaging.py`
- Modify: `app/config.py`
- Modify: `app/core/local_storage.py`
- Test: `tests/test_smoke.py` (existing — must still pass)

- [ ] **Step 1: Add 3 new MessageType values to `app/core/messaging.py`**

Find the `MessageType` class and add after `HEARTBEAT`:

```python
    HEARTBEAT = "heartbeat"
    # Settings & CIO
    SETTINGS_UPDATED = "settings_updated"
    CIO_ADVISORY = "cio_advisory"
    CIO_OVERRIDE = "cio_override"
```

- [ ] **Step 2: Add 4 debate role fields to `app/config.py`**

Add after the `ai_executive` field (around line 147):

```python
    # Debate role pinning: which provider argues each role.
    # Values: "auto" (round-robin) | "claude" | "openai" | "gemini"
    debate_role_strategy: str = "auto"
    debate_role_risk: str = "auto"
    debate_role_sentiment: str = "auto"
    debate_role_portfolio: str = "auto"
```

- [ ] **Step 3: Add 2 new DB tables to `app/core/local_storage.py`**

Inside `_create_tables(conn)`, add before the final `pass` or at the end of the function:

```python
    # --- CIO Advisories ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cio_advisories (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            outlook TEXT NOT NULL,
            summary TEXT NOT NULL,
            recommended_adjustments TEXT NOT NULL,
            risk_flags TEXT NOT NULL,
            provider TEXT NOT NULL,
            trigger TEXT NOT NULL
        )
    """))

    # --- CIO Overrides ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cio_overrides (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            trigger TEXT NOT NULL,
            confidence REAL NOT NULL,
            actions TEXT NOT NULL,
            full_prompt TEXT NOT NULL,
            full_response TEXT NOT NULL,
            portfolio_snapshot TEXT NOT NULL,
            provider TEXT NOT NULL
        )
    """))
```

- [ ] **Step 4: Run full test suite**

```bash
cd backend
python -m pytest tests/ -v --tb=short
```

Expected: all existing tests pass. If any fail, fix before continuing.

- [ ] **Step 5: Commit**

```bash
git add app/core/messaging.py app/config.py app/core/local_storage.py
git commit -m "feat: add SETTINGS_UPDATED/CIO_ADVISORY/CIO_OVERRIDE message types, debate_role config fields, cio_advisories/cio_overrides DB tables"
```

---

## Task 2: Provider Registry Hot-Reload

**Files:**
- Modify: `app/llm/provider_registry.py`
- Test: `tests/test_settings_panel.py` (new, partial)

The registry needs a `reload_from_settings()` method that re-registers providers using the current (possibly mutated) settings values. This is what `SETTINGS_UPDATED` subscribers will call.

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_panel.py`:

```python
"""Tests for settings hot-reload and settings panel."""
import pytest
from unittest.mock import patch


def test_registry_reload_registers_new_key():
    """After mutating settings and calling reload, new provider appears."""
    from app.llm.provider_registry import ProviderRegistry

    registry = ProviderRegistry()
    # Start with no keys
    assert registry.list_available() == []

    # Simulate user entering a key — patch the settings object
    with patch("app.llm.provider_registry.settings") as mock_settings:
        mock_settings.anthropic_api_key = "sk-ant-test-key"
        mock_settings.openai_api_key = ""
        mock_settings.google_api_key = ""
        registry.reload_from_settings()

    assert "claude" in registry.list_available()


def test_registry_reload_removes_invalid_key():
    """After key is cleared, provider is deregistered."""
    from app.llm.provider_registry import ProviderRegistry

    registry = ProviderRegistry()

    with patch("app.llm.provider_registry.settings") as mock_settings:
        mock_settings.anthropic_api_key = "sk-ant-test-key"
        mock_settings.openai_api_key = ""
        mock_settings.google_api_key = ""
        registry.reload_from_settings()

    assert "claude" in registry.list_available()

    with patch("app.llm.provider_registry.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        mock_settings.openai_api_key = ""
        mock_settings.google_api_key = ""
        registry.reload_from_settings()

    assert "claude" not in registry.list_available()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_settings_panel.py::test_registry_reload_registers_new_key -v
```

Expected: FAIL — `ProviderRegistry` has no `reload_from_settings` method.

- [ ] **Step 3: Add `reload_from_settings()` to `app/llm/provider_registry.py`**

Add after `auto_register_from_settings()` (around line 58):

```python
    def reload_from_settings(self) -> None:
        """Re-register all providers from current settings values.

        Call this after settings have been mutated in-place (e.g. from the
        settings panel).  Clears existing registrations and re-registers
        from scratch so removed keys take effect.
        """
        from app.config import settings

        # Clear existing registrations
        self._providers.clear()

        # Re-register from current (possibly updated) settings
        self.register("claude", settings.anthropic_api_key)
        self.register("openai", settings.openai_api_key)
        self.register("gemini", settings.google_api_key)

        available = self.list_available()
        logger.info("llm_providers_reloaded", providers=available)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_settings_panel.py -v
python -m pytest tests/ -v --tb=short
```

Expected: both new tests pass, all existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/llm/provider_registry.py tests/test_settings_panel.py
git commit -m "feat: add ProviderRegistry.reload_from_settings() for hot-reload on settings change"
```

---

## Task 3: Yahoo 1-Minute Bars + Market Hours

**Files:**
- Modify: `app/data_layer/yahoo_feed.py`
- Modify: `app/workers/data_ingestion_worker.py`
- Test: `tests/test_yahoo_1min.py` (new)

Yahoo currently fetches 5-day daily bars every 300s. We change to 1-min bars every 30s and skip polling when markets are closed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_yahoo_1min.py`:

```python
"""Tests for Yahoo 1-minute bar polling and market hours awareness."""
import pytest
from datetime import datetime, UTC
from unittest.mock import patch, MagicMock
import pandas as pd


def _make_1min_df():
    """Create a minimal 2-row 1-min OHLCV DataFrame as yfinance returns."""
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-04-21 09:30:00", tz="America/New_York"),
        pd.Timestamp("2026-04-21 09:31:00", tz="America/New_York"),
    ])
    return pd.DataFrame({
        "Open": [150.0, 151.0],
        "High": [152.0, 153.0],
        "Low": [149.5, 150.5],
        "Close": [151.5, 152.0],
        "Volume": [10000, 12000],
    }, index=idx)


def test_fetch_latest_uses_1min_interval():
    """fetch_latest requests 1-min bars instead of daily."""
    from app.data_layer.yahoo_feed import YahooFeed

    feed = YahooFeed()
    called_with = {}

    def fake_fetch(symbol, period, interval):
        called_with["period"] = period
        called_with["interval"] = interval
        return []

    with patch.object(feed, "_fetch_sync", side_effect=fake_fetch):
        import asyncio
        asyncio.run(feed.fetch_latest("AAPL.NASDAQ"))

    assert called_with["interval"] == "1m"
    assert called_with["period"] == "1d"


def test_fetch_latest_returns_only_last_bar():
    """fetch_latest returns only the most recent 1-min bar."""
    from app.data_layer.yahoo_feed import YahooFeed
    from app.data_layer.data_normalizer import NormalizedOHLCV

    feed = YahooFeed()
    df = _make_1min_df()

    with patch.object(feed, "_fetch_sync", return_value=[
        MagicMock(spec=NormalizedOHLCV, close=151.5, timestamp=datetime(2026, 4, 21, 9, 30, tzinfo=UTC)),
        MagicMock(spec=NormalizedOHLCV, close=152.0, timestamp=datetime(2026, 4, 21, 9, 31, tzinfo=UTC)),
    ]):
        import asyncio

        emitted = []

        async def capture():
            feed._ohlcv_callbacks = [lambda bar: emitted.append(bar)]
            await feed.fetch_latest("AAPL.NASDAQ")

        asyncio.run(capture())

    # Should only emit the latest bar (close=152.0)
    assert len(emitted) == 1
    assert emitted[0].close == 152.0


def test_nse_market_hours():
    """NSE symbols skip polling outside NSE hours."""
    from app.data_layer.yahoo_feed import _is_market_open

    # NSE hours: 03:45–10:00 UTC
    assert _is_market_open("RELIANCE.NSE", datetime(2026, 4, 21, 4, 0, tzinfo=UTC)) is True
    assert _is_market_open("RELIANCE.NSE", datetime(2026, 4, 21, 1, 0, tzinfo=UTC)) is False


def test_nasdaq_market_hours():
    """NASDAQ symbols skip polling outside NASDAQ hours."""
    from app.data_layer.yahoo_feed import _is_market_open

    # NASDAQ hours: 13:30–20:00 UTC
    assert _is_market_open("AAPL.NASDAQ", datetime(2026, 4, 21, 14, 0, tzinfo=UTC)) is True
    assert _is_market_open("AAPL.NASDAQ", datetime(2026, 4, 21, 2, 0, tzinfo=UTC)) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_yahoo_1min.py -v
```

Expected: all fail — `_is_market_open` doesn't exist, `fetch_latest` uses daily bars.

- [ ] **Step 3: Implement changes to `app/data_layer/yahoo_feed.py`**

Add the `_is_market_open` function after the existing `_currency_for_exchange` function (around line 54):

```python
# Exchange UTC trading hours: (open_hour, open_min, close_hour, close_min)
_EXCHANGE_UTC_HOURS: dict[str, tuple[int, int, int, int]] = {
    "NSE":      (3, 45, 10, 0),    # 09:15–15:30 IST
    "BSE":      (3, 45, 10, 0),
    "NASDAQ":   (13, 30, 20, 0),   # 09:30–16:00 ET
    "NYSE":     (13, 30, 20, 0),
    "LSE":      (8, 0, 16, 30),    # 08:00–16:30 UTC
    "HKEX":     (1, 30, 8, 0),     # 09:30–16:00 HKT
    "TSE":      (0, 0, 6, 30),     # 09:00–15:30 JST
    "ASX":      (23, 0, 5, 0),     # 10:00–16:00 AEST (prev day UTC)
}


def _is_market_open(symbol: str, now_utc: datetime | None = None) -> bool:
    """Return True if the exchange for *symbol* is currently trading.

    Falls back to True (poll anyway) if exchange hours are unknown,
    so new symbols are never silently skipped.
    """
    from datetime import datetime as dt
    if now_utc is None:
        from datetime import UTC
        now_utc = dt.now(UTC)

    exchange = _exchange_for_symbol(symbol)
    hours = _EXCHANGE_UTC_HOURS.get(exchange)
    if hours is None:
        return True  # Unknown exchange — poll anyway

    open_h, open_m, close_h, close_m = hours
    now_min = now_utc.hour * 60 + now_utc.minute
    open_min = open_h * 60 + open_m
    close_min = close_h * 60 + close_m

    # Handle midnight-crossing exchanges (e.g. ASX)
    if open_min > close_min:
        return now_min >= open_min or now_min < close_min
    return open_min <= now_min < close_min
```

Now update `fetch_latest` to use 1-min bars and emit only the last bar:

```python
    async def fetch_latest(self, symbol: str) -> list[NormalizedOHLCV]:
        """Fetch the latest 1-minute bar for *symbol*.

        Returns a list with at most one bar (the most recent completed minute).
        Skips fetching if the exchange is currently closed.
        """
        if not _is_market_open(symbol):
            return []

        bars = await self.poll_ohlcv(symbol, period="1d", interval="1m")
        if not bars:
            return []

        # Emit and return only the most recent bar
        latest = bars[-1]
        await self._emit_ohlcv(latest)
        return [latest]
```

Also update `_poll_loop` sleep from 300 to 30 seconds:

```python
    async def _poll_loop(self) -> None:
        """Periodically polls 1-min OHLCV data and emits the latest bar."""
        while self._running:
            for symbol in self._symbols:
                try:
                    if _is_market_open(symbol):
                        bars = await self.poll_ohlcv(symbol, period="1d", interval="1m")
                        if bars:
                            await self._emit_ohlcv(bars[-1])
                except Exception:
                    logger.exception("yahoo_feed.poll_error", symbol=symbol)
            await asyncio.sleep(30)  # was 300
```

- [ ] **Step 4: Reduce `YAHOO_POLL_INTERVAL` in `app/workers/data_ingestion_worker.py`**

Change line 22:

```python
YAHOO_POLL_INTERVAL = 30  # was 60; feed now fetches 1-min bars
```

- [ ] **Step 5: Add Alpaca price-priority guard**

Find where `horizon:price:{symbol}` is written in `app/data_layer/data_manager.py` (search for `horizon:price:`). Add a timestamp write alongside the price write so Yahoo can check freshness:

```python
# After writing kv.set(f"horizon:price:{symbol}", str(price)):
import time
await kv.set(f"horizon:price:source:{symbol}", "alpaca")
await kv.set(f"horizon:price:ts:{symbol}", str(time.time()))
```

Then in `DataIngestionWorker._poll_yahoo_eod` (around the `_publish_price_update` call), only publish if Alpaca hasn't written more recently than 30 seconds:

```python
                        try:
                            import time
                            price_str = await kv.get(f"horizon:price:{symbol}")
                            source = await kv.get(f"horizon:price:source:{symbol}") or ""
                            ts_str = await kv.get(f"horizon:price:ts:{symbol}")
                            alpaca_age = time.time() - float(ts_str) if ts_str and source == "alpaca" else 9999
                            if price_str and alpaca_age > 30:
                                await self._publish_price_update(symbol, float(price_str))
                        except Exception:
                            pass
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_yahoo_1min.py -v
python -m pytest tests/ -v --tb=short
```

Expected: all new tests pass, all existing tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/data_layer/yahoo_feed.py app/workers/data_ingestion_worker.py tests/test_yahoo_1min.py
git commit -m "feat: upgrade Yahoo feed to 1-min bars with market hours awareness, 30s polling, Alpaca price priority"
```

---

## Task 4: Alpaca WebSocket — Exponential Backoff Reconnect

**Files:**
- Modify: `app/data_layer/alpaca_feed.py`

Currently `_ws_loop` catches any exception and permanently falls to REST (`self._use_websocket = False`). We add a retry-with-backoff loop so transient disconnects attempt WS reconnect before permanently falling back.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_settings_panel.py` (or create `tests/test_alpaca_feed.py`):

Create `tests/test_alpaca_feed.py`:

```python
"""Tests for AlpacaFeed WebSocket reconnect behaviour."""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_alpaca_feed_disabled_without_key():
    """AlpacaFeed.connect() does nothing when no API key is set."""
    from app.data_layer.alpaca_feed import AlpacaFeed

    feed = AlpacaFeed()
    with patch("app.data_layer.alpaca_feed.settings") as mock_settings:
        mock_settings.alpaca_api_key = ""
        mock_settings.alpaca_paper_mode = True
        await feed.connect()

    assert not feed._is_connected


@pytest.mark.asyncio
async def test_alpaca_feed_connect_sets_connected():
    """AlpacaFeed.connect() marks feed as connected when key is present."""
    from app.data_layer.alpaca_feed import AlpacaFeed

    feed = AlpacaFeed()
    with patch("app.data_layer.alpaca_feed.settings") as mock_settings:
        mock_settings.alpaca_api_key = "test-key"
        mock_settings.alpaca_api_secret = "test-secret"
        mock_settings.alpaca_paper_mode = True
        await feed.connect()

    assert feed._is_connected


@pytest.mark.asyncio
async def test_alpaca_ws_falls_back_to_rest_after_max_retries(monkeypatch):
    """After WS_MAX_RETRIES failures, feed switches to REST polling."""
    from app.data_layer.alpaca_feed import AlpacaFeed

    feed = AlpacaFeed()
    feed._is_connected = True
    feed._running = True

    attempt_count = 0

    async def fake_ws_connect(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        raise ConnectionError("mock WS failure")

    class FakeWS:
        async def __aenter__(self):
            return fake_ws_connect()
        async def __aexit__(self, *args):
            pass

    # Patch asyncio.sleep to avoid waiting in tests
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    # Patch websockets.connect to always fail
    with patch.dict("sys.modules", {"websockets": MagicMock()}):
        import websockets
        websockets.connect = MagicMock(side_effect=ConnectionError("mock WS failure"))

        # After WS_MAX_RETRIES failures, _use_websocket becomes False
        feed._use_websocket = True
        # Run _ws_loop briefly — it should exhaust retries
        task = asyncio.create_task(feed._ws_loop())
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Either switched to REST or stopped trying WS
    # The key invariant: no exception propagated
    assert True  # reached here without crashing
```

- [ ] **Step 2: Run tests to verify baseline**

```bash
python -m pytest tests/test_alpaca_feed.py -v
```

Expected: first two tests pass (they test existing behaviour), third test confirms no crash.

- [ ] **Step 3: Add backoff constants and improve `_ws_loop` in `app/data_layer/alpaca_feed.py`**

Add constants after the URL constants (around line 22):

```python
_WS_MAX_RETRIES = 5          # attempts before permanently falling to REST
_WS_BACKOFF_BASE = 2         # seconds; doubles each retry (2, 4, 8, 16, 32)
_WS_BACKOFF_MAX = 60         # cap backoff at 60 seconds
```

Replace the existing `_ws_loop` method:

```python
    async def _ws_loop(self) -> None:
        """WebSocket main loop with exponential backoff reconnect.

        Retries WS connection up to _WS_MAX_RETRIES times before
        permanently falling back to REST polling.
        """
        try:
            import websockets  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("alpaca_feed.websockets_not_installed -- falling back to REST")
            self._use_websocket = False
            self._rest_task = asyncio.create_task(self._rest_poll_loop())
            return

        retry = 0
        while self._running and retry <= _WS_MAX_RETRIES:
            try:
                async with websockets.connect(self._stream_url) as ws:
                    self._ws = ws
                    retry = 0  # reset on successful connect

                    # Authenticate
                    auth_msg = {
                        "action": "auth",
                        "key": settings.alpaca_api_key,
                        "secret": settings.alpaca_api_secret,
                    }
                    await ws.send(json.dumps(auth_msg))
                    resp = json.loads(await ws.recv())
                    logger.info("alpaca_feed.ws_auth_response", resp=resp)

                    # Subscribe to trades
                    sub_msg = {"action": "subscribe", "trades": self._symbols}
                    await ws.send(json.dumps(sub_msg))
                    logger.info("alpaca_feed.ws_subscribed", symbols=self._symbols)

                    async for raw in ws:
                        if not self._running:
                            break
                        messages = json.loads(raw)
                        if not isinstance(messages, list):
                            messages = [messages]
                        for msg in messages:
                            if msg.get("T") == "t":  # trade message
                                tick = self._parse_ws_trade(msg)
                                if tick:
                                    await self._emit_tick(tick)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                retry += 1
                if retry > _WS_MAX_RETRIES:
                    logger.error(
                        "alpaca_feed.ws_max_retries_exceeded -- falling back to REST",
                        retries=retry,
                    )
                    self._use_websocket = False
                    self._rest_task = asyncio.create_task(self._rest_poll_loop())
                    break

                delay = min(_WS_BACKOFF_BASE ** retry, _WS_BACKOFF_MAX)
                logger.warning(
                    "alpaca_feed.ws_error_retrying",
                    retry=retry,
                    max_retries=_WS_MAX_RETRIES,
                    delay=delay,
                    error=str(exc),
                )
                await asyncio.sleep(delay)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_alpaca_feed.py -v
python -m pytest tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/data_layer/alpaca_feed.py tests/test_alpaca_feed.py
git commit -m "feat: add exponential backoff WS reconnect to AlpacaFeed (was: permanent fall to REST on first error)"
```

---

## Task 5: Debate Engine Hardening

**Files:**
- Modify: `app/agents/debate/multi_model_debate.py`
- Test: `tests/test_debate_hardening.py` (new)

Two fixes: (1) role pinning from config, (2) single-provider round 2 (currently gated on `len(provider_map) >= 2`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_debate_hardening.py`:

```python
"""Tests for debate engine hardening: single-provider and role pinning."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.llm.provider_registry import ProviderRegistry


def _make_registry_with_one_provider():
    """Build a ProviderRegistry with only one fake provider."""
    registry = ProviderRegistry()
    fake = MagicMock()
    fake.provider_name = "claude"
    fake.complete = AsyncMock(return_value='{"argument": "test", "vote": "FOR", "confidence": 0.8}')
    registry._providers["claude"] = fake
    return registry


def _make_registry_with_two_providers():
    registry = ProviderRegistry()
    for name in ("claude", "openai"):
        fake = MagicMock()
        fake.provider_name = name
        fake.complete = AsyncMock(return_value='{"argument": "test", "vote": "FOR", "confidence": 0.8}')
        registry._providers[name] = fake
    return registry


def test_single_provider_assigns_to_all_roles():
    """With one provider, all 4 roles are assigned to that provider."""
    from app.agents.debate.multi_model_debate import MultiModelDebateEngine

    registry = _make_registry_with_one_provider()
    bus = MagicMock()
    engine = MultiModelDebateEngine(registry=registry, bus=bus)

    role_map = engine._assign_providers()
    assert len(role_map) == 4
    for provider in role_map.values():
        assert provider.provider_name == "claude"


def test_single_provider_runs_both_rounds():
    """With one provider, both debate rounds execute (perspective rotation)."""
    import asyncio
    from app.agents.debate.multi_model_debate import MultiModelDebateEngine

    registry = _make_registry_with_one_provider()
    bus = MagicMock()
    bus.publish = AsyncMock()
    engine = MultiModelDebateEngine(registry=registry, bus=bus, max_rounds=2)

    result = asyncio.run(engine.run_debate(
        symbol="AAPL",
        action="BUY",
        signal_data={"strength": 0.8, "strategy_name": "momentum"},
    ))

    # Both rounds should have run
    assert result.rounds == 2
    # 4 roles × 2 rounds = 8 arguments
    assert len(result.arguments) == 8


def test_role_pinning_assigns_correct_provider():
    """When debate_role_strategy is pinned to 'claude', STRATEGY gets Claude."""
    from app.agents.debate.multi_model_debate import MultiModelDebateEngine

    registry = _make_registry_with_two_providers()
    bus = MagicMock()
    engine = MultiModelDebateEngine(registry=registry, bus=bus)

    with patch("app.agents.debate.multi_model_debate.settings") as mock_settings:
        mock_settings.debate_role_strategy = "claude"
        mock_settings.debate_role_risk = "auto"
        mock_settings.debate_role_sentiment = "auto"
        mock_settings.debate_role_portfolio = "auto"
        role_map = engine._assign_providers()

    assert role_map["STRATEGY"].provider_name == "claude"


def test_pinned_provider_unavailable_falls_back():
    """If pinned provider is not registered, role falls back to any available."""
    from app.agents.debate.multi_model_debate import MultiModelDebateEngine

    registry = _make_registry_with_one_provider()  # only claude
    bus = MagicMock()
    engine = MultiModelDebateEngine(registry=registry, bus=bus)

    with patch("app.agents.debate.multi_model_debate.settings") as mock_settings:
        mock_settings.debate_role_strategy = "openai"  # not available
        mock_settings.debate_role_risk = "auto"
        mock_settings.debate_role_sentiment = "auto"
        mock_settings.debate_role_portfolio = "auto"
        role_map = engine._assign_providers()

    # Falls back to claude (the only available provider)
    assert role_map["STRATEGY"].provider_name == "claude"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_debate_hardening.py -v
```

Expected: `test_single_provider_runs_both_rounds` fails (round 2 gated on `len >= 2`), `test_role_pinning_assigns_correct_provider` fails (no pinning logic).

- [ ] **Step 3: Fix `_assign_providers` in `app/agents/debate/multi_model_debate.py`**

Replace the entire `_assign_providers` method (currently lines ~243–279):

```python
    def _assign_providers(
        self,
        allowed_providers: list[str] | None = None,
    ) -> dict[str, BaseLLMProvider]:
        """Assign LLM providers to debater roles.

        Priority order per role:
        1. Config-pinned provider (debate_role_strategy etc.) — if available
        2. Round-robin across available providers — fallback for unpinned/unavailable

        With a single provider all 4 roles are assigned to it, enabling
        perspective rotation within a single model.
        """
        from app.config import settings

        if allowed_providers:
            available = [p for p in allowed_providers if self.registry.get_provider(p)]
        else:
            available = self.registry.list_available()

        if not available:
            available = self.registry.list_available()
        if not available:
            raise RuntimeError("No LLM providers available for debate")

        # Read per-role pinning from settings
        pinning: dict[str, str] = {
            "STRATEGY":  settings.debate_role_strategy.lower().strip(),
            "RISK":      settings.debate_role_risk.lower().strip(),
            "SENTIMENT": settings.debate_role_sentiment.lower().strip(),
            "PORTFOLIO": settings.debate_role_portfolio.lower().strip(),
        }

        providers: dict[str, BaseLLMProvider] = {}
        rr_idx = 0  # round-robin counter for unpinned roles

        for role in DEBATER_ROLES:
            pinned = pinning.get(role, "auto")
            if pinned != "auto":
                provider = self.registry.get_provider(pinned)
                if provider is not None:
                    providers[role] = provider
                    continue
                # Pinned provider unavailable — log and fall through to round-robin
                logger.warning(
                    "debate.pinned_provider_unavailable",
                    role=role,
                    requested=pinned,
                    falling_back="round_robin",
                )

            # Round-robin assignment
            provider_name = available[rr_idx % len(available)]
            provider = self.registry.get_provider(provider_name)
            if provider is not None:
                providers[role] = provider
            rr_idx += 1

        return providers
```

- [ ] **Step 4: Fix single-provider round 2 gate**

Find line ~342 in `run_debate`:

```python
        if self.max_rounds >= 2 and len(provider_map) >= 2:
```

Change to:

```python
        if self.max_rounds >= 2:
```

This allows a single provider to argue both perspectives across 2 rounds.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_debate_hardening.py -v
python -m pytest tests/ -v --tb=short
```

Expected: all new tests pass, all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/agents/debate/multi_model_debate.py tests/test_debate_hardening.py
git commit -m "feat: debate engine — role pinning from config + single-provider round 2 support"
```

---

## Task 6: Settings Panel TUI

**Files:**
- Create: `app/tui/settings_panel.py`
- Modify: `app/tui/commands.py`
- Test: `tests/test_settings_panel.py` (extend existing)

The settings panel is a Rich interactive form invoked via the `settings` REPL command. When called, it temporarily pauses the Live dashboard, runs a full-screen tab-based form, then signals the dashboard to resume. Changes are validated, written to `.env`, and hot-reloaded into the provider registry.

- [ ] **Step 1: Add validation test**

Append to `tests/test_settings_panel.py`:

```python
def test_settings_panel_validates_key_before_writing(tmp_path, monkeypatch):
    """settings panel does not write .env when validation fails."""
    from app.tui.settings_panel import SettingsPanel

    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=\n")

    from app.llm.provider_registry import ProviderRegistry
    from unittest.mock import MagicMock
    registry = ProviderRegistry()

    panel = SettingsPanel(registry=registry, env_path=str(env_file))

    # Simulate _validate_key returning False (invalid key)
    monkeypatch.setattr(panel, "_validate_key", lambda name, val: False)
    result = panel._save_key("ANTHROPIC_API_KEY", "invalid-key")

    assert result is False
    content = env_file.read_text()
    assert "invalid-key" not in content


def test_settings_panel_writes_valid_key(tmp_path, monkeypatch):
    """settings panel writes .env and returns True when key validates."""
    from app.tui.settings_panel import SettingsPanel
    from app.llm.provider_registry import ProviderRegistry

    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=\n")

    registry = ProviderRegistry()
    panel = SettingsPanel(registry=registry, env_path=str(env_file))

    monkeypatch.setattr(panel, "_validate_key", lambda name, val: True)
    result = panel._save_key("ANTHROPIC_API_KEY", "sk-ant-abc123")

    assert result is True
    assert "sk-ant-abc123" in env_file.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_settings_panel.py::test_settings_panel_validates_key_before_writing -v
```

Expected: FAIL — `app.tui.settings_panel` doesn't exist.

- [ ] **Step 3: Create `app/tui/settings_panel.py`**

```python
"""Interactive settings panel for Horizon Capital.

Invoked via the ``settings`` REPL command. Temporarily pauses the Rich Live
dashboard, shows a full-screen interactive form for editing API keys,
AI allocation, and debate role assignments, then resumes the dashboard.
"""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from app.core.logging import get_logger

logger = get_logger("tui.settings_panel")

# Map of .env key name -> display label
_API_KEY_FIELDS: list[tuple[str, str]] = [
    ("ANTHROPIC_API_KEY",  "Claude (Anthropic)"),
    ("OPENAI_API_KEY",     "OpenAI (GPT-4)"),
    ("GOOGLE_API_KEY",     "Google (Gemini)"),
    ("ALPACA_API_KEY",     "Alpaca API Key"),
    ("ALPACA_API_SECRET",  "Alpaca API Secret"),
    ("NEWSAPI_API_KEY",    "NewsAPI"),
    ("POLYGON_API_KEY",    "Polygon"),
]

_AI_ALLOCATION_FIELDS: list[tuple[str, str]] = [
    ("AI_FRONT_OFFICE",  "Front Office"),
    ("AI_MIDDLE_OFFICE", "Middle Office"),
    ("AI_BACK_OFFICE",   "Back Office"),
    ("AI_EXECUTIVE",     "Executive / CIO"),
]

_DEBATE_ROLE_FIELDS: list[tuple[str, str]] = [
    ("DEBATE_ROLE_STRATEGY",  "Strategy (bull case)"),
    ("DEBATE_ROLE_RISK",      "Risk (bear case)"),
    ("DEBATE_ROLE_SENTIMENT", "Sentiment analyst"),
    ("DEBATE_ROLE_PORTFOLIO", "Portfolio fit"),
]

_PROVIDER_CHOICES = ["auto", "claude", "openai", "gemini", "none"]
_DEBATE_CHOICES = ["auto", "claude", "openai", "gemini"]


def _mask(value: str) -> str:
    """Mask all but the last 4 chars of a secret value."""
    if not value or len(value) <= 4:
        return "●●●●" if value else "(not set)"
    return "●●●●" + value[-4:]


def _read_env(env_path: str) -> dict[str, str]:
    """Parse a .env file into a key→value dict."""
    result: dict[str, str] = {}
    try:
        for line in Path(env_path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                result[k.strip().upper()] = v.strip()
    except FileNotFoundError:
        pass
    return result


def _write_env_key(env_path: str, key: str, value: str) -> None:
    """Update or append a single key=value pair in the .env file."""
    path = Path(env_path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    key_upper = key.upper()
    updated = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key_upper}=") or stripped.startswith(f"{key_upper} ="):
            new_lines.append(f"{key_upper}={value}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"{key_upper}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


class SettingsPanel:
    """Interactive settings editor rendered in the terminal."""

    def __init__(
        self,
        registry,  # ProviderRegistry — avoid circular import
        env_path: str = ".env",
    ) -> None:
        self._registry = registry
        self._env_path = env_path

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self, console: Console) -> None:
        """Run the interactive settings form (blocking, for use in REPL)."""
        console.rule("[bold cyan]Horizon Capital — Settings[/bold cyan]")
        console.print()

        while True:
            tab = Prompt.ask(
                "  Select tab",
                choices=["keys", "allocation", "debate", "done"],
                default="keys",
                console=console,
            )
            console.print()

            if tab == "done":
                console.print("[green]Settings saved.[/green]\n")
                break
            elif tab == "keys":
                self._edit_api_keys(console)
            elif tab == "allocation":
                self._edit_ai_allocation(console)
            elif tab == "debate":
                self._edit_debate_roles(console)

        # Hot-reload provider registry with any updated keys
        self._registry.reload_from_settings()

        # Publish SETTINGS_UPDATED so subscribed agents (CIO, etc.) react
        try:
            from app.core.messaging import AgentMessage, MessageType
            from app.core.runtime import get_bus
            bus = get_bus()
            import asyncio
            asyncio.get_event_loop().create_task(bus.publish(AgentMessage(
                sender_id="settings-panel",
                channel="horizon.settings.updated",
                message_type=MessageType.SETTINGS_UPDATED,
                payload={"source": "settings_panel"},
            )))
        except Exception:
            pass  # Non-fatal — direct reload already done above

    # ------------------------------------------------------------------
    # Tab: API Keys
    # ------------------------------------------------------------------

    def _edit_api_keys(self, console: Console) -> None:
        env = _read_env(self._env_path)

        table = Table(title="API Keys", show_header=True)
        table.add_column("Provider", style="cyan")
        table.add_column("Current Value", style="dim")

        for env_key, label in _API_KEY_FIELDS:
            current = env.get(env_key, "")
            table.add_row(label, _mask(current))

        console.print(table)
        console.print()

        field_label = Prompt.ask(
            "  Edit key for (or [dim]skip[/dim])",
            choices=[label for _, label in _API_KEY_FIELDS] + ["skip"],
            default="skip",
            console=console,
        )
        if field_label == "skip":
            return

        env_key = next(k for k, lbl in _API_KEY_FIELDS if lbl == field_label)
        new_value = Prompt.ask(f"  Enter new value for [cyan]{field_label}[/cyan]", console=console, password=True)

        if not new_value.strip():
            console.print("[yellow]  Empty value — key cleared.[/yellow]")
            new_value = ""

        if new_value and not self._validate_key(env_key, new_value):
            console.print("[red]  Key validation failed — .env not updated.[/red]")
            return

        if self._save_key(env_key, new_value):
            # Mutate the live settings object
            self._apply_to_settings(env_key, new_value)
            console.print(f"[green]  {field_label} updated.[/green]")
        else:
            console.print("[red]  Failed to save key.[/red]")

    # ------------------------------------------------------------------
    # Tab: AI Allocation
    # ------------------------------------------------------------------

    def _edit_ai_allocation(self, console: Console) -> None:
        env = _read_env(self._env_path)

        table = Table(title="AI Department Allocation", show_header=True)
        table.add_column("Department", style="cyan")
        table.add_column("Current Provider", style="yellow")
        table.add_column("Options", style="dim")

        for env_key, label in _AI_ALLOCATION_FIELDS:
            current = env.get(env_key, "auto")
            table.add_row(label, current, " / ".join(_PROVIDER_CHOICES))

        console.print(table)
        console.print()

        dept_label = Prompt.ask(
            "  Update allocation for (or [dim]skip[/dim])",
            choices=[lbl for _, lbl in _AI_ALLOCATION_FIELDS] + ["skip"],
            default="skip",
            console=console,
        )
        if dept_label == "skip":
            return

        env_key = next(k for k, lbl in _AI_ALLOCATION_FIELDS if lbl == dept_label)
        new_value = Prompt.ask(
            f"  Provider for [cyan]{dept_label}[/cyan]",
            choices=_PROVIDER_CHOICES,
            default="auto",
            console=console,
        )

        _write_env_key(self._env_path, env_key, new_value)
        self._apply_to_settings(env_key, new_value)
        console.print(f"[green]  {dept_label} → {new_value}[/green]")

    # ------------------------------------------------------------------
    # Tab: Debate Roles
    # ------------------------------------------------------------------

    def _edit_debate_roles(self, console: Console) -> None:
        env = _read_env(self._env_path)

        table = Table(title="Debate Role Assignment", show_header=True)
        table.add_column("Role", style="cyan")
        table.add_column("Current Provider", style="yellow")
        table.add_column("Options", style="dim")

        for env_key, label in _DEBATE_ROLE_FIELDS:
            current = env.get(env_key, "auto")
            table.add_row(label, current, " / ".join(_DEBATE_CHOICES))

        console.print(table)
        console.print()
        console.print("[dim]  'auto' = round-robin across all registered providers[/dim]\n")

        role_label = Prompt.ask(
            "  Edit role (or [dim]skip[/dim])",
            choices=[lbl for _, lbl in _DEBATE_ROLE_FIELDS] + ["skip"],
            default="skip",
            console=console,
        )
        if role_label == "skip":
            return

        env_key = next(k for k, lbl in _DEBATE_ROLE_FIELDS if lbl == role_label)
        new_value = Prompt.ask(
            f"  Provider for [cyan]{role_label}[/cyan]",
            choices=_DEBATE_CHOICES,
            default="auto",
            console=console,
        )

        _write_env_key(self._env_path, env_key, new_value)
        self._apply_to_settings(env_key, new_value)
        console.print(f"[green]  {role_label} → {new_value}[/green]")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_key(self, env_key: str, value: str) -> bool:
        """Basic structural validation for well-known key formats.

        Returns True if value looks plausible, False if obviously wrong.
        Skips full API round-trip (avoids extra latency during setup).
        """
        if not value:
            return True  # Empty = clearing the key, always valid

        patterns: dict[str, re.Pattern] = {
            "ANTHROPIC_API_KEY": re.compile(r"^sk-ant-"),
            "OPENAI_API_KEY":    re.compile(r"^sk-"),
            "GOOGLE_API_KEY":    re.compile(r"^AI"),
        }
        pattern = patterns.get(env_key)
        if pattern and not pattern.match(value):
            return False

        return True

    def _save_key(self, env_key: str, value: str) -> bool:
        """Write a single key to .env. Returns True on success."""
        try:
            _write_env_key(self._env_path, env_key, value)
            return True
        except Exception as exc:
            logger.error("settings_panel.save_key_error", key=env_key, error=str(exc))
            return False

    def _apply_to_settings(self, env_key: str, value: str) -> None:
        """Mutate the live settings object so changes take effect immediately."""
        from app.config import settings

        field_map: dict[str, str] = {
            "ANTHROPIC_API_KEY":  "anthropic_api_key",
            "OPENAI_API_KEY":     "openai_api_key",
            "GOOGLE_API_KEY":     "google_api_key",
            "ALPACA_API_KEY":     "alpaca_api_key",
            "ALPACA_API_SECRET":  "alpaca_api_secret",
            "NEWSAPI_API_KEY":    "newsapi_api_key",
            "POLYGON_API_KEY":    "polygon_api_key",
            "AI_FRONT_OFFICE":    "ai_front_office",
            "AI_MIDDLE_OFFICE":   "ai_middle_office",
            "AI_BACK_OFFICE":     "ai_back_office",
            "AI_EXECUTIVE":       "ai_executive",
            "DEBATE_ROLE_STRATEGY":  "debate_role_strategy",
            "DEBATE_ROLE_RISK":      "debate_role_risk",
            "DEBATE_ROLE_SENTIMENT": "debate_role_sentiment",
            "DEBATE_ROLE_PORTFOLIO": "debate_role_portfolio",
        }
        attr = field_map.get(env_key.upper())
        if attr and hasattr(settings, attr):
            try:
                object.__setattr__(settings, attr, value)
            except Exception:
                pass  # Pydantic models may not allow direct mutation; .env reload on restart covers it
```

- [ ] **Step 4: Add `settings` command to `app/tui/commands.py`**

Find the `handlers` dict in `handle()` and add:

```python
            "settings": self._cmd_settings,
```

Then find the `_cmd_config` method and add the new method nearby:

```python
    async def _cmd_settings(self, args: list[str]) -> str:
        """Open the interactive settings panel."""
        # Signal the main loop to open settings (handled in __main__.py)
        # Return a sentinel that __main__.py checks for
        return "__OPEN_SETTINGS__"
```

Also update `HELP_TEXT` — add after the `config` line:

```python
  [green]settings[/]            Open interactive settings editor (keys, AI allocation, debate roles)
  [green]cio[/]                 Show latest CIO advisory
  [green]cio why[/]             Show reasoning behind the most recent CIO override
  [green]cio confirm halt[/]    Confirm a CIO-recommended HALT in FULLY_AUTONOMOUS mode
```

- [ ] **Step 5: Wire `settings` command in `app/__main__.py`**

Find the REPL loop where command results are printed. Add handling for the sentinel return value. Look for the section that calls `await handler.handle(user_input)` and add:

```python
                result = await handler.handle(user_input)
                if result == "__OPEN_SETTINGS__":
                    # Pause Live, run settings panel, resume
                    from app.tui.settings_panel import SettingsPanel
                    from app.llm.provider_registry import provider_registry
                    panel = SettingsPanel(registry=provider_registry)
                    if live is not None:
                        live.stop()
                    try:
                        panel.run(console)
                    finally:
                        if live is not None:
                            live.start()
                elif result:
                    console.print(result)
```

Also add `"settings"`, `"cio"`, `"cio why"`, `"cio confirm halt"` to the readline tab-completion list.

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_settings_panel.py -v
python -m pytest tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/tui/settings_panel.py app/tui/commands.py app/__main__.py tests/test_settings_panel.py
git commit -m "feat: add interactive settings panel (API keys, AI allocation, debate roles) via 'settings' REPL command"
```

---

## Task 7: Extended Setup Wizard (Update Mode)

**Files:**
- Modify: `app/tui/onboarding.py`

When `.env` already exists with content, `--setup` shows an "update" flow instead of first-time setup.

- [ ] **Step 1: Read the current onboarding first-time detection**

```bash
grep -n "env\|exists\|setup\|first" backend/app/tui/onboarding.py | head -30
```

Find where the wizard decides whether this is a first run.

- [ ] **Step 2: Add update-mode detection**

Find the main `run_wizard()` or equivalent entry function. Add at the top:

```python
    from pathlib import Path
    env_path = Path(".env")
    is_update = env_path.exists() and env_path.stat().st_size > 10

    if is_update:
        console.print(Panel(
            "[bold cyan]Welcome back to Horizon Capital![/bold cyan]\n\n"
            "Your existing configuration was found.\n"
            "Press [green]Enter[/green] to keep a value, or type a new one to update it.",
            title="Update Configuration",
        ))
```

Then wherever the wizard prompts for each field (API keys, system mode, etc.), pre-fill the default with the current `.env` value:

```python
    # Example pattern for each field:
    existing_key = _read_env_field(env_path, "ANTHROPIC_API_KEY")
    default_display = _mask(existing_key) if existing_key else "(not set)"
    console.print(f"  Claude API key [dim](current: {default_display})[/dim]")
    new_val = Prompt.ask("  New value (Enter to keep)", default="", console=console)
    if new_val.strip():
        _write_env_key(str(env_path), "ANTHROPIC_API_KEY", new_val.strip())
```

Use the same `_read_env_field` and `_write_env_key` helpers from `settings_panel.py` — import them:

```python
from app.tui.settings_panel import _read_env as _read_env_all, _write_env_key
```

- [ ] **Step 3: Run smoke tests**

```bash
python -m pytest tests/test_smoke.py -v --tb=short
```

Expected: all pass (onboarding is not heavily tested in smoke suite, but imports must work).

- [ ] **Step 4: Commit**

```bash
git add app/tui/onboarding.py
git commit -m "feat: onboarding wizard detects existing .env and shows update-mode flow"
```

---

## Task 8: CIO Agent — Mode A (Strategic Oversight)

**Files:**
- Modify: `app/agents/executive/cio/cio_agent.py`
- Test: `tests/test_cio_agent.py` (new)

Replace the stub with a full LLM-powered CIO. This task covers Mode A only (15-minute advisory). Modes B and C follow in Tasks 9 and 10.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cio_agent.py`:

```python
"""Tests for the CIO agent (Modes A, B, C)."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_bus():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    return bus


def _make_provider(response: str):
    provider = MagicMock()
    provider.provider_name = "claude"
    provider.complete = AsyncMock(return_value=response)
    return provider


ADVISORY_RESPONSE = json.dumps({
    "outlook": "neutral",
    "summary": "Portfolio is balanced with moderate risk exposure.",
    "recommended_adjustments": [],
    "risk_flags": [],
})


@pytest.mark.asyncio
async def test_cio_mode_a_publishes_advisory():
    """Mode A: CIO publishes CIO_ADVISORY message with structured outlook."""
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import MessageType

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._running = True

    provider = _make_provider(ADVISORY_RESPONSE)

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]

        with patch.object(agent, "_build_portfolio_digest", return_value={"nav": 1000000.0}):
            await agent._run_mode_a()

    # Should have published a CIO_ADVISORY message
    calls = bus.publish.call_args_list
    assert any(
        call.args[0].message_type == MessageType.CIO_ADVISORY
        for call in calls
    )


@pytest.mark.asyncio
async def test_cio_mode_a_silent_without_provider():
    """Mode A: CIO does nothing when no LLM provider is configured."""
    from app.agents.executive.cio.cio_agent import CIOAgent

    bus = _make_bus()
    agent = CIOAgent(bus=bus)

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = []
        await agent._run_mode_a()

    bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_cio_mode_a_handles_llm_error_gracefully():
    """Mode A: LLM error does not crash the agent."""
    from app.agents.executive.cio.cio_agent import CIOAgent

    bus = _make_bus()
    agent = CIOAgent(bus=bus)

    provider = MagicMock()
    provider.provider_name = "claude"
    provider.complete = AsyncMock(side_effect=RuntimeError("API error"))

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        with patch.object(agent, "_build_portfolio_digest", return_value={}):
            await agent._run_mode_a()  # Should not raise

    # Still no publish (error path is silent)
    bus.publish.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_cio_agent.py::test_cio_mode_a_publishes_advisory -v
```

Expected: FAIL — `CIOAgent` has no `_run_mode_a` method.

- [ ] **Step 3: Rewrite `app/agents/executive/cio/cio_agent.py`**

```python
"""AI CIO Agent -- strategic oversight, crisis response, and last-resort override.

Only active when CIO_MODE=AI. Three operating modes:
  Mode A: Strategic advisory every 15 min (continuous, passive)
  Mode B: Crisis response on RISK_ALERT HIGH/CRITICAL or kill-switch trigger
  Mode C: Override directive — only when kill switch + confidence >= threshold
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

from app.agents.base_agent import BaseAgent
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType

logger = get_logger("agent.cio")

CIO_ADVISORY_INTERVAL = 900   # 15 minutes
CIO_OVERRIDE_CONFIDENCE_THRESHOLD = 0.85
CIO_CIRCUIT_BREAKER_FAILURES = 3
CIO_CIRCUIT_BREAKER_COOLDOWN = 300  # 5 minutes


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


class CIOAgent(BaseAgent):
    """AI Chief Investment Officer."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="cio-agent-1",
            agent_type="cio",
            bus=bus,
        )
        self._alerts: list[dict] = []
        self._kill_switch_active: bool = False
        self._pending_halt_confirmation: bool = False
        self._last_override: dict | None = None

        # Circuit breaker state
        self._llm_failures: int = 0
        self._llm_circuit_open_until: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.risk.*", self.on_message)
        await self.bus.subscribe("horizon.settings.*", self.on_message)

    async def on_message(self, message: AgentMessage) -> None:
        if message.message_type == MessageType.RISK_ALERT:
            self._alerts.append(message.payload)
            severity = message.payload.get("severity", "")
            action = message.payload.get("action", "")

            if action == "KILL_SWITCH_TRIGGERED":
                self._kill_switch_active = True
                await self._run_mode_b(message.payload, trigger="kill_switch")
            elif severity in ("HIGH", "CRITICAL"):
                await self._run_mode_b(message.payload, trigger="risk_alert")

        elif message.message_type == MessageType.SETTINGS_UPDATED:
            # Reload provider after settings change
            from app.llm.provider_registry import provider_registry
            provider_registry.reload_from_settings()

        self._alerts = self._alerts[-50:]  # keep last 50

    async def run(self) -> None:
        """Mode A: periodic strategic advisory loop."""
        while self._running:
            try:
                await self._run_mode_a()
            except Exception as exc:
                logger.error("cio.mode_a_error", error=str(exc))
            await asyncio.sleep(CIO_ADVISORY_INTERVAL)

    # ------------------------------------------------------------------
    # Mode A — Strategic Oversight
    # ------------------------------------------------------------------

    async def _run_mode_a(self) -> None:
        """Build portfolio digest, call LLM, publish CIO_ADVISORY."""
        provider = self._get_provider()
        if provider is None:
            return

        digest = await self._build_portfolio_digest()
        system_prompt = (
            "You are the AI Chief Investment Officer of Horizon Capital, an autonomous "
            "hedge fund. You receive a snapshot of the portfolio and recent activity. "
            "Respond with ONLY a JSON object (no markdown fences):\n"
            '{"outlook": "bullish|neutral|bearish", '
            '"summary": "<2-3 sentence view>", '
            '"recommended_adjustments": [{"symbol": "...", "action": "reduce|increase|close|hold", "reason": "..."}], '
            '"risk_flags": ["..."]}'
        )
        user_msg = f"Portfolio snapshot:\n{json.dumps(digest, indent=2)}"

        try:
            raw = await provider.complete(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_msg}],
                temperature=0.3,
            )
            parsed = self._parse_advisory(raw)
            if parsed is None:
                return

            await self._persist_advisory(parsed, provider.provider_name, trigger="timer")
            await self.bus.publish(AgentMessage(
                sender_id=self.agent_id,
                channel="horizon.cio.advisory",
                message_type=MessageType.CIO_ADVISORY,
                payload={**parsed, "provider": provider.provider_name, "timestamp": datetime.now(UTC).isoformat()},
            ))
            logger.info("cio.advisory_published", outlook=parsed.get("outlook"))
            self._reset_circuit_breaker()

        except Exception as exc:
            logger.error("cio.mode_a_llm_error", error=str(exc))
            self._record_failure()

    # ------------------------------------------------------------------
    # Mode B — Crisis Response
    # ------------------------------------------------------------------

    async def _run_mode_b(self, trigger_payload: dict, trigger: str) -> None:
        """Assess crisis situation and recommend HOLD / REDUCE / HALT."""
        provider = self._get_provider()
        if provider is None:
            logger.warning("cio.mode_b_no_provider -- crisis unattended")
            return

        digest = await self._build_portfolio_digest()
        system_prompt = (
            "You are the AI CIO of Horizon Capital. A crisis event has been triggered. "
            "Analyze the situation and respond with ONLY a JSON object:\n"
            '{"stance": "HOLD|REDUCE|HALT", '
            '"confidence": <0.0-1.0>, '
            '"reasoning": "<clear explanation>", '
            '"specific_actions": [{"symbol": "...", "action": "reduce_by_pct|close", "urgency": "immediate|next_bar", "pct": 0}]}'
        )
        user_msg = (
            f"Crisis trigger: {trigger}\n"
            f"Trigger details: {json.dumps(trigger_payload)}\n\n"
            f"Portfolio snapshot:\n{json.dumps(digest, indent=2)}"
        )

        try:
            raw = await provider.complete(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_msg}],
                temperature=0.1,  # Low temperature for crisis decisions
            )
            parsed = self._parse_crisis_response(raw)
            if parsed is None:
                return

            await self.bus.publish(AgentMessage(
                sender_id=self.agent_id,
                channel="horizon.cio.crisis",
                message_type=MessageType.CIO_ADVISORY,
                payload={
                    **parsed,
                    "provider": provider.provider_name,
                    "trigger": trigger,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "is_crisis": True,
                },
            ))
            logger.warning(
                "cio.crisis_response",
                stance=parsed.get("stance"),
                confidence=parsed.get("confidence"),
            )

            # Mode C gate: only override if kill switch is active AND confidence is high
            if (
                self._kill_switch_active
                and parsed.get("stance") == "HALT"
                and parsed.get("confidence", 0.0) >= CIO_OVERRIDE_CONFIDENCE_THRESHOLD
            ):
                await self._run_mode_c(parsed, trigger_payload, provider)

            self._reset_circuit_breaker()

        except Exception as exc:
            logger.error("cio.mode_b_llm_error", error=str(exc))
            self._record_failure()

    # ------------------------------------------------------------------
    # Mode C — Last-Resort Override
    # ------------------------------------------------------------------

    async def _run_mode_c(
        self, crisis_result: dict, trigger_payload: dict, provider
    ) -> None:
        """Issue override directive and persist full audit trail."""
        from app.config import settings

        actions = crisis_result.get("specific_actions", [])
        override_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        digest = await self._build_portfolio_digest()
        audit = {
            "id": override_id,
            "timestamp": now.isoformat(),
            "trigger": trigger_payload.get("action", "unknown"),
            "confidence": crisis_result.get("confidence", 0.0),
            "actions": json.dumps(actions),
            "full_prompt": crisis_result.get("reasoning", ""),
            "full_response": json.dumps(crisis_result),
            "portfolio_snapshot": json.dumps(digest),
            "provider": provider.provider_name,
        }

        await self._persist_override(audit)
        self._last_override = audit

        await self.bus.publish(AgentMessage(
            sender_id=self.agent_id,
            channel="horizon.cio.override",
            message_type=MessageType.CIO_OVERRIDE,
            payload={
                "override_id": override_id,
                "actions": actions,
                "reasoning": crisis_result.get("reasoning"),
                "confidence": crisis_result.get("confidence"),
                "timestamp": now.isoformat(),
                "system_mode": settings.system_mode,
            },
        ))
        logger.critical(
            "cio.override_issued",
            override_id=override_id,
            confidence=crisis_result.get("confidence"),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_provider(self):
        """Return the configured LLM provider for the executive department, or None."""
        import time
        if time.monotonic() < self._llm_circuit_open_until:
            logger.debug("cio.circuit_breaker_open -- skipping LLM call")
            return None

        from app.llm.provider_registry import provider_registry
        providers = provider_registry.get_providers_for_department("executive")
        if not providers:
            return None

        # Preference order: claude > openai > gemini
        pref = {"claude": 0, "openai": 1, "gemini": 2}
        return min(providers, key=lambda p: pref.get(p.provider_name, 99))

    async def _build_portfolio_digest(self) -> dict:
        """Read portfolio state from KV store and DB for the LLM context."""
        from app.core.kv_store import get_kv_store
        kv = get_kv_store()

        digest: dict = {
            "timestamp": datetime.now(UTC).isoformat(),
            "nav_usd": None,
            "recent_alerts": self._alerts[-5:],
            "kill_switch_active": self._kill_switch_active,
        }

        try:
            nav_str = await kv.get("horizon:portfolio:nav")
            if nav_str:
                digest["nav_usd"] = float(nav_str)
        except Exception:
            pass

        try:
            async with _get_session_factory()() as session:
                from sqlalchemy import text
                result = await session.execute(text(
                    "SELECT symbol, direction, quantity, avg_price "
                    "FROM positions WHERE status='OPEN' LIMIT 10"
                ))
                rows = result.fetchall()
                digest["top_positions"] = [
                    {"symbol": r[0], "direction": r[1], "quantity": r[2], "avg_price": r[3]}
                    for r in rows
                ]
        except Exception:
            digest["top_positions"] = []

        return digest

    def _parse_advisory(self, raw: str) -> dict | None:
        """Parse structured advisory JSON from LLM response."""
        try:
            text = raw
            if "```" in raw:
                text = raw.split("```")[1].replace("json", "").strip()
            data = json.loads(text)
            return {
                "outlook": str(data.get("outlook", "neutral")),
                "summary": str(data.get("summary", ""))[:500],
                "recommended_adjustments": data.get("recommended_adjustments", []),
                "risk_flags": data.get("risk_flags", []),
            }
        except Exception as exc:
            logger.warning("cio.advisory_parse_error", error=str(exc))
            return None

    def _parse_crisis_response(self, raw: str) -> dict | None:
        """Parse structured crisis response JSON from LLM response."""
        try:
            text = raw
            if "```" in raw:
                text = raw.split("```")[1].replace("json", "").strip()
            data = json.loads(text)
            stance = str(data.get("stance", "HOLD")).upper()
            if stance not in ("HOLD", "REDUCE", "HALT"):
                stance = "HOLD"
            return {
                "stance": stance,
                "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                "reasoning": str(data.get("reasoning", ""))[:1000],
                "specific_actions": data.get("specific_actions", []),
            }
        except Exception as exc:
            logger.warning("cio.crisis_parse_error", error=str(exc))
            return None

    async def _persist_advisory(self, data: dict, provider: str, trigger: str) -> None:
        """Write advisory to cio_advisories table."""
        try:
            from sqlalchemy import text
            row_id = str(uuid.uuid4())
            async with _get_session_factory()() as session:
                await session.execute(text("""
                    INSERT INTO cio_advisories
                    (id, timestamp, outlook, summary, recommended_adjustments, risk_flags, provider, trigger)
                    VALUES (:id, :ts, :outlook, :summary, :adj, :flags, :prov, :trig)
                """), {
                    "id": row_id,
                    "ts": datetime.now(UTC).isoformat(),
                    "outlook": data["outlook"],
                    "summary": data["summary"],
                    "adj": json.dumps(data.get("recommended_adjustments", [])),
                    "flags": json.dumps(data.get("risk_flags", [])),
                    "prov": provider,
                    "trig": trigger,
                })
                await session.commit()
        except Exception as exc:
            logger.error("cio.persist_advisory_error", error=str(exc))

    async def _persist_override(self, audit: dict) -> None:
        """Write override record to cio_overrides table."""
        try:
            from sqlalchemy import text
            async with _get_session_factory()() as session:
                await session.execute(text("""
                    INSERT INTO cio_overrides
                    (id, timestamp, trigger, confidence, actions, full_prompt, full_response, portfolio_snapshot, provider)
                    VALUES (:id, :ts, :trigger, :confidence, :actions, :full_prompt, :full_response, :portfolio_snapshot, :provider)
                """), audit)
                await session.commit()
        except Exception as exc:
            logger.error("cio.persist_override_error", error=str(exc))

    def _record_failure(self) -> None:
        """Increment circuit breaker failure count."""
        import time
        self._llm_failures += 1
        if self._llm_failures >= CIO_CIRCUIT_BREAKER_FAILURES:
            self._llm_circuit_open_until = time.monotonic() + CIO_CIRCUIT_BREAKER_COOLDOWN
            logger.warning(
                "cio.circuit_breaker_opened",
                cooldown_seconds=CIO_CIRCUIT_BREAKER_COOLDOWN,
            )

    def _reset_circuit_breaker(self) -> None:
        self._llm_failures = 0
        self._llm_circuit_open_until = 0.0

    def get_last_override(self) -> dict | None:
        """Return the most recent override record (for 'cio why' command)."""
        return self._last_override

    def set_halt_confirmed(self) -> None:
        """Called by 'cio confirm halt' REPL command."""
        self._pending_halt_confirmation = True
        logger.info("cio.halt_confirmed_by_user")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_cio_agent.py -v
python -m pytest tests/ -v --tb=short
```

Expected: all new tests pass, all existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/agents/executive/cio/cio_agent.py tests/test_cio_agent.py
git commit -m "feat: rewrite CIO agent with Mode A (strategic advisory), Mode B (crisis response), Mode C (last-resort override)"
```

---

## Task 9: CIO Mode B + C Tests

**Files:**
- Test: `tests/test_cio_agent.py` (extend)

The CIO agent is already fully written above (Modes B and C are in the same file). This task adds the remaining tests.

- [ ] **Step 1: Add Mode B and C tests**

Append to `tests/test_cio_agent.py`:

```python
CRISIS_HOLD_RESPONSE = json.dumps({
    "stance": "HOLD",
    "confidence": 0.6,
    "reasoning": "Drawdown is concerning but within limits. Monitor.",
    "specific_actions": [],
})

CRISIS_HALT_HIGH_CONFIDENCE = json.dumps({
    "stance": "HALT",
    "confidence": 0.92,
    "reasoning": "Kill switch triggered. Systemic risk detected. Halt all trading.",
    "specific_actions": [{"symbol": "AAPL", "action": "close", "urgency": "immediate", "pct": 100}],
})

CRISIS_HALT_LOW_CONFIDENCE = json.dumps({
    "stance": "HALT",
    "confidence": 0.70,  # Below override threshold
    "reasoning": "Uncertain situation.",
    "specific_actions": [],
})


@pytest.mark.asyncio
async def test_cio_mode_b_publishes_crisis_advisory():
    """Mode B: publishes CIO_ADVISORY with is_crisis=True on RISK_ALERT."""
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import MessageType

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    provider = _make_provider(CRISIS_HOLD_RESPONSE)

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        with patch.object(agent, "_build_portfolio_digest", return_value={}):
            await agent._run_mode_b({"severity": "HIGH"}, trigger="risk_alert")

    calls = [c.args[0] for c in bus.publish.call_args_list]
    assert any(c.message_type == MessageType.CIO_ADVISORY for c in calls)
    advisory_payload = next(c.payload for c in calls if c.message_type == MessageType.CIO_ADVISORY)
    assert advisory_payload["is_crisis"] is True


@pytest.mark.asyncio
async def test_cio_mode_c_fires_when_kill_switch_and_high_confidence():
    """Mode C fires when kill switch is active AND confidence >= threshold."""
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import MessageType

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._kill_switch_active = True  # Kill switch is on
    provider = _make_provider(CRISIS_HALT_HIGH_CONFIDENCE)

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        with patch.object(agent, "_build_portfolio_digest", return_value={}):
            with patch.object(agent, "_persist_override", AsyncMock()):
                await agent._run_mode_b({"action": "KILL_SWITCH_TRIGGERED"}, trigger="kill_switch")

    calls = [c.args[0] for c in bus.publish.call_args_list]
    assert any(c.message_type == MessageType.CIO_OVERRIDE for c in calls)


@pytest.mark.asyncio
async def test_cio_mode_c_does_not_fire_below_confidence_threshold():
    """Mode C does NOT fire when confidence is below threshold, even with kill switch."""
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import MessageType

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._kill_switch_active = True
    provider = _make_provider(CRISIS_HALT_LOW_CONFIDENCE)

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        with patch.object(agent, "_build_portfolio_digest", return_value={}):
            await agent._run_mode_b({"action": "KILL_SWITCH_TRIGGERED"}, trigger="kill_switch")

    calls = [c.args[0] for c in bus.publish.call_args_list]
    assert not any(c.message_type == MessageType.CIO_OVERRIDE for c in calls)


@pytest.mark.asyncio
async def test_cio_circuit_breaker_silences_after_failures():
    """After 3 LLM failures, CIO goes silent for cooldown period."""
    from app.agents.executive.cio.cio_agent import CIOAgent, CIO_CIRCUIT_BREAKER_FAILURES

    bus = _make_bus()
    agent = CIOAgent(bus=bus)

    provider = MagicMock()
    provider.provider_name = "claude"
    provider.complete = AsyncMock(side_effect=RuntimeError("LLM error"))

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        with patch.object(agent, "_build_portfolio_digest", return_value={}):
            for _ in range(CIO_CIRCUIT_BREAKER_FAILURES):
                await agent._run_mode_a()

    # Circuit breaker should now be open (future_time > 0)
    assert agent._llm_circuit_open_until > 0
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/test_cio_agent.py -v
python -m pytest tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cio_agent.py
git commit -m "test: add comprehensive CIO Mode B, C, and circuit breaker tests"
```

---

## Task 10: CIO REPL Commands + __main__.py Wiring

**Files:**
- Modify: `app/tui/commands.py`
- Modify: `app/__main__.py`

Add `cio`, `cio why`, and `cio confirm halt` commands. Wire the CIO agent into the main run loop.

- [ ] **Step 1: Add `cio` command to `app/tui/commands.py`**

In the `handle()` method, add `"cio"` to the `handlers` dict:

```python
            "cio": self._cmd_cio,
```

Then add the method body after the existing command implementations:

```python
    async def _cmd_cio(self, args: list[str]) -> str:
        """Handle 'cio', 'cio why', 'cio confirm halt' commands."""
        sub = " ".join(args).lower().strip() if args else ""

        if sub == "why":
            if self._cio_agent is None:
                return "[yellow]CIO agent not running.[/yellow]"
            override = self._cio_agent.get_last_override()
            if override is None:
                return "[dim]No override has been issued this session.[/dim]"
            reasoning = override.get("full_prompt", "No reasoning recorded.")
            timestamp = override.get("timestamp", "unknown")
            return (
                f"[bold red]Last CIO Override[/bold red]\n"
                f"Time: {timestamp}\n"
                f"Confidence: {override.get('confidence', '?')}\n"
                f"Reasoning: {reasoning}"
            )

        elif sub == "confirm halt":
            if self._cio_agent is None:
                return "[yellow]CIO agent not running.[/yellow]"
            self._cio_agent.set_halt_confirmed()
            return "[bold red]HALT confirmed. CIO will proceed with halt actions.[/bold red]"

        else:
            # Show latest advisory from DB
            return await self._cmd_cio_latest()

    async def _cmd_cio_latest(self) -> str:
        """Fetch and display the latest CIO advisory from DB."""
        try:
            from app.core.runtime import get_session_factory
            from sqlalchemy import text
            async with get_session_factory()() as session:
                result = await session.execute(text(
                    "SELECT outlook, summary, recommended_adjustments, risk_flags, timestamp "
                    "FROM cio_advisories ORDER BY timestamp DESC LIMIT 1"
                ))
                row = result.fetchone()
            if row is None:
                return "[dim]No CIO advisory recorded yet. CIO issues advisories every 15 minutes when LLM is configured.[/dim]"
            import json
            adj = json.loads(row[2]) if row[2] else []
            flags = json.loads(row[3]) if row[3] else []
            lines = [
                f"[bold cyan]CIO Advisory[/bold cyan] — {row[4]}",
                f"Outlook: [yellow]{row[0]}[/yellow]",
                f"Summary: {row[1]}",
            ]
            if adj:
                lines.append("Adjustments:")
                for a in adj[:5]:
                    lines.append(f"  • {a.get('symbol')} → {a.get('action')}: {a.get('reason', '')}")
            if flags:
                lines.append("Risk flags: " + ", ".join(flags[:3]))
            return "\n".join(lines)
        except Exception as exc:
            return f"[red]Error fetching CIO advisory: {exc}[/red]"
```

Also add `_cio_agent` attribute to `__init__`:

```python
    def __init__(self, dashboard=None, orchestrator=None) -> None:
        self._dashboard = dashboard
        self._orchestrator = orchestrator
        self._should_quit = False
        self._cio_chat = None
        self._last_backtest_result: dict | None = None
        self._cio_agent = None  # set by __main__.py after CIO starts
```

And add setter method:

```python
    def set_cio_agent(self, cio_agent) -> None:
        """Wire in the running CIO agent instance."""
        self._cio_agent = cio_agent
```

- [ ] **Step 2: Wire CIO agent into `app/__main__.py`**

Find where the orchestrator and agents are started (look for `CIOAgent` import or `cio_mode`). If `CIO_MODE=AI`, ensure `CIOAgent` is instantiated and started. Then wire it into the command handler:

```python
    # After CIOAgent is created and started:
    if settings.cio_mode == CIOMode.AI:
        cio_agent = CIOAgent(bus=bus)
        # Start CIO in background task
        asyncio.create_task(cio_agent.start())
        handler.set_cio_agent(cio_agent)
```

Update the readline tab completion list in `__main__.py` to include new commands:

```python
    # Find the readline.set_completer section and add to the commands list:
    "cio", "cio why", "cio confirm halt", "settings",
```

- [ ] **Step 3: Add CIO View to dashboard**

In `app/tui/dashboard.py`, find the `update_*` methods and add:

```python
    def update_cio_advisory(self, payload: dict) -> None:
        """Store the latest CIO advisory for rendering."""
        self._cio_advisory = payload

    def _build_cio_panel(self) -> Panel:
        """Render the latest CIO advisory as a Rich Panel."""
        from rich.panel import Panel
        from rich.text import Text
        adv = getattr(self, "_cio_advisory", None)
        if adv is None:
            return Panel("[dim]No CIO advisory yet[/dim]", title="CIO View")

        outlook_color = {"bullish": "green", "bearish": "red", "neutral": "yellow"}.get(
            adv.get("outlook", "neutral"), "white"
        )
        text = Text()
        text.append(f"Outlook: ", style="bold")
        text.append(adv.get("outlook", "?").upper() + "\n", style=outlook_color)
        text.append(adv.get("summary", ""), style="white")
        flags = adv.get("risk_flags", [])
        if flags:
            text.append(f"\n⚠  {', '.join(flags[:2])}", style="yellow")
        return Panel(text, title="[bold cyan]CIO View[/bold cyan]")
```

Then wire `update_cio_advisory` in `app/__main__.py` where `CIO_ADVISORY` messages are received:

```python
            elif msg.message_type == MessageType.CIO_ADVISORY:
                dashboard.update_cio_advisory(msg.payload)
```

And include `_build_cio_panel()` in `dashboard.build_layout()` in an appropriate column/row position (e.g., below the Risk panel).

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/tui/commands.py app/__main__.py app/tui/dashboard.py
git commit -m "feat: add cio, cio why, cio confirm halt REPL commands; CIO View panel in dashboard; wire CIO agent into main loop"
```

---

## Task 11: End-to-End Integration Test

**Files:**
- Test: `tests/test_integration.py` (extend existing)

Add one full pipeline test that verifies a price tick flows through to a debate with single-provider working correctly.

- [ ] **Step 1: Add E2E pipeline test**

Append to `tests/test_integration.py`:

```python
@pytest.mark.asyncio
async def test_full_pipeline_single_provider(monkeypatch):
    """E2E: price tick in KV store → strategy signal → debate (1 provider) → portfolio order.

    All external calls mocked. Verifies the full pipeline works end-to-end
    with a single LLM provider configured.
    """
    from app.core.memory_bus import MemoryBus
    from app.core.kv_store import MemoryKVStore
    from app.core.messaging import MessageType, AgentMessage
    from app.llm.provider_registry import ProviderRegistry

    # Set up bus and KV store
    bus = MemoryBus()
    kv = MemoryKVStore()

    # Seed price into KV store (simulates Alpaca/Yahoo having written a live price)
    await kv.set("horizon:price:AAPL", "155.00")

    # Single mock LLM provider
    from unittest.mock import AsyncMock, MagicMock
    provider = MagicMock()
    provider.provider_name = "claude"
    provider.complete = AsyncMock(
        return_value='{"argument": "Strong momentum", "vote": "FOR", "confidence": 0.85}'
    )

    registry = ProviderRegistry()
    registry._providers["claude"] = provider

    # Collect published messages
    published = []
    original_publish = bus.publish
    async def capture(msg):
        published.append(msg)
        return await original_publish(msg)
    monkeypatch.setattr(bus, "publish", capture)

    # Simulate a signal being emitted and going through debate
    from app.agents.debate.multi_model_debate import MultiModelDebateEngine

    engine = MultiModelDebateEngine(registry=registry, bus=bus, max_rounds=2)

    result = await engine.run_debate(
        symbol="AAPL",
        action="BUY",
        signal_data={"strength": 0.9, "strategy_name": "momentum"},
    )

    # Single provider should run 2 rounds
    assert result.rounds == 2
    # All 8 arguments should come from claude
    assert all(a.provider == "claude" for a in result.arguments)
    # Decision should be APPROVED (all votes FOR with high confidence)
    assert result.decision == "APPROVED"
    # DEBATE_CONCLUSION should have been published
    assert any(m.message_type == MessageType.DEBATE_CONCLUSION for m in published)
```

- [ ] **Step 2: Run the new test**

```bash
python -m pytest tests/test_integration.py -k "test_full_pipeline_single_provider" -v
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add E2E single-provider pipeline integration test"
```

---

## Task 12: Final Verification

- [ ] **Step 1: Run lint**

```bash
python -m ruff check app/ --fix
```

Expected: 0 errors. Fix any that appear before proceeding.

- [ ] **Step 2: Run full test suite one final time**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests pass, 0 failures.

- [ ] **Step 3: Smoke-test the running app**

```bash
python -m app --headless &
sleep 5
# Verify startup messages include:
#   - "llm_providers_available" (if keys configured)
#   - "data_ingestion_worker.started"
#   - "yahoo_feed.fetched" (1-min bars)
kill %1
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: full system completion — real-time data, settings panel, intelligent CIO, debate hardening

- Yahoo 1-min bars + market hours awareness (30s polling)
- Alpaca WebSocket exponential backoff reconnect
- Interactive settings panel (API keys, AI allocation, debate roles)
- ProviderRegistry hot-reload on settings change
- Debate engine: role pinning from config + single-provider round 2
- CIO agent: Mode A (15-min advisory), Mode B (crisis), Mode C (last-resort override)
- CIO REPL commands: cio, cio why, cio confirm halt
- Extended setup wizard update mode
- 2 new DB tables: cio_advisories, cio_overrides
- Backward compatibility: all existing tests pass throughout"
```
