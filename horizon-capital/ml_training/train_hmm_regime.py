# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-076457F51150
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Train HMM regime classifier on historical NIFTY + SPX data.

Usage:
    python train_hmm_regime.py --output artifacts/hmm_regime.pkl
"""

import argparse
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from hmmlearn.hmm import GaussianHMM


def fetch_data(tickers: list[str], period: str = "5y") -> pd.DataFrame:
    """Fetch OHLCV data and compute features for HMM."""
    frames = []
    for ticker in tickers:
        df = yf.download(ticker, period=period, interval="1d", progress=False)
        df["returns"] = df["Close"].pct_change()
        df["vol_20"] = df["returns"].rolling(20).std() * np.sqrt(252)
        df["vol_60"] = df["returns"].rolling(60).std() * np.sqrt(252)
        df["vol_of_vol"] = df["vol_20"].rolling(20).std()
        df["skew_20"] = df["returns"].rolling(20).skew()
        df["kurt_20"] = df["returns"].rolling(20).kurt()
        df = df.dropna()
        df["ticker"] = ticker
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def prepare_features(df: pd.DataFrame) -> np.ndarray:
    """Extract feature matrix for HMM."""
    features = ["returns", "vol_20", "vol_60", "vol_of_vol", "skew_20", "kurt_20"]
    X = df[features].values
    return X


def label_states(model: GaussianHMM, n_states: int = 4) -> dict[int, str]:
    """Map HMM states to regime labels based on means."""
    means = model.means_
    covars = model.covars_

    # Sort by return mean
    return_means = means[:, 0]
    vol_means = means[:, 1]

    labels = {}
    state_info = []
    for i in range(n_states):
        state_info.append({
            "state": i,
            "return_mean": return_means[i],
            "vol_mean": vol_means[i],
            "var": covars[i][0][0] if len(covars.shape) == 3 else covars[i][0],
        })

    # Sort by return mean
    sorted_by_return = sorted(state_info, key=lambda x: x["return_mean"])

    # Lowest return = CRISIS or BEAR
    # Highest return = BULL
    # Highest vol = HIGH_VOL
    sorted_by_vol = sorted(state_info, key=lambda x: x["vol_mean"], reverse=True)

    assigned = set()

    # Highest vol state = HIGH_VOL (if not extreme negative return)
    high_vol_state = sorted_by_vol[0]["state"]
    if sorted_by_vol[0]["return_mean"] < sorted_by_return[0]["return_mean"] * 0.5:
        labels[high_vol_state] = "CRISIS"
    else:
        labels[high_vol_state] = "HIGH_VOL"
    assigned.add(high_vol_state)

    # Highest return = BULL
    for s in reversed(sorted_by_return):
        if s["state"] not in assigned:
            labels[s["state"]] = "BULL"
            assigned.add(s["state"])
            break

    # Lowest return = BEAR or CRISIS
    for s in sorted_by_return:
        if s["state"] not in assigned:
            if s["return_mean"] < -0.001:
                labels[s["state"]] = "CRISIS"
            else:
                labels[s["state"]] = "BEAR"
            assigned.add(s["state"])
            break

    # Remaining = BEAR
    for i in range(n_states):
        if i not in assigned:
            labels[i] = "BEAR"

    return labels


def train(tickers: list[str], n_states: int = 4, n_iter: int = 100) -> dict:
    """Train HMM and return model artifacts."""
    print(f"Fetching data for {tickers}...")
    df = fetch_data(tickers)
    print(f"Data shape: {df.shape}")

    X = prepare_features(df)
    print(f"Feature matrix shape: {X.shape}")

    print(f"Training GaussianHMM with {n_states} states...")
    model = GaussianHMM(
        n_components=n_states,
        covariance_type="full",
        n_iter=n_iter,
        random_state=42,
        verbose=True,
    )
    model.fit(X)

    state_labels = label_states(model, n_states)
    print(f"State labels: {state_labels}")

    # Predict on training data
    states = model.predict(X)
    for state_id, label in state_labels.items():
        count = (states == state_id).sum()
        pct = count / len(states) * 100
        print(f"  {label} (state {state_id}): {count} days ({pct:.1f}%)")

    return {
        "model": model,
        "state_labels": state_labels,
        "feature_names": ["returns", "vol_20", "vol_60", "vol_of_vol", "skew_20", "kurt_20"],
        "training_tickers": tickers,
        "n_samples": len(X),
    }


def main():
    parser = argparse.ArgumentParser(description="Train HMM regime model")
    parser.add_argument("--output", default="artifacts/hmm_regime.pkl")
    parser.add_argument("--tickers", nargs="+", default=["^NSEI", "^GSPC"])
    parser.add_argument("--states", type=int, default=4)
    args = parser.parse_args()

    artifacts = train(args.tickers, n_states=args.states)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        pickle.dump(artifacts, f)
    print(f"Model saved to {output_path}")


if __name__ == "__main__":
    main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 076457F51150 - verify with scripts/authorship.py verify
