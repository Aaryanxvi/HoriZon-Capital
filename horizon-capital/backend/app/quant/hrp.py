"""Hierarchical Risk Parity (Lopez de Prado 2016, JPM).

3-step portfolio construction:
  1. Tree clustering on correlation distance
  2. Quasi-diagonalisation
  3. Recursive bisection — split capital inversely to cluster variance

Out-of-sample Sharpe consistently beats Markowitz mean-variance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform


def _correl_distance(corr: pd.DataFrame) -> pd.DataFrame:
    return ((1 - corr) / 2.0) ** 0.5


def _quasi_diag(link: np.ndarray) -> list[int]:
    """Order leaves so most similar items adjacent."""
    link = link.astype(int)
    sort_ix = pd.Series([link[-1, 0], link[-1, 1]])
    n = link[-1, 3]
    while sort_ix.max() >= n:
        sort_ix.index = range(0, sort_ix.shape[0] * 2, 2)
        df0 = sort_ix[sort_ix >= n]
        i = df0.index
        j = df0.values - n
        sort_ix[i] = link[j, 0]
        df0 = pd.Series(link[j, 1], index=i + 1)
        sort_ix = pd.concat([sort_ix, df0]).sort_index()
        sort_ix.index = range(sort_ix.shape[0])
    return sort_ix.tolist()


def _cluster_var(cov: pd.DataFrame, items: list[int]) -> float:
    cov_ = cov.iloc[items, items]
    ivp = 1.0 / np.diag(cov_)
    ivp /= ivp.sum()
    w = ivp.reshape(-1, 1)
    return float((w.T @ cov_.values @ w)[0, 0])


def _recursive_bisection(cov: pd.DataFrame, sort_ix: list[int]) -> pd.Series:
    w = pd.Series(1.0, index=sort_ix)
    clusters = [sort_ix]
    while clusters:
        clusters = [c[i:j] for c in clusters
                    for i, j in ((0, len(c)//2), (len(c)//2, len(c)))
                    if len(c) > 1]
        for i in range(0, len(clusters), 2):
            c0 = clusters[i]
            c1 = clusters[i + 1]
            v0 = _cluster_var(cov, c0)
            v1 = _cluster_var(cov, c1)
            alpha = 1 - v0 / (v0 + v1) if v0 + v1 > 0 else 0.5
            w[c0] *= alpha
            w[c1] *= (1 - alpha)
    return w


def hrp_weights(returns: pd.DataFrame) -> pd.Series:
    """Compute HRP weights from a (T x N) returns DataFrame.

    Returns weights summing to 1 over the N assets.
    """
    returns = returns.dropna(axis=1, how="any")
    if returns.shape[1] < 2:
        if returns.shape[1] == 1:
            return pd.Series(1.0, index=returns.columns)
        return pd.Series(dtype=float)
    cov = returns.cov()
    corr = returns.corr()
    dist = _correl_distance(corr)
    # squareform expects condensed distance
    cond = squareform(dist.values, checks=False)
    link = linkage(cond, method="single")
    sort_ix = _quasi_diag(link)
    sort_tickers = [corr.index[i] for i in sort_ix]
    cov_ord = cov.loc[sort_tickers, sort_tickers]
    weights_int = _recursive_bisection(cov_ord, list(range(len(sort_tickers))))
    weights = pd.Series(weights_int.values, index=sort_tickers)
    return weights.reindex(returns.columns).fillna(0.0)
