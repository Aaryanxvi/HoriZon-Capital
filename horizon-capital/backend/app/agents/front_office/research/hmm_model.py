"""Hidden Markov Model for market-regime detection.

Uses ``hmmlearn.hmm.GaussianHMM`` with 4 hidden states that are mapped to
human-readable regime labels after fitting, based on the learned means and
covariances:

    BULL     -- state with highest mean return
    BEAR     -- state with lowest mean return
    HIGH_VOL -- state with highest variance (but not the lowest mean)
    CRISIS   -- state with both low mean *and* high variance
"""

from __future__ import annotations

import pathlib

import numpy as np

from app.core.logging import get_logger

logger = get_logger("regime.hmm_model")

REGIME_NAMES = ["BULL", "BEAR", "HIGH_VOL", "CRISIS"]

try:
    import joblib as _joblib
    from hmmlearn.hmm import GaussianHMM as _GaussianHMM
    _HMM_AVAILABLE = True
except ImportError:
    _joblib = None  # type: ignore[assignment]
    _GaussianHMM = None  # type: ignore[assignment]
    _HMM_AVAILABLE = False
    logger.warning(
        "hmmlearn_not_available",
        reason="hmmlearn or joblib not installed; HMM regime model disabled",
    )


class HMMRegimeModel:
    """4-state Gaussian HMM trained on return + volatility features."""

    @classmethod
    def is_available(cls) -> bool:
        return _HMM_AVAILABLE

    def __init__(
        self,
        n_components: int = 4,
        covariance_type: str = "full",
        n_iter: int = 200,
        random_state: int = 42,
    ) -> None:
        if not _HMM_AVAILABLE:
            raise ImportError("hmmlearn is not installed. Install it with: pip install hmmlearn")
        self.n_components = n_components
        self._model = _GaussianHMM(
            n_components=n_components,
            covariance_type=covariance_type,
            n_iter=n_iter,
            random_state=random_state,
        )
        self._state_to_regime: dict[int, str] = {}
        self._fitted: bool = False

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, returns_data: np.ndarray) -> None:
        """Fit the HMM on historical data.

        Parameters
        ----------
        returns_data : np.ndarray
            1-D array of log-returns.  The method internally derives a rolling
            volatility feature so that the model receives a 2-column matrix
            ``[return, rolling_vol]``.
        """
        returns = returns_data.flatten()
        if len(returns) < 30:
            raise ValueError("Need at least 30 data points to train the HMM.")

        # Build feature matrix: [return, 20-day rolling volatility]
        window = min(20, len(returns) // 2)
        rolling_vol = np.array(
            [np.std(returns[max(0, i - window) : i + 1]) for i in range(len(returns))]
        )
        features = np.column_stack([returns, rolling_vol])

        self._model.fit(features)
        self._map_states_to_regimes()
        self._fitted = True
        logger.info("hmm_trained", n_samples=len(returns))

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, features: np.ndarray) -> tuple[str, float]:
        """Predict the current regime.

        Parameters
        ----------
        features : np.ndarray
            Shape ``(T, 2)`` -- most recent observations of ``[return, vol]``.
            At minimum a single row ``(1, 2)`` is required.

        Returns
        -------
        tuple[str, float]
            ``(regime_name, confidence)`` where confidence is the posterior
            probability of the predicted state.
        """
        if not self._fitted:
            raise RuntimeError("Model has not been trained yet.")

        if features.ndim == 1:
            features = features.reshape(1, -1)

        # Posterior probabilities for the last observation
        log_prob, posteriors = self._model.score_samples(features)
        last_posterior = posteriors[-1]
        predicted_state = int(np.argmax(last_posterior))
        confidence = float(last_posterior[predicted_state])
        regime_name = self._state_to_regime.get(predicted_state, "UNKNOWN")
        return regime_name, confidence

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def save(self, path: str | pathlib.Path) -> None:
        """Persist the model and state mapping to disk via joblib."""
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _joblib.dump(
            {"model": self._model, "state_map": self._state_to_regime, "fitted": self._fitted},
            path,
        )
        logger.info("hmm_model_saved", path=str(path))

    def load(self, path: str | pathlib.Path) -> None:
        """Load a previously saved model."""
        data = _joblib.load(path)
        self._model = data["model"]
        self._state_to_regime = data["state_map"]
        self._fitted = data["fitted"]
        logger.info("hmm_model_loaded", path=str(path))

    # ------------------------------------------------------------------
    # Internal: map learned states to regime labels
    # ------------------------------------------------------------------

    def _map_states_to_regimes(self) -> None:
        """Assign regime names to HMM states based on learned parameters.

        Heuristic
        ---------
        1. ``BULL``    -- highest mean return
        2. ``BEAR``    -- lowest mean return
        3. ``HIGH_VOL``-- highest variance (excluding BEAR if overlap)
        4. ``CRISIS``  -- remaining state (typically low mean + high vol)
        """
        means = self._model.means_[:, 0]  # mean return per state
        # Variance of the return dimension
        if self._model.covariance_type == "full":
            variances = np.array([self._model.covars_[i][0, 0] for i in range(self.n_components)])
        elif self._model.covariance_type == "diag":
            variances = self._model.covars_[:, 0]
        else:
            variances = self._model.covars_.copy()

        assigned: set[int] = set()
        mapping: dict[int, str] = {}

        # BULL: highest mean
        bull_idx = int(np.argmax(means))
        mapping[bull_idx] = "BULL"
        assigned.add(bull_idx)

        # BEAR: lowest mean
        bear_idx = int(np.argmin(means))
        if bear_idx in assigned:
            # Edge case: only pick second-lowest if collision
            sorted_mean_idx = np.argsort(means)
            for idx in sorted_mean_idx:
                if idx not in assigned:
                    bear_idx = int(idx)
                    break
        mapping[bear_idx] = "BEAR"
        assigned.add(bear_idx)

        # HIGH_VOL: highest variance among remaining
        remaining = [i for i in range(self.n_components) if i not in assigned]
        if remaining:
            high_vol_idx = int(remaining[np.argmax(variances[remaining])])
            mapping[high_vol_idx] = "HIGH_VOL"
            assigned.add(high_vol_idx)

        # CRISIS: whatever is left
        for i in range(self.n_components):
            if i not in assigned:
                mapping[i] = "CRISIS"
                assigned.add(i)

        self._state_to_regime = mapping
        logger.info(
            "hmm_state_mapping",
            mapping={v: float(means[k]) for k, v in mapping.items()},
        )
