# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-019DE49B3A6D
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Polymarket: symbol convention, feed resolution/polling, broker routing, REPL."""
from __future__ import annotations

import json

import httpx
import pytest

from app.agents.front_office.trading.execution_agent import (
    ExecutionAgent,
    _polymarket_guard_ok,
)
from app.agents.front_office.trading.polymarket_broker import PolymarketBroker
from app.core.memory_bus import MemoryBus
from app.data_layer.polymarket_feed import PolymarketFeed, pm_symbol


def _make_agent() -> ExecutionAgent:
    return ExecutionAgent(bus=MemoryBus())


# --------------------------------------------------------------------------- #
# Symbol convention
# --------------------------------------------------------------------------- #

def test_pm_symbol_sanitization():
    assert pm_symbol("Fed-Cut-Sept! 2026") == "PM-fed-cut-sept-2026.POLY"

    long_slug = "a" * 60
    symbol = pm_symbol(long_slug)
    assert symbol == f"PM-{'a' * 40}.POLY"

    assert pm_symbol("Will??  Team---Win") == "PM-will-team-win.POLY"


# --------------------------------------------------------------------------- #
# Feed: resolution + disabled state
# --------------------------------------------------------------------------- #

class _FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_feed_resolves_yes_token(monkeypatch):
    from app.config import settings
    from app.core.kv_store import get_kv_store

    monkeypatch.setattr(settings, "polymarket_markets", "test-slug", raising=False)

    token_yes = "1" * 77
    token_no = "2" * 77
    gamma_body = [
        {
            "slug": "test-slug",
            "question": "Will it happen?",
            "conditionId": "0xcond",
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": json.dumps([token_yes, token_no]),
            "volume24hr": 1234.5,
            "closed": False,
        }
    ]

    async def fake_get(self, url, params=None, **kwargs):
        assert "markets" in url
        return _FakeResponse(200, gamma_body)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    feed = PolymarketFeed()
    await feed.connect()

    symbol = pm_symbol("test-slug")
    assert feed.is_connected is True
    assert symbol in feed._meta
    assert feed._meta[symbol]["token_id"] == json.loads(gamma_body[0]["clobTokenIds"])[0]

    kv = get_kv_store()
    meta_raw = await kv.get(f"horizon:pm:meta:{symbol}")
    assert meta_raw is not None
    assert json.loads(meta_raw)["question"] == "Will it happen?"


@pytest.mark.asyncio
async def test_feed_disabled_when_no_markets(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "polymarket_markets", "", raising=False)

    async def fail_get(self, url, params=None, **kwargs):
        raise AssertionError("HTTP should not be called when feature is disabled")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_get)

    feed = PolymarketFeed()
    await feed.connect()

    assert feed.is_connected is False


# --------------------------------------------------------------------------- #
# Guard + routing
# --------------------------------------------------------------------------- #

def test_guard_default_off():
    assert _polymarket_guard_ok() is False


@pytest.mark.asyncio
async def test_broker_for_routes_poly_to_paper(monkeypatch):
    agent = _make_agent()

    broker, name = agent._broker_for("PM-x.POLY")
    assert (broker, name) == (agent.paper_broker, "PAPER")

    broker, name = agent._broker_for("AAPL.NASDAQ")
    assert (broker, name) == (agent.broker, agent.broker_name)

    monkeypatch.setattr(
        "app.agents.front_office.trading.execution_agent._polymarket_guard_ok",
        lambda: True,
    )
    broker, name = agent._broker_for("PM-x.POLY")
    assert (broker, name) == (agent.polymarket_broker, "POLYMARKET")


# --------------------------------------------------------------------------- #
# PolymarketBroker: missing client lib fails soft
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_polymarket_broker_none_without_client(monkeypatch):
    from app.core.kv_store import get_kv_store

    kv = get_kv_store()
    await kv.set(
        "horizon:pm:meta:PM-x.POLY",
        json.dumps({"token_id": "123", "condition_id": "c", "slug": "x",
                    "question": "q", "end_date": ""}),
    )

    import sys
    monkeypatch.setitem(sys.modules, "py_clob_client_v2.clob_types", None)

    broker = PolymarketBroker()
    fill = await broker.execute({"id": "o1", "symbol": "PM-x.POLY", "side": "BUY", "quantity": 10})
    assert fill is None


# --------------------------------------------------------------------------- #
# REPL: pm command
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_pm_command_lists_markets(monkeypatch):
    from app.config import settings
    from app.core.kv_store import get_kv_store
    from app.tui.commands import CommandHandler

    monkeypatch.setattr(settings, "polymarket_markets", "test-market", raising=False)
    symbol = pm_symbol("test-market")

    kv = get_kv_store()
    await kv.set(
        f"horizon:pm:meta:{symbol}",
        json.dumps({"token_id": "1", "condition_id": "c", "slug": "test-market",
                    "question": "Will it resolve YES?", "end_date": ""}),
    )
    await kv.set(f"horizon:price:{symbol}", "0.5")
    await kv.set(f"horizon:volume:{symbol}", "1000")

    handler = CommandHandler()
    output = await handler.handle("pm")

    assert symbol in output
    assert "0.5" in output


@pytest.mark.asyncio
async def test_pm_command_empty_config(monkeypatch):
    from app.config import settings
    from app.tui.commands import CommandHandler

    monkeypatch.setattr(settings, "polymarket_markets", "", raising=False)

    handler = CommandHandler()
    output = await handler.handle("pm")
    assert "No Polymarket markets configured" in output


# --------------------------------------------------------------------------- #
# Poll loop: one iteration emits a tick
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_midpoint_tick_emitted(monkeypatch):
    symbol = pm_symbol("poll-test")

    async def fake_get(self, url, params=None, **kwargs):
        assert "midpoint" in url
        return _FakeResponse(200, {"mid": "0.42"})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    feed = PolymarketFeed()
    feed._symbols = [symbol]
    feed._meta[symbol] = {
        "token_id": "999", "condition_id": "c", "slug": "poll-test",
        "question": "q", "end_date": "",
    }

    received = []

    async def on_tick(tick):
        received.append(tick)

    feed.on_tick(on_tick)

    async with httpx.AsyncClient(timeout=15.0) as client:
        await feed._poll_once(client)

    assert len(received) == 1
    assert received[0].symbol == symbol
    assert received[0].last_price == pytest.approx(0.42)
    assert received[0].exchange == "POLY"
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 019DE49B3A6D - verify with scripts/authorship.py verify
