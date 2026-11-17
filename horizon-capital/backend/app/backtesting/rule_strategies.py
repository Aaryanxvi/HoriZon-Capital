"""Rule strategies for the bar-replay backtester.

One copy shared by the REPL ``backtest`` command and the desktop Backtest page.
Each takes the bar history so far plus ``{"cash", "position_qty"}`` and returns a
``SimOrder`` or ``None``; the engine fills orders for the symbol it is replaying.
"""

from __future__ import annotations

import pandas as pd

from app.backtesting.backtest_broker import SimOrder


def _buy(ctx: dict, price: float, frac: float = 0.1) -> SimOrder:
    return SimOrder(side="BUY", quantity=round(ctx["cash"] * frac / price, 4))


def _sell(ctx: dict) -> SimOrder:
    return SimOrder(side="SELL", quantity=ctx["position_qty"])


def _momentum(history: pd.DataFrame, ctx: dict) -> SimOrder | None:
    if len(history) < 20:
        return None
    fast = float(history["close"].iloc[-5:].mean())
    slow = float(history["close"].iloc[-20:].mean())
    if fast > slow * 1.02 and ctx["position_qty"] == 0:
        return _buy(ctx, float(history["close"].iloc[-1]))
    if fast < slow * 0.98 and ctx["position_qty"] > 0:
        return _sell(ctx)
    return None


def _mean_reversion(history: pd.DataFrame, ctx: dict) -> SimOrder | None:
    if len(history) < 20:
        return None
    close = history["close"]
    sma = float(close.iloc[-20:].mean())
    std = float(close.iloc[-20:].std())
    if std == 0:
        return None
    z = (float(close.iloc[-1]) - sma) / std
    if z < -2.0 and ctx["position_qty"] == 0:
        return _buy(ctx, float(close.iloc[-1]))
    if z > 1.0 and ctx["position_qty"] > 0:
        return _sell(ctx)
    return None


def _volatility(history: pd.DataFrame, ctx: dict) -> SimOrder | None:
    if len(history) < 30:
        return None
    rets = history["close"].pct_change().dropna()
    vol = float(rets.iloc[-20:].std())
    avg_vol = float(rets.iloc[-30:].std())
    if vol < avg_vol * 0.7 and ctx["position_qty"] == 0:
        return _buy(ctx, float(history["close"].iloc[-1]))
    if vol > avg_vol * 1.5 and ctx["position_qty"] > 0:
        return _sell(ctx)
    return None


def _crisis(history: pd.DataFrame, ctx: dict) -> SimOrder | None:
    if len(history) < 50:
        return None
    close = history["close"]
    sma_50 = float(close.iloc[-50:].mean())
    current = float(close.iloc[-1])
    if current > sma_50 and ctx["position_qty"] == 0:
        return _buy(ctx, current, 0.05)
    if current < sma_50 * 0.95 and ctx["position_qty"] > 0:
        return _sell(ctx)
    return None


STRATEGIES = {
    "momentum": (_momentum, "5/20-day SMA cross (±2%), 10% of cash per entry"),
    "mean_reversion": (_mean_reversion, "Buy z < −2 vs 20-day mean, sell z > 1; 10% of cash"),
    "volatility": (_volatility, "Buy when 20-day vol < 0.7× 30-day, sell > 1.5×; 10% of cash"),
    "crisis": (_crisis, "Above 50-day SMA long, exit 5% below it; 5% of cash"),
}
