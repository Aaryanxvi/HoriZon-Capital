"""Statistical Jump Model for market-regime detection.

Uses the ``jumpmodels`` library (scikit-learn-style API) for regime
classification.  Produces more persistent regime sequences and is less
sensitive to initialization than HMM.

Falls back to HMM if ``jumpmodels`` is not installed.

References
----------
- Shu, Yu & Mulvey (2024), "Downside Risk Reduction Using Regime-Switching
  Signals: A Statistical Jump Model Approach", J. Asset Management.
- Aydinhan, Kolm, Mulvey & Shu (2024), "Identifying Patterns in Financial
  Markets: Extending the Statistical Jump Model", Annals of Operations Research.
"""

from __future__ import annotations

import pathlib

import numpy as np

from app.core.logging import get_logger

logger = get_logger("regime.jump_model")

REGIME_NAMES = ["BULL", "BEAR", "HIGH_VOL", "CRISIS"]

# Minimum data points for fitting
_MIN_SAMPLES = 50


class JumpRegimeModel:
    """4-state Statistical Jump Model trained on return + volatility features."""

    def __init__(
        self,
        n_components: int = 4,
        jump_penalty: float = 1.0,
        random_state: int = 42,
    ) -> None:
        self.n_components = n_components
        self._jump_penalty = jump_penalty
        self._random_state = random_state
        self._model = None
        self._state_to_regime: dict[int, str] = {}
        self._fitted: bool = False
        self._available: bool = False

        try:
            import jumpmodels  # noqa: F401
            self._available = True
        except ImportError:
            logger.warning("jumpmodels_not_installed_will_use_hmm_fallback")

    @property
    def is_available(self) -> bool:
        """Whether the jumpmodels library is installed."""
        return self._available

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, returns_data: np.ndarray) -> None:
        """Fit the Statistical Jump Model on historical data.

        Parameters
        ----------
        returns_data : np.ndarray
            1-D array of log-returns.
        """
        if not self._available:
            raise RuntimeError("jumpmodels library not installed.")

        returns = returns_data.flatten()
        if len(returns) < _MIN_SAMPLES:
            raise ValueError(f"Need at least {_MIN_SAMPLES} data points.")

        from jumpmodels import JumpModel

        # Build feature matrix: [return, 20-day rolling volatility]
        window = min(20, len(returns) // 2)
        rolling_vol = np.array(
            [np.std(returns[max(0, i - window) : i + 1]) for i in range(len(returns))]
        )
        features = np.column_stack([returns, rolling_vol])

        self._model = JumpModel(
            n_components=self.n_components,
            jump_penalty=self._jump_penalty,
        )
        self._model.fit(features)
        self._map_states_to_regimes(features)
        self._fitted = True
        logger.info("jump_model_trained", n_samples=len(returns))

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, features: np.ndarray) -> tuple[str, float]:
        """Predict the current regime.

        Parameters
        ----------
        features : np.ndarray
            Shape ``(T, 2)`` -- [return, vol] observations.

        Returns
        -------
        tuple[str, float]
            ``(regime_name, confidence)``
        """
        if not self._fitted or self._model is None:
            raise RuntimeError("Model has not been trained yet.")

        if features.ndim == 1:
            features = features.reshape(1, -1)

        labels = self._model.predict(features)
        predicted_state = int(labels[-1])
        regime_name = self._state_to_regime.get(predicted_state, "NEUTRAL")

        # Confidence: use distance to cluster center as proxy
        # Closer to center = higher confidence
        confidence = 0.7  # default moderate confidence
        if hasattr(self._model, "means_") and self._model.means_ is not None:
            means = self._model.means_
            if predicted_state < len(means):
                center = means[predicted_state]
                dist = np.linalg.norm(features[-1] - center)
                # Scale: small distance = high confidence
                max_dist = np.max([np.linalg.norm(m) for m in means]) + 1e-8
                confidence = max(0.3, min(1.0 - dist / (2 * max_dist), 0.95))

        return regime_name, float(confidence)

    def predict_online(self, features: np.ndarray) -> tuple[str, float]:
        """Online prediction for streaming data.

        Uses predict_online if available, otherwise falls back to predict.
        """
        if not self._fitted or self._model is None:
            raise RuntimeError("Model has not been trained yet.")

        if features.ndim == 1:
            features = features.reshape(1, -1)

        if hasattr(self._model, "predict_online"):
            labels = self._model.predict_online(features)
        else:
            labels = self._model.predict(features)

        predicted_state = int(labels[-1])
        regime_name = self._state_to_regime.get(predicted_state, "NEUTRAL")
        return regime_name, 0.7

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def save(self, path: str | pathlib.Path) -> None:
        """Persist the model to disk via joblib."""
        import joblib

        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {"model": self._model, "state_map": self._state_to_regime, "fitted": self._fitted},
            path,
        )
        logger.info("jump_model_saved", path=str(path))

    def load(self, path: str | pathlib.Path) -> None:
        """Load a previously saved model."""
        import joblib

        data = joblib.load(path)
        self._model = data["model"]
        self._state_to_regime = data["state_map"]
        self._fitted = data["fitted"]
        logger.info("jump_model_loaded", path=str(path))

    # ------------------------------------------------------------------
    # Internal: map learned states to regime labels
    # ------------------------------------------------------------------

    def _map_states_to_regimes(self, features: np.ndarray) -> None:
        """Assign regime names based on cluster characteristics.

        Same heuristic as HMM: BULL=highest mean return, BEAR=lowest,
        HIGH_VOL=highest variance, CRISIS=remaining.
        """
        labels = self._model.predict(features)
        returns = features[:, 0]

        # Compute per-state statistics
        state_means: dict[int, float] = {}
        state_vars: dict[int, float] = {}

        for state in range(self.n_components):
            mask = labels == state
            if mask.sum() > 0:
                state_means[state] = float(np.mean(returns[mask]))
                state_vars[state] = float(np.var(returns[mask]))
            else:
                state_means[state] = 0.0
                state_vars[state] = 0.0

        assigned: set[int] = set()
        mapping: dict[int, str] = {}

        # BULL: highest mean
        bull_idx = max(state_means, key=state_means.get)  # type: ignore[arg-type]
        mapping[bull_idx] = "BULL"
        assigned.add(bull_idx)

        # BEAR: lowest mean
        remaining_means = {k: v for k, v in state_means.items() if k not in assigned}
        if remaining_means:
            bear_idx = min(remaining_means, key=remaining_means.get)  # type: ignore[arg-type]
            mapping[bear_idx] = "BEAR"
            assigned.add(bear_idx)

        # HIGH_VOL: highest variance among remaining
        remaining_vars = {k: v for k, v in state_vars.items() if k not in assigned}
        if remaining_vars:
            hv_idx = max(remaining_vars, key=remaining_vars.get)  # type: ignore[arg-type]
            mapping[hv_idx] = "HIGH_VOL"
            assigned.add(hv_idx)

        # CRISIS: whatever is left
        for i in range(self.n_components):
            if i not in assigned:
                mapping[i] = "CRISIS"
                assigned.add(i)

        self._state_to_regime = mapping
        logger.info(
            "jump_model_state_mapping",
            mapping={v: round(state_means.get(k, 0.0), 6) for k, v in mapping.items()},
        )
