# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-D4D6A379ECB6
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
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


def test_backtest_sharpe_default_matches_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """BacktestMetrics.sharpe_ratio default must defer to settings.risk_free_rate, not 0.05."""
    from app.backtesting.backtest_metrics import BacktestMetrics

    monkeypatch.setattr(settings, "risk_free_rate", 0.0)
    rng = np.random.default_rng(42)
    daily = rng.normal(0.0, 0.01, size=252)
    s_default = BacktestMetrics.sharpe_ratio(daily)
    s_explicit_zero = BacktestMetrics.sharpe_ratio(daily, risk_free=0.0)
    assert abs(s_default - s_explicit_zero) < 1e-9


def test_backtest_sharpe_reads_nonzero_config_rf(monkeypatch: pytest.MonkeyPatch) -> None:
    """BacktestMetrics.sharpe_ratio must subtract a non-zero settings.risk_free_rate."""
    from app.backtesting.backtest_metrics import BacktestMetrics

    monkeypatch.setattr(settings, "risk_free_rate", 0.05)
    daily_rf = (1.05) ** (1 / 252) - 1
    daily = np.array([daily_rf] * 252, dtype=np.float64)
    sharpe = BacktestMetrics.sharpe_ratio(daily)
    # All returns equal daily_rf -> excess all zero -> guard returns 0.0
    assert sharpe == 0.0, f"expected 0 Sharpe (uniform returns at rf), got {sharpe}"


def test_quant_sharpe_subtracts_rf(monkeypatch: pytest.MonkeyPatch) -> None:
    """metrics_advanced.sharpe_ratio must subtract settings.risk_free_rate from returns."""
    from app.quant import metrics_advanced as ma

    monkeypatch.setattr(settings, "risk_free_rate", 0.05)
    daily_rf = (1.05) ** (1 / 252) - 1
    daily = np.array([daily_rf] * 252, dtype=np.float64)
    s = ma.sharpe_ratio(daily)
    # All returns equal daily_rf -> excess all zero -> Sharpe should be 0.0
    assert s == 0.0, f"expected 0 Sharpe (uniform returns at rf), got {s}"


@pytest.mark.asyncio
async def test_worker_publishes_alpha_keys_service_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Service reads horizon:performance:alpha_india / alpha_us. Worker MUST write them."""
    from app.core.kv_store import get_kv_store
    from app.workers.performance_worker import PerformanceWorker
    from app.workers.performance_worker import PerformanceService as PS
    import app.workers.performance_worker as pw

    async def fake_snapshot(self, period: str) -> dict:
        return {
            "period": period,
            "total_return": 0.0,
            "annualized_return": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "calmar_ratio": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "alpha_india": 0.0123,
            "alpha_us": 0.0456,
            "total_trades": 0,
            "attribution": {},
        }
    monkeypatch.setattr(PS, "compute_snapshot", fake_snapshot)

    class _NoOpSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def execute(self, *a, **k):
            return None
        async def commit(self):
            return None

    def fake_factory():
        return lambda: _NoOpSession()
    monkeypatch.setattr(pw, "_get_session_factory", fake_factory)

    worker = PerformanceWorker()
    await worker._compute_and_store_all()

    kv = get_kv_store()
    india = await kv.get("horizon:performance:alpha_india")
    us = await kv.get("horizon:performance:alpha_us")
    assert india is not None, "alpha_india KV key was never written"
    assert us is not None, "alpha_us KV key was never written"
    assert float(india) == pytest.approx(0.0123)
    assert float(us) == pytest.approx(0.0456)


@pytest.mark.asyncio
async def test_service_period_case_insensitive_ytd(monkeypatch: pytest.MonkeyPatch) -> None:
    """compute_snapshot('ytd') must scope to year-start, not last 30 days."""
    from datetime import datetime, UTC
    captured: dict = {}

    class _Result:
        def fetchall(self):
            return []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, _stmt, params):
            captured.setdefault("starts", []).append(params["start"])
            return _Result()

    from app.services.performance import PerformanceService
    import app.services.performance as svc

    monkeypatch.setattr(svc, "_get_session_factory", lambda: lambda: _Session())

    await PerformanceService.compute_snapshot("ytd")
    assert len(captured["starts"]) > 0, "no queries executed"
    start_date = captured["starts"][0]
    now = datetime.now(UTC)
    assert start_date.year == now.year, f"YTD start should be year {now.year}, got {start_date.year}"
    assert start_date.month == 1, f"YTD start should be month 1, got {start_date.month}"
    assert start_date.day == 1, f"YTD start should be day 1, got {start_date.day}"


@pytest.mark.asyncio
async def test_service_period_case_insensitive_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """compute_snapshot('all') must scope from year 2000, not last 30 days."""
    from datetime import datetime, UTC
    captured: dict = {}

    class _Result:
        def fetchall(self):
            return []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, _stmt, params):
            captured.setdefault("starts", []).append(params["start"])
            return _Result()

    from app.services.performance import PerformanceService
    import app.services.performance as svc

    monkeypatch.setattr(svc, "_get_session_factory", lambda: lambda: _Session())

    await PerformanceService.compute_snapshot("all")
    assert len(captured["starts"]) > 0, "no queries executed"
    start_date = captured["starts"][0]
    assert start_date.year == 2000, f"ALL start should be year 2000, got {start_date.year}"
    assert start_date.month == 1, f"ALL start should be month 1, got {start_date.month}"
    assert start_date.day == 1, f"ALL start should be day 1, got {start_date.day}"


@pytest.mark.asyncio
async def test_service_pnl_curve_case_insensitive_ytd(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_pnl_curve('ytd') must scope to year-start, not last 30 days."""
    from datetime import datetime, UTC
    captured: dict = {}

    class _Result:
        def fetchall(self):
            return []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, _stmt, params):
            captured.setdefault("starts", []).append(params["start"])
            return _Result()

    from app.services.performance import PerformanceService
    import app.services.performance as svc

    monkeypatch.setattr(svc, "_get_session_factory", lambda: lambda: _Session())

    await PerformanceService.get_pnl_curve("ytd")
    assert len(captured["starts"]) > 0, "no queries executed"
    start_date = captured["starts"][0]
    now = datetime.now(UTC)
    assert start_date.year == now.year, f"YTD start should be year {now.year}, got {start_date.year}"
    assert start_date.month == 1, f"YTD start should be month 1, got {start_date.month}"
    assert start_date.day == 1, f"YTD start should be day 1, got {start_date.day}"


@pytest.mark.asyncio
async def test_service_pnl_curve_case_insensitive_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_pnl_curve('all') must scope from year 2000, not last 30 days."""
    from datetime import datetime, UTC
    captured: dict = {}

    class _Result:
        def fetchall(self):
            return []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, _stmt, params):
            captured.setdefault("starts", []).append(params["start"])
            return _Result()

    from app.services.performance import PerformanceService
    import app.services.performance as svc

    monkeypatch.setattr(svc, "_get_session_factory", lambda: lambda: _Session())

    await PerformanceService.get_pnl_curve("all")
    assert len(captured["starts"]) > 0, "no queries executed"
    start_date = captured["starts"][0]
    assert start_date.year == 2000, f"ALL start should be year 2000, got {start_date.year}"
    assert start_date.month == 1, f"ALL start should be month 1, got {start_date.month}"
    assert start_date.day == 1, f"ALL start should be day 1, got {start_date.day}"
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token D4D6A379ECB6 - verify with scripts/authorship.py verify
