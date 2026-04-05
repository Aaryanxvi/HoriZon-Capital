"""Performance dispatcher: Rust when available, Python fallback."""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

try:
    from horizon_core_rs import (  # type: ignore[import]
        compute_all_indicators as _rs_all,
    )
    from horizon_core_rs import (
        run_backtest_fast as _rs_backtest,
    )

    _RUST = True
    logger.info("Rust acceleration loaded")
except ImportError:
    _RUST = False
    logger.info("Rust not available — Python fallback")


def is_rust_available() -> bool:
    return _RUST


def compute_indicators(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
) -> dict[str, np.ndarray]:
    if _RUST:
        return _rs_all(close, high, low, volume)
    return _python_indicators(close, high, low, volume)


def run_backtest(
    close: np.ndarray,
    signals: np.ndarray,
    initial_capital: float = 100_000.0,
    commission_bps: float = 10.0,
) -> dict:
    if _RUST:
        return _rs_backtest(close, signals.astype(np.int32), initial_capital, commission_bps)
    return _python_backtest(close, signals, initial_capital, commission_bps)


def _python_indicators(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
) -> dict[str, np.ndarray]:
    import pandas as pd
    import ta

    df = pd.DataFrame({"close": close, "high": high, "low": low, "volume": volume})
    result = {}
    result["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi().to_numpy()
    macd = ta.trend.MACD(df["close"])
    result["macd"] = macd.macd().to_numpy()
    result["macd_signal"] = macd.macd_signal().to_numpy()
    result["macd_hist"] = macd.macd_diff().to_numpy()
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    result["bb_upper"] = bb.bollinger_hband().to_numpy()
    result["bb_middle"] = bb.bollinger_mavg().to_numpy()
    result["bb_lower"] = bb.bollinger_lband().to_numpy()
    result["atr"] = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=14
    ).average_true_range().to_numpy()
    result["sma_20"] = ta.trend.SMAIndicator(df["close"], window=20).sma_indicator().to_numpy()
    result["sma_50"] = ta.trend.SMAIndicator(df["close"], window=50).sma_indicator().to_numpy()
    result["ema_12"] = ta.trend.EMAIndicator(df["close"], window=12).ema_indicator().to_numpy()
    result["ema_26"] = ta.trend.EMAIndicator(df["close"], window=26).ema_indicator().to_numpy()
    return result


def _python_backtest(
    close: np.ndarray,
    signals: np.ndarray,
    initial_capital: float,
    commission_bps: float,
) -> dict:
    n = len(close)
    commission_rate = commission_bps / 10000.0
    cash = initial_capital
    position = 0.0
    entry_price = 0.0
    equity_curve = np.empty(n)
    trade_returns = []

    for i in range(n):
        equity_curve[i] = cash + position * close[i]
        if signals[i] == 1 and position == 0.0:
            cost = cash * commission_rate
            position = (cash - cost) / close[i]
            entry_price = close[i]
            cash = 0.0
        elif signals[i] == -1 and position > 0.0:
            proceeds = position * close[i]
            cash = proceeds - proceeds * commission_rate
            trade_returns.append((close[i] - entry_price) / entry_price)
            position = 0.0

    if position > 0.0:
        trade_returns.append((close[-1] - entry_price) / entry_price)

    total_return = (equity_curve[-1] - initial_capital) / initial_capital
    daily_returns = np.diff(equity_curve) / equity_curve[:-1]
    mean_ret = float(np.nanmean(daily_returns))
    std_ret = float(np.nanstd(daily_returns, ddof=1))
    sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0.0
    peak = np.maximum.accumulate(equity_curve)
    max_dd = float(np.nanmax((peak - equity_curve) / peak))
    wins = sum(1 for r in trade_returns if r > 0)
    num_trades = len(trade_returns)
    win_rate = wins / num_trades if num_trades > 0 else 0.0

    return {
        "total_return": float(total_return),
        "sharpe_ratio": float(sharpe),
        "max_drawdown": float(max_dd),
        "win_rate": float(win_rate),
        "num_trades": num_trades,
    }
