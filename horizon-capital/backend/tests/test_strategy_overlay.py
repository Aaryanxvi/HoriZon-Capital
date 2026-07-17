"""StrategyAgent wiring: validated sleeve mix + overlay hook (flag-gated)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.agents.front_office.strategy.strategy_agent import StrategyAgent
from app.config import settings
from app.core.memory_bus import MemoryBus


def _agent() -> StrategyAgent:
    return StrategyAgent(bus=MemoryBus())


def _spy_bars(start: float, end: float, n: int = 300) -> dict[str, pd.DataFrame]:
    idx = pd.bdate_range("2019-01-01", periods=n)
    close = pd.Series(np.linspace(start, end, n), index=idx)
    df = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1e6},
        index=idx,
    )
    return {"SPY.NYSE": df}


def test_live_mix_is_the_validated_configuration():
    # Holdout gate (PIT 2008-17): Sharpe 0.70 vs 0.63, maxDD -19.1 vs -26.9, same
    # CAGR. breadth_alpha dropped 2026-07-17 (failed attribution + this gate).
    # dual_momentum and the overlay failed their own ship gate (2026-07-02) and
    # must NOT be wired.
    weights = {s.name: s.target_weight for s in _agent()._sleeves}
    assert weights == {
        "research_stack": 0.500,
        "trend_filter": 0.333,
        "momentum_rank": 0.167,
    }
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    assert "dual_momentum" not in weights
    assert "breadth_alpha" not in weights


def test_overlay_disabled_is_identity(monkeypatch):
    monkeypatch.setattr(settings, "overlay_enabled", False, raising=False)
    targets = {"SPY.NYSE": 0.5}
    assert _agent()._apply_overlay(targets, _spy_bars(100.0, 200.0)) == targets


def test_overlay_zeroes_exposure_in_downtrend(monkeypatch):
    monkeypatch.setattr(settings, "overlay_enabled", True, raising=False)
    out = _agent()._apply_overlay({"SPY.NYSE": 0.5}, _spy_bars(200.0, 100.0))
    assert out["SPY.NYSE"] == 0.0


def test_overlay_fail_open_without_spy(monkeypatch):
    monkeypatch.setattr(settings, "overlay_enabled", True, raising=False)
    bars = {k.replace("SPY.NYSE", "QQQ.NASDAQ"): v for k, v in _spy_bars(200.0, 100.0).items()}
    targets = {"QQQ.NASDAQ": 0.5}
    assert _agent()._apply_overlay(targets, bars) == targets
