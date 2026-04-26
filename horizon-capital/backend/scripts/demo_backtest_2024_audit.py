"""Demo backtest: SPY 2024-01-01 → 2024-12-31 with full per-bar audit log.

Output files (written to backend/):
    demo_2024_audit.csv     — every signal from every agent, every bar
    demo_2024_trades.csv    — every executed trade with reasoning chain
    demo_2024_equity.csv    — daily NAV
    demo_2024_summary.txt   — final metrics

This script bypasses the LLM stack on purpose: it exercises the same
deterministic strategy code (RSIStrategy, MACDStrategy, BollingerBandStrategy)
the live system uses, so the audit trail proves logic — not a black box.
"""
from __future__ import annotations

import csv
import math
import statistics
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agents.front_office.strategy.simple_strategies import (
    BollingerBandStrategy,
    MACDStrategy,
    RSIStrategy,
)

SYMBOL = "SPY"
START = "2024-01-01"
END = "2024-12-31"
INITIAL_CAPITAL = 100_000.0
COMMISSION_BPS = 1.0  # 1 bp per side
SLIPPAGE_BPS = 2.0    # 2 bp slippage per side

OUT_AUDIT = ROOT / "demo_2024_audit.csv"
OUT_TRADES = ROOT / "demo_2024_trades.csv"
OUT_EQUITY = ROOT / "demo_2024_equity.csv"
OUT_SUMMARY = ROOT / "demo_2024_summary.txt"


def fetch_bars() -> pd.DataFrame:
    print(f"[data] fetching {SYMBOL} {START}->{END} via yfinance...")
    df = yf.download(SYMBOL, start=START, end=END, progress=False, auto_adjust=True)
    if df.empty:
        raise SystemExit("no data fetched")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    print(f"[data] {len(df)} bars loaded")
    return df


def aggregate_vote(signals: list) -> tuple[int, float, str]:
    """Return (direction, conviction, reason). Majority vote weighted by strength."""
    if not signals:
        return 0, 0.0, "no signals"
    score = 0.0
    parts = []
    for s in signals:
        score += s.direction * s.strength
        parts.append(f"{s.strategy_name}:{s.direction:+d}@{s.strength:.2f}({s.reasoning})")
    if abs(score) < 0.15:
        return 0, score, "low conviction; " + " | ".join(parts)
    direction = 1 if score > 0 else -1
    return direction, score, " | ".join(parts)


def main() -> None:
    df = fetch_bars()

    strategies = [RSIStrategy(), MACDStrategy(), BollingerBandStrategy()]

    cash = INITIAL_CAPITAL
    qty = 0.0
    avg_entry = 0.0
    equity_curve: list[tuple[str, float]] = []

    audit_rows = []
    trade_rows = []
    pending = None  # (direction, conviction, reason)

    for i in range(len(df)):
        bar_ts = df.index[i]
        bar = df.iloc[i]
        history = df.iloc[: i + 1]
        open_p = float(bar["open"])
        close_p = float(bar["close"])

        # 1. Execute pending order at this bar's open
        executed = None
        if pending is not None:
            direction, conviction, reason = pending
            slip_mult = 1.0 + (SLIPPAGE_BPS / 1e4) * direction  # buy worse, sell worse
            fill_price = open_p * slip_mult
            commission_rate = COMMISSION_BPS / 1e4

            if direction == 1 and qty == 0:
                # full deploy of cash
                target_notional = cash * 0.95  # keep 5% buffer
                qty_buy = target_notional / fill_price
                cost = qty_buy * fill_price * (1 + commission_rate)
                if cost <= cash:
                    cash -= cost
                    avg_entry = fill_price
                    qty = qty_buy
                    executed = ("BUY", qty_buy, fill_price, reason)
            elif direction == -1 and qty > 0:
                proceeds = qty * fill_price * (1 - commission_rate)
                pnl = (fill_price - avg_entry) * qty
                cash += proceeds
                executed = ("SELL", qty, fill_price, reason, round(pnl, 2))
                qty = 0.0
                avg_entry = 0.0
            pending = None

        # 2. Mark equity
        nav = cash + qty * close_p
        equity_curve.append((str(bar_ts.date()), nav))

        # 3. Run all strategies, log every signal
        signals = []
        for strat in strategies:
            sig = strat.generate_signal(SYMBOL, history)
            audit_rows.append({
                "date": str(bar_ts.date()),
                "agent": strat.name,
                "signal": sig.direction if sig else 0,
                "strength": round(sig.strength, 3) if sig else 0.0,
                "reason": sig.reasoning if sig else "no signal",
                "close": round(close_p, 2),
                "position_qty": round(qty, 4),
                "nav": round(nav, 2),
            })
            if sig:
                signals.append(sig)

        # 4. Aggregate vote -> next-bar order
        direction, conviction, reason = aggregate_vote(signals)
        if direction != 0:
            # only act if it would change position
            want_long = direction == 1 and qty == 0
            want_exit = direction == -1 and qty > 0
            if want_long or want_exit:
                pending = (direction, conviction, reason)

        # 5. Record any executed trade
        if executed:
            row = {
                "date": str(bar_ts.date()),
                "side": executed[0],
                "qty": round(executed[1], 4),
                "fill_price": round(executed[2], 4),
                "reasoning_chain": executed[3],
                "pnl": executed[4] if len(executed) >= 5 else 0.0,
                "cash_after": round(cash, 2),
                "nav_after": round(nav, 2),
            }
            trade_rows.append(row)
            print(f"[trade] {row['date']} {row['side']:4s} {row['qty']:.2f}@{row['fill_price']:.2f} "
                  f"pnl={row['pnl']} nav={row['nav_after']}")

    # ---- Write artifacts
    with open(OUT_AUDIT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()))
        w.writeheader(); w.writerows(audit_rows)
    with open(OUT_TRADES, "w", newline="") as f:
        if trade_rows:
            w = csv.DictWriter(f, fieldnames=list(trade_rows[0].keys()))
            w.writeheader(); w.writerows(trade_rows)
        else:
            f.write("no trades\n")
    with open(OUT_EQUITY, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "nav"]); w.writerows(equity_curve)

    # ---- Metrics
    navs = [v for _, v in equity_curve]
    total_ret = navs[-1] / navs[0] - 1
    rets = [navs[i] / navs[i-1] - 1 for i in range(1, len(navs)) if navs[i-1] > 0]
    mu = statistics.mean(rets) if rets else 0
    sd = statistics.pstdev(rets) if rets else 0
    sharpe = (mu / sd) * math.sqrt(252) if sd > 0 else 0
    peak = navs[0]; mdd = 0.0
    for v in navs:
        peak = max(peak, v); dd = (v - peak) / peak; mdd = min(mdd, dd)

    # SPY buy-and-hold benchmark
    spy_ret = float(df["close"].iloc[-1]) / float(df["close"].iloc[0]) - 1

    summary = (
        f"DEMO BACKTEST — SPY 2024 ({START} -> {END})\n"
        f"=========================================\n"
        f"Bars processed       : {len(df)}\n"
        f"Strategies           : RSI, MACD, BollingerBands (deterministic, no LLM)\n"
        f"Initial capital      : ${INITIAL_CAPITAL:,.2f}\n"
        f"Final NAV            : ${navs[-1]:,.2f}\n"
        f"Total return         : {total_ret*100:+.2f}%\n"
        f"SPY buy-and-hold     : {spy_ret*100:+.2f}%\n"
        f"Alpha vs SPY         : {(total_ret - spy_ret)*100:+.2f}%\n"
        f"Sharpe (rf=0)        : {sharpe:.2f}\n"
        f"Max drawdown         : {mdd*100:.2f}%\n"
        f"Trades executed      : {len(trade_rows)}\n"
        f"Audit rows logged    : {len(audit_rows)}\n"
        f"\nFiles:\n  {OUT_AUDIT.name}\n  {OUT_TRADES.name}\n  {OUT_EQUITY.name}\n"
    )
    OUT_SUMMARY.write_text(summary)
    print("\n" + summary)


if __name__ == "__main__":
    main()
