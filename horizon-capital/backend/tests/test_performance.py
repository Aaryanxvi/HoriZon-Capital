"""Tests for the performance reporting pipeline P0 fixes."""
from __future__ import annotations

import numpy as np
import pytest

from app.config import settings
from app.workers.performance_worker import PerformanceService as WorkerPerfSvc


def test_risk_free_rate_default_is_zero() -> None:
    """Canonical rf default = 0.0 so backtest <-> live Sharpe match unless user opts in."""
    assert hasattr(settings, "risk_free_rate")
    assert settings.risk_free_rate == 0.0


def test_worker_sharpe_uses_config_risk_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker Sharpe must subtract settings.risk_free_rate, not the hard-coded 0.0."""
    monkeypatch.setattr(settings, "risk_free_rate", 0.05)
    daily_rf = (1.05) ** (1 / 252) - 1
    eq = np.array([100.0 * (1 + daily_rf) ** i for i in range(60)], dtype=np.float64)
    sharpe = WorkerPerfSvc._sharpe_ratio(eq)
    assert abs(sharpe) < 0.05, f"expected ~0 Sharpe at rf=5%, got {sharpe}"


def test_worker_sortino_uses_config_risk_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker Sortino must subtract settings.risk_free_rate, not the hard-coded 0.0."""
    monkeypatch.setattr(settings, "risk_free_rate", 0.05)
    daily_rf = (1.05) ** (1 / 252) - 1
    eq = np.array([100.0 * (1 + daily_rf) ** i for i in range(60)], dtype=np.float64)
    sortino = WorkerPerfSvc._sortino_ratio(eq)
    assert abs(sortino) < 0.2, f"expected ~0 Sortino at rf=5%, got {sortino}"
