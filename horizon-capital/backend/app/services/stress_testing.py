"""Stress Testing & Scenario Analysis Service.

Implements historical scenario replay, parametric stress tests, and
correlation breakdown analysis for portfolio risk assessment.

Research references
-------------------
- Jorion, P. (2006). "Value at Risk: The New Benchmark for Managing
  Financial Risk", 3rd ed. (McGraw-Hill) — Ch. 14: Stress Testing.
- Basel Committee on Banking Supervision (2009). "Principles for sound
  stress testing practices and supervision" — regulatory framework.
- Kupiec, P. (1998). "Stress Testing in a Value at Risk Framework",
  J. Derivatives — combining VaR with scenario analysis.
- Rebonato, R. (2010). "Coherent Stress Testing" (Wiley) — systematic
  stress test design with correlation breakdowns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from app.core.logging import get_logger

logger = get_logger("services.stress_testing")


# ---------------------------------------------------------------------------
# Historical crisis scenarios (daily return shocks as multipliers)
# Source: Bloomberg terminal data, widely documented in academic literature
# ---------------------------------------------------------------------------

HISTORICAL_SCENARIOS: dict[str, dict] = {
    "GFC_2008": {
        "name": "Global Financial Crisis (Sep-Nov 2008)",
        "description": "Lehman collapse, credit freeze. S&P500 -38%, NIFTY -52%.",
        "equity_shock": -0.40,
        "bond_shock": 0.05,
        "crypto_shock": 0.0,  # BTC didn't exist
        "fx_usd_inr_shock": 0.12,  # INR depreciated ~12%
        "volatility_multiplier": 3.5,
        "correlation_increase": 0.30,  # correlations spike in crisis
        "duration_days": 65,
        "reference": "Brunnermeier 2009, J. Econ. Perspectives",
    },
    "COVID_2020": {
        "name": "COVID-19 Crash (Feb-Mar 2020)",
        "description": "Pandemic selloff. S&P500 -34%, NIFTY -38%, BTC -50%.",
        "equity_shock": -0.35,
        "bond_shock": 0.08,
        "crypto_shock": -0.50,
        "fx_usd_inr_shock": 0.06,
        "volatility_multiplier": 4.0,
        "correlation_increase": 0.35,
        "duration_days": 23,
        "reference": "Baker et al. 2020, Rev. Asset Pricing Studies",
    },
    "TAPER_TANTRUM_2013": {
        "name": "Taper Tantrum (May-Aug 2013)",
        "description": "Fed tapering fears. EM selloff, INR -20%.",
        "equity_shock": -0.08,
        "bond_shock": -0.05,
        "crypto_shock": 0.0,
        "fx_usd_inr_shock": 0.20,
        "volatility_multiplier": 2.0,
        "correlation_increase": 0.20,
        "duration_days": 90,
        "reference": "Eichengreen & Gupta 2015, J. Policy Modeling",
    },
    "DOT_COM_2000": {
        "name": "Dot-Com Bust (Mar 2000 - Oct 2002)",
        "description": "Tech bubble collapse. NASDAQ -78%.",
        "equity_shock": -0.45,
        "bond_shock": 0.10,
        "crypto_shock": 0.0,
        "fx_usd_inr_shock": 0.03,
        "volatility_multiplier": 2.5,
        "correlation_increase": 0.15,
        "duration_days": 920,
        "reference": "Ofek & Richardson 2003, J. Finance",
    },
    "CRYPTO_WINTER_2022": {
        "name": "Crypto Winter (Nov 2021 - Dec 2022)",
        "description": "Luna/FTX collapse. BTC -77%, ETH -82%.",
        "equity_shock": -0.10,
        "bond_shock": -0.12,
        "crypto_shock": -0.77,
        "fx_usd_inr_shock": 0.10,
        "volatility_multiplier": 2.0,
        "correlation_increase": 0.10,
        "duration_days": 395,
        "reference": "Bianchi 2023, J. Financial Economics",
    },
    "FLASH_CRASH_2010": {
        "name": "Flash Crash (May 6, 2010)",
        "description": "Intraday -9.2% in minutes, rapid recovery.",
        "equity_shock": -0.09,
        "bond_shock": 0.02,
        "crypto_shock": 0.0,
        "fx_usd_inr_shock": 0.01,
        "volatility_multiplier": 5.0,
        "correlation_increase": 0.50,
        "duration_days": 1,
        "reference": "Kirilenko et al. 2017, J. Finance",
    },
    "RATE_HIKE_2022": {
        "name": "Fed Rate Hike Cycle (Jan-Oct 2022)",
        "description": "Aggressive Fed tightening. 60/40 worst year since 1937.",
        "equity_shock": -0.25,
        "bond_shock": -0.18,
        "crypto_shock": -0.65,
        "fx_usd_inr_shock": 0.11,
        "volatility_multiplier": 2.0,
        "correlation_increase": 0.25,
        "duration_days": 280,
        "reference": "Campbell et al. 2023, NBER Working Paper",
    },
    "INDIA_DEMONETIZATION_2016": {
        "name": "India Demonetization (Nov 2016)",
        "description": "Sudden 86% currency withdrawal. NIFTY -6%, banking chaos.",
        "equity_shock": -0.06,
        "bond_shock": 0.02,
        "crypto_shock": 0.15,  # BTC rallied in India
        "fx_usd_inr_shock": 0.03,
        "volatility_multiplier": 1.8,
        "correlation_increase": 0.10,
        "duration_days": 30,
        "reference": "Chodorow-Reich et al. 2020, Econometrica",
    },
}


@dataclass
class ScenarioResult:
    """Result of applying a stress scenario to the portfolio."""

    scenario_name: str
    scenario_key: str
    portfolio_impact_pct: float  # portfolio return under scenario
    portfolio_impact_abs: float  # absolute dollar impact
    var_under_stress: float  # stressed VaR
    worst_asset: str  # most impacted asset
    worst_asset_impact: float
    best_asset: str  # least impacted asset
    best_asset_impact: float
    stressed_correlation: float  # avg correlation under stress
    recovery_estimate_days: int
    details: dict = field(default_factory=dict)


@dataclass
class StressTestReport:
    """Full stress test report across multiple scenarios."""

    timestamp: str
    portfolio_value: float
    n_scenarios: int
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    worst_case_scenario: str = ""
    worst_case_impact_pct: float = 0.0
    aggregate_risk_score: float = 0.0  # 0-100 scale
    parametric_results: dict = field(default_factory=dict)


class StressTestingService:
    """Portfolio stress testing using historical scenarios and parametric shocks.

    Ref: Jorion 2006, "Value at Risk" Ch. 14 — combines historical scenarios
    with hypothetical (parametric) stress tests for comprehensive risk coverage.
    """

    def __init__(self) -> None:
        self._scenarios = HISTORICAL_SCENARIOS

    # ------------------------------------------------------------------
    # Historical scenario analysis
    # ------------------------------------------------------------------

    def run_historical_scenarios(
        self,
        positions: list[dict],
        portfolio_value: float,
    ) -> StressTestReport:
        """Apply all historical crisis scenarios to current portfolio.

        Parameters
        ----------
        positions : list[dict]
            Current positions: [{symbol, exchange, quantity, current_price, weight_pct}]
        portfolio_value : float
            Current total portfolio value.

        Returns
        -------
        StressTestReport
        """
        results: list[ScenarioResult] = []

        for key, scenario in self._scenarios.items():
            result = self._apply_scenario(key, scenario, positions, portfolio_value)
            results.append(result)

        # Find worst case
        worst = min(results, key=lambda r: r.portfolio_impact_pct) if results else None

        # Aggregate risk score (0-100): weighted avg of impact severity
        # Score = 100 means all scenarios cause >50% loss
        if results:
            impacts = [abs(r.portfolio_impact_pct) for r in results]
            raw_score = np.mean(impacts) / 0.50 * 100  # normalize: 50% loss = 100
            aggregate_score = min(100.0, max(0.0, float(raw_score)))
        else:
            aggregate_score = 0.0

        report = StressTestReport(
            timestamp=datetime.now(UTC).isoformat(),
            portfolio_value=portfolio_value,
            n_scenarios=len(results),
            scenario_results=results,
            worst_case_scenario=worst.scenario_key if worst else "",
            worst_case_impact_pct=worst.portfolio_impact_pct if worst else 0.0,
            aggregate_risk_score=round(aggregate_score, 1),
        )

        logger.info(
            "stress_test_complete",
            n_scenarios=len(results),
            worst_case=report.worst_case_scenario,
            worst_impact=f"{report.worst_case_impact_pct:.1%}",
            risk_score=report.aggregate_risk_score,
        )

        return report

    def _apply_scenario(
        self,
        key: str,
        scenario: dict,
        positions: list[dict],
        portfolio_value: float,
    ) -> ScenarioResult:
        """Apply a single scenario to the portfolio."""
        asset_impacts: dict[str, float] = {}
        total_impact = 0.0

        for pos in positions:
            symbol = pos.get("symbol", "")
            weight = pos.get("weight_pct", 0.0) / 100.0
            value = portfolio_value * weight

            # Classify asset and apply appropriate shock
            shock = self._get_shock_for_asset(symbol, scenario)

            # Add correlation-spike adjustment
            # Ref: Rebonato 2010 — correlations increase in crisis
            corr_adj = scenario.get("correlation_increase", 0.0)
            # Slightly amplify shock for correlated assets
            adjusted_shock = shock * (1 + corr_adj * 0.5)

            impact = value * adjusted_shock
            total_impact += impact
            asset_impacts[symbol] = adjusted_shock

        impact_pct = total_impact / portfolio_value if portfolio_value > 0 else 0.0

        # Stressed VaR: scale normal VaR by volatility multiplier
        # Ref: Basel II.5 stressed VaR = VaR under stress period
        vol_mult = scenario.get("volatility_multiplier", 1.0)
        base_daily_vol = 0.015  # assume 1.5% daily portfolio vol
        stressed_var = base_daily_vol * vol_mult * 2.326  # 99% VaR

        # Find best/worst assets
        if asset_impacts:
            worst_asset = min(asset_impacts, key=asset_impacts.get)
            best_asset = max(asset_impacts, key=asset_impacts.get)
        else:
            worst_asset = best_asset = "N/A"

        # Estimate recovery time (heuristic based on historical data)
        duration = scenario.get("duration_days", 30)
        recovery_days = int(duration * 1.5)  # recovery typically 1.5x crash duration

        return ScenarioResult(
            scenario_name=scenario["name"],
            scenario_key=key,
            portfolio_impact_pct=round(impact_pct, 6),
            portfolio_impact_abs=round(total_impact, 2),
            var_under_stress=round(stressed_var, 6),
            worst_asset=worst_asset,
            worst_asset_impact=round(asset_impacts.get(worst_asset, 0.0), 4),
            best_asset=best_asset,
            best_asset_impact=round(asset_impacts.get(best_asset, 0.0), 4),
            stressed_correlation=round(
                0.50 + scenario.get("correlation_increase", 0.0), 4
            ),
            recovery_estimate_days=recovery_days,
            details={
                "reference": scenario.get("reference", ""),
                "description": scenario.get("description", ""),
            },
        )

    @staticmethod
    def _get_shock_for_asset(symbol: str, scenario: dict) -> float:
        """Map a symbol to the appropriate scenario shock."""
        sym = symbol.upper()

        # Crypto
        if any(c in sym for c in ("BTC", "ETH", "CRYPTO", "-USD")):
            return scenario.get("crypto_shock", 0.0)

        # Indian equities
        if sym.endswith(".NSE") or sym.endswith(".BSE"):
            # Indian stocks get equity shock + FX shock (dollar-denominated impact)
            return scenario.get("equity_shock", 0.0) - scenario.get("fx_usd_inr_shock", 0.0)

        # US equities
        if sym.endswith(".NASDAQ") or sym.endswith(".NYSE"):
            return scenario.get("equity_shock", 0.0)

        # Default: treat as equity
        return scenario.get("equity_shock", 0.0)

    # ------------------------------------------------------------------
    # Parametric stress tests
    # ------------------------------------------------------------------

    def run_parametric(
        self,
        positions: list[dict],
        portfolio_value: float,
        equity_shock: float = -0.20,
        rate_shock_bps: float = 200,
        fx_shock: float = -0.10,
        vol_shock_mult: float = 2.0,
    ) -> dict:
        """Run a custom parametric stress test.

        Parameters
        ----------
        equity_shock : float
            Equity price shock (e.g., -0.20 = -20%).
        rate_shock_bps : float
            Interest rate shock in basis points.
        fx_shock : float
            FX rate shock (e.g., -0.10 = INR depreciates 10%).
        vol_shock_mult : float
            Volatility multiplier.

        Returns
        -------
        dict with impact breakdown.

        Ref: Kupiec 1998, "Stress Testing in a Value at Risk Framework"
        """
        equity_impact = 0.0
        crypto_impact = 0.0
        fx_impact = 0.0

        for pos in positions:
            symbol = pos.get("symbol", "")
            weight = pos.get("weight_pct", 0.0) / 100.0
            value = portfolio_value * weight
            sym = symbol.upper()

            if any(c in sym for c in ("BTC", "ETH", "-USD")):
                crypto_impact += value * equity_shock * 1.5  # crypto beta ~1.5 to equity
            elif sym.endswith(".NSE") or sym.endswith(".BSE"):
                equity_impact += value * equity_shock
                fx_impact += value * fx_shock
            else:
                equity_impact += value * equity_shock

        total_impact = equity_impact + crypto_impact + fx_impact
        # Bond duration impact: roughly 7y duration * rate_shock_bps/10000
        # For a typical 60/40 portfolio, 40% in bonds
        bond_pct = max(0, 1.0 - sum(
            p.get("weight_pct", 0) / 100 for p in positions
        ))
        bond_impact = portfolio_value * bond_pct * (-7.0 * rate_shock_bps / 10000)
        total_impact += bond_impact

        impact_pct = total_impact / portfolio_value if portfolio_value > 0 else 0.0

        result = {
            "equity_impact": round(equity_impact, 2),
            "crypto_impact": round(crypto_impact, 2),
            "fx_impact": round(fx_impact, 2),
            "bond_impact": round(bond_impact, 2),
            "total_impact": round(total_impact, 2),
            "impact_pct": round(impact_pct, 6),
            "stressed_volatility": round(0.015 * vol_shock_mult * np.sqrt(252), 4),
            "parameters": {
                "equity_shock": equity_shock,
                "rate_shock_bps": rate_shock_bps,
                "fx_shock": fx_shock,
                "vol_shock_mult": vol_shock_mult,
            },
        }

        logger.info("parametric_stress_complete", **result)
        return result

    # ------------------------------------------------------------------
    # Correlation breakdown analysis
    # ------------------------------------------------------------------

    @staticmethod
    def correlation_breakdown(
        returns_matrix: np.ndarray,
        asset_names: list[str],
        crisis_threshold: float = -0.02,
    ) -> dict:
        """Analyze how correlations change during crisis periods.

        Ref: Rebonato 2010, "Coherent Stress Testing" — correlations
        systematically increase during market stress, reducing
        diversification benefits when they're needed most.

        Parameters
        ----------
        returns_matrix : np.ndarray
            (n_days, n_assets) matrix of daily returns.
        asset_names : list[str]
            Asset names corresponding to columns.
        crisis_threshold : float
            Define a crisis day as avg return < this threshold.

        Returns
        -------
        dict with normal_corr, crisis_corr, and diversification_decay.
        """
        if returns_matrix.shape[0] < 30 or returns_matrix.shape[1] < 2:
            return {"normal_corr": {}, "crisis_corr": {}, "diversification_decay": 0.0}

        # Identify crisis days
        avg_return = np.mean(returns_matrix, axis=1)
        crisis_mask = avg_return < crisis_threshold
        normal_mask = ~crisis_mask

        if crisis_mask.sum() < 5 or normal_mask.sum() < 5:
            return {"normal_corr": {}, "crisis_corr": {}, "diversification_decay": 0.0}

        normal_corr = np.corrcoef(returns_matrix[normal_mask].T)
        crisis_corr = np.corrcoef(returns_matrix[crisis_mask].T)

        # Average off-diagonal correlation
        n = len(asset_names)
        mask = ~np.eye(n, dtype=bool)
        avg_normal = float(np.mean(normal_corr[mask]))
        avg_crisis = float(np.mean(crisis_corr[mask]))

        # Diversification decay = how much diversification benefit disappears in crisis
        decay = (avg_crisis - avg_normal) / max(1 - avg_normal, 0.01)

        return {
            "normal_avg_correlation": round(avg_normal, 4),
            "crisis_avg_correlation": round(avg_crisis, 4),
            "diversification_decay": round(float(decay), 4),
            "crisis_days_pct": round(float(crisis_mask.mean()), 4),
            "n_assets": n,
        }
