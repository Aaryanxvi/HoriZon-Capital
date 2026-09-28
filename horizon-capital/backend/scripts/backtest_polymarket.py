# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-18BBA66639CE
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Standalone backtest of PolymarketMomentumSleeve against real CLOB history.

Discovers resolved Polymarket markets (Gamma API), pulls each market's YES-token
daily probability history (CLOB prices-history), and replays the sleeve's own
compute() rule day by day. This is NOT a gate pass — see the caveats block
printed at the end. Pre-register a proper gate (scripts/validate_*.py pattern)
before flipping POLYMARKET_SLEEVE_ENABLED.

Usage:
    python -m scripts.backtest_polymarket [--slugs a,b,c] [--top 50] [--days 365]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agents.front_office.strategy.sleeves.polymarket_momentum import (  # noqa: E402
    PolymarketMomentumSleeve,
)

_GAMMA_URL = "https://gamma-api.polymarket.com/markets"
_HISTORY_URL = "https://clob.polymarket.com/prices-history"
_RETURN_CAP = 0.50  # cap daily |return| at 50% — probabilities near 0/1 blow up pct returns
TRADING_DAYS = 365


async def discover_markets(client: httpx.AsyncClient, top: int) -> list[dict]:
    """Resolved markets, highest volume first (survivorship-lite: outcomes known).

    Returns the raw Gamma market dicts (token IDs inline) — a second per-slug
    Gamma lookup is flaky (some resolved slugs 404/empty on ?slug= even though
    they appear in the list response), so we keep what discovery already gave us.
    """
    resp = await client.get(
        _GAMMA_URL,
        params={"closed": "true", "limit": top, "order": "volumeNum", "ascending": "false"},
    )
    markets = resp.json()
    if not isinstance(markets, list) or not markets:
        # Fallback: order param rejected — fetch a larger page, sort client-side.
        resp = await client.get(_GAMMA_URL, params={"closed": "true", "limit": 500})
        markets = resp.json()
        markets = sorted(markets, key=lambda m: float(m.get("volumeNum") or 0), reverse=True)
    return [m for m in markets if m.get("slug")][:top]


async def market_by_slug(client: httpx.AsyncClient, slug: str) -> dict | None:
    resp = await client.get(_GAMMA_URL, params={"slug": slug})
    markets = resp.json()
    return markets[0] if markets else None


def yes_token_id(market: dict) -> str | None:
    outcomes = market.get("outcomes", [])
    token_ids = market.get("clobTokenIds", [])
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    if isinstance(token_ids, str):
        token_ids = json.loads(token_ids)
    yes_idx = next((i for i, o in enumerate(outcomes) if str(o).lower() == "yes"), 0)
    return token_ids[yes_idx] if yes_idx < len(token_ids) else None


async def fetch_history(client: httpx.AsyncClient, token_id: str) -> pd.Series | None:
    resp = await client.get(
        _HISTORY_URL, params={"market": token_id, "interval": "max", "fidelity": 1440}
    )
    history = resp.json().get("history", [])
    if not history:
        return None
    idx = pd.to_datetime([h["t"] for h in history], unit="s").normalize()
    s = pd.Series([float(h["p"]) for h in history], index=idx)
    return s[~s.index.duplicated(keep="last")].sort_index()


def simulate_market(prob: pd.Series, days: int) -> pd.Series | None:
    """Walk the sleeve's own compute() day by day; return daily P&L series."""
    prob = prob.iloc[-days:] if len(prob) > days else prob
    if len(prob) < PolymarketMomentumSleeve._MOM_DAYS + 2:
        return None

    df = pd.DataFrame(
        {"open": prob, "high": prob, "low": prob, "close": prob, "volume": 0.0}
    )
    sleeve = PolymarketMomentumSleeve()
    bars = {"MKT.POLY": df}

    rets = []
    position = 0.0
    for i in range(len(prob) - 1):
        as_of = prob.index[i]
        signals = sleeve.compute(bars, as_of)
        position = signals[0].target_weight if signals else 0.0

        p_t, p_next = prob.iloc[i], prob.iloc[i + 1]
        day_ret = (p_next / p_t - 1.0) if p_t > 0 else 0.0
        day_ret = float(np.clip(day_ret, -_RETURN_CAP, _RETURN_CAP))
        rets.append(position * day_ret)

    return pd.Series(rets, index=prob.index[1:])


def aggregate_metrics(all_rets: list[pd.Series]) -> dict:
    combined = pd.concat(all_rets, axis=1).fillna(0.0).sum(axis=1) if all_rets else pd.Series(
        dtype=float
    )
    if combined.empty:
        return {"total_return": 0.0, "sharpe": 0.0, "max_dd": 0.0, "hit_rate": 0.0}

    equity = (1 + combined).cumprod()
    total_return = equity.iloc[-1] - 1.0
    vol = combined.std() * np.sqrt(TRADING_DAYS)
    sharpe = (combined.mean() * TRADING_DAYS) / vol if vol > 0 else 0.0
    dd = ((equity - equity.cummax()) / equity.cummax()).min()
    traded = combined[combined != 0.0]
    hit_rate = (traded > 0).mean() if len(traded) else 0.0
    return {
        "total_return": round(total_return * 100, 2),
        "sharpe": round(sharpe, 2),
        "max_dd": round(dd * 100, 2),
        "hit_rate": round(hit_rate * 100, 1),
    }


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--slugs", default="", help="comma-separated market slugs")
    p.add_argument("--top", type=int, default=50)
    p.add_argument("--days", type=int, default=365)
    args = p.parse_args()

    async with httpx.AsyncClient(timeout=20.0) as client:
        requested = [s.strip() for s in args.slugs.split(",") if s.strip()]
        if requested:
            markets = [m for s in requested if (m := await market_by_slug(client, s))]
        else:
            markets = await discover_markets(client, args.top)
        print(f"Discovered {len(markets)} markets")

        market_rets: list[pd.Series] = []
        per_market: list[tuple[str, float]] = []
        for market in markets:
            slug = market["slug"]
            try:
                token_id = yes_token_id(market)
                if not token_id:
                    continue
                prob = await fetch_history(client, token_id)
                if prob is None:
                    continue
                rets = simulate_market(prob, args.days)
                if rets is None or rets.abs().sum() == 0:
                    continue
                market_rets.append(rets)
                per_market.append((slug, float((1 + rets).prod() - 1.0)))
            except Exception as exc:
                print(f"  skip {slug}: {exc}")

    print(f"\nTraded {len(per_market)}/{len(markets)} markets:")
    for slug, ret in sorted(per_market, key=lambda x: -x[1])[:10]:
        print(f"  {slug:50s} {ret * 100:+7.2f}%")

    m = aggregate_metrics(market_rets)
    print("\n========== AGGREGATE ==========")
    print(f"Total return:     {m['total_return']:+.2f}%")
    print(f"Ann. Sharpe:      {m['sharpe']:.2f}")
    print(f"Max drawdown:     {m['max_dd']:.2f}%")
    print(f"Hit rate:         {m['hit_rate']:.1f}%")
    print(f"Markets traded:   {len(per_market)}")
    print("================================\n")
    print(
        "CAVEATS: midpoint fills (no spread), zero fees, resolved-market discovery\n"
        "= survivorship-lite, single parameter set, daily returns capped at "
        f"+/-{_RETURN_CAP:.0%} — NOT a gate pass.\n"
        "Pre-register a gate before enabling the sleeve."
    )


if __name__ == "__main__":
    asyncio.run(main())
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 18BBA66639CE - verify with scripts/authorship.py verify
