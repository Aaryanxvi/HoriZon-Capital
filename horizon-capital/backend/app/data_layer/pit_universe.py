# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-9D08BB452271
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Point-in-time S&P 500 membership (free — fja05680/sp500 dataset).

Fixes the UNIVERSE half of survivorship bias: at each past date we know which
tickers were ACTUALLY in the index then, instead of ranking today's winners.

HONEST residual gap: this gives historical membership, but yfinance has no daily
PRICES for names that have since delisted — those silently drop out. So this is a
PARTIAL fix (correct universe, minus the names that died). The full fix needs a
paid survivorship-free price vendor (Sharadar/Norgate). Still, it removes the
worst of the bias — we no longer rank only the post-hoc mega-cap winners.
"""
from __future__ import annotations

import urllib.parse
from pathlib import Path

import pandas as pd

from app.core.logging import get_logger

logger = get_logger("data.pit_universe")

_FILE = "S&P 500 Historical Components & Changes (Updated).csv"
_URL = "https://raw.githubusercontent.com/fja05680/sp500/master/" + urllib.parse.quote(_FILE)
_CACHE = Path.home() / ".horizon-capital" / "sp500_pit_membership.csv"

_df: pd.DataFrame | None = None


def _load() -> pd.DataFrame:
    """Load the change-log (date, tickers), cached to disk after first download."""
    global _df
    if _df is not None:
        return _df
    if _CACHE.exists():
        df = pd.read_csv(_CACHE)
    else:
        df = pd.read_csv(_URL)
        try:
            _CACHE.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(_CACHE, index=False)
            logger.info("pit_membership_cached", path=str(_CACHE), rows=len(df))
        except Exception as exc:
            logger.warning("pit_cache_write_failed", error=str(exc))
    df["date"] = pd.to_datetime(df["date"])
    _df = df.sort_values("date").reset_index(drop=True)
    return _df


def _tickers(row_value: str) -> set[str]:
    # Normalize to yfinance form (BRK.B -> BRK-B).
    return {t.strip().replace(".", "-") for t in str(row_value).split(",") if t.strip()}


def members_on(date) -> set[str]:
    """Index membership as of ``date`` (the last change-row at or before it)."""
    df = _load()
    sub = df[df["date"] <= pd.Timestamp(date)]
    if sub.empty:
        return set()
    return _tickers(sub.iloc[-1]["tickers"])


def union_members(start, end) -> set[str]:
    """Every ticker that was a member at any point in [start, end]."""
    df = _load()
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    out = members_on(s)
    for _, r in df[(df["date"] >= s) & (df["date"] <= e)].iterrows():
        out |= _tickers(r["tickers"])
    return out


def _demo() -> None:
    m2015 = members_on("2015-06-01")
    assert 480 <= len(m2015) <= 520, f"unexpected 2015 membership: {len(m2015)}"
    assert "AAPL" in m2015
    u = union_members("2018-01-01", "2024-01-01")
    # Union must exceed any single date's membership (names entered AND left).
    assert len(u) > len(members_on("2024-01-01"))
    print(f"pit_universe demo OK: 2015={len(m2015)} members, "
          f"2018-2024 union={len(u)} names (incl. ones that later left)")


if __name__ == "__main__":
    _demo()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 9D08BB452271 - verify with scripts/authorship.py verify
