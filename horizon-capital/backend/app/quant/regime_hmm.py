"""2-state regime detection via Gaussian Mixture (Hamilton 1989 spirit).

Lightweight HMM substitute — no hmmlearn dep needed. Uses sklearn GaussianMixture
on (return, vol) feature pairs. Identifies 'risk-on' vs 'risk-off' state.

Trade-off vs full HMM: no transition matrix learnt — purely based on emission
density. Good enough for regime gating in production. Hamilton's 1989 paper
showed this captures business-cycle regimes; we apply same logic to equity ret/vol.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture


def detect_regime(close: pd.Series, lookback: int = 252) -> tuple[str, float]:
    """Return ('RISK_ON' | 'RISK_OFF', confidence_in_[0,1]).

    Fits 2-state Gaussian mixture on (rolling_5d_return, rolling_20d_vol).
    Higher-mean cluster = RISK_ON.
    """
    close = close.dropna()
    if len(close) < lookback + 25:
        return "RISK_OFF", 0.0

    rets = close.pct_change().dropna()
    feat = pd.DataFrame({
        "ret_5d": rets.rolling(5).mean(),
        "vol_20d": rets.rolling(20).std() * np.sqrt(252),
    }).dropna().tail(lookback)

    if len(feat) < 50:
        return "RISK_OFF", 0.0

    x = feat.values
    try:
        gmm = GaussianMixture(n_components=2, random_state=42, max_iter=100)
        gmm.fit(x)
    except Exception:
        return "RISK_OFF", 0.0

    means = gmm.means_  # 2 x 2: [ret_mean, vol_mean]
    risk_on_state = int(np.argmax(means[:, 0] - means[:, 1]))  # high-ret, low-vol
    last_x = x[-1].reshape(1, -1)
    probs = gmm.predict_proba(last_x)[0]
    conf = float(probs[risk_on_state])
    state = "RISK_ON" if conf > 0.5 else "RISK_OFF"
    return state, conf


def regime_score(close: pd.Series) -> float:
    """Single number: +1 strong-on, 0 neutral, -1 strong-off."""
    state, conf = detect_regime(close)
    if state == "RISK_ON":
        return float(conf * 2 - 1)
    return float(-(conf * 2 - 1))
