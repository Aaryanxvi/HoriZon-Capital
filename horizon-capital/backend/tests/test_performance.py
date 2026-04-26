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
    """Worker Sortino must subtract settings.risk_free_rate, not the hard-coded 0.0.

    With rf=5% and equity growing at exactly the daily rf, *correct* Sortino is small
    but non-zero (~0.06) due to floating-point noise. A Sortino of exactly 0.0 would
    indicate the rf subtraction was omitted entirely (returns become uniform
    positives -> downside_diff zero -> guard returns 0.0).
    """
    monkeypatch.setattr(settings, "risk_free_rate", 0.05)
    daily_rf = (1.05) ** (1 / 252) - 1
    eq = np.array([100.0 * (1 + daily_rf) ** i for i in range(60)], dtype=np.float64)
    sortino = WorkerPerfSvc._sortino_ratio(eq)
    assert abs(sortino) < 0.2, f"expected ~0 Sortino at rf=5%, got {sortino}"
    assert sortino != 0.0, (
        "Sortino returned exactly 0.0 -- rf subtraction likely missing "
        "(uniform positive returns -> empty downside)"
    )


def test_service_does_not_hardcode_5pct_rf() -> None:
    """services.performance must not hard-code 1.05 -- it must read settings."""
    import inspect
    from app.services.performance import PerformanceService as SvcPerfSvc

    src = inspect.getsource(SvcPerfSvc.compute_snapshot)
    assert "(1.05) ** (1 / 252)" not in src, "found hard-coded 5% rf -- must read settings.risk_free_rate"
    assert "settings.risk_free_rate" in src


def test_report_generator_does_not_hardcode_5pct_rf() -> None:
    """report_generator must not hard-code 1.05 either."""
    import inspect
    from app.services import report_generator as rg

    src = inspect.getsource(rg.ReportGenerator._fill_performance)
    # Allow `1.05` only inside comments / strings if any; the daily_rf computation
    # specifically must use settings.risk_free_rate.
    assert "(1.05) ** (1 / 252)" not in src, (
        "report_generator still hard-codes 5% daily_rf"
    )
    assert "settings.risk_free_rate" in src
