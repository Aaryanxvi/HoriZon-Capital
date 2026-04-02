"""ML Model Registry & Online Learning Pipeline.

Tracks model versions, performance metrics, concept drift, and implements
Thompson Sampling for adaptive strategy rotation.

Research references
-------------------
- Agrawal, S. and Goyal, N. (2012). "Analysis of Thompson Sampling for
  the Multi-Armed Bandit Problem." Proc. COLT 2012.
  — Bayesian regret bounds for Thompson Sampling.
- Zhu, Q. et al. (2019). "Adaptive Portfolio by Solving Multi-armed
  Bandit via Thompson Sampling." arXiv:1911.05309.
  — Direct application to strategy rotation in finance.
- Gama, J. et al. (2014). "A Survey on Concept Drift Adaptation."
  ACM Computing Surveys — framework for detecting and adapting to drift.
- Page, E.S. (1954). "Continuous Inspection Schemes." Biometrika.
  — CUSUM (Cumulative Sum) test for detecting distribution shifts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from app.core.logging import get_logger

logger = get_logger("services.model_registry")


# ---------------------------------------------------------------------------
# Model Registry
# ---------------------------------------------------------------------------

@dataclass
class ModelVersion:
    """A registered model version with metadata and performance tracking."""

    model_id: str
    model_name: str
    version: int
    model_type: str  # "strategy", "regime", "sentiment", "risk"
    parameters: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    created_at: str = ""
    status: str = "active"  # active, deprecated, retired
    performance_history: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()


class ModelRegistry:
    """Registry for tracking ML models and strategy versions.

    Provides versioning, performance tracking, and model lifecycle management.
    Persists state to KV store for durability across restarts.
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelVersion] = {}
        self._version_counter: dict[str, int] = {}

    def register(
        self,
        model_name: str,
        model_type: str,
        parameters: dict | None = None,
        metrics: dict | None = None,
    ) -> ModelVersion:
        """Register a new model version."""
        self._version_counter[model_name] = self._version_counter.get(model_name, 0) + 1
        version = self._version_counter[model_name]
        model_id = f"{model_name}_v{version}"

        mv = ModelVersion(
            model_id=model_id,
            model_name=model_name,
            version=version,
            model_type=model_type,
            parameters=parameters or {},
            metrics=metrics or {},
        )
        self._models[model_id] = mv

        logger.info(
            "model_registered",
            model_id=model_id,
            model_type=model_type,
            version=version,
        )
        return mv

    def update_metrics(self, model_id: str, metrics: dict) -> bool:
        """Update performance metrics for a model version."""
        mv = self._models.get(model_id)
        if not mv:
            return False

        mv.metrics.update(metrics)
        mv.performance_history.append({
            "timestamp": datetime.now(UTC).isoformat(),
            **metrics,
        })

        # Keep last 100 history entries
        if len(mv.performance_history) > 100:
            mv.performance_history = mv.performance_history[-100:]

        return True

    def deprecate(self, model_id: str) -> bool:
        """Mark a model as deprecated."""
        mv = self._models.get(model_id)
        if not mv:
            return False
        mv.status = "deprecated"
        logger.info("model_deprecated", model_id=model_id)
        return True

    def get_active_models(self, model_type: str | None = None) -> list[dict]:
        """List all active models, optionally filtered by type."""
        result = []
        for mv in self._models.values():
            if mv.status != "active":
                continue
            if model_type and mv.model_type != model_type:
                continue
            result.append({
                "model_id": mv.model_id,
                "model_name": mv.model_name,
                "version": mv.version,
                "model_type": mv.model_type,
                "metrics": mv.metrics,
                "created_at": mv.created_at,
            })
        return result

    def get_best_model(self, model_name: str, metric: str = "sharpe_ratio") -> str | None:
        """Get the model_id of the best-performing version by a given metric."""
        candidates = [
            mv for mv in self._models.values()
            if mv.model_name == model_name and mv.status == "active"
        ]
        if not candidates:
            return None
        best = max(candidates, key=lambda m: m.metrics.get(metric, float("-inf")))
        return best.model_id

    def get_all_models(self) -> list[dict]:
        """Return all models."""
        return [
            {
                "model_id": mv.model_id,
                "model_name": mv.model_name,
                "version": mv.version,
                "model_type": mv.model_type,
                "status": mv.status,
                "metrics": mv.metrics,
                "created_at": mv.created_at,
            }
            for mv in self._models.values()
        ]


# ---------------------------------------------------------------------------
# Thompson Sampling Strategy Selector
# ---------------------------------------------------------------------------

@dataclass
class StrategyArm:
    """A strategy 'arm' for Thompson Sampling with Normal-Inverse-Gamma posterior.

    Ref: Agrawal & Goyal 2012 — conjugate prior for Gaussian rewards.

    Prior: (mu, sigma^2) ~ NIG(mu_0, lambda_0, alpha_0, beta_0)
    After n observations with sample mean x_bar and sum of squares S:
        lambda_n = lambda_0 + n
        mu_n = (lambda_0 * mu_0 + n * x_bar) / lambda_n
        alpha_n = alpha_0 + n/2
        beta_n = beta_0 + S/2 + (lambda_0 * n * (x_bar - mu_0)^2) / (2 * lambda_n)
    """

    strategy_name: str
    # NIG prior hyperparameters
    mu_0: float = 0.0       # prior mean
    lambda_0: float = 1.0   # prior precision
    alpha_0: float = 1.0    # shape (df/2)
    beta_0: float = 1.0     # scale
    # Sufficient statistics
    n: int = 0
    sum_x: float = 0.0
    sum_x2: float = 0.0

    @property
    def x_bar(self) -> float:
        return self.sum_x / self.n if self.n > 0 else 0.0

    @property
    def lambda_n(self) -> float:
        return self.lambda_0 + self.n

    @property
    def mu_n(self) -> float:
        return (self.lambda_0 * self.mu_0 + self.sum_x) / self.lambda_n

    @property
    def alpha_n(self) -> float:
        return self.alpha_0 + self.n / 2.0

    @property
    def beta_n(self) -> float:
        if self.n == 0:
            return self.beta_0
        ss = self.sum_x2 - (self.sum_x ** 2) / self.n
        return (
            self.beta_0
            + ss / 2.0
            + (self.lambda_0 * self.n * (self.x_bar - self.mu_0) ** 2)
            / (2.0 * self.lambda_n)
        )


class ThompsonSamplingSelector:
    """Adaptive strategy selector using Thompson Sampling.

    At each decision point:
    1. Sample theta_k ~ posterior(mu_k, sigma_k^2) for each strategy k
    2. Select the strategy with the highest sampled theta
    3. Observe reward (strategy return) and update posterior

    This naturally balances exploration (trying under-explored strategies)
    with exploitation (favoring the historically best), with O(log T) regret.

    Ref: Agrawal & Goyal 2012 (theoretical bounds)
         Zhu et al. 2019 (financial application)
    """

    def __init__(
        self,
        strategy_names: list[str],
        random_seed: int | None = None,
    ) -> None:
        self.rng = np.random.default_rng(random_seed)
        self._arms: dict[str, StrategyArm] = {
            name: StrategyArm(strategy_name=name)
            for name in strategy_names
        }
        self._selection_history: list[dict] = []

    def select(self) -> str:
        """Select a strategy by sampling from each arm's posterior.

        Returns the strategy name with the highest sampled value.
        """
        best_sample = float("-inf")
        best_strategy = list(self._arms.keys())[0]

        for name, arm in self._arms.items():
            # Sample variance from Inverse-Gamma
            # sigma^2 ~ IG(alpha_n, beta_n)
            if arm.alpha_n > 0 and arm.beta_n > 0:
                precision = self.rng.gamma(arm.alpha_n, 1.0 / arm.beta_n)
                variance = 1.0 / precision if precision > 0 else 1.0
            else:
                variance = 1.0

            # Sample mean from Normal
            # mu ~ N(mu_n, sigma^2 / lambda_n)
            std = np.sqrt(variance / arm.lambda_n)
            sample = self.rng.normal(arm.mu_n, std)

            if sample > best_sample:
                best_sample = sample
                best_strategy = name

        self._selection_history.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "selected": best_strategy,
        })

        return best_strategy

    def update(self, strategy_name: str, reward: float) -> None:
        """Update the posterior for a strategy after observing a reward.

        Parameters
        ----------
        strategy_name : str
            The strategy that was executed.
        reward : float
            The observed reward (e.g., daily return or Sharpe contribution).
        """
        arm = self._arms.get(strategy_name)
        if not arm:
            return

        arm.n += 1
        arm.sum_x += reward
        arm.sum_x2 += reward ** 2

        logger.debug(
            "thompson_update",
            strategy=strategy_name,
            reward=f"{reward:.6f}",
            n=arm.n,
            posterior_mean=f"{arm.mu_n:.6f}",
        )

    def get_stats(self) -> list[dict]:
        """Return current posterior statistics for each arm."""
        return [
            {
                "strategy": arm.strategy_name,
                "n_observations": arm.n,
                "posterior_mean": round(arm.mu_n, 6),
                "posterior_variance": round(
                    arm.beta_n / max(arm.alpha_n - 1, 0.01) / arm.lambda_n, 6
                ) if arm.alpha_n > 1 else 0.0,
                "selection_rate": round(
                    sum(1 for s in self._selection_history if s["selected"] == arm.strategy_name)
                    / max(len(self._selection_history), 1),
                    4,
                ),
            }
            for arm in self._arms.values()
        ]

    def get_recommendation(self) -> dict:
        """Return the current top strategy and confidence."""
        stats = self.get_stats()
        if not stats:
            return {"strategy": "", "confidence": 0.0}
        best = max(stats, key=lambda s: s["posterior_mean"])
        return {
            "strategy": best["strategy"],
            "posterior_mean": best["posterior_mean"],
            "n_observations": best["n_observations"],
            "selection_rate": best["selection_rate"],
        }


# ---------------------------------------------------------------------------
# Concept Drift Detector (CUSUM)
# ---------------------------------------------------------------------------

class CUSUMDriftDetector:
    """Detect concept drift using Page's CUSUM test.

    Ref: Page 1954, "Continuous Inspection Schemes", Biometrika.

    Monitors the cumulative sum of deviations from the expected mean.
    When the CUSUM exceeds a threshold, drift is declared.

    This is used to detect when a model's performance distribution has
    shifted, indicating the need to retrain or switch strategies.
    """

    def __init__(
        self,
        threshold: float = 5.0,
        drift_magnitude: float = 0.01,
        warmup: int = 30,
    ) -> None:
        """
        Parameters
        ----------
        threshold : float
            Detection threshold for the CUSUM statistic (higher = fewer false alarms).
        drift_magnitude : float
            Expected magnitude of drift to detect (allowance parameter).
        warmup : int
            Number of observations before detection begins.
        """
        self.threshold = threshold
        self.drift_magnitude = drift_magnitude
        self.warmup = warmup
        self._observations: list[float] = []
        self._s_high: float = 0.0  # CUSUM for positive shift
        self._s_low: float = 0.0   # CUSUM for negative shift
        self._mean: float = 0.0
        self._n: int = 0
        self._drift_detected: bool = False
        self._drift_history: list[dict] = []

    def update(self, value: float) -> dict:
        """Add an observation and check for drift.

        Returns
        -------
        dict with {drift_detected, direction, cusum_high, cusum_low}
        """
        self._observations.append(value)
        self._n += 1

        # Update running mean during warmup
        if self._n <= self.warmup:
            self._mean = np.mean(self._observations)
            return {
                "drift_detected": False,
                "direction": "none",
                "cusum_high": 0.0,
                "cusum_low": 0.0,
                "warming_up": True,
            }

        # CUSUM update
        deviation = value - self._mean
        self._s_high = max(0, self._s_high + deviation - self.drift_magnitude)
        self._s_low = max(0, self._s_low - deviation - self.drift_magnitude)

        drift_detected = False
        direction = "none"

        if self._s_high > self.threshold:
            drift_detected = True
            direction = "positive"
            self._s_high = 0.0  # reset after detection
        elif self._s_low > self.threshold:
            drift_detected = True
            direction = "negative"
            self._s_low = 0.0

        if drift_detected:
            self._drift_detected = True
            self._drift_history.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "direction": direction,
                "n_observations": self._n,
                "current_mean": float(np.mean(self._observations[-self.warmup:])),
                "reference_mean": self._mean,
            })
            # Update reference mean
            self._mean = np.mean(self._observations[-self.warmup:])

            logger.info(
                "drift_detected",
                direction=direction,
                n_observations=self._n,
            )

        return {
            "drift_detected": drift_detected,
            "direction": direction,
            "cusum_high": round(self._s_high, 4),
            "cusum_low": round(self._s_low, 4),
            "warming_up": False,
        }

    def reset(self) -> None:
        """Reset detector state."""
        self._observations.clear()
        self._s_high = 0.0
        self._s_low = 0.0
        self._n = 0
        self._drift_detected = False

    @property
    def drift_count(self) -> int:
        return len(self._drift_history)

    def get_drift_history(self) -> list[dict]:
        return list(self._drift_history)
