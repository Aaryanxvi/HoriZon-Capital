"""Auto-discovery: Gamma market filters, CoinGecko universe filters, wiring."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.config import settings
from app.data_layer import polymarket_feed as pmf
from app.data_layer.crypto_universe import (
    DEFAULT_UNIVERSE,
    _filter_coins,
    crypto_universe,
    refresh_crypto_universe,
)
from app.data_layer.polymarket_feed import (
    _filter_gamma_markets,
    active_slugs,
    pm_symbol,
    refresh_discovery,
)

_NOW = datetime(2026, 8, 30, tzinfo=UTC)
_TOKENS = json.dumps(["1" * 77, "2" * 77])


def _market(
    slug: str,
    *,
    volume: float = 100_000.0,
    days: float = 30.0,
    closed: bool = False,
    order_book: bool = True,
    outcomes: str = '["Yes", "No"]',
    tokens: str = _TOKENS,
    mid: float | None = 0.5,
) -> dict:
    market = {
        "slug": slug,
        "question": f"Will {slug}?",
        "conditionId": "0xc",
        "outcomes": outcomes,
        "clobTokenIds": tokens,
        "volume24hr": volume,
        "closed": closed,
        "active": True,
        "enableOrderBook": order_book,
        "endDate": (_NOW + timedelta(days=days)).isoformat().replace("+00:00", "Z"),
    }
    if mid is not None:
        market["outcomePrices"] = json.dumps([str(mid), str(round(1.0 - mid, 4))])
    return market


def _filter(markets, **kw):
    params = {
        "min_volume": 25_000.0,
        "min_days": 10,
        "max_days": 180,
        "top_n": 10,
        "now": _NOW,
    }
    params.update(kw)
    return _filter_gamma_markets(markets, **params)


class _FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


# --------------------------------------------------------------------------- #
# Polymarket: Gamma filtering
# --------------------------------------------------------------------------- #

def test_gamma_filter_ranks_by_volume_and_caps_top_n():
    markets = [
        _market("small", volume=30_000),
        _market("huge", volume=900_000),
        _market("mid", volume=200_000),
    ]
    kept = [m["slug"] for m in _filter(markets, top_n=2)]
    assert kept == ["huge", "mid"]


def test_gamma_filter_rejects_untradable_and_out_of_window():
    markets = [
        _market("ok"),
        _market("closed", closed=True),
        _market("thin", volume=100.0),
        _market("no-book", order_book=False),
        _market("resolves-tomorrow", days=1),
        _market("resolves-in-3-years", days=1095),
        _market("no-yes-token", outcomes='["Up", "Down"]', tokens=json.dumps([])),
    ]
    assert [m["slug"] for m in _filter(markets)] == ["ok"]


def test_gamma_filter_survives_junk_rows():
    markets = [_market("ok"), {"slug": "broken"}, {"volume24hr": "abc"}]
    assert [m["slug"] for m in _filter(markets)] == ["ok"]


def test_gamma_filter_rejects_resolved_tails():
    """A 1c market has volume but no tradable band left — the sleeve skips it."""
    markets = [
        _market("live", mid=0.42),
        _market("near-zero", mid=0.013, volume=800_000),
        _market("near-one", mid=0.987, volume=700_000),
        _market("unquoted", mid=None, volume=50_000),  # fail-open
    ]
    assert [m["slug"] for m in _filter(markets)] == ["live", "unquoted"]


def test_gamma_filter_drops_slug_truncation_collisions():
    """Two slugs sharing a 40-char prefix map to one symbol — keep the bigger."""
    long_a = "will-the-fed-increase-interest-rates-by-50-bps-in-september"
    long_b = "will-the-fed-increase-interest-rates-by-75-bps-in-september"
    assert pm_symbol(long_a) == pm_symbol(long_b)

    kept = _filter([_market(long_a, volume=100_000), _market(long_b, volume=900_000)])
    assert [m["slug"] for m in kept] == [long_b]


def test_gamma_filter_collision_does_not_eat_a_top_n_slot():
    long_a = "will-the-fed-increase-interest-rates-by-50-bps-in-september"
    long_b = "will-the-fed-increase-interest-rates-by-75-bps-in-september"
    markets = [
        _market(long_a, volume=900_000),
        _market(long_b, volume=800_000),
        _market("other", volume=700_000),
    ]
    assert [m["slug"] for m in _filter(markets, top_n=2)] == [long_a, "other"]


# --------------------------------------------------------------------------- #
# Polymarket: refresh_discovery + active_slugs
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _no_network_bars(monkeypatch):
    """Crypto discovery bar-checks every candidate — never let that hit yfinance."""
    import pandas as pd

    df = pd.DataFrame({"close": [1.0] * 300})

    async def fake_batch(symbols, period="1200d"):
        return {s: df for s in symbols}

    monkeypatch.setattr("app.data_layer.batch_bars.fetch_batch", fake_batch)


@pytest.fixture(autouse=True)
def _reset_discovery_state():
    pmf._discovered_slugs = []
    pmf._discovered_meta.clear()
    pmf._discovered_at = 0.0
    yield
    pmf._discovered_slugs = []
    pmf._discovered_meta.clear()
    pmf._discovered_at = 0.0


@pytest.mark.asyncio
async def test_discovery_disabled_makes_no_call(monkeypatch):
    monkeypatch.setattr(settings, "polymarket_discovery_enabled", False, raising=False)

    async def fail_get(self, url, params=None, **kwargs):
        raise AssertionError("no HTTP when discovery is off")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_get)
    assert await refresh_discovery() == []


@pytest.mark.asyncio
async def test_discovery_writes_meta_and_dedupes_configured(monkeypatch):
    from app.core.kv_store import get_kv_store

    monkeypatch.setattr(settings, "polymarket_discovery_enabled", True, raising=False)
    monkeypatch.setattr(settings, "polymarket_discovery_top_n", 5, raising=False)
    monkeypatch.setattr(settings, "polymarket_markets", "manual-one", raising=False)

    body = [_market("manual-one", volume=500_000), _market("found-one", volume=400_000)]

    async def fake_get(self, url, params=None, **kwargs):
        assert params["order"] == "volume24hr"
        return _FakeResponse(200, body)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    found = await refresh_discovery(force=True)
    # The configured slug is not repeated in the discovered list...
    assert found == ["found-one"]
    # ...but active_slugs unions both, configured first.
    assert active_slugs() == ["manual-one", "found-one"]

    meta_raw = await get_kv_store().get(f"horizon:pm:meta:{pm_symbol('found-one')}")
    assert meta_raw is not None
    assert json.loads(meta_raw)["token_id"] == json.loads(_TOKENS)[0]


@pytest.mark.asyncio
async def test_discovery_drops_markets_that_fall_out(monkeypatch):
    monkeypatch.setattr(settings, "polymarket_discovery_enabled", True, raising=False)
    monkeypatch.setattr(settings, "polymarket_discovery_top_n", 5, raising=False)
    monkeypatch.setattr(settings, "polymarket_markets", "", raising=False)

    body = [_market("first-round")]

    async def fake_get(self, url, params=None, **kwargs):
        return _FakeResponse(200, body)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert await refresh_discovery(force=True) == ["first-round"]

    body = [_market("second-round")]
    assert await refresh_discovery(force=True) == ["second-round"]
    # Stale market must stop being polled, not accumulate.
    assert list(pmf._discovered_meta) == [pm_symbol("second-round")]


@pytest.mark.asyncio
async def test_configured_market_keeps_its_symbol_on_collision(monkeypatch):
    """A discovered slug must never overwrite a configured market's token meta."""
    from app.core.kv_store import get_kv_store

    configured = "will-the-fed-increase-interest-rates-by-50-bps-in-september"
    rival = "will-the-fed-increase-interest-rates-by-75-bps-in-september"
    symbol = pm_symbol(configured)
    assert pm_symbol(rival) == symbol

    monkeypatch.setattr(settings, "polymarket_discovery_enabled", True, raising=False)
    monkeypatch.setattr(settings, "polymarket_discovery_top_n", 5, raising=False)
    monkeypatch.setattr(settings, "polymarket_markets", configured, raising=False)

    kv = get_kv_store()
    await kv.set(
        f"horizon:pm:meta:{symbol}",
        json.dumps({"token_id": "configured-token", "slug": configured}),
    )

    async def fake_get(self, url, params=None, **kwargs):
        return _FakeResponse(200, [_market(rival, volume=900_000)])

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    assert await refresh_discovery(force=True) == []
    meta = json.loads(await kv.get(f"horizon:pm:meta:{symbol}"))
    assert meta["token_id"] == "configured-token"


@pytest.mark.asyncio
async def test_discovery_http_error_keeps_previous_list(monkeypatch):
    monkeypatch.setattr(settings, "polymarket_discovery_enabled", True, raising=False)
    monkeypatch.setattr(settings, "polymarket_discovery_top_n", 5, raising=False)
    monkeypatch.setattr(settings, "polymarket_markets", "", raising=False)

    async def ok_get(self, url, params=None, **kwargs):
        return _FakeResponse(200, [_market("keeper")])

    monkeypatch.setattr(httpx.AsyncClient, "get", ok_get)
    assert await refresh_discovery(force=True) == ["keeper"]

    async def boom_get(self, url, params=None, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx.AsyncClient, "get", boom_get)
    assert await refresh_discovery(force=True) == ["keeper"]


@pytest.mark.asyncio
async def test_discovery_cached_within_ttl(monkeypatch):
    monkeypatch.setattr(settings, "polymarket_discovery_enabled", True, raising=False)
    monkeypatch.setattr(settings, "polymarket_discovery_top_n", 5, raising=False)
    monkeypatch.setattr(settings, "polymarket_markets", "", raising=False)

    calls = []

    async def counting_get(self, url, params=None, **kwargs):
        calls.append(url)
        return _FakeResponse(200, [_market("keeper")])

    monkeypatch.setattr(httpx.AsyncClient, "get", counting_get)
    await refresh_discovery(force=True)
    await refresh_discovery()
    await refresh_discovery()
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# Crypto: CoinGecko filtering
# --------------------------------------------------------------------------- #

def _coins() -> list[dict]:
    return [
        {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"},
        {"id": "ethereum", "symbol": "eth", "name": "Ethereum"},
        {"id": "tether", "symbol": "usdt", "name": "Tether"},
        {"id": "ripple", "symbol": "xrp", "name": "XRP"},
        {"id": "binance-peg-weth", "symbol": "weth", "name": "Binance-Peg WETH"},
        {"id": "wrapped-steth", "symbol": "wsteth", "name": "Wrapped stETH"},
        {"id": "usd-coin", "symbol": "usdc", "name": "USDC"},
        {"id": "solana", "symbol": "sol", "name": "Solana"},
    ]


def test_crypto_filter_excludes_stables_and_wrappers():
    assert _filter_coins(_coins(), top_n=10) == (
        "BTC-USD", "ETH-USD", "XRP-USD", "SOL-USD",
    )


def test_crypto_filter_respects_top_n_and_order():
    assert _filter_coins(_coins(), top_n=2) == ("BTC-USD", "ETH-USD")


def test_crypto_filter_intersects_broker_tradable():
    tradable = frozenset({"BTC", "ETH", "SOL"})
    assert _filter_coins(_coins(), top_n=10, tradable=tradable) == (
        "BTC-USD", "ETH-USD", "SOL-USD",
    )


def test_crypto_filter_ignores_duplicate_symbols():
    coins = [
        {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"},
        {"id": "bitcoin-clone", "symbol": "btc", "name": "Bitcoin Clone"},
    ]
    assert _filter_coins(coins, top_n=5) == ("BTC-USD",)


# --------------------------------------------------------------------------- #
# Crypto: refresh + sleeve wiring
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_crypto_discovery_disabled_returns_default(monkeypatch):
    monkeypatch.setattr(settings, "crypto_discovery_enabled", False, raising=False)

    async def fail_get(self, url, params=None, **kwargs):
        raise AssertionError("no HTTP when discovery is off")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_get)
    assert await refresh_crypto_universe() == DEFAULT_UNIVERSE
    assert crypto_universe() == DEFAULT_UNIVERSE


@pytest.mark.asyncio
async def test_crypto_discovery_sets_sleeve_universe(monkeypatch):
    from app.agents.front_office.strategy.sleeves.crypto_trend import CryptoTrendSleeve

    monkeypatch.setattr(settings, "crypto_discovery_enabled", True, raising=False)
    monkeypatch.setattr(settings, "crypto_discovery_top_n", 3, raising=False)
    monkeypatch.setattr(settings, "execution_broker", "PAPER", raising=False)

    async def fake_get(self, url, params=None, **kwargs):
        assert "coins/markets" in url
        return _FakeResponse(200, _coins())

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    universe = await refresh_crypto_universe(force=True)
    assert universe == ("BTC-USD", "ETH-USD", "XRP-USD")
    assert CryptoTrendSleeve().universe() == universe


@pytest.mark.asyncio
async def test_crypto_discovery_error_keeps_last_good(monkeypatch):
    monkeypatch.setattr(settings, "crypto_discovery_enabled", True, raising=False)
    monkeypatch.setattr(settings, "crypto_discovery_top_n", 2, raising=False)
    monkeypatch.setattr(settings, "execution_broker", "PAPER", raising=False)

    async def ok_get(self, url, params=None, **kwargs):
        return _FakeResponse(200, _coins())

    monkeypatch.setattr(httpx.AsyncClient, "get", ok_get)
    good = await refresh_crypto_universe(force=True)

    async def boom_get(self, url, params=None, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx.AsyncClient, "get", boom_get)
    assert await refresh_crypto_universe(force=True) == good


@pytest.mark.asyncio
async def test_sleeve_weights_split_across_discovered_universe(monkeypatch):
    """Five coins in trend -> each gets a fifth of the sleeve, not a half."""
    import pandas as pd

    from app.agents.front_office.strategy.sleeves.crypto_trend import CryptoTrendSleeve

    monkeypatch.setattr(settings, "crypto_discovery_enabled", True, raising=False)
    monkeypatch.setattr(settings, "crypto_discovery_top_n", 4, raising=False)
    monkeypatch.setattr(settings, "execution_broker", "PAPER", raising=False)

    async def fake_get(self, url, params=None, **kwargs):
        return _FakeResponse(200, _coins())

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    universe = await refresh_crypto_universe(force=True)
    assert len(universe) == 4

    idx = pd.date_range("2024-01-01", periods=260, freq="D")
    closes = [100.0 + i for i in range(260)]  # steady uptrend, low vol
    bars = {
        sym: pd.DataFrame(
            {"open": closes, "high": closes, "low": closes,
             "close": closes, "volume": 0.0},
            index=idx,
        )
        for sym in universe
    }

    signals = CryptoTrendSleeve().compute(bars, idx[-1])
    assert len(signals) == 4
    assert all(s.target_weight == pytest.approx(0.25) for s in signals)


def test_missing_bars_leave_cash_not_concentration():
    """A coin with no bars leaves its 1/N share in cash — it does not double up.

    A transient fetch failure must never silently concentrate the sleeve into
    whatever happened to download. Permanently unpriceable coins are dropped
    earlier, by discovery (see test below).
    """
    import pandas as pd

    from app.agents.front_office.strategy.sleeves.crypto_trend import CryptoTrendSleeve

    idx = pd.date_range("2024-01-01", periods=260, freq="D")
    closes = [100.0 + i for i in range(260)]
    bars = {
        sym: pd.DataFrame(
            {"open": closes, "high": closes, "low": closes,
             "close": closes, "volume": 0.0},
            index=idx,
        )
        for sym in ("BTC-USD", "ETH-USD")
    }

    sleeve = CryptoTrendSleeve()
    sleeve.universe = lambda: ("BTC-USD", "ETH-USD", "HYPE-USD")  # type: ignore[method-assign]
    signals = sleeve.compute(bars, idx[-1])

    assert {s.symbol for s in signals} == {"BTC-USD", "ETH-USD"}
    assert all(s.target_weight == pytest.approx(1 / 3) for s in signals)


def test_sleeve_returns_nothing_when_no_bars():
    import pandas as pd

    from app.agents.front_office.strategy.sleeves.crypto_trend import CryptoTrendSleeve

    assert CryptoTrendSleeve().compute({}, pd.Timestamp("2026-01-01")) == []


@pytest.mark.asyncio
async def test_discovery_drops_unpriceable_coins(monkeypatch):
    """Alpaca-tradable but yfinance-unknown (HYPE in the live run) must not ship."""
    import pandas as pd

    monkeypatch.setattr(settings, "crypto_discovery_enabled", True, raising=False)
    monkeypatch.setattr(settings, "crypto_discovery_top_n", 3, raising=False)
    monkeypatch.setattr(settings, "execution_broker", "PAPER", raising=False)

    coins = _coins() + [{"id": "hyperliquid", "symbol": "hype", "name": "Hyperliquid"}]

    async def fake_get(self, url, params=None, **kwargs):
        return _FakeResponse(200, coins)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    df = pd.DataFrame({"close": [1.0] * 300})

    async def fake_batch(symbols, period="1200d"):
        # Everything prices except HYPE.
        return {s: df for s in symbols if s != "HYPE-USD"}

    monkeypatch.setattr("app.data_layer.batch_bars.fetch_batch", fake_batch)

    assert await refresh_crypto_universe(force=True) == (
        "BTC-USD", "ETH-USD", "XRP-USD",
    )


# --------------------------------------------------------------------------- #
# REPL wiring
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_pm_auto_toggle_writes_env(monkeypatch):
    from app.tui.commands import CommandHandler

    monkeypatch.setattr(settings, "polymarket_discovery_enabled", False, raising=False)
    monkeypatch.setattr(settings, "polymarket_discovery_top_n", 10, raising=False)
    monkeypatch.setattr(settings, "polymarket_markets", "", raising=False)

    written: dict[str, str] = {}
    monkeypatch.setattr(
        CommandHandler, "_update_env",
        lambda self, key, value: written.__setitem__(key, value),
    )

    async def fake_get(self, url, params=None, **kwargs):
        return _FakeResponse(200, [_market("auto-found")])

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    handler = CommandHandler()
    out = await handler.handle("pm auto on 3")

    assert written["POLYMARKET_DISCOVERY_ENABLED"] == "true"
    assert written["POLYMARKET_DISCOVERY_TOP_N"] == "3"
    assert settings.polymarket_discovery_enabled is True
    assert "1 market(s) found" in out


@pytest.mark.asyncio
async def test_sleeve_on_polymarket_allowed_with_discovery(monkeypatch):
    from app.tui.commands import CommandHandler

    monkeypatch.setattr(settings, "polymarket_markets", "", raising=False)
    monkeypatch.setattr(settings, "polymarket_discovery_enabled", True, raising=False)
    monkeypatch.setattr(settings, "polymarket_sleeve_enabled", False, raising=False)
    monkeypatch.setattr(settings, "polymarket_sleeve_weight", 0.05, raising=False)
    monkeypatch.setattr(settings, "crypto_sleeve_enabled", False, raising=False)
    monkeypatch.setattr(CommandHandler, "_update_env", lambda self, k, v: None)

    out = await CommandHandler().handle("sleeve on polymarket")
    assert "enabled" in out
    assert settings.polymarket_sleeve_enabled is True


@pytest.mark.asyncio
async def test_crypto_command_reports_universe(monkeypatch):
    from app.tui.commands import CommandHandler

    monkeypatch.setattr(settings, "crypto_discovery_enabled", False, raising=False)
    monkeypatch.setattr(settings, "crypto_sleeve_enabled", False, raising=False)

    out = await CommandHandler().handle("crypto")
    assert "BTC-USD" in out
    assert "static" in out
