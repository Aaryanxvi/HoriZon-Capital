# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-BC54438BF103
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Demo v3 — profit-maximised multi-sleeve backtest.

Differences from v2 (each tied to research):
  * Daily rebalance              (Carver 2015 "Systematic Trading")
  * Top-3 concentration          (Cohen, Polk & Silli 2010 "Best Ideas")
  * Vol target 20% (up from 15%) (higher risk for higher return)
  * Leverage cap 2.0×            (Clenow 2013 "Following the Trend")
  * TLT bond hedge in cash mode  (flight-to-quality, Asness et al)
  * TQQQ/UPRO when strong regime (3× leverage proxy, AQR style)
  * Forecast scaling by signal magnitude (Carver chapter 7)

CLI:
  python scripts/demo_backtest_v3_aggressive.py            # default 2024
  python scripts/demo_backtest_v3_aggressive.py 2019 2024
  python scripts/demo_backtest_v3_aggressive.py 2022 2022
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

# Risk universe
RISK_UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "GOOGL",
                 "AMZN", "META", "TSLA", "JPM", "AVGO", "XLE"]
# Bear-regime hedges
DEFENSE_UNIVERSE = ["TLT", "GLD"]
# Strong-regime leveraged sleeves (add only when SPY 5% above 200d SMA)
LEVERED_UNIVERSE = ["TQQQ"]
ALL_UNIVERSE = RISK_UNIVERSE + DEFENSE_UNIVERSE + LEVERED_UNIVERSE

INITIAL_CAPITAL = 100_000.0
COMMISSION_BPS = 1.0
SLIPPAGE_BPS = 2.0

TARGET_ANNUAL_VOL = 0.20
MAX_GROSS_LEVERAGE = 2.0
SMA_WINDOW = 200
STRONG_REGIME_BUFFER = 0.05  # 5% above SMA → strong
TSMOM_LOOKBACK = 252
TSMOM_SKIP = 21
SHORT_MOMO_LOOKBACK = 63   # 3-month for sub-signal
VOL_WINDOW = 60
TOP_N = 3
REBALANCE_EVERY = 1  # daily


def fetch_universe(start: str, end: str) -> dict[str, pd.DataFrame]:
    warmup = (pd.Timestamp(start) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    print(f"[data] fetching {len(ALL_UNIVERSE)} symbols {warmup}->{end}")
    raw = yf.download(" ".join(ALL_UNIVERSE), start=warmup, end=end,
                      progress=False, auto_adjust=True, group_by="ticker")
    out = {}
    for sym in ALL_UNIVERSE:
        try:
            df = raw[sym].dropna()
        except KeyError:
            continue
        df.columns = [c.lower() for c in df.columns]
        if len(df) > 50:
            out[sym] = df[["open", "high", "low", "close", "volume"]]
    print(f"[data] {len(out)} symbols loaded")
    return out


def regime_state(spy_close: pd.Series) -> str:
    """Return 'STRONG', 'ON', or 'OFF'."""
    if len(spy_close) < SMA_WINDOW + 1:
        return "OFF"
    sma = spy_close.rolling(SMA_WINDOW).mean().iloc[-1]
    price = spy_close.iloc[-1]
    if price > sma * (1 + STRONG_REGIME_BUFFER):
        return "STRONG"
    if price > sma:
        return "ON"
    return "OFF"


def tsmom_score(close: pd.Series) -> float | None:
    if len(close) < TSMOM_LOOKBACK + 1:
        return None
    past = close.iloc[-TSMOM_LOOKBACK]
    recent = close.iloc[-TSMOM_SKIP] if TSMOM_SKIP > 0 else close.iloc[-1]
    if past <= 0:
        return None
    return float((recent - past) / past)


def short_momo(close: pd.Series) -> float | None:
    if len(close) < SHORT_MOMO_LOOKBACK + 1:
        return None
    past = close.iloc[-SHORT_MOMO_LOOKBACK]
    if past <= 0:
        return None
    return float((close.iloc[-1] - past) / past)


def realised_vol(close: pd.Series, window: int = VOL_WINDOW) -> float | None:
    rets = close.pct_change().dropna()
    if len(rets) < window:
        return None
    return float(rets.tail(window).std() * math.sqrt(252))


def compute_target_weights(
    bars: dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
) -> tuple[dict[str, float], list[dict]]:
    audit: list[dict] = []
    spy_hist = bars["SPY"].loc[:as_of]["close"]
    regime = regime_state(spy_hist)
    audit.append({
        "date": str(as_of.date()), "agent": "regime", "symbol": "SPY",
        "signal": {"STRONG": 2, "ON": 1, "OFF": 0}[regime],
        "strength": 1.0,
        "reason": f"regime={regime}",
    })

    # OFF regime: rotate to defensive (TLT/GLD) using 12-1 momo on those
    if regime == "OFF":
        weights = {s: 0.0 for s in bars}
        defense_scores = {}
        for s in DEFENSE_UNIVERSE:
            if s not in bars: continue
            hist = bars[s].loc[:as_of]["close"]
            score = tsmom_score(hist)
            vol = realised_vol(hist)
            if score is None or vol is None or vol <= 0: continue
            defense_scores[s] = (score, vol)
            audit.append({
                "date": str(as_of.date()), "agent": "defense_tsmom", "symbol": s,
                "signal": 1 if score > 0 else -1,
                "strength": min(abs(score), 1.0),
                "reason": f"12-1 ret {score*100:+.1f}%",
            })
        # split equally among defenses with positive momo
        positive = [s for s, (sc, _) in defense_scores.items() if sc > 0]
        if positive:
            # vol-target the defense allocation at 10% (lower target — bonds boring)
            for s in positive:
                _, vol = defense_scores[s]
                w = (0.10 / vol) / len(positive) if vol > 0 else 0
                weights[s] = min(w, 0.5)
            audit.append({
                "date": str(as_of.date()), "agent": "alloc", "symbol": "DEFENSE",
                "signal": 1, "strength": 1.0,
                "reason": f"OFF regime: long {','.join(positive)}",
            })
        return weights, audit

    # ON / STRONG: rank risk universe
    scores: dict[str, tuple[float, float, float]] = {}  # sym -> (combined, tsmom, vol)
    for s in RISK_UNIVERSE:
        if s not in bars: continue
        hist = bars[s].loc[:as_of]["close"]
        ts = tsmom_score(hist)
        sm = short_momo(hist)
        vol = realised_vol(hist)
        if ts is None or sm is None or vol is None or vol <= 0: continue
        # Combined forecast: 60% long-term + 40% short-term momentum (Carver)
        combined = 0.6 * ts + 0.4 * sm
        scores[s] = (combined, ts, vol)
        audit.append({
            "date": str(as_of.date()), "agent": "tsmom_short", "symbol": s,
            "signal": 1 if combined > 0 else -1,
            "strength": min(abs(combined), 1.0),
            "reason": f"long={ts*100:+.1f}% short={sm*100:+.1f}% vol={vol*100:.0f}%",
        })

    positive = {s: v for s, v in scores.items() if v[0] > 0}
    if not positive:
        return {s: 0.0 for s in bars}, audit
    ranked = sorted(positive.items(), key=lambda kv: kv[1][0], reverse=True)
    winners = [s for s, _ in ranked[:TOP_N]]

    # Forecast-scaled inverse-vol weighting (Carver)
    raw_weights = {}
    for s in winners:
        combined, _, vol = scores[s]
        # scale by forecast strength (capped 2x)
        forecast_mult = min(abs(combined) * 4, 2.0)
        raw_weights[s] = forecast_mult / vol
    s_w = sum(raw_weights.values())
    raw_weights = {s: w / s_w for s, w in raw_weights.items()}

    # Vol target overlay
    weighted_vol = sum(raw_weights[s] * scores[s][2] for s in winners)
    n = len(winners); avg_corr = 0.5
    port_vol = math.sqrt(weighted_vol**2 * (1/n + (n-1)/n * avg_corr)) if n > 0 else weighted_vol
    scale = TARGET_ANNUAL_VOL / port_vol if port_vol > 0 else 1.0

    # STRONG regime: add TQQQ kicker, allow up to MAX leverage
    if regime == "STRONG":
        scale = min(scale * 1.2, MAX_GROSS_LEVERAGE)
    else:
        scale = min(scale, MAX_GROSS_LEVERAGE * 0.75)

    weights = {s: 0.0 for s in bars}
    for s, w in raw_weights.items():
        weights[s] = w * scale

    # Add small TQQQ kicker in STRONG regime if it qualifies
    if regime == "STRONG" and "TQQQ" in bars:
        tq_hist = bars["TQQQ"].loc[:as_of]["close"]
        tq_score = tsmom_score(tq_hist)
        if tq_score is not None and tq_score > 0:
            weights["TQQQ"] = 0.10  # 10% TQQQ kicker
            audit.append({
                "date": str(as_of.date()), "agent": "leverage_kicker", "symbol": "TQQQ",
                "signal": 1, "strength": 1.0,
                "reason": f"STRONG regime + TQQQ momo {tq_score*100:+.1f}% → 10% sleeve",
            })

    gross = sum(weights.values())
    if gross > MAX_GROSS_LEVERAGE:
        weights = {s: w * MAX_GROSS_LEVERAGE / gross for s, w in weights.items()}

    audit.append({
        "date": str(as_of.date()), "agent": "vol_target", "symbol": "PORTFOLIO",
        "signal": 1, "strength": round(scale, 3),
        "reason": f"port_vol~{port_vol*100:.1f}% target=20% scale={scale:.2f}",
    })
    return weights, audit


def run(start: str, end: str, tag: str = "v3") -> dict:
    bars = fetch_universe(start, end)
    spy_idx = bars["SPY"].index
    trading_dates = spy_idx[(spy_idx >= pd.Timestamp(start, tz=spy_idx.tz)) &
                            (spy_idx <= pd.Timestamp(end, tz=spy_idx.tz))]

    cash = INITIAL_CAPITAL
    positions = {s: 0.0 for s in bars}
    avg_entry = {s: 0.0 for s in bars}
    equity_curve: list[tuple[str, float]] = []
    audit_all: list[dict] = []
    trades: list[dict] = []
    pending_targets: dict[str, float] | None = None
    days_since_rebalance = REBALANCE_EVERY

    for i, dt in enumerate(trading_dates):
        nav_at_open = cash
        for s, q in positions.items():
            if q == 0: continue
            try: nav_at_open += q * float(bars[s].loc[dt, "open"])
            except KeyError: pass

        if pending_targets is not None:
            for s, tw in pending_targets.items():
                df = bars.get(s)
                if df is None or dt not in df.index: continue
                op = float(df.loc[dt, "open"])
                if op <= 0: continue
                target_qty = nav_at_open * tw / op
                delta = target_qty - positions[s]
                if abs(delta * op) < nav_at_open * 0.005: continue
                side = "BUY" if delta > 0 else "SELL"
                slip = 1 + (SLIPPAGE_BPS / 1e4) * (1 if side == "BUY" else -1)
                fp = op * slip
                qa = abs(delta)
                notional = qa * fp
                comm = notional * COMMISSION_BPS / 1e4
                pnl = 0.0
                if side == "BUY":
                    cost = notional + comm
                    if cost > cash:
                        # leverage allowed via margin: spend up to MAX_GROSS limit
                        max_spend = nav_at_open * MAX_GROSS_LEVERAGE
                        deployed = sum(positions[x] * float(bars[x].loc[dt, "open"])
                                       for x in positions if positions[x] > 0
                                       and dt in bars[x].index)
                        if deployed + cost > max_spend:
                            qa = max(0, (max_spend - deployed - comm) / fp)
                            if qa <= 0: continue
                            notional = qa * fp; comm = notional * COMMISSION_BPS / 1e4
                    nt = positions[s] + qa
                    if nt > 0:
                        avg_entry[s] = (avg_entry[s]*positions[s] + fp*qa) / nt
                    positions[s] = nt
                    cash -= (notional + comm)
                else:
                    qa = min(qa, positions[s])
                    if qa <= 0: continue
                    pnl = (fp - avg_entry[s]) * qa
                    cash += qa * fp - comm
                    positions[s] -= qa
                    if positions[s] <= 1e-6:
                        positions[s] = 0.0; avg_entry[s] = 0.0
                trades.append({
                    "date": str(dt.date()), "symbol": s, "side": side,
                    "qty": round(qa, 4), "fill_price": round(fp, 4),
                    "target_weight": round(tw, 4),
                    "pnl": round(pnl, 2), "cash_after": round(cash, 2),
                })
            pending_targets = None

        nav = cash
        for s, q in positions.items():
            if q == 0: continue
            try: nav += q * float(bars[s].loc[dt, "close"])
            except KeyError: pass
        equity_curve.append((str(dt.date()), nav))

        days_since_rebalance += 1
        if days_since_rebalance >= REBALANCE_EVERY:
            tgt, ar = compute_target_weights(bars, dt)
            for r in ar:
                r["nav"] = round(nav, 2); audit_all.append(r)
            pending_targets = tgt
            days_since_rebalance = 0

    audit_path = ROOT / f"demo_{tag}_audit.csv"
    trades_path = ROOT / f"demo_{tag}_trades.csv"
    eq_path = ROOT / f"demo_{tag}_equity.csv"
    summary_path = ROOT / f"demo_{tag}_summary.txt"
    if audit_all:
        with open(audit_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(audit_all[0].keys()))
            w.writeheader(); w.writerows(audit_all)
    if trades:
        with open(trades_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
            w.writeheader(); w.writerows(trades)
    with open(eq_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["date","nav"]); w.writerows(equity_curve)

    navs = [v for _, v in equity_curve]
    total_ret = navs[-1]/navs[0]-1
    days = len(navs); years = days/252
    cagr = (navs[-1]/navs[0])**(1/years)-1 if years > 0 else 0
    rets = [navs[i]/navs[i-1]-1 for i in range(1, len(navs)) if navs[i-1] > 0]
    mu = statistics.mean(rets); sd = statistics.pstdev(rets)
    sharpe = (mu/sd)*math.sqrt(252) if sd > 0 else 0
    peak = navs[0]; mdd = 0.0
    for v in navs:
        peak = max(peak, v); dd = (v-peak)/peak; mdd = min(mdd, dd)

    spy = bars["SPY"]
    spw = spy.loc[trading_dates[0]:trading_dates[-1]]["close"]
    spy_total = float(spw.iloc[-1])/float(spw.iloc[0])-1
    spy_cagr = (1+spy_total)**(1/years)-1 if years > 0 else 0
    spr = spw.pct_change().dropna()
    spy_sharpe = (spr.mean()/spr.std())*math.sqrt(252) if spr.std() > 0 else 0

    summary = (
        f"DEMO v3 PROFIT-MAX ({start} -> {end})\n"
        f"=========================================================\n"
        f"Universe risk        : {', '.join(RISK_UNIVERSE)}\n"
        f"Defense              : {', '.join(DEFENSE_UNIVERSE)}\n"
        f"Leverage proxy       : {', '.join(LEVERED_UNIVERSE)}\n"
        f"Initial capital      : ${INITIAL_CAPITAL:,.2f}\n"
        f"Final NAV            : ${navs[-1]:,.2f}\n"
        f"Total return         : {total_ret*100:+.2f}%\n"
        f"CAGR                 : {cagr*100:+.2f}%\n"
        f"Sharpe (rf=0)        : {sharpe:.2f}\n"
        f"Max drawdown         : {mdd*100:.2f}%\n"
        f"Trades executed      : {len(trades)}\n"
        f"\n--- Benchmark: SPY buy-and-hold ---\n"
        f"SPY total return     : {spy_total*100:+.2f}%\n"
        f"SPY CAGR             : {spy_cagr*100:+.2f}%\n"
        f"SPY Sharpe           : {spy_sharpe:.2f}\n"
        f"Alpha vs SPY         : {(total_ret-spy_total)*100:+.2f}%\n"
    )
    summary_path.write_text(summary, encoding="utf-8")
    print("\n" + summary)
    return {"total_ret": total_ret, "cagr": cagr, "sharpe": sharpe, "mdd": mdd}


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 2:
        run(f"{args[0]}-01-01", f"{args[1]}-12-31", tag=f"v3_{args[0]}_{args[1]}")
    else:
        run("2024-01-01", "2024-12-31", tag="v3")
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token BC54438BF103 - verify with scripts/authorship.py verify
