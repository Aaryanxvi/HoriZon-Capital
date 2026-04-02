"""Cross-market arbitrage detection via PCA eigenportfolios and pairs trading.

Identifies statistical arbitrage opportunities across NSE, NASDAQ, and crypto
markets using principal component analysis and mean-reverting spread signals.

Research references
-------------------
- Avellaneda & Lee 2010, Quantitative Finance (~800 citations)
  — "Statistical Arbitrage in the U.S. Equities Market."
  PCA on normalized cumulative returns → eigenportfolios explain ~55%
  of variance. Idiosyncratic residuals modeled as mean-reverting AR(1):
  dr_i = -κ(r_i - r̄)dt + σ dW_i.
  s-score = (r_i - r̄) / σ_eq  where σ_eq = σ / √(2κ).
  Entry when |s-score| > 1.25, exit when |s-score| < 0.5.
  Average Sharpe ratio: 1.44 (1997-2007).

- Gatev, Goetzmann & Rouwenhorst 2006, Review of Financial Studies (~2,000 citations)
  — "Pairs Trading: Performance of a Relative Value Arbitrage Rule."
  Distance method: D(i,j) = Σ(P_i(t)/P_i(0) - P_j(t)/P_j(0))².
  252-day formation period, select top 20 closest pairs.
  Entry at 2σ divergence, exit at convergence.
  Annualized excess returns: up to 11%.

- Vidyamurthy 2004, "Pairs Trading: Quantitative Methods and Analysis" (Wiley)
  — Cointegration-based pair identification using Engle-Granger two-step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.core.logging import get_logger

logger = get_logger("strategy.arbitrage")


@dataclass
class ArbitragePair:
    """A detected arbitrage pair with spread statistics."""

    symbol_a: str
    symbol_b: str
    distance: float        # Euclidean distance (Gatev et al. 2006)
    correlation: float
    spread_zscore: float   # Current z-score of spread
    half_life: float       # Mean-reversion half-life in days
    s_score: float         # Avellaneda-Lee s-score
    signal: str            # "LONG_A_SHORT_B", "SHORT_A_LONG_B", "NONE"
    confidence: float


@dataclass
class EigenportfolioResult:
    """PCA eigenportfolio decomposition result."""

    n_components: int
    variance_explained: float
    eigenvalues: list[float]
    residuals: dict[str, np.ndarray]  # symbol -> idiosyncratic residual
    s_scores: dict[str, float]        # symbol -> s-score


# ------------------------------------------------------------------
# PCA Eigenportfolio Method (Avellaneda & Lee 2010)
# ------------------------------------------------------------------

class EigenportfolioDetector:
    """Statistical arbitrage via PCA eigenportfolios.

    Avellaneda & Lee 2010 protocol:
    1. Normalize cumulative returns across universe.
    2. Compute correlation matrix, extract eigenvalues/vectors via PCA.
    3. Select components explaining ≥55% variance.
    4. Compute idiosyncratic residuals = total return - systematic component.
    5. Model residuals as mean-reverting AR(1): dr = -κ(r - r̄)dt + σ dW.
    6. Compute s-score = (r - r̄) / σ_eq where σ_eq = σ / √(2κ).
    7. Entry when |s-score| > 1.25, exit when |s-score| < 0.50.
    """

    def __init__(
        self,
        variance_threshold: float = 0.55,
        entry_s_score: float = 1.25,
        exit_s_score: float = 0.50,
    ) -> None:
        self.variance_threshold = variance_threshold
        self.entry_s_score = entry_s_score
        self.exit_s_score = exit_s_score

    def decompose(
        self,
        returns: dict[str, np.ndarray],
    ) -> EigenportfolioResult:
        """PCA decomposition on normalized returns.

        Avellaneda & Lee 2010, Section 2.1:
        1. Construct matrix X where X[t, i] = cumulative normalized return.
        2. Compute correlation matrix Σ = X^T X / T.
        3. Eigendecomposition: Σ = VΛV^T.
        4. Select top k eigenvectors explaining ≥ variance_threshold.
        5. Residual = X - X_hat where X_hat = X · V_k · V_k^T.
        """
        symbols = list(returns.keys())
        if len(symbols) < 3:
            return EigenportfolioResult(0, 0.0, [], {}, {})

        # Build return matrix (T x N)
        min_len = min(len(r) for r in returns.values())
        R = np.column_stack([returns[s][:min_len] for s in symbols])  # noqa: N806

        # Normalize: cumulative returns
        cum_returns = np.cumsum(R, axis=0)

        # Demean
        cum_returns -= cum_returns.mean(axis=0)

        # Correlation matrix
        if cum_returns.shape[0] < 2:
            return EigenportfolioResult(0, 0.0, [], {}, {})

        cov_matrix = np.cov(cum_returns.T)
        if cov_matrix.ndim < 2:
            return EigenportfolioResult(0, 0.0, [], {}, {})

        # Eigendecomposition
        eigenvalues, eigenvectors = np.linalg.eigh(cov_matrix)

        # Sort descending
        idx = np.argsort(eigenvalues)[::-1]
        eigenvalues = eigenvalues[idx]
        eigenvectors = eigenvectors[:, idx]

        # Select components explaining >= threshold variance
        total_var = np.sum(eigenvalues)
        if total_var <= 0:
            return EigenportfolioResult(0, 0.0, [], {}, {})

        cumulative_var = np.cumsum(eigenvalues) / total_var
        n_components = int(np.searchsorted(cumulative_var, self.variance_threshold) + 1)
        n_components = min(n_components, len(eigenvalues))

        # Systematic component: projection onto top eigenvectors
        V_k = eigenvectors[:, :n_components]  # noqa: N806
        systematic = cum_returns @ V_k @ V_k.T

        # Idiosyncratic residuals (Avellaneda & Lee 2010, eq. 3)
        residuals_matrix = cum_returns - systematic

        # Compute s-scores for each symbol (Avellaneda & Lee 2010, eq. 6-7)
        residuals = {}
        s_scores = {}

        for i, sym in enumerate(symbols):
            res = residuals_matrix[:, i]
            residuals[sym] = res

            # Fit AR(1): r_t = a + b·r_{t-1} + ε_t
            if len(res) > 10:
                kappa, sigma_eq = self._fit_ou(res)
                r_bar = np.mean(res)
                if sigma_eq > 0:
                    s_scores[sym] = float((res[-1] - r_bar) / sigma_eq)
                else:
                    s_scores[sym] = 0.0
            else:
                s_scores[sym] = 0.0

        return EigenportfolioResult(
            n_components=n_components,
            variance_explained=float(cumulative_var[n_components - 1]),
            eigenvalues=[float(e) for e in eigenvalues[:n_components]],
            residuals=residuals,
            s_scores=s_scores,
        )

    def get_signals(
        self, result: EigenportfolioResult,
    ) -> list[dict[str, Any]]:
        """Generate trading signals from s-scores.

        Avellaneda & Lee 2010, Section 3.2:
        - s-score > +entry → SHORT (mean revert down)
        - s-score < -entry → LONG (mean revert up)
        - |s-score| < exit → CLOSE position
        """
        signals = []
        for sym, s in result.s_scores.items():
            if s > self.entry_s_score:
                signals.append({
                    "symbol": sym,
                    "direction": -1,  # SHORT
                    "strength": min(1.0, abs(s) / 3.0),
                    "s_score": round(s, 4),
                    "reasoning": (
                        f"s-score={s:.2f} > {self.entry_s_score} → "
                        f"idiosyncratic overvaluation. Ref: Avellaneda & Lee 2010."
                    ),
                })
            elif s < -self.entry_s_score:
                signals.append({
                    "symbol": sym,
                    "direction": 1,  # LONG
                    "strength": min(1.0, abs(s) / 3.0),
                    "s_score": round(s, 4),
                    "reasoning": (
                        f"s-score={s:.2f} < -{self.entry_s_score} → "
                        f"idiosyncratic undervaluation. Ref: Avellaneda & Lee 2010."
                    ),
                })
        return signals

    @staticmethod
    def _fit_ou(residuals: np.ndarray) -> tuple[float, float]:
        """Fit Ornstein-Uhlenbeck process to residuals via OLS.

        Avellaneda & Lee 2010, eq. 4-5:
        Discrete AR(1): r_t = a + b·r_{t-1} + ε
        κ = -ln(b) / Δt  (mean-reversion speed)
        σ_eq = σ_ε / √(2κ)  (equilibrium standard deviation)
        """
        y = residuals[1:]
        x = residuals[:-1]

        if len(x) < 5:
            return 0.0, 1.0

        x_mean = np.mean(x)
        b = np.sum((x - x_mean) * (y - np.mean(y))) / (np.sum((x - x_mean) ** 2) + 1e-12)
        a = np.mean(y) - b * x_mean

        # Mean-reversion speed
        b = max(0.01, min(0.999, b))  # Bound for stability
        kappa = -np.log(b)

        # Residual std
        eps = y - (a + b * x)
        sigma_eps = float(np.std(eps))

        # Equilibrium std
        sigma_eq = sigma_eps / np.sqrt(2 * kappa) if kappa > 0 else sigma_eps

        return float(kappa), float(sigma_eq)


# ------------------------------------------------------------------
# Pairs Trading (Gatev, Goetzmann & Rouwenhorst 2006)
# ------------------------------------------------------------------

class PairsTradingDetector:
    """Distance-based pairs trading.

    Gatev et al. 2006 protocol:
    1. 252-day formation period: normalize prices, compute distance matrix.
    2. D(i,j) = Σ(P_i(t)/P_i(0) - P_j(t)/P_j(0))² (squared Euclidean).
    3. Select top_n pairs with smallest distance.
    4. Trading period: enter when spread > 2σ, exit at convergence.
    5. Hold max 6 months.
    """

    def __init__(
        self,
        formation_days: int = 252,
        top_n: int = 20,
        entry_threshold: float = 2.0,
        exit_threshold: float = 0.5,
    ) -> None:
        self.formation_days = formation_days
        self.top_n = top_n
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold

    def find_pairs(
        self, prices: dict[str, np.ndarray],
    ) -> list[ArbitragePair]:
        """Find closest pairs using distance method.

        Gatev et al. 2006, Section II.A:
        D(i,j) = Σ_t (P_i(t)/P_i(0) - P_j(t)/P_j(0))²
        """
        symbols = list(prices.keys())
        n = len(symbols)
        if n < 2:
            return []

        # Normalize prices (Gatev et al. 2006)
        min_len = min(len(p) for p in prices.values())
        normed: dict[str, np.ndarray] = {}
        for s in symbols:
            p = prices[s][:min_len]
            if p[0] > 0:
                normed[s] = p / p[0]
            else:
                normed[s] = np.ones(min_len)

        # Compute distance matrix
        pairs: list[tuple[float, str, str]] = []
        for i in range(n):
            for j in range(i + 1, n):
                diff = normed[symbols[i]] - normed[symbols[j]]
                dist = float(np.sum(diff ** 2))
                pairs.append((dist, symbols[i], symbols[j]))

        # Sort by distance (smallest first)
        pairs.sort(key=lambda x: x[0])

        # Select top N closest pairs
        results: list[ArbitragePair] = []
        for dist, sym_a, sym_b in pairs[: self.top_n]:
            # Compute spread statistics
            spread = normed[sym_a] - normed[sym_b]
            spread_mean = float(np.mean(spread))
            spread_std = float(np.std(spread))
            if spread_std < 1e-10:
                continue

            zscore = float((spread[-1] - spread_mean) / spread_std)

            # Correlation
            corr = float(np.corrcoef(normed[sym_a], normed[sym_b])[0, 1])

            # Half-life from AR(1) (Vidyamurthy 2004)
            half_life = self._compute_half_life(spread)

            # s-score (Avellaneda & Lee 2010 style)
            s_score = zscore

            # Signal based on z-score thresholds (Gatev et al. 2006)
            if zscore > self.entry_threshold:
                signal = "SHORT_A_LONG_B"
                confidence = min(1.0, abs(zscore) / 4.0)
            elif zscore < -self.entry_threshold:
                signal = "LONG_A_SHORT_B"
                confidence = min(1.0, abs(zscore) / 4.0)
            else:
                signal = "NONE"
                confidence = 0.0

            results.append(ArbitragePair(
                symbol_a=sym_a,
                symbol_b=sym_b,
                distance=round(dist, 6),
                correlation=round(corr, 4),
                spread_zscore=round(zscore, 4),
                half_life=round(half_life, 1),
                s_score=round(s_score, 4),
                signal=signal,
                confidence=round(confidence, 4),
            ))

        return results

    @staticmethod
    def _compute_half_life(spread: np.ndarray) -> float:
        """Compute mean-reversion half-life from AR(1) regression.

        Vidyamurthy 2004: t_{1/2} = -ln(2) / ln(b)
        where b is the AR(1) coefficient.
        """
        y = spread[1:]
        x = spread[:-1]

        if len(x) < 5:
            return 999.0

        x_mean = np.mean(x)
        denom = np.sum((x - x_mean) ** 2)
        if denom < 1e-12:
            return 999.0

        b = np.sum((x - x_mean) * (y - np.mean(y))) / denom

        if b <= 0 or b >= 1:
            return 999.0

        return float(-np.log(2) / np.log(b))


# ------------------------------------------------------------------
# Combined Arbitrage Detector
# ------------------------------------------------------------------

class CrossMarketArbitrageDetector:
    """Combines PCA eigenportfolio and pairs trading for cross-market detection.

    Uses Avellaneda & Lee 2010 for universe-wide systematic decomposition
    and Gatev et al. 2006 for pairwise spread trading.
    """

    def __init__(self) -> None:
        self.eigen = EigenportfolioDetector(
            variance_threshold=0.55,
            entry_s_score=1.25,
            exit_s_score=0.50,
        )
        self.pairs = PairsTradingDetector(
            formation_days=252,
            top_n=20,
            entry_threshold=2.0,
            exit_threshold=0.5,
        )

    def detect(
        self,
        returns: dict[str, np.ndarray],
        prices: dict[str, np.ndarray],
    ) -> dict[str, Any]:
        """Run both detection methods and return combined results.

        Parameters
        ----------
        returns : dict[str, ndarray]
            Daily returns per symbol.
        prices : dict[str, ndarray]
            Daily prices per symbol.

        Returns
        -------
        dict with keys:
            eigenportfolio: EigenportfolioResult
            eigen_signals: list of signal dicts
            pairs: list of ArbitragePair
            summary: aggregated summary
        """
        # PCA eigenportfolio analysis (Avellaneda & Lee 2010)
        eigen_result = self.eigen.decompose(returns)
        eigen_signals = self.eigen.get_signals(eigen_result)

        # Pairs trading (Gatev et al. 2006)
        pair_results = self.pairs.find_pairs(prices)
        active_pairs = [p for p in pair_results if p.signal != "NONE"]

        logger.info(
            "arbitrage_scan_complete",
            eigen_signals=len(eigen_signals),
            active_pairs=len(active_pairs),
            n_components=eigen_result.n_components,
            variance_explained=round(eigen_result.variance_explained, 3),
        )

        return {
            "eigenportfolio": eigen_result,
            "eigen_signals": eigen_signals,
            "pairs": pair_results,
            "active_pairs": active_pairs,
            "summary": {
                "total_pairs_scanned": len(pair_results),
                "active_arbitrage_signals": len(eigen_signals) + len(active_pairs),
                "pca_components": eigen_result.n_components,
                "variance_explained": round(eigen_result.variance_explained, 3),
            },
        }
