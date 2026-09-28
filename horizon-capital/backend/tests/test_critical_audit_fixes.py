# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-583FE64D4D3C
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Regression tests for the 2026 critical-audit fixes.

Covers the behaviors that had no prior coverage and fail silently:
  - C2: a stop-loss SELL bypasses the 120s cooldown / dedup (risk-reducing
    exits must never be dropped because a normal order just fired).
  - C3: the FULLY_AUTONOMOUS debate buffer keeps only the latest signal per
    symbol (no unbounded growth, no stale multi-flush).
"""
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent


def _make_agent() -> PortfolioAgent:
    agent = PortfolioAgent(bus=MagicMock())
    agent._size_and_emit = AsyncMock(return_value=True)
    return agent


def test_stop_loss_bypasses_cooldown():
    """A normal signal in cooldown is dropped; a stop-loss is not."""
    agent = _make_agent()
    sym = "AAPL"
    agent._last_order_time[sym] = datetime.now(UTC)  # cooldown active

    # Normal buy within cooldown → dropped (no emit).
    asyncio.run(agent._handle_signal({"symbol": sym, "direction": 1}))
    assert agent._size_and_emit.await_count == 0

    # Stop-loss within the same cooldown → emitted anyway.
    asyncio.run(agent._handle_signal(
        {"symbol": sym, "direction": -1, "strategy_name": "stop_loss"}
    ))
    assert agent._size_and_emit.await_count == 1


def test_buffer_keeps_only_latest_signal():
    """In FULLY_AUTONOMOUS, two buffered signals collapse to the latest one."""
    agent = _make_agent()
    sym = "MSFT"

    mode = MagicMock()
    mode.value = "FULLY_AUTONOMOUS"
    with patch(
        "app.agents.front_office.portfolio.portfolio_agent.settings"
    ) as s:
        s.system_mode = mode
        asyncio.run(agent._handle_signal(
            {"symbol": sym, "direction": 1, "signal_id": "a", "bar_timestamp": "t1"}
        ))
        asyncio.run(agent._handle_signal(
            {"symbol": sym, "direction": 1, "signal_id": "b", "bar_timestamp": "t2"}
        ))

    assert len(agent._pending_signals[sym]) == 1
    assert agent._pending_signals[sym][0]["signal_id"] == "b"
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 583FE64D4D3C - verify with scripts/authorship.py verify
