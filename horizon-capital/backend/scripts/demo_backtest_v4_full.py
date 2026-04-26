"""Demo v4 — full research stack: HRP + Half-Kelly + HMM regime + Quality tilt
+ LLM/LM sentiment overlay + PSR/DSR honest metrics.

Modules used (all in app/quant):
  metrics_advanced  — PSR, DSR, Sortino, Calmar
  hrp               — Hierarchical Risk Parity weights (Lopez de Prado 2016)
  kelly             — Half-Kelly sizing per asset (Thorp 1969)
  regime_hmm        — 2-state regime via Gaussian Mixture (Hamilton-style)
  quality           — QMJ via yfinance fundamentals (AFP 2013)
  iv_features       — 30/90d IV skew + term + cp-spread (live-only signal)
  llm_sentiment     — Claude OR LM-dict OR deterministic mock

Caveats explicitly noted in summary:
  * Quality fundamentals snapshot — point-in-time bias for historical backtests
  * IV features live-only — yfinance has no historical IV
  * Mock sentiment used when no API key + no news feed
"""
from __future__ import annotations

import csv
import math
import os
import statistics
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.quant.hrp import hrp_weights
from app.quant.kelly import kelly_size_per_asset
from app.quant.metrics_advanced import (
    deflated_sharpe_ratio,
    max_drawdown,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
    sortino_ratio,
)
from app.quant.regime_hmm import detect_regime
from app.quant.quality import cross_section_quality
from app.quant.llm_sentiment import (
    LLMSentimentScorer,
    deterministic_mock_sentiment,
)

UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "GOOGL",
            "AMZN", "META", "TSLA", "JPM", "AVGO", "XLE", "TLT", "GLD"]
DEFENSE = ["TLT", "GLD"]

INITIAL_CAPITAL = 100_000.0
COMMISSION_BPS = 1.0
SLIPPAGE_BPS = 2.0

REBALANCE_EVERY = 5         # weekly rebalance — Carver 2015 lower turnover
HRP_LOOKBACK = 126           # 6 months of returns for clustering
KELLY_LOOKBACK = 252
TSMOM_LOOKBACK = 252
TSMOM_SKIP = 21
TOP_N = 5
KELLY_FRACTIONAL = 0.5       # half-Kelly
KELLY_CAP = 1.0              # per-asset max 1x NAV
MAX_GROSS = 1.5              # portfolio gross leverage cap
SENTIMENT_WEIGHT = 0.0       # disabled by user request
QUALITY_WEIGHT = 0.20

# Cache fundamentals once (point-in-time bias acknowledged)
_QUALITY_CACHE: dict[str, float] | None = None


def fetch_universe(start: str, end: str) -> dict[str, pd.DataFrame]:
    warmup = (pd.Timestamp(start) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    print(f"[data] fetching {len(UNIVERSE)} symbols {warmup}->{end}")
    raw = yf.download(" ".join(UNIVERSE), start=warmup, end=end,
                      progress=False, auto_adjust=True, group_by="ticker")
    out = {}
    for sym in UNIVERSE:
        try:
            df = raw[sym].dropna()
        except KeyError:
            continue
        df.columns = [c.lower() for c in df.columns]
        if len(df) > 50:
            out[sym] = df[["open", "high", "low", "close", "volume"]]
    print(f"[data] {len(out)} symbols loaded")
    return out


def get_quality_scores(symbols: list[str]) -> dict[str, float]:
    global _QUALITY_CACHE
    if _QUALITY_CACHE is None:
        print("[quality] fetching fundamentals (current snapshot, point-in-time bias)")
        try:
            scores = cross_section_quality(symbols)
            _QUALITY_CACHE = {s: r.composite for s, r in scores.items()}
        except Exception as e:
            print(f"[quality] failed: {e} — using zero scores")
            _QUALITY_CACHE = {s: 0.0 for s in symbols}
    return _QUALITY_CACHE


def tsmom_score(close: pd.Series) -> float | None:
    if len(close) < TSMOM_LOOKBACK + 1:
        return None
    past = close.iloc[-TSMOM_LOOKBACK]
    recent = close.iloc[-TSMOM_SKIP] if TSMOM_SKIP > 0 else close.iloc[-1]
    if past <= 0:
        return None
    return float((recent - past) / past)


def compute_target_weights(
    bars: dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
    sentiment_scorer: LLMSentimentScorer,
    use_mock_sentiment: bool,
) -> tuple[dict[str, float], list[dict]]:
    audit: list[dict] = []
    spy_close = bars["SPY"].loc[:as_of]["close"]
    state, conf = detect_regime(spy_close)
    audit.append({
        "date": str(as_of.date()), "agent": "hmm_regime", "symbol": "SPY",
        "signal": 1 if state == "RISK_ON" else -1,
        "strength": round(conf, 3),
        "reason": f"GMM regime={state} conf={conf:.2f}",
    })

    weights = {s: 0.0 for s in bars}

    if state == "RISK_OFF":
        # Defensive only — equal-vol on TLT/GLD
        defs = [s for s in DEFENSE if s in bars]
        if defs:
            for s in defs:
                weights[s] = 0.5 / len(defs)
        audit.append({
            "date": str(as_of.date()), "agent": "alloc", "symbol": "DEFENSE",
            "signal": 0, "strength": 1.0,
            "reason": f"RISK_OFF (conf {conf:.2f}) -> 50% defense, 50% cash",
        })
        return weights, audit

    # Risk-on path: rank universe
    qual = get_quality_scores([s for s in UNIVERSE if s not in DEFENSE])
    sentiment_cache: dict[str, float] = {}

    candidates = [s for s in bars if s not in DEFENSE]
    combined: dict[str, float] = {}
    for s in candidates:
        hist = bars[s].loc[:as_of]["close"]
        ts = tsmom_score(hist)
        if ts is None:
            continue
        sent = 0.0  # sentiment disabled
        sentiment_cache[s] = sent
        q = qual.get(s, 0.0)
        score = ts + SENTIMENT_WEIGHT * sent + QUALITY_WEIGHT * q
        combined[s] = score
        audit.append({
            "date": str(as_of.date()), "agent": "combined_signal", "symbol": s,
            "signal": 1 if score > 0 else -1,
            "strength": round(min(abs(score), 1.0), 3),
            "reason": f"tsmom={ts:.2f} sent={sent:+.2f} qual={q:+.2f} -> {score:+.3f}",
        })

    positive = {s: v for s, v in combined.items() if v > 0}
    if not positive:
        return weights, audit

    ranked = sorted(positive.items(), key=lambda kv: kv[1], reverse=True)
    winners = [s for s, _ in ranked[:TOP_N]]

    # 1. HRP weights on winners
    rets_panel = pd.DataFrame({
        s: bars[s].loc[:as_of]["close"].pct_change()
        .tail(HRP_LOOKBACK)
        for s in winners
    }).dropna()
    if rets_panel.shape[0] < 30 or rets_panel.shape[1] < 2:
        # Fallback: equal weight
        hrp = pd.Series([1.0 / len(winners)] * len(winners), index=winners)
    else:
        hrp = hrp_weights(rets_panel)
        if hrp.sum() == 0:
            hrp = pd.Series([1.0 / len(winners)] * len(winners), index=winners)

    audit.append({
        "date": str(as_of.date()), "agent": "hrp", "symbol": "PORTFOLIO",
        "signal": 1, "strength": 1.0,
        "reason": "HRP weights: " + ", ".join(f"{s}={hrp.get(s, 0):.2f}" for s in winners),
    })

    # 2. Half-Kelly per asset (caps each leg)
    kelly_panel = pd.DataFrame({
        s: bars[s].loc[:as_of]["close"].pct_change().tail(KELLY_LOOKBACK)
        for s in winners
    }).dropna()
    kelly_caps = kelly_size_per_asset(kelly_panel, cap=KELLY_CAP, fractional=KELLY_FRACTIONAL)
    audit.append({
        "date": str(as_of.date()), "agent": "kelly_size", "symbol": "PORTFOLIO",
        "signal": 1, "strength": 1.0,
        "reason": "half-Kelly caps: " + ", ".join(f"{s}={kelly_caps.get(s, 0):.2f}" for s in winners),
    })

    # 3. Combine: HRP weight * Kelly cap (per-leg cap), then normalise to MAX_GROSS
    raw = {s: float(hrp.get(s, 0)) * kelly_caps.get(s, 0) for s in winners}
    total = sum(raw.values())
    if total <= 0:
        return weights, audit
    # Vol-target the gross to MAX_GROSS or less
    if total > MAX_GROSS:
        scale = MAX_GROSS / total
        raw = {s: w * scale for s, w in raw.items()}
    for s, w in raw.items():
        weights[s] = w
    audit.append({
        "date": str(as_of.date()), "agent": "final_weights", "symbol": "PORTFOLIO",
        "signal": 1, "strength": round(sum(raw.values()), 3),
        "reason": "final: " + ", ".join(f"{s}={raw[s]:.3f}" for s in winners),
    })
    return weights, audit


def run(start: str, end: str, tag: str = "v4", use_mock_sentiment: bool = True) -> dict:
    bars = fetch_universe(start, end)
    spy_idx = bars["SPY"].index
    trading_dates = spy_idx[(spy_idx >= pd.Timestamp(start, tz=spy_idx.tz)) &
                            (spy_idx <= pd.Timestamp(end, tz=spy_idx.tz))]

    sentiment_scorer = LLMSentimentScorer(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    )
    print(f"[sentiment] backend={'claude' if sentiment_scorer._client else 'lm_dict_or_mock'}, "
          f"mock={use_mock_sentiment}")

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
                        max_spend = nav_at_open * MAX_GROSS
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
            tgt, ar = compute_target_weights(bars, dt, sentiment_scorer, use_mock_sentiment)
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

    navs = np.array([v for _, v in equity_curve])
    rets = np.diff(navs) / navs[:-1]
    rets = rets[~np.isnan(rets)]
    total_ret = navs[-1] / navs[0] - 1
    years = len(navs) / 252
    cagr = (navs[-1] / navs[0]) ** (1/years) - 1 if years > 0 else 0
    sr = sharpe_ratio(rets)
    sortino = sortino_ratio(rets)
    mdd = max_drawdown(navs)
    psr = probabilistic_sharpe_ratio(rets, benchmark_sr=0.0)
    # Assume we tried 4 strategy variants (v1..v4) — apply DSR for honesty
    dsr = deflated_sharpe_ratio(rets, n_trials=4)

    spy = bars["SPY"]
    spw = spy.loc[trading_dates[0]:trading_dates[-1]]["close"]
    spy_total = float(spw.iloc[-1])/float(spw.iloc[0])-1
    spy_cagr = (1+spy_total)**(1/years)-1 if years > 0 else 0
    spr = spw.pct_change().dropna()
    spy_sharpe = sharpe_ratio(spr.values)
    spy_psr = probabilistic_sharpe_ratio(spr.values, benchmark_sr=0.0)

    summary = (
        f"DEMO v4 FULL STACK ({start} -> {end})\n"
        f"=========================================================\n"
        f"Stack: HRP weights + Half-Kelly sizing + GMM regime gate + Quality tilt + Sentiment overlay\n"
        f"Universe : {', '.join(UNIVERSE)}\n"
        f"Initial capital      : ${INITIAL_CAPITAL:,.2f}\n"
        f"Final NAV            : ${navs[-1]:,.2f}\n"
        f"Total return         : {total_ret*100:+.2f}%\n"
        f"CAGR                 : {cagr*100:+.2f}%\n"
        f"Sharpe               : {sr:.2f}\n"
        f"Sortino              : {sortino:.2f}\n"
        f"Max drawdown         : {mdd*100:.2f}%\n"
        f"Probabilistic SR     : {psr*100:.1f}%   (prob true SR > 0)\n"
        f"Deflated SR (4 trials): {dsr*100:.1f}%   (prob true SR > 0 after multi-test deflation)\n"
        f"Trades executed      : {len(trades)}\n"
        f"Audit rows           : {len(audit_all)}\n"
        f"\n--- Benchmark: SPY buy-and-hold ---\n"
        f"SPY total return     : {spy_total*100:+.2f}%\n"
        f"SPY CAGR             : {spy_cagr*100:+.2f}%\n"
        f"SPY Sharpe           : {spy_sharpe:.2f}\n"
        f"SPY PSR              : {spy_psr*100:.1f}%\n"
        f"Alpha vs SPY         : {(total_ret-spy_total)*100:+.2f}%\n"
        f"\n--- Caveats (read these) ---\n"
        f"* Quality fundamentals: yfinance gives current snapshot only -> point-in-time bias\n"
        f"* IV features: live-only signal (yfinance has no historical IV) -> not active in backtest\n"
        f"* Sentiment: deterministic mock used (no historical news feed). Real use needs news API.\n"
        f"* Universe chosen post-hoc -> survivorship bias risk\n"
        f"* PSR/DSR computed; DSR < 50% means the result may be noise after multi-test deflation.\n"
    )
    summary_path.write_text(summary, encoding="utf-8")
    print("\n" + summary)
    return {"total_ret": total_ret, "cagr": cagr, "sharpe": sr, "psr": psr, "dsr": dsr, "mdd": mdd}


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 2:
        run(f"{args[0]}-01-01", f"{args[1]}-12-31", tag=f"v4_{args[0]}_{args[1]}")
    else:
        run("2024-01-01", "2024-12-31", tag="v4")
