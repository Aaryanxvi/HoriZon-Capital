"""Tests for the performance reporting pipeline P0 fixes."""
from __future__ import annotations

from app.config import settings


def test_risk_free_rate_default_is_zero() -> None:
    """Canonical rf default = 0.0 so backtest <-> live Sharpe match unless user opts in."""
    assert hasattr(settings, "risk_free_rate")
    assert settings.risk_free_rate == 0.0
