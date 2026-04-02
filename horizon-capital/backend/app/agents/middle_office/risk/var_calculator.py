"""Value-at-Risk and drawdown calculations.

Primary method: GJR-GARCH(1,1) + EVT (Generalized Pareto Distribution)
per McNeil & Frey (2000) and Kuester et al. (2006).
Fallback: Historical simulation when arch library is unavailable.

References
----------
- McNeil & Frey (2000), "Estimation of Tail-Related Risk Measures for
  Heteroscedastic Financial Time Series", J. Empirical Finance.
- Kuester, Mittnik & Paolella (2006), "Value-at-Risk Prediction:
  A Comparison of Alternative Strategies", J. Financial Econometrics.
- Hansen & Lunde (2005), "A Forecast Comparison of Volatility Models",
  J. Applied Econometrics.
"""

import numpy as np

from app.core.logging import get_logger

logger = get_logger("risk.var_calculator")

# Minimum samples for GARCH fitting
_GARCH_MIN_SAMPLES = 100
# Minimum tail observations for GPD fitting
_GPD_MIN_TAIL = 25


class VaRCalculator:
    """GARCH-EVT VaR calculator with historical simulation fallback.

    All methods are pure functions operating on numpy arrays so that the
    calculator stays stateless and easy to test.
    """

    # ------------------------------------------------------------------ #
    # GARCH-EVT VaR (primary)
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_var_garch_evt(
        returns: np.ndarray,
        confidence: float = 0.95,
    ) -> dict:
        """GJR-GARCH(1,1) + EVT VaR and CVaR.

        Steps (McNeil-Frey method):
        1. Fit GJR-GARCH(1,1) with Student-t innovations to capture
           time-varying volatility and leverage effects.
        2. Extract standardised residuals (z_t = r_t / sigma_t).
        3. Fit Generalized Pareto Distribution (GPD) to the left tail
           of standardised residuals for proper tail modeling.
        4. Combine GARCH conditional volatility forecast with GPD quantile
           to produce VaR and Expected Shortfall.

        Parameters
        ----------
        returns:
            Array of daily log-returns.  Needs >= 100 observations for
            reliable GARCH fitting.
        confidence:
            Confidence level (0.95 or 0.99).

        Returns
        -------
        dict
            Keys: ``var``, ``cvar``, ``cond_vol``, ``method``.
            ``method`` is ``"garch_evt"`` or ``"historical"`` (fallback).
        """
        if len(returns) < _GARCH_MIN_SAMPLES:
            # Not enough data — fall back
            var_val = VaRCalculator.compute_var(returns, confidence)
            cvar_val = VaRCalculator.compute_cvar(returns, confidence)
            return {
                "var": var_val,
                "cvar": cvar_val,
                "cond_vol": float(np.std(returns)) if len(returns) > 0 else 0.0,
                "method": "historical",
            }

        try:
            from arch import arch_model
            from scipy.stats import genpareto
        except ImportError:
            logger.warning("arch_or_scipy_not_installed_falling_back_to_historical")
            var_val = VaRCalculator.compute_var(returns, confidence)
            cvar_val = VaRCalculator.compute_cvar(returns, confidence)
            return {
                "var": var_val,
                "cvar": cvar_val,
                "cond_vol": float(np.std(returns)),
                "method": "historical",
            }

        # --- Step 1: Fit GJR-GARCH(1,1) with Student-t ---
        # Scale returns to percentage for numerical stability
        scaled = returns * 100.0
        try:
            model = arch_model(
                scaled,
                vol="GARCH",
                p=1,
                o=1,  # GJR asymmetric term
                q=1,
                dist="StudentsT",
                mean="Zero",
            )
            result = model.fit(disp="off", show_warning=False)
        except Exception as exc:
            logger.warning("garch_fit_failed", error=str(exc))
            var_val = VaRCalculator.compute_var(returns, confidence)
            cvar_val = VaRCalculator.compute_cvar(returns, confidence)
            return {
                "var": var_val,
                "cvar": cvar_val,
                "cond_vol": float(np.std(returns)),
                "method": "historical",
            }

        # --- Step 2: Extract standardised residuals ---
        std_resid = result.std_resid

        # One-step-ahead conditional volatility forecast (scaled back)
        forecast = result.forecast(horizon=1)
        next_vol = float(np.sqrt(forecast.variance.values[-1, 0])) / 100.0

        # --- Step 3: Fit GPD to left tail of standardised residuals ---
        # Use the 10th percentile as the threshold (u)
        losses = -std_resid  # flip sign so losses are positive
        losses = losses[np.isfinite(losses)]
        threshold_pct = 90  # top 10% of losses
        u = float(np.percentile(losses, threshold_pct))
        exceedances = losses[losses > u] - u

        if len(exceedances) < _GPD_MIN_TAIL:
            # Not enough tail data for GPD — use GARCH quantile only
            alpha = 1 - confidence
            from scipy.stats import t as student_t

            nu = result.params.get("nu", 5.0)
            if hasattr(nu, "item"):
                nu = nu.item()
            var_quantile = -student_t.ppf(alpha, df=nu) * next_vol
            cvar_val = var_quantile * 1.2  # rough approximation
            return {
                "var": abs(var_quantile),
                "cvar": abs(cvar_val),
                "cond_vol": next_vol,
                "method": "garch_t",
            }

        # Fit GPD to exceedances
        try:
            shape, _, scale = genpareto.fit(exceedances, floc=0)
        except Exception:
            # GPD fit failed — use parametric GARCH
            alpha = 1 - confidence
            from scipy.stats import t as student_t

            nu = result.params.get("nu", 5.0)
            if hasattr(nu, "item"):
                nu = nu.item()
            var_quantile = -student_t.ppf(alpha, df=nu) * next_vol
            return {
                "var": abs(var_quantile),
                "cvar": abs(var_quantile) * 1.2,
                "cond_vol": next_vol,
                "method": "garch_t",
            }

        # --- Step 4: Compute VaR and ES from GARCH + GPD ---
        n = len(losses)
        n_u = len(exceedances) + 1  # number above threshold
        alpha = 1 - confidence

        # GPD quantile for standardised residuals
        try:
            z_var = u + (scale / shape) * ((n / n_u * alpha) ** (-shape) - 1)
        except (ZeroDivisionError, FloatingPointError):
            z_var = u + scale * (-np.log(n / n_u * alpha))

        # Expected Shortfall (CVaR) from GPD
        if shape < 1:
            z_es = z_var / (1 - shape) + (scale - shape * u) / (1 - shape)
        else:
            z_es = z_var * 1.5  # fallback for heavy tails

        # Scale back to return space
        var_value = abs(z_var * next_vol)
        cvar_value = abs(z_es * next_vol)

        return {
            "var": var_value,
            "cvar": cvar_value,
            "cond_vol": next_vol,
            "method": "garch_evt",
        }

    # ------------------------------------------------------------------ #
    # Historical VaR (fallback / legacy)
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_var(returns: np.ndarray, confidence: float = 0.95) -> float:
        """Historical VaR at the given confidence level.

        Parameters
        ----------
        returns:
            Array of daily (or intraday) returns.
        confidence:
            Confidence level, e.g. 0.95 for 95 % VaR.

        Returns
        -------
        float
            Positive VaR value representing the maximum expected loss.
        """
        if len(returns) == 0:
            return 0.0
        percentile = (1 - confidence) * 100
        var_value = float(np.percentile(returns, percentile))
        return abs(var_value)

    # ------------------------------------------------------------------ #
    # Conditional VaR (Expected Shortfall)
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
        """Conditional VaR (Expected Shortfall) -- the mean of losses
        exceeding the VaR threshold.
        """
        if len(returns) == 0:
            return 0.0
        percentile = (1 - confidence) * 100
        var_threshold = np.percentile(returns, percentile)
        tail_returns = returns[returns <= var_threshold]
        if len(tail_returns) == 0:
            return abs(float(var_threshold))
        return abs(float(np.mean(tail_returns)))

    # ------------------------------------------------------------------ #
    # Drawdown helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_max_drawdown(equity_curve: np.ndarray) -> float:
        """Maximum peak-to-trough drawdown as a positive fraction."""
        if len(equity_curve) < 2:
            return 0.0
        running_max = np.maximum.accumulate(equity_curve)
        drawdowns = (running_max - equity_curve) / np.where(running_max == 0, 1.0, running_max)
        return float(np.max(drawdowns))

    @staticmethod
    def compute_current_drawdown(equity_curve: np.ndarray) -> float:
        """Current drawdown from the last peak as a positive fraction."""
        if len(equity_curve) < 2:
            return 0.0
        peak = float(np.max(equity_curve))
        if peak == 0:
            return 0.0
        current = float(equity_curve[-1])
        dd = (peak - current) / peak
        return max(dd, 0.0)
