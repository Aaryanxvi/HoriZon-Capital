"""Desktop analysis API — "what is making or losing money, and why". LOCAL SQLite only.

Mounted at ``/api/desktop/analysis``. Same rules as ``api/desktop_viz.py``: raw
read-only SQL over the tables the terminal writes, never a write.

Every aggregate ships its sample size. Below its minimum the value is ``None``
(the UI shows "needs N"), never a number computed from one or two points.
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from typing import Any

import pandas as pd
from fastapi import APIRouter

from app.api.desktop import _f, _query
from app.data_layer.watchlist import entry_key

router = APIRouter(prefix="/api/desktop/analysis", tags=["desktop"])

MIN_SAMPLE = 5  # means / hit rates / approval rates
MIN_OVERLAP = 20  # beta and correlation need this many overlapping daily returns
HORIZONS = (1, 5, 20)  # trading days
US_CLOSE = time(19, 55)  # UTC; an intraday-only day counts as closed after this
MAX_QUOTE_AGE = timedelta(minutes=5)  # execution reference bar must be this fresh

VOTES = ("FOR", "AGAINST", "ABSTAIN", "ERROR")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value))


def _stat(values: list[float], minimum: int = MIN_SAMPLE) -> dict[str, Any]:
    """Mean with its sample size; None below the minimum."""
    n = len(values)
    return {"value": sum(values) / n if n >= minimum else None, "n": n, "min": minimum}


def _rate(hits: int, n: int, minimum: int = MIN_SAMPLE) -> dict[str, Any]:
    return {"value": hits / n if n >= minimum else None, "n": n, "min": minimum}


def _asset_class(symbol: str, catalog_row: dict | None) -> str:
    s = symbol.upper()
    if s.endswith(".POLY"):
        return "prediction"
    if s.endswith("-USD") or (catalog_row or {}).get("asset_class") == "crypto":
        return "crypto"
    return "etf" if (catalog_row or {}).get("etf") else "equity"


# Signals are stored as the aggregated "sleeve_system", so the sleeve is not
# recorded per order. Only crypto_trend trades crypto and only polymarket_momentum
# trades .POLY; every equity sleeve shares the same universe and cannot be split.
_SLEEVE_BY_CLASS = {
    "crypto": "crypto_trend",
    "prediction": "polymarket_momentum",
    "etf": "equity sleeves",
    "equity": "equity sleeves",
}


async def _catalog() -> Any:
    """Catalog lookup (sector, ETF flag); enrichment only, never fatal."""
    from app.data_layer import watchlist as wl

    try:
        await wl.load_catalog()
    except Exception:  # noqa: BLE001 — enrichment
        pass
    return wl.lookup


async def _daily_closes() -> dict[str, pd.Series]:
    """Close per symbol key per day: 1d bars, else the last intraday bar of a
    day that reached the US close. Keyed by `entry_key` (SPY.NYSE == SPY)."""
    daily = await _query(
        "SELECT symbol, date(timestamp) AS d, close, max(timestamp) AS ts FROM ohlcv "
        "WHERE timeframe = '1d' AND close IS NOT NULL GROUP BY symbol, date(timestamp)"
    )
    intraday = await _query(
        "SELECT symbol, date(timestamp) AS d, close, max(timestamp) AS ts FROM ohlcv "
        "WHERE timeframe != '1d' AND close IS NOT NULL GROUP BY symbol, date(timestamp)"
    )
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for r in daily:
        out[entry_key(r["symbol"])][r["d"]] = _f(r["close"])
    for r in intraday:
        key, day = entry_key(r["symbol"]), r["d"]
        if day not in out[key] and _ts(r["ts"]).time() >= US_CLOSE:
            out[key][day] = _f(r["close"])
    return {
        k: pd.Series(list(v.values()), index=pd.to_datetime(list(v))).sort_index()
        for k, v in out.items() if v
    }


def _forward(closes: pd.Series | None, at: str, days: int, direction: int) -> float | None:
    """Direction-adjusted return from the first close after `at` to `days` closes later."""
    if closes is None or closes.empty:
        return None
    t = _ts(at)
    # A signal after the close enters at the next day's close.
    start = pd.Timestamp(t.date()) + pd.Timedelta(days=int(t.time() >= US_CLOSE))
    i = int(closes.index.searchsorted(start))
    if i + days >= len(closes):
        return None
    entry, exit_ = closes.iloc[i], closes.iloc[i + days]
    return float(exit_ / entry - 1) * direction if entry else None


def _last_close(closes: dict[str, pd.Series]) -> str | None:
    """Latest day any symbol has a close — forward returns cannot reach past it."""
    last = max((c.index[-1] for c in closes.values()), default=None)
    return last.date().isoformat() if last is not None else None


def _forward_block(rets: dict[int, list[float]]) -> dict[str, Any]:
    return {
        f"{h}d": {
            "avg": _stat(rets[h]),
            "hit_rate": _rate(sum(r > 0 for r in rets[h]), len(rets[h])),
        }
        for h in HORIZONS
    }


# ---------------------------------------------------------------------------
# 1. P&L attribution
# ---------------------------------------------------------------------------

@router.get("/pnl")
async def pnl() -> dict[str, Any]:
    lookup = await _catalog()
    positions = await _query(
        "SELECT symbol, side, quantity, avg_entry_price, current_price, "
        "unrealized_pnl, realized_pnl FROM positions"
    )
    snaps = await _query(
        "SELECT total_value, created_at FROM portfolio_snapshots ORDER BY created_at"
    )
    # Contribution is measured against the first recorded NAV.
    base = _f(snaps[0]["total_value"]) if snaps else 0.0
    nav = _f(snaps[-1]["total_value"]) if snaps else 0.0

    rows, sleeves = [], defaultdict(lambda: {"realized": 0.0, "unrealized": 0.0, "positions": 0})
    for p in positions:
        cls = _asset_class(p["symbol"], lookup(p["symbol"]))
        sleeve = _SLEEVE_BY_CLASS[cls]
        realized, unrealized = _f(p["realized_pnl"]), _f(p["unrealized_pnl"])
        rows.append({
            "symbol": p["symbol"],
            "asset_class": cls,
            "sleeve": sleeve,
            "open": abs(_f(p["quantity"])) > 0,
            "realized": realized,
            "unrealized": unrealized,
            "total": realized + unrealized,
            "contribution": (realized + unrealized) / base if base else None,
        })
        s = sleeves[sleeve]
        s["realized"] += realized
        s["unrealized"] += unrealized
        s["positions"] += 1
    rows.sort(key=lambda r: r["total"])
    explained = sum(r["total"] for r in rows)
    return {
        "base_nav": base or None,
        "base_at": snaps[0]["created_at"] if snaps else None,
        "nav": nav or None,
        "nav_change": nav - base if snaps else None,
        "explained": explained,
        # Fees, closed rows the positions table no longer holds, cash moves.
        "unexplained": (nav - base - explained) if snaps else None,
        "positions": rows,
        "sleeves": sorted(
            (
                {
                    "sleeve": k,
                    **v,
                    "total": v["realized"] + v["unrealized"],
                    "contribution": (v["realized"] + v["unrealized"]) / base if base else None,
                }
                for k, v in sleeves.items()
            ),
            key=lambda r: r["total"],
        ),
        "attribution": "asset_class",
    }


# ---------------------------------------------------------------------------
# 2. Exposure & correlation
# ---------------------------------------------------------------------------

def _beta(asset: pd.Series, market: pd.Series) -> dict[str, Any]:
    both = pd.concat([asset, market], axis=1, join="inner").dropna()
    n = len(both)
    if n < MIN_OVERLAP:
        return {"value": None, "n": n, "min": MIN_OVERLAP}
    var = both.iloc[:, 1].var()
    return {"value": float(both.iloc[:, 0].cov(both.iloc[:, 1]) / var) if var else None,
            "n": n, "min": MIN_OVERLAP}


def _exposure_math(
    holdings: list[dict], closes: dict[str, pd.Series], nav_daily: pd.Series
) -> dict[str, Any]:
    spy = closes.get("SPY")
    spy_ret = spy.pct_change().dropna() if spy is not None else pd.Series(dtype=float)
    rets = {
        h["symbol"]: closes[h["key"]].pct_change().dropna()
        for h in holdings if h["key"] in closes
    }
    for h in holdings:
        r = rets.get(h["symbol"])
        h["beta"] = _beta(r if r is not None else pd.Series(dtype=float), spy_ret)
        h.pop("key")

    symbols = [h["symbol"] for h in holdings]
    matrix, counts = [], []
    for a in symbols:
        row, nrow = [], []
        for b in symbols:
            ra, rb = rets.get(a), rets.get(b)
            if ra is None or rb is None:
                row.append(None)
                nrow.append(0)
                continue
            both = pd.concat([ra, rb], axis=1, join="inner").dropna()
            n = len(both)
            c = both.iloc[:, 0].corr(both.iloc[:, 1]) if n >= MIN_OVERLAP else None
            row.append(None if c is None or pd.isna(c) else float(c))
            nrow.append(n)
        matrix.append(row)
        counts.append(nrow)

    return {
        "holdings": holdings,
        "book_beta": _beta(nav_daily.pct_change().dropna(), spy_ret),
        "correlation": {"symbols": symbols, "matrix": matrix, "n": counts, "min": MIN_OVERLAP},
    }


@router.get("/exposure")
async def exposure() -> dict[str, Any]:
    lookup = await _catalog()
    positions = await _query(
        "SELECT symbol, side, quantity, current_price FROM positions WHERE quantity != 0"
    )
    nav_rows = await _query(
        "SELECT date(created_at) AS d, total_value, max(created_at) AS ts "
        "FROM portfolio_snapshots GROUP BY date(created_at) ORDER BY d"
    )
    nav = _f(nav_rows[-1]["total_value"]) if nav_rows else 0.0
    closes = await _daily_closes()

    holdings = []
    for p in positions:
        row = lookup(p["symbol"])
        sign = -1 if str(p["side"]).upper() == "SHORT" else 1
        value = sign * abs(_f(p["quantity"])) * _f(p["current_price"])
        holdings.append({
            "symbol": p["symbol"],
            "key": entry_key(p["symbol"]),
            "asset_class": _asset_class(p["symbol"], row),
            "sector": (row or {}).get("sector"),
            "value": value,
            "weight": value / nav if nav else None,
        })

    by_class: Counter[str] = Counter()
    by_sector: Counter[str] = Counter()
    for h in holdings:
        by_class[h["asset_class"]] += h["value"]
        by_sector[h["sector"] or "Unknown"] += h["value"]

    nav_daily = pd.Series(
        {pd.Timestamp(r["d"]): _f(r["total_value"]) for r in nav_rows}, dtype=float
    )
    math = await asyncio.to_thread(_exposure_math, holdings, closes, nav_daily)
    return {
        "nav": nav or None,
        "gross": sum(abs(h["value"]) for h in holdings),
        "net": sum(h["value"] for h in holdings),
        "by_asset_class": [{"name": k, "value": v} for k, v in by_class.most_common()],
        "by_sector": [{"name": k, "value": v} for k, v in by_sector.most_common()],
        **math,
    }


# ---------------------------------------------------------------------------
# 3. Debate analytics
# ---------------------------------------------------------------------------

def _debate_math(sessions: list[dict], args: list[dict], closes: dict[str, pd.Series]) -> dict:
    # Approval rate per day.
    days: dict[str, Counter] = defaultdict(Counter)
    for s in sessions:
        days[str(s["created_at"])[:10]][s["final_decision"] or "UNKNOWN"] += 1
    by_day = []
    for day in sorted(days):
        c = days[day]
        total = sum(c.values())
        by_day.append({
            "date": day,
            "approved": c["APPROVED"],
            "rejected": c["REJECTED"],
            "other": total - c["APPROVED"] - c["REJECTED"],
            "rate": _rate(c["APPROVED"], total),
        })
    approved = sum(d["approved"] for d in by_day)

    # Votes by the role argued ("STRATEGY (as RISK)" argues RISK) and by provider.
    by_role: dict[str, Counter] = defaultdict(Counter)
    by_provider: dict[str, Counter] = defaultdict(Counter)
    seats: dict[tuple[str, str], dict[int, str]] = defaultdict(dict)
    for a in args:
        role = str(a["role"] or "?")
        seat, _, played = role.partition(" (as ")
        vote = str(a["vote"] or "ERROR").upper()
        by_role[(played.rstrip(")") or seat).upper()][vote] += 1
        by_provider[str(a["agent_id"] or "?")][vote] += 1
        seats[(a["session_id"], seat.upper())][int(a["round_number"] or 1)] = vote

    # Round-2 flip: the same seat went FOR <-> AGAINST between rounds.
    pairs = flips = 0
    for rounds in seats.values():
        r1, r2 = rounds.get(1), rounds.get(2)
        if r1 in ("FOR", "AGAINST") and r2 in ("FOR", "AGAINST"):
            pairs += 1
            flips += r1 != r2

    # Did approved vs rejected trades go on to make money?
    outcome: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    rows = []
    for s in sessions:
        direction = -1 if str(s["proposed_action"]).upper() == "SELL" else 1
        series = closes.get(entry_key(s["symbol"]))
        fwd = {h: _forward(series, s["created_at"], h, direction) for h in HORIZONS}
        decision = s["final_decision"] or "UNKNOWN"
        for h, r in fwd.items():
            if r is not None:
                outcome[decision][h].append(r)
        rows.append({
            "id": s["id"],
            "symbol": s["symbol"],
            "action": s["proposed_action"],
            "decision": decision,
            "created_at": s["created_at"],
            **{f"fwd_{h}d": fwd[h] for h in HORIZONS},
        })

    def counts(groups: dict[str, Counter]) -> list[dict]:
        return [{"name": k, **{v.lower(): groups[k][v] for v in VOTES}} for k in sorted(groups)]

    return {
        "total": len(sessions),
        "approval_rate": _rate(approved, len(sessions)),
        "by_day": by_day,
        "by_role": counts(by_role),
        "by_provider": counts(by_provider),
        "round2_flips": {**_rate(flips, pairs), "flips": flips},
        "outcome": {k: _forward_block(v) for k, v in sorted(outcome.items())},
        "sessions": rows,
        "last_close": _last_close(closes),
    }


@router.get("/debates")
async def debates() -> dict[str, Any]:
    sessions = await _query(
        "SELECT id, symbol, proposed_action, final_decision, created_at "
        "FROM debate_sessions WHERE status = 'COMPLETED' ORDER BY created_at"
    )
    args = await _query(
        "SELECT session_id, agent_id, role, vote, round_number FROM debate_arguments"
    )
    closes = await _daily_closes()
    return await asyncio.to_thread(_debate_math, sessions, args, closes)


# ---------------------------------------------------------------------------
# 4. Signal quality
# ---------------------------------------------------------------------------

@router.get("/signals")
async def signals() -> dict[str, Any]:
    lookup = await _catalog()
    rows = await _query("SELECT symbol, direction, created_at FROM signals ORDER BY created_at")
    closes = await _daily_closes()

    def math() -> list[dict]:
        groups: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
        count: Counter[str] = Counter()
        for r in rows:
            sleeve = _SLEEVE_BY_CLASS[_asset_class(r["symbol"], lookup(r["symbol"]))]
            count[sleeve] += 1
            direction = -1 if str(r["direction"]).upper() in ("SELL", "-1") else 1
            series = closes.get(entry_key(r["symbol"]))
            for h in HORIZONS:
                fwd = _forward(series, r["created_at"], h, direction)
                if fwd is not None:
                    groups[sleeve][h].append(fwd)
        return [
            {"sleeve": k, "signals": count[k], **_forward_block(groups[k])}
            for k in sorted(count)
        ]

    return {
        "sleeves": await asyncio.to_thread(math),
        "attribution": "asset_class",
        "last_close": _last_close(closes),
    }


# ---------------------------------------------------------------------------
# 5. Execution quality
# ---------------------------------------------------------------------------

async def _quote_at(symbol: str, at: str | None) -> float | None:
    """Last intraday close at or before `at`, if no older than MAX_QUOTE_AGE."""
    if not at:
        return None
    key = entry_key(symbol)
    rows = await _query(
        "SELECT symbol, close, timestamp FROM ohlcv WHERE timeframe != '1d' "
        "AND (symbol = :key OR symbol LIKE :key || '.%') AND timestamp <= :at "
        "ORDER BY timestamp DESC LIMIT 1",
        {"key": key, "at": str(at)},
    )
    if not rows or _ts(at) - _ts(rows[0]["timestamp"]) > MAX_QUOTE_AGE:
        return None
    return _f(rows[0]["close"]) or None


@router.get("/execution")
async def execution() -> dict[str, Any]:
    fills = await _query(
        "SELECT f.fill_price, f.filled_qty, f.filled_at, f.broker AS fill_broker, "
        "o.symbol, o.side, o.broker, o.created_at AS order_at, s.created_at AS signal_at "
        "FROM fills f JOIN orders o ON o.id = f.order_id "
        "LEFT JOIN signals s ON s.signal_id = o.signal_id ORDER BY f.filled_at"
    )
    rows = []
    by_broker: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for f in fills:
        sign = -1 if str(f["side"]).upper() == "SELL" else 1
        price = _f(f["fill_price"])
        broker = f["fill_broker"] or f["broker"] or "?"
        out = {
            "symbol": f["symbol"], "side": f["side"], "broker": broker,
            "filled_at": f["filled_at"], "fill_price": price,
        }
        # Positive bps = paid more than the reference (a cost) on either side.
        for name, at in (("arrival", f["order_at"]), ("decision", f["signal_at"])):
            ref = await _quote_at(f["symbol"], at)
            bps = sign * (price / ref - 1) * 1e4 if ref and price else None
            out[f"{name}_price"] = ref
            out[f"{name}_bps"] = bps
            if bps is not None:
                by_broker[broker][name].append(bps)
        rows.append(out)

    brokers = sorted({r["broker"] for r in rows})
    return {
        "fills": rows,
        "by_broker": [
            {
                "broker": b,
                "fills": sum(r["broker"] == b for r in rows),
                "arrival_bps": _stat(by_broker[b]["arrival"]),
                "decision_bps": _stat(by_broker[b]["decision"]),
            }
            for b in brokers
        ],
        "max_quote_age_s": int(MAX_QUOTE_AGE.total_seconds()),
    }
