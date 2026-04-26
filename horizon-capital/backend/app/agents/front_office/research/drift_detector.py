"""Four-rate concept drift detector.

Tracks four classification performance rates (TPR, TNR, PPV, NPV) using
EWMA smoothing and normal-approximation control bounds to detect when a
model's predictive accuracy degrades significantly.

When any rate drops below its control limit, a WARNING (at ``alpha_warn``)
or DRIFT (at ``alpha_detect``) signal is emitted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger("regime.drift_detector")


@dataclass
class _RateTracker:
    """EWMA tracker for a single rate with normal-approximation bounds."""

    name: str
    beta: float = 0.9
    _ewma: float = 1.0
    _count: int = 0
    _sum: float = 0.0
    _sum_sq: float = 0.0

    def update(self, value: float) -> None:
        """Update the tracker with a new binary observation (0 or 1)."""
        self._count += 1
        self._ewma = self.beta * self._ewma + (1.0 - self.beta) * value
        self._sum += value
        self._sum_sq += value * value

    @property
    def rate(self) -> float:
        return self._ewma

    @property
    def mean(self) -> float:
        if self._count == 0:
            return 1.0
        return self._sum / self._count

    @property
    def std(self) -> float:
        if self._count < 2:
            return 0.0
        mean = self.mean
        var = (self._sum_sq / self._count) - mean * mean
        return math.sqrt(max(var, 0.0))

    def bound(self, alpha: float) -> float:
        """Lower control bound at significance level ``alpha``.

        Uses a normal approximation:  bound = mean - z * (std / sqrt(n))
        """
        if self._count < 10:
            # Not enough data to compute a meaningful bound
            return 0.0
        # z-scores for common alpha values (one-sided)
        z = _z_score(alpha)
        se = self.std / math.sqrt(self._count)
        return max(self.mean - z * se, 0.0)

    def is_below_bound(self, alpha: float) -> bool:
        return self._count >= 10 and self.rate < self.bound(alpha)

    def reset(self) -> None:
        self._ewma = 1.0
        self._count = 0
        self._sum = 0.0
        self._sum_sq = 0.0


def _z_score(alpha: float) -> float:
    """Return the one-sided z-score for a given significance level.

    Uses a small lookup + linear interpolation for common values.
    """
    _table = {
        0.10: 1.282,
        0.05: 1.645,
        0.025: 1.960,
        0.01: 2.326,
        0.005: 2.576,
        0.001: 3.090,
    }
    if alpha in _table:
        return _table[alpha]
    # Fallback: Abramowitz & Stegun rational approximation
    # For alpha in (0, 0.5)
    if alpha <= 0.0 or alpha >= 0.5:
        return 1.645  # default
    t = math.sqrt(-2.0 * math.log(alpha))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    return t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)


class LFRDriftDetector:
    """Four-rate drift detector with EWMA smoothing and normal-approximation bounds.

    Parameters
    ----------
    beta : float
        EWMA smoothing factor (higher = more memory, slower reaction).
    alpha_warn : float
        Significance level for WARNING.
    alpha_detect : float
        Significance level for confirmed DRIFT.
    """

    def __init__(
        self,
        beta: float = 0.9,
        alpha_warn: float = 0.05,
        alpha_detect: float = 0.01,
    ) -> None:
        self.beta = beta
        self.alpha_warn = alpha_warn
        self.alpha_detect = alpha_detect

        self._tpr = _RateTracker(name="TPR", beta=beta)
        self._tnr = _RateTracker(name="TNR", beta=beta)
        self._ppv = _RateTracker(name="PPV", beta=beta)
        self._npv = _RateTracker(name="NPV", beta=beta)

        # Confusion matrix running counts
        self._tp: int = 0
        self._tn: int = 0
        self._fp: int = 0
        self._fn: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        prediction_correct: bool,
        predicted_positive: bool,
        actual_positive: bool,
    ) -> None:
        """Feed a new observation into the detector.

        Parameters
        ----------
        prediction_correct : bool
            Whether the model's prediction was correct.
        predicted_positive : bool
            Whether the model predicted the *positive* class.
        actual_positive : bool
            The true label.
        """
        if actual_positive and predicted_positive:
            self._tp += 1
        elif not actual_positive and not predicted_positive:
            self._tn += 1
        elif not actual_positive and predicted_positive:
            self._fp += 1
        else:
            self._fn += 1

        # Update individual rate trackers with binary hit/miss
        # TPR: among actual positives, did we predict positive?
        if actual_positive:
            self._tpr.update(1.0 if predicted_positive else 0.0)
        # TNR: among actual negatives, did we predict negative?
        if not actual_positive:
            self._tnr.update(1.0 if not predicted_positive else 0.0)
        # PPV: among predicted positives, was it actually positive?
        if predicted_positive:
            self._ppv.update(1.0 if actual_positive else 0.0)
        # NPV: among predicted negatives, was it actually negative?
        if not predicted_positive:
            self._npv.update(1.0 if not actual_positive else 0.0)

    def check_drift(self) -> tuple[str, dict]:
        """Check whether concept drift has been detected.

        Returns
        -------
        tuple[str, dict]
            ``("NONE" | "WARNING" | "DRIFT", details_dict)``
        """
        trackers = {
            "TPR": self._tpr,
            "TNR": self._tnr,
            "PPV": self._ppv,
            "NPV": self._npv,
        }

        drift_rates: list[str] = []
        warn_rates: list[str] = []
        details: dict = {}

        for name, tracker in trackers.items():
            details[name] = {
                "rate": round(tracker.rate, 4),
                "mean": round(tracker.mean, 4),
                "warn_bound": round(tracker.bound(self.alpha_warn), 4),
                "drift_bound": round(tracker.bound(self.alpha_detect), 4),
            }
            if tracker.is_below_bound(self.alpha_detect):
                drift_rates.append(name)
            elif tracker.is_below_bound(self.alpha_warn):
                warn_rates.append(name)

        if drift_rates:
            level = "DRIFT"
            details["triggered_rates"] = drift_rates
            logger.warning("drift_detected", rates=drift_rates, details=details)
        elif warn_rates:
            level = "WARNING"
            details["triggered_rates"] = warn_rates
            logger.info("drift_warning", rates=warn_rates, details=details)
        else:
            level = "NONE"

        return level, details

    def reset(self) -> None:
        """Reset all internal state after a confirmed drift."""
        self._tpr.reset()
        self._tnr.reset()
        self._ppv.reset()
        self._npv.reset()
        self._tp = 0
        self._tn = 0
        self._fp = 0
        self._fn = 0
        logger.info("drift_detector_reset")
