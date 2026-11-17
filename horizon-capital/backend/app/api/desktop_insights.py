"""Desktop insights API — risk, trades, benchmark, costs and health, LOCAL SQLite only.

Mounted at ``/api/desktop/insights``. Same rules as ``api/desktop.py``: read-only
raw SQL over the tables the terminal reads. Every statistic ships with its
sample size and is ``None`` below its minimum — a beta from three days is noise,
not a number.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections import defaultdict, deque
from datetime import UTC, datetime, time
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Request

from app.api.desktop import _f, _kv, _orchestrator, _query
from app.config import settings
from app.data_layer.watchlist import entry_key

router = APIRouter(prefix="/api/desktop/insights", tags=["desktop"])

MIN_BARS = 60  # daily returns for vol, beta, risk contribution, historical replay
MIN_ADV_BARS = 20  # daily bars for average dollar volume
MIN_TRADES = 10  # closed round trips, same bar as the Performance page
MIN_BENCH_DAYS = 30  # overlapping daily returns vs SPY, same bar as the Performance page
MIN_CAPTURE_DAYS = 10  # up (or down) SPY days for capture ratios
MIN_EXCESS_DAYS = 5  # cumulative excess return, same bar as PortfolioVsBenchmark
PARTICIPATION = 0.10  # share of daily volume an exit may take
LOOKBACK = 252  # trailing daily returns for vol/beta/covariance
SPY_SHOCKS = (-0.05, -0.10, -0.20)
CRYPTO_SHOCK = -0.30
US_CLOSE = time(19, 55)  # UTC; an intraday-only day counts as closed after this


def _gate(value: float | None, n: int, minimum: int) -> dict[str, Any]:
    ok = n >= minimum and value is not None and math.isfinite(value)
    return {"value": float(value) if ok else None, "n": n, "min": minimum}


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _age_s(value: Any, now: datetime) -> float | None:
    dt = _ts(value)
    return (now - dt).total_seconds() if dt else None


def _is_crypto(p: dict) -> bool:
    return p.get("exchange") == "CRYPTO" or str(p["symbol"]).upper().endswith("-USD")


async def _book() -> tuple[list[dict[str, Any]], float, float]:
    """Open positions with signed market value, plus NAV and USD cash."""
    kv = await _kv()
    cash = _f(await kv.get("horizon:cash:usd"))
    rows = await _query(
        "SELECT symbol, exchange, side, quantity, avg_entry_price, current_price, "
        "unrealized_pnl, realized_pnl, stop_loss_price, created_at, updated_at "
        "FROM positions WHERE quantity != 0 ORDER BY symbol"
    )
    for r in rows:
        qty = _f(r["quantity"])
        short = str(r["side"]).upper() == "SHORT" or qty < 0
        r["qty"] = abs(qty)
        r["short"] = short
        r["price"] = _f(r["current_price"])
        r["mv"] = abs(qty) * r["price"] * (-1 if short else 1)
        r["key"] = entry_key(r["symbol"])
    nav = _f(await kv.get("horizon:portfolio:nav")) or cash + sum(r["mv"] for r in rows)
    return rows, nav, cash


async def _daily_bars(keys: set[str]) -> pd.DataFrame:
    """1d bars (date, key, high, low, close, volume), last bar per key per day."""
    if not keys:
        return pd.DataFrame(columns=["date", "key", "high", "low", "close", "volume"])
    rows = await _query(
        "SELECT symbol, date(timestamp) AS date, high, low, close, volume, max(timestamp) AS ts "
        "FROM ohlcv WHERE timeframe = '1d' AND close IS NOT NULL "
        "GROUP BY symbol, date(timestamp)"
    )
    df = pd.DataFrame(rows, columns=["symbol", "date", "high", "low", "close", "volume", "ts"])
    df["key"] = df["symbol"].map(entry_key)
    df = df[df["key"].isin(keys)].drop_duplicates(["key", "date"], keep="last")
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "key", "high", "low", "close", "volume"]]


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

def _spy_shock(positions: list[dict], shock: float) -> dict[str, float]:
    """P&L of a SPY move through each position's beta; no beta = not modelled."""
    pnl = sum(p["mv"] * p["beta"] * shock for p in positions if p.get("beta") is not None)
    unmodeled = sum(abs(p["mv"]) for p in positions if p.get("beta") is None)
    return {"pnl": pnl, "unmodeled_usd": unmodeled}


def _risk_math(book: list[dict], nav: float, bars: pd.DataFrame) -> dict[str, Any]:
    closes = bars.pivot(index="date", columns="key", values="close").sort_index()
    rets = closes.pct_change(fill_method=None)
    dollar_vol = (bars.assign(dv=bars["close"] * bars["volume"])
                  .pivot(index="date", columns="key", values="dv").sort_index())
    spy = rets["SPY"] if "SPY" in rets else pd.Series(dtype=float)

    for p in book:
        k = p["key"]
        r = rets[k].dropna().tail(LOOKBACK) if k in rets else pd.Series(dtype=float)
        p["bars"] = len(r)
        p["last_bar"] = closes[k].dropna().index.max().date().isoformat() if k in closes else None
        p["vol"] = float(r.std() * math.sqrt(252)) if len(r) >= MIN_BARS else None
        both = pd.concat([r, spy], axis=1, join="inner").dropna()
        var = both.iloc[:, 1].var() if len(both) else 0
        p["beta"] = (float(both.iloc[:, 0].cov(both.iloc[:, 1]) / var)
                     if len(both) >= MIN_BARS and var else None)
        dv = dollar_vol[k].dropna().tail(MIN_ADV_BARS) if k in dollar_vol else pd.Series()
        p["adv_usd"] = float(dv.mean()) if len(dv) >= MIN_ADV_BARS else None
        p["days_to_exit"] = (abs(p["mv"]) / (PARTICIPATION * p["adv_usd"])
                             if p["adv_usd"] else None)

    # ponytail: positions sharing an entry_key would double up in the covariance; the book
    # holds one row per symbol, so it cannot happen today.
    covered = [p for p in book if p["vol"] is not None]
    window = rets[[p["key"] for p in covered]].dropna().tail(LOOKBACK) if covered else None
    port_vol = None
    if window is not None and len(window) >= MIN_BARS and nav > 0:
        cov = window.cov().to_numpy() * 252
        w = np.array([p["mv"] / nav for p in covered])
        var = float(w @ cov @ w)
        port_vol = math.sqrt(var) if var > 0 else None
        if var > 0:
            for p, c in zip(covered, w * (cov @ w) / var, strict=True):
                p["risk_share"] = float(c)

    # Replay the worst day / week of history on today's book (covered positions only).
    replay = None
    if covered:
        hist = closes[[p["key"] for p in covered]].dropna()
        mv = np.array([p["mv"] for p in covered])
        day = hist.pct_change().dropna() @ mv
        week = hist.pct_change(5).dropna() @ mv
        if len(day) >= MIN_BARS:
            replay = {
                "day": {"pnl": float(day.min()), "date": day.idxmin().date().isoformat()},
                "week": {"pnl": float(week.min()), "end": week.idxmin().date().isoformat()},
                "history_from": hist.index.min().date().isoformat(),
                "days": len(day),
            }
    return {
        "port_vol": port_vol,
        "covered_usd": sum(abs(p["mv"]) for p in covered),
        "window_days": 0 if window is None else len(window),
        "replay": replay,
    }


@router.get("/risk")
async def risk() -> dict[str, Any]:
    book, nav, cash = await _book()
    bars = await _daily_bars({p["key"] for p in book} | {"SPY"})
    calc = await asyncio.to_thread(_risk_math, book, nav, bars)

    gross = sum(abs(p["mv"]) for p in book)
    positions, at_stop = [], 0.0
    for p in book:
        stop = _f(p["stop_loss_price"], 0.0) or None
        loss = None
        if stop:
            loss = p["qty"] * ((stop - p["price"]) if p["short"] else (p["price"] - stop))
            at_stop += loss
        positions.append({
            "symbol": p["symbol"],
            "market_value": p["mv"],
            "weight": p["mv"] / nav if nav else None,
            "price": p["price"],
            "stop": stop,
            "stop_distance_pct": (abs(p["price"] - stop) / p["price"] * 100
                                  if stop and p["price"] else None),
            "loss_at_stop": loss,
            "bars": p["bars"],
            "last_bar": p["last_bar"],
            "vol": p["vol"],
            "beta": p["beta"],
            "risk_share": p.get("risk_share"),
            "adv_usd": p["adv_usd"],
            "days_to_exit": p["days_to_exit"],
        })

    scenarios = [
        {"key": f"spy{int(s * 100)}", "label": f"SPY {int(s * 100)}%", **_spy_shock(book, s)}
        for s in SPY_SHOCKS
    ]
    crypto = [p for p in book if _is_crypto(p)]
    scenarios.append({
        "key": "crypto30", "label": f"Crypto {int(CRYPTO_SHOCK * 100)}%",
        "pnl": sum(p["mv"] for p in crypto) * CRYPTO_SHOCK, "unmodeled_usd": 0.0,
    })
    replay = calc["replay"]
    for k, label in (("day", "Worst historical day"), ("week", "Worst historical week")):
        scenarios.append({
            "key": f"worst_{k}", "label": label,
            "pnl": replay[k]["pnl"] if replay else None,
            "unmodeled_usd": gross - calc["covered_usd"],
            "date": replay[k].get("date") or replay[k].get("end") if replay else None,
        })

    weights = sorted((abs(p["mv"]) / gross for p in book), reverse=True) if gross else []
    hhi = sum(w * w for w in weights) if weights else None
    unprotected = [p for p in positions if p["stop"] is None]
    return {
        "nav": nav,
        "cash": cash,
        "cash_pct": cash / nav if nav else None,
        "gross": gross,
        "positions": positions,
        "port_vol": _gate(calc["port_vol"], calc["window_days"], MIN_BARS),
        "risk_covered_usd": calc["covered_usd"],
        "book_beta": {
            "value": (sum(p["mv"] * p["beta"] for p in book if p["beta"] is not None) / nav
                      if nav else None),
            "covered_usd": sum(abs(p["mv"]) for p in book if p["beta"] is not None),
            "min": MIN_BARS,
        },
        "scenarios": scenarios,
        "replay_days": replay["days"] if replay else 0,
        "replay_from": replay["history_from"] if replay else None,
        "stops": {
            "loss_if_all_hit": at_stop,
            "unprotected_count": len(unprotected),
            "unprotected_usd": sum(abs(p["market_value"]) for p in unprotected),
        },
        "concentration": {
            "top1": weights[0] * gross / nav if weights and nav else None,
            "top5": sum(weights[:5]) * gross / nav if weights and nav else None,
            "hhi": hhi,
            "effective_n": 1 / hhi if hhi else None,
            "count": len(book),
        },
        "assumptions": {
            "lookback_days": LOOKBACK, "min_bars": MIN_BARS, "participation": PARTICIPATION,
            "adv_days": MIN_ADV_BARS,
        },
    }


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

def _round_trips(fills: list[dict]) -> tuple[list[dict], list[dict]]:
    """FIFO-match SELL fills against earlier BUY lots. Long-only: a SELL with no
    recorded BUY (a position the broker sync brought in) is returned unmatched."""
    lots: dict[str, deque] = defaultdict(deque)
    closed, unmatched = [], []
    for f in fills:
        sym, qty, px = f["symbol"], _f(f["filled_qty"]), _f(f["fill_price"])
        comm = _f(f["commission"])
        if qty <= 0:
            continue
        if str(f["side"]).upper() == "BUY":
            lots[sym].append([qty, px, f["filled_at"], comm / qty])
            continue
        left, matched, cost, entry_comm, first = qty, 0.0, 0.0, 0.0, None
        while left > 1e-12 and lots[sym]:
            lot = lots[sym][0]
            take = min(left, lot[0])
            cost += take * lot[1]
            entry_comm += take * lot[3]
            matched += take
            first = first or lot[2]
            lot[0] -= take
            left -= take
            if lot[0] <= 1e-12:
                lots[sym].popleft()
        if left > 1e-9:
            unmatched.append({"symbol": sym, "qty": left, "price": px, "filled_at": f["filled_at"]})
        if matched:
            pnl = matched * px - cost - entry_comm - comm * matched / qty
            t0, t1 = _ts(first), _ts(f["filled_at"])
            closed.append({
                "symbol": sym, "qty": matched, "entry_price": cost / matched, "exit_price": px,
                "entry_at": first, "exit_at": f["filled_at"], "pnl": pnl,
                "return_pct": pnl / cost * 100 if cost else None,
                "holding_days": (t1 - t0).total_seconds() / 86400 if t0 and t1 else None,
            })
    return closed, unmatched


def _streak(flags: list[bool], want: bool) -> int:
    best = run = 0
    for f in flags:
        run = run + 1 if f == want else 0
        best = max(best, run)
    return best


def _trade_stats(closed: list[dict]) -> dict[str, Any]:
    n = len(closed)
    pnls = [t["pnl"] for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    def g(value: float | None) -> dict[str, Any]:
        return _gate(value, n, MIN_TRADES)

    return {
        "count": n,
        "win_rate": g(len(wins) / n if n else None),
        "avg_win": g(sum(wins) / len(wins) if wins else None),
        "avg_loss": g(sum(losses) / len(losses) if losses else None),
        "expectancy": g(sum(pnls) / n if n else None),
        "profit_factor": g(sum(wins) / -sum(losses) if losses else None),
        "max_win_streak": g(_streak([p > 0 for p in pnls], True)),
        "max_loss_streak": g(_streak([p < 0 for p in pnls], True)),
        "total_pnl": sum(pnls),
    }


def _excursions(closed: list[dict], bars: pd.DataFrame) -> None:
    """MAE/MFE from daily highs/lows between entry and exit dates, in % of entry."""
    for t in closed:
        t["mae_pct"] = t["mfe_pct"] = None
        k, t0, t1 = entry_key(t["symbol"]), _ts(t["entry_at"]), _ts(t["exit_at"])
        if not (t0 and t1 and t["entry_price"]):
            continue
        b = bars[(bars["key"] == k) & (bars["date"] >= pd.Timestamp(t0.date()))
                 & (bars["date"] <= pd.Timestamp(t1.date()))]
        if len(b):
            t["mae_pct"] = float((b["low"].min() / t["entry_price"] - 1) * 100)
            t["mfe_pct"] = float((b["high"].max() / t["entry_price"] - 1) * 100)


@router.get("/trades")
async def trades() -> dict[str, Any]:
    fills = await _query(
        "SELECT o.symbol, o.side, f.filled_qty, f.fill_price, f.commission, f.filled_at "
        "FROM fills f JOIN orders o ON f.order_id = o.id ORDER BY f.filled_at"
    )
    closed, unmatched = _round_trips(fills)
    bars = await _daily_bars({entry_key(t["symbol"]) for t in closed})
    await asyncio.to_thread(_excursions, closed, bars)

    navs = {r["m"]: _f(r["nav"]) for r in await _query(
        "SELECT strftime('%Y-%m', created_at) AS m, avg(total_value) AS nav "
        "FROM portfolio_snapshots GROUP BY m"
    )}
    months = await _query(
        "SELECT strftime('%Y-%m', filled_at) AS m, sum(filled_qty * fill_price) AS notional, "
        "count(*) AS fills FROM fills GROUP BY m ORDER BY m"
    )
    turnover = [{
        "month": r["m"], "notional": _f(r["notional"]), "fills": r["fills"],
        "avg_nav": navs.get(r["m"]),
        "turnover": _f(r["notional"]) / navs[r["m"]] if navs.get(r["m"]) else None,
    } for r in months]

    book, _, _ = await _book()
    now = datetime.now(UTC)
    open_trades = []
    for p in book:
        # created_at = first time this book recorded the position (a broker sync counts).
        age = _age_s(p["created_at"], now)
        open_trades.append({
            "symbol": p["symbol"], "qty": p["qty"], "short": p["short"],
            "entry_price": _f(p["avg_entry_price"]), "price": p["price"],
            "market_value": p["mv"], "unrealized_pnl": _f(p["unrealized_pnl"]),
            "realized_pnl": _f(p["realized_pnl"]),
            "age_days": age / 86400 if age is not None else None,
        })

    return {
        "closed": closed[::-1],
        "stats": _trade_stats(closed),
        "unmatched_exits": unmatched[::-1],
        "turnover": turnover,
        "open": open_trades,
        "min_trades": MIN_TRADES,
    }


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

def _bench_math(nav: pd.Series, spy: pd.Series) -> dict[str, Any]:
    both = pd.concat([nav.rename("p"), spy.rename("b")], axis=1, join="inner").dropna()
    r = both.pct_change().dropna()
    n = len(r)
    p, b = r["p"], r["b"]
    out: dict[str, Any] = {
        "days": n,
        "window": [both.index.min().date().isoformat(), both.index.max().date().isoformat()]
        if len(both) else None,
    }
    var = b.var() if n > 1 else 0
    beta = p.cov(b) / var if var else None
    active = p - b
    te = active.std() * math.sqrt(252) if n > 1 else None
    up, down = b > 0, b < 0
    out.update({
        "beta": _gate(beta, n, MIN_BENCH_DAYS),
        "alpha": _gate((p.mean() - beta * b.mean()) * 252 if beta is not None else None,
                       n, MIN_BENCH_DAYS),
        "correlation": _gate(p.corr(b) if n > 1 else None, n, MIN_BENCH_DAYS),
        "tracking_error": _gate(te, n, MIN_BENCH_DAYS),
        "information_ratio": _gate(active.mean() * 252 / te if te else None, n, MIN_BENCH_DAYS),
        "up_capture": _gate(p[up].mean() / b[up].mean() if up.any() else None,
                            min(n, int(up.sum())), MIN_CAPTURE_DAYS),
        "down_capture": _gate(p[down].mean() / b[down].mean() if down.any() else None,
                              min(n, int(down.sum())), MIN_CAPTURE_DAYS),
    })
    if len(both) >= 2:
        port_ret = both["p"].iloc[-1] / both["p"].iloc[0] - 1
        bench_ret = both["b"].iloc[-1] / both["b"].iloc[0] - 1
    else:
        port_ret = bench_ret = None
    out["portfolio_return"] = _gate(port_ret, n, MIN_EXCESS_DAYS)
    out["benchmark_return"] = _gate(bench_ret, n, MIN_EXCESS_DAYS)
    out["excess_return"] = _gate(port_ret - bench_ret if port_ret is not None else None,
                                 n, MIN_EXCESS_DAYS)
    return out


@router.get("/benchmark")
async def benchmark() -> dict[str, Any]:
    nav_rows = await _query(
        "SELECT date(created_at) AS d, total_value, max(created_at) AS ts "
        "FROM portfolio_snapshots GROUP BY date(created_at)"
    )
    # SPY close per day: the 1d bar, else the day's last intraday bar (the 1d feed lags).
    spy_rows = await _query(
        "SELECT date(timestamp) AS d, timeframe, close, max(timestamp) AS ts FROM ohlcv "
        "WHERE (symbol = 'SPY' OR symbol LIKE 'SPY.%') AND close IS NOT NULL "
        "GROUP BY date(timestamp), timeframe = '1d'"
    )
    spy: dict[str, float] = {}
    for r in sorted(spy_rows, key=lambda r: r["timeframe"] == "1d"):  # 1d rows sort last, win
        ts = _ts(r["ts"])
        if r["timeframe"] == "1d" or (ts and ts.time() >= US_CLOSE):
            spy[r["d"]] = _f(r["close"])
    nav = pd.Series({pd.Timestamp(r["d"]): _f(r["total_value"]) for r in nav_rows}, dtype=float)
    spy_s = pd.Series({pd.Timestamp(d): v for d, v in spy.items()}, dtype=float)
    out = await asyncio.to_thread(_bench_math, nav.sort_index(), spy_s.sort_index())
    return {
        "symbol": "SPY",
        "nav_days": len(nav),
        "min_days": MIN_BENCH_DAYS,
        "min_capture_days": MIN_CAPTURE_DAYS,
        **out,
    }


# ---------------------------------------------------------------------------
# Costs
# ---------------------------------------------------------------------------

@router.get("/costs")
async def costs() -> dict[str, Any]:
    fees = (await _query(
        "SELECT count(*) AS fills, coalesce(sum(commission), 0) AS commission, "
        "coalesce(sum(slippage), 0) AS slippage, "
        "coalesce(sum(filled_qty * fill_price), 0) AS notional, "
        "sum(CASE WHEN broker = 'ALPACA' THEN 1 ELSE 0 END) AS broker_fills FROM fills"
    ))[0]
    out: dict[str, Any] = {
        "fills": {
            "count": fees["fills"],
            "notional": _f(fees["notional"]),
            "commission": _f(fees["commission"]),
            "slippage": _f(fees["slippage"]),
            # Alpaca fills store slippage 0.0 — no arrival price is captured, so it is unmeasured.
            "slippage_unmeasured": fees["broker_fills"] or 0,
        },
    }

    has_table = await _query(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'llm_usage'"
    )
    if not has_table:
        out["llm"] = {"recorded": False}
        return out

    totals = (await _query(
        "SELECT count(*) AS calls, coalesce(sum(cost_usd), 0) AS cost, "
        "coalesce(sum(input_tokens), 0) AS tin, coalesce(sum(output_tokens), 0) AS tout, "
        "coalesce(sum(estimated), 0) AS est, min(ts) AS first, max(ts) AS last FROM llm_usage"
    ))[0]
    if not totals["calls"]:
        out["llm"] = {"recorded": False}
        return out

    def grouped(col: str) -> str:
        return (f"SELECT {col} AS k, count(*) AS calls, coalesce(sum(cost_usd), 0) AS cost, "
                "coalesce(sum(input_tokens + output_tokens), 0) AS tokens "
                f"FROM llm_usage GROUP BY {col} ORDER BY cost DESC")

    by_day = await _query(grouped("date(ts)"))
    by_agent = await _query(grouped("coalesce(agent_id, 'unknown')"))
    by_model = await _query(grouped("provider || ' / ' || coalesce(model, '?')"))
    by_purpose = await _query(grouped("coalesce(purpose, 'unknown')"))
    span = {"a": str(totals["first"])[:10], "b": str(totals["last"])[:10]}
    debates = (await _query(
        "SELECT count(*) AS n FROM debate_sessions WHERE date(created_at) BETWEEN :a AND :b", span
    ))[0]["n"]
    filled = (await _query(
        "SELECT count(*) AS n FROM orders WHERE status = 'FILLED' "
        "AND date(created_at) BETWEEN :a AND :b", span
    ))[0]["n"]
    debate_cost = sum(_f(r["cost"]) for r in by_purpose if r["k"] == "debate")
    total = _f(totals["cost"])

    def rows(rs: list[dict]) -> list[dict]:
        return [{"key": str(r["k"]), "calls": r["calls"], "cost": _f(r["cost"]),
                 "tokens": int(_f(r["tokens"]))} for r in rs]

    out["llm"] = {
        "recorded": True,
        "calls": totals["calls"],
        "cost": total,
        "input_tokens": int(_f(totals["tin"])),
        "output_tokens": int(_f(totals["tout"])),
        "estimated_calls": int(_f(totals["est"])),
        "first": totals["first"],
        "last": totals["last"],
        "by_day": sorted(rows(by_day), key=lambda r: r["key"]),
        "by_agent": rows(by_agent),
        "by_model": rows(by_model),
        "by_purpose": rows(by_purpose),
        "per_debate": {"value": debate_cost / debates if debates else None, "n": debates},
        "per_filled_order": {"value": total / filled if filled else None, "n": filled},
    }
    return out


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    now = datetime.now(UTC)
    kv = await _kv()
    orch = _orchestrator(request)

    async def newest(sql: str) -> Any:
        rows = await _query(sql)
        return next(iter(rows[0].values())) if rows else None

    bar_rows = await _query(
        "SELECT symbol, timeframe, max(timestamp) AS last FROM ohlcv GROUP BY symbol, timeframe"
    )
    held = {entry_key(r["symbol"]) for r in await _query(
        "SELECT symbol FROM positions WHERE quantity != 0"
    )}
    per_symbol: dict[str, dict[str, Any]] = {}
    for r in bar_rows:
        k = entry_key(r["symbol"])
        row = per_symbol.setdefault(k, {"symbol": k, "held": k in held,
                                        "last_daily": None, "last_intraday": None})
        col = "last_daily" if r["timeframe"] == "1d" else "last_intraday"
        if row[col] is None or str(r["last"]) > str(row[col]):
            row[col] = r["last"]
    for k in held - set(per_symbol):
        per_symbol[k] = {"symbol": k, "held": True, "last_daily": None, "last_intraday": None}
    for row in per_symbol.values():
        row["daily_age_s"] = _age_s(row["last_daily"], now)
        row["intraday_age_s"] = _age_s(row["last_intraday"], now)

    feeds_src = [
        ("Daily bars", "SELECT max(timestamp) FROM ohlcv WHERE timeframe = '1d'", 4 * 86400),
        ("Intraday bars", "SELECT max(timestamp) FROM ohlcv WHERE timeframe != '1d'", 600),
        ("Position marks", "SELECT max(updated_at) FROM positions WHERE quantity != 0", 120),
        ("Portfolio snapshot", "SELECT max(created_at) FROM portfolio_snapshots", 300),
        ("Risk snapshot", "SELECT max(created_at) FROM risk_metrics", 120),
        ("Performance snapshot", "SELECT max(created_at) FROM performance_snapshots", 1800),
        ("Agent heartbeat", "SELECT max(last_heartbeat) FROM agent_states", 60),
    ]
    feeds = []
    for name, sql, stale_after in feeds_src:
        last = await newest(sql)
        feeds.append({"name": name, "last": last, "age_s": _age_s(last, now),
                      "stale_after_s": stale_after})

    from app.llm.provider_registry import provider_registry

    failing = await _query(
        "SELECT title, message, payload, created_at, acknowledged FROM alert_history "
        "WHERE rule_name = 'llm_provider_failing' ORDER BY created_at DESC LIMIT 20"
    )
    failures = []
    for a in failing:
        try:
            payload = json.loads(a["payload"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        failures.append({"provider": payload.get("provider"), "error": payload.get("error_class"),
                         "message": a["message"], "at": a["created_at"],
                         "acknowledged": bool(a["acknowledged"])})
    last_ok: dict[str, Any] = {}
    if await _query("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'llm_usage'"):
        last_ok = {r["provider"]: r["last"] for r in await _query(
            "SELECT provider, max(ts) AS last FROM llm_usage GROUP BY provider"
        )}

    if orch:
        agents = [{"agent_id": aid, "status": s.get("status"), "restarts": s.get("retries", 0),
                   "last_heartbeat": s.get("last_heartbeat"),
                   "age_s": _age_s(s.get("last_heartbeat"), now)}
                  for aid, s in orch.get_agent_statuses().items()]
        workers = [{"name": n, "status": s.get("status"), "restarts": s.get("restarts", 0)}
                   for n, s in orch.get_worker_statuses().items()]
    else:
        agents = [{"agent_id": r["agent_id"], "status": r["status"], "restarts": None,
                   "last_heartbeat": r["last_heartbeat"],
                   "age_s": _age_s(r["last_heartbeat"], now), "error": r["error_message"]}
                  for r in await _query(
                      "SELECT agent_id, status, last_heartbeat, error_message FROM agent_states "
                      "ORDER BY agent_id")]
        workers = []

    alerts = await _query(
        "SELECT severity, count(*) AS n, max(created_at) AS last FROM alert_history "
        "WHERE acknowledged = 0 GROUP BY severity"
    )
    return {
        "now": now.isoformat(),
        "engine": {
            "running": bool(orch),
            "mode": await kv.get("horizon:system:mode") or settings.system_mode.value,
            "halted": (await kv.get("horizon:system:halted")) == "1",
            "kill_switch": (await kv.get("horizon:system:kill_switch")) == "1",
        },
        "feeds": feeds,
        "symbols": sorted(per_symbol.values(), key=lambda r: (not r["held"], r["symbol"])),
        "llm": {
            "configured": provider_registry.list_available(),
            "failures": failures,
            "last_logged_call": last_ok,
        },
        "agents": agents,
        "workers": workers,
        "agents_live": bool(orch),
        "unacked_alerts": {r["severity"]: {"count": r["n"], "last": r["last"]} for r in alerts},
    }
