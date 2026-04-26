"""Multi-sleeve backtest harness.

Replays the trend / gap / momentum sleeves over historical Alpaca bars with
realistic transaction costs. Writes a summary report to stdout and a CSV of
the equity curve to ``sleeve_backtest_equity.csv``.

Usage:
    python -m scripts.backtest_sleeves --start 2020-01-01 --capital 100000
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.front_office.strategy.sleeves import (  # noqa: E402, I001
    GapFadeSleeve,
    MomentumRankSleeve,
    TrendFilterSleeve,
)
from app.data_layer import alpaca_quotes  # noqa: E402, I001


# Universe for the backtest. Must include SPY + QQQ for trend/gap sleeves
# and enough names for the momentum sleeve to pick from.
UNIVERSE = [
    "SPY.NYSE", "QQQ.NASDAQ",
    "AAPL.NASDAQ", "MSFT.NASDAQ", "GOOGL.NASDAQ", "AMZN.NASDAQ",
    "META.NASDAQ", "NVDA.NASDAQ", "JPM.NYSE", "XOM.NYSE",
]

SLEEVES = [TrendFilterSleeve(), GapFadeSleeve(), MomentumRankSleeve()]

# Realistic costs mirroring paper_broker.py (US equities).
COMMISSION_BPS = 1.0        # ~0 + SEC fees
SLIPPAGE_BPS = 1.0          # ~1 bp half-spread for SPY/QQQ/mega-caps
TRADING_DAYS = 252


async def fetch_all(start: str) -> dict[str, pd.DataFrame]:
    """Fetch daily bars from Alpaca for every symbol in the universe."""
    lookback_days = (pd.Timestamp.utcnow() - pd.Timestamp(start, tz="UTC")).days + 260
    bars: dict[str, pd.DataFrame] = {}
    for symbol in UNIVERSE:
        df = await alpaca_quotes.get_bars(
            symbol, timeframe="1Day", lookback_days=lookback_days
        )
        if df is None or df.empty:
            print(f"[WARN] no data for {symbol}")
            continue
        df.index = df.index.tz_convert("UTC").normalize()
        bars[symbol] = df
        print(f"  {symbol}: {len(df)} bars {df.index[0].date()} -> {df.index[-1].date()}")
    return bars


def build_calendar(bars: dict[str, pd.DataFrame], start: str) -> pd.DatetimeIndex:
    """Union of all trading dates >= start across the universe."""
    dates: set[pd.Timestamp] = set()
    start_ts = pd.Timestamp(start, tz="UTC")
    for df in bars.values():
        dates.update(d for d in df.index if d >= start_ts)
    return pd.DatetimeIndex(sorted(dates))


def compute_target_weights(
    bars: dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
    bar_index: int,
    sleeve_cache: dict[str, list],
) -> tuple[dict[str, float], bool]:
    """Return (target_weights, changed).

    ``changed`` is True only when at least one sleeve refreshed on this bar
    AND its target differed from the previous snapshot. Lets the outer loop
    skip trading on quiet bars and prevents NAV-drift-induced churn.
    """
    combined: dict[str, float] = {}
    any_changed = False
    for sleeve in SLEEVES:
        if bar_index % sleeve.rebalance_days == 0 or sleeve.name not in sleeve_cache:
            new_signals = sleeve.compute(bars, as_of)
            prev = sleeve_cache.get(sleeve.name)
            if prev is None or _sleeve_targets_differ(prev, new_signals):
                any_changed = True
            sleeve_cache[sleeve.name] = new_signals
        for sig in sleeve_cache[sleeve.name]:
            share = sig.target_weight * sleeve.target_weight
            combined[sig.symbol] = combined.get(sig.symbol, 0.0) + share
    return combined, any_changed


def _sleeve_targets_differ(a: list, b: list) -> bool:
    """Compare two signal lists by (symbol, weight) — ignore ordering/reasons."""
    amap = {s.symbol: round(s.target_weight, 4) for s in a}
    bmap = {s.symbol: round(s.target_weight, 4) for s in b}
    return amap != bmap


def run_backtest(
    bars: dict[str, pd.DataFrame],
    calendar: pd.DatetimeIndex,
    initial_capital: float,
) -> tuple[pd.Series, pd.DataFrame]:
    """Run the sleeve replay and return (equity_curve, trade_log)."""
    cash = initial_capital
    shares: dict[str, float] = {}
    equity_series: list[tuple[pd.Timestamp, float]] = []
    trades: list[dict] = []
    sleeve_cache: dict[str, list] = {}

    for i, date in enumerate(calendar):
        # Determine next-day open price for fills (we decide at date, fill at t+1).
        if i + 1 >= len(calendar):
            break
        fill_date = calendar[i + 1]

        targets, any_changed = compute_target_weights(bars, date, i, sleeve_cache)

        # Compute today's mark-to-market NAV using the current bar close
        nav = cash
        for s, q in shares.items():
            bar = bars.get(s)
            if bar is None or date not in bar.index:
                continue
            nav += q * bar.loc[date]["close"]
        equity_series.append((date, nav))

        # Only trade when at least one sleeve's target actually changed on
        # this bar. Prevents NAV-drift rebalances every single day.
        if not any_changed:
            continue

        # For each symbol, trade to target shares at next bar open.
        for symbol in UNIVERSE:
            bar = bars.get(symbol)
            if bar is None or fill_date not in bar.index:
                continue
            fill_px = bar.loc[fill_date]["open"]
            if fill_px <= 0:
                continue

            target_dollars = nav * targets.get(symbol, 0.0)
            target_shares = target_dollars / fill_px
            cur_shares = shares.get(symbol, 0.0)
            delta = target_shares - cur_shares
            if abs(delta * fill_px) < nav * 0.001:
                continue  # skip rebalances below 10 bps of NAV

            side = "BUY" if delta > 0 else "SELL"
            qty = abs(delta)
            notional = qty * fill_px
            slip = notional * SLIPPAGE_BPS / 10_000
            comm = notional * COMMISSION_BPS / 10_000
            # Executed price worse by slippage direction
            slip_frac = SLIPPAGE_BPS / 10_000
            exec_px = (
                fill_px * (1 + slip_frac) if side == "BUY"
                else fill_px * (1 - slip_frac)
            )

            if side == "BUY":
                cost = qty * exec_px + comm
                if cost > cash:
                    # Scale down to fit available cash (no margin in backtest)
                    max_qty = max(0.0, (cash - comm) / exec_px)
                    qty = max_qty
                    if qty <= 0:
                        continue
                    cost = qty * exec_px + comm
                cash -= cost
                shares[symbol] = cur_shares + qty
            else:
                proceeds = qty * exec_px - comm
                shares[symbol] = cur_shares - qty
                cash += proceeds

            trades.append({
                "date": fill_date, "symbol": symbol, "side": side,
                "qty": round(qty, 4), "price": round(exec_px, 4),
                "slippage": round(slip, 4), "commission": round(comm, 4),
            })

    equity = pd.Series({d: v for d, v in equity_series})
    return equity, pd.DataFrame(trades)


def summarize(equity: pd.Series, trades: pd.DataFrame) -> dict:
    """Compute summary metrics for the backtest."""
    if len(equity) < 2:
        return {}
    returns = equity.pct_change().dropna()
    total_ret = equity.iloc[-1] / equity.iloc[0] - 1
    years = len(equity) / TRADING_DAYS
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    vol = returns.std() * np.sqrt(TRADING_DAYS)
    sharpe = (returns.mean() * TRADING_DAYS - 0.04) / vol if vol > 0 else 0
    roll_max = equity.cummax()
    dd = (equity - roll_max) / roll_max
    max_dd = dd.min()
    return {
        "start": str(equity.index[0].date()),
        "end": str(equity.index[-1].date()),
        "days": len(equity),
        "initial": round(equity.iloc[0], 2),
        "final": round(equity.iloc[-1], 2),
        "total_return_pct": round(total_ret * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "vol_pct": round(vol * 100, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "trades": len(trades),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--out", default="sleeve_backtest_equity.csv")
    args = parser.parse_args()

    if not alpaca_quotes.is_configured():
        print("ERROR: Alpaca not configured. Set ALPACA_API_KEY + SECRET in .env.")
        return

    print(f"Fetching bars from Alpaca since {args.start}...")
    bars = await fetch_all(args.start)
    if len(bars) < len(UNIVERSE):
        print(f"[WARN] got {len(bars)} of {len(UNIVERSE)} symbols — backtest may be incomplete")

    calendar = build_calendar(bars, args.start)
    print(f"Calendar: {len(calendar)} days\n")

    equity, trades = run_backtest(bars, calendar, args.capital)
    summary = summarize(equity, trades)

    # Benchmark: buy-and-hold SPY over the same calendar.
    spy = bars.get("SPY.NYSE")
    bench_summary = None
    if spy is not None:
        start_px = spy.loc[calendar[0]]["close"] if calendar[0] in spy.index else None
        if start_px:
            bench = spy.loc[calendar[0]: calendar[-1]]["close"]
            bench_eq = (bench / start_px) * args.capital
            bench_summary = summarize(bench_eq, pd.DataFrame())

    print("\n=== Sleeve System ===")
    for k, v in summary.items():
        print(f"  {k:22s}: {v}")

    if bench_summary:
        print("\n=== Buy-and-Hold SPY (benchmark) ===")
        for k, v in bench_summary.items():
            print(f"  {k:22s}: {v}")

    equity.to_csv(args.out, header=["nav"])
    if not trades.empty:
        trades.to_csv("sleeve_backtest_trades.csv", index=False)
    print(f"\nEquity curve -> {args.out}")
    print("Trade log    -> sleeve_backtest_trades.csv")


if __name__ == "__main__":
    asyncio.run(main())
