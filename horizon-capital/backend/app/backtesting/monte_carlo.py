"""Monte Carlo simulation for risk scenario analysis.

Generates confidence intervals for portfolio outcomes using bootstrap
resampling and parametric (GBM) simulation paths.

Research references
-------------------
- Glasserman 2003, "Monte Carlo Methods in Financial Engineering" (Springer)
  — the standard reference for Monte Carlo in finance. Bootstrap resampling
  of daily returns preserves empirical distribution (fat tails, skew).
- Efron & Tibshirani 1993, "An Introduction to the Bootstrap" — foundation
  for bootstrap confidence intervals.
- McNeil & Frey 2000, J. Empirical Finance (~2,500 citations) — GARCH-EVT
  for tail-aware parametric simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.core.logging import get_logger

logger = get_logger("backtesting.monte_carlo")


@dataclass
class MonteCarloResult:
    """Results from Monte Carlo simulation."""

    n_simulations: int
    n_days: int
    method: str  # "bootstrap" or "gbm"
    initial_value: float

    # Terminal value statistics
    mean_terminal: float = 0.0
    median_terminal: float = 0.0
    percentile_5: float = 0.0
    percentile_25: float = 0.0
    percentile_75: float = 0.0
    percentile_95: float = 0.0

    # Return statistics
    mean_return: float = 0.0
    prob_loss: float = 0.0  # P(terminal < initial)
    prob_gain_10: float = 0.0  # P(return > 10%)
    prob_loss_10: float = 0.0  # P(return < -10%)

    # Drawdown statistics
    mean_max_drawdown: float = 0.0
    worst_max_drawdown: float = 0.0
    percentile_95_drawdown: float = 0.0

    # Sharpe distribution
    mean_sharpe: float = 0.0
    percentile_5_sharpe: float = 0.0
    percentile_95_sharpe: float = 0.0

    # Raw paths for visualization (optional, first 100)
    sample_paths: list[list[float]] = field(default_factory=list)


class MonteCarloSimulator:
    """Monte Carlo simulation engine for portfolio risk analysis.

    Supports two methods:

    1. **Bootstrap resampling** (Ref: Efron & Tibshirani 1993) — resamples
       from actual daily returns, preserving the empirical distribution
       including fat tails and skewness. Preferred when sufficient history
       is available.

    2. **Geometric Brownian Motion** (GBM) — parametric simulation assuming
       log-normal returns. Uses mean and std of historical returns. Faster
       but assumes normality (misses tail risk).
    """

    def __init__(
        self,
        n_simulations: int = 1000,
        random_seed: int | None = None,
    ) -> None:
        self.n_simulations = n_simulations
        self.rng = np.random.default_rng(random_seed)

    # ------------------------------------------------------------------
    # Bootstrap resampling (Ref: Glasserman 2003, Ch. 8)
    # ------------------------------------------------------------------

    def bootstrap(
        self,
        returns: np.ndarray,
        n_days: int = 252,
        initial_value: float = 1_000_000.0,
        block_size: int = 1,
    ) -> MonteCarloResult:
        """Run bootstrap Monte Carlo simulation.

        Parameters
        ----------
        returns:
            Historical daily returns (1D array).
        n_days:
            Number of trading days to simulate forward.
        initial_value:
            Starting portfolio value.
        block_size:
            Block bootstrap size. 1 = i.i.d. bootstrap. > 1 preserves
            short-term autocorrelation (Ref: Politis & Romano 1994).
        """
        ret = np.asarray(returns, dtype=np.float64)
        ret = ret[~np.isnan(ret)]
        if len(ret) < 10:
            logger.warning("monte_carlo_insufficient_data", n_returns=len(ret))
            return MonteCarloResult(
                n_simulations=0, n_days=n_days,
                method="bootstrap", initial_value=initial_value,
            )

        # Generate simulation paths
        paths = np.zeros((self.n_simulations, n_days + 1))
        paths[:, 0] = initial_value

        if block_size <= 1:
            # Standard i.i.d. bootstrap
            sampled_idx = self.rng.integers(0, len(ret), size=(self.n_simulations, n_days))
            sampled_returns = ret[sampled_idx]
        else:
            # Block bootstrap — preserves autocorrelation
            n_blocks = (n_days + block_size - 1) // block_size
            sampled_returns = np.zeros((self.n_simulations, n_days))
            for sim in range(self.n_simulations):
                block_starts = self.rng.integers(0, len(ret) - block_size + 1, size=n_blocks)
                blocks = np.concatenate([ret[s:s + block_size] for s in block_starts])
                sampled_returns[sim] = blocks[:n_days]

        # Compound returns into price paths
        for t in range(n_days):
            paths[:, t + 1] = paths[:, t] * (1 + sampled_returns[:, t])

        return self._compute_statistics(paths, n_days, "bootstrap", initial_value)

    # ------------------------------------------------------------------
    # Geometric Brownian Motion
    # ------------------------------------------------------------------

    def gbm(
        self,
        returns: np.ndarray,
        n_days: int = 252,
        initial_value: float = 1_000_000.0,
    ) -> MonteCarloResult:
        """Run GBM-based Monte Carlo simulation.

        Uses historical mean and volatility to parameterize the GBM:
            dS/S = mu*dt + sigma*dW

        Ref: Glasserman 2003, Ch. 3 — geometric Brownian motion.
        """
        ret = np.asarray(returns, dtype=np.float64)
        ret = ret[~np.isnan(ret)]
        if len(ret) < 10:
            return MonteCarloResult(
                n_simulations=0, n_days=n_days,
                method="gbm", initial_value=initial_value,
            )

        mu = float(np.mean(ret))
        sigma = float(np.std(ret, ddof=1))

        paths = np.zeros((self.n_simulations, n_days + 1))
        paths[:, 0] = initial_value

        # Generate standard normal shocks
        z = self.rng.standard_normal(size=(self.n_simulations, n_days))

        # GBM discretization: S(t+1) = S(t) * exp((mu - 0.5*sigma^2) + sigma*z)
        drift = mu - 0.5 * sigma ** 2
        for t in range(n_days):
            paths[:, t + 1] = paths[:, t] * np.exp(drift + sigma * z[:, t])

        return self._compute_statistics(paths, n_days, "gbm", initial_value)

    # ------------------------------------------------------------------
    # Statistics computation
    # ------------------------------------------------------------------

    def _compute_statistics(
        self,
        paths: np.ndarray,
        n_days: int,
        method: str,
        initial_value: float,
    ) -> MonteCarloResult:
        """Compute summary statistics from simulation paths."""
        terminal = paths[:, -1]
        terminal_returns = (terminal - initial_value) / initial_value

        # Drawdown per path
        max_dds = []
        for i in range(len(paths)):
            running_max = np.maximum.accumulate(paths[i])
            dd = (paths[i] - running_max) / np.where(running_max == 0, 1, running_max)
            max_dds.append(float(abs(np.min(dd))))
        max_dds_arr = np.array(max_dds)

        # Sharpe per path (annualized)
        sharpes = []
        for i in range(len(paths)):
            daily_ret = np.diff(paths[i]) / paths[i][:-1]
            if np.std(daily_ret, ddof=1) > 0:
                sharpes.append(float(np.mean(daily_ret) / np.std(daily_ret, ddof=1) * np.sqrt(252)))
            else:
                sharpes.append(0.0)
        sharpes_arr = np.array(sharpes)

        # Sample paths (first 100 for visualization)
        n_sample = min(100, self.n_simulations)
        sample_paths = [paths[i].tolist() for i in range(n_sample)]

        result = MonteCarloResult(
            n_simulations=self.n_simulations,
            n_days=n_days,
            method=method,
            initial_value=initial_value,
            mean_terminal=round(float(np.mean(terminal)), 2),
            median_terminal=round(float(np.median(terminal)), 2),
            percentile_5=round(float(np.percentile(terminal, 5)), 2),
            percentile_25=round(float(np.percentile(terminal, 25)), 2),
            percentile_75=round(float(np.percentile(terminal, 75)), 2),
            percentile_95=round(float(np.percentile(terminal, 95)), 2),
            mean_return=round(float(np.mean(terminal_returns)), 6),
            prob_loss=round(float(np.mean(terminal < initial_value)), 4),
            prob_gain_10=round(float(np.mean(terminal_returns > 0.10)), 4),
            prob_loss_10=round(float(np.mean(terminal_returns < -0.10)), 4),
            mean_max_drawdown=round(float(np.mean(max_dds_arr)), 6),
            worst_max_drawdown=round(float(np.max(max_dds_arr)), 6),
            percentile_95_drawdown=round(float(np.percentile(max_dds_arr, 95)), 6),
            mean_sharpe=round(float(np.mean(sharpes_arr)), 4),
            percentile_5_sharpe=round(float(np.percentile(sharpes_arr, 5)), 4),
            percentile_95_sharpe=round(float(np.percentile(sharpes_arr, 95)), 4),
            sample_paths=sample_paths,
        )

        logger.info(
            "monte_carlo_complete",
            method=method,
            n_sims=self.n_simulations,
            mean_return=result.mean_return,
            prob_loss=result.prob_loss,
            mean_dd=result.mean_max_drawdown,
        )

        return result
