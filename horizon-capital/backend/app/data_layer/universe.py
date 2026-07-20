"""Dynamic trading universe — current liquid US equities, not a hardcoded list.

Pulls current S&P 500 constituents (the liquid, actually-tradeable universe) so
the breadth engine ranks the whole market instead of a fixed handful. Falls back
to a bundled liquid list if the live fetch fails (offline / source down), so the
system always runs.

NOTE: current constituents is correct for LIVE trading — you can only buy what's
investable today. Backtests need point-in-time membership (incl. names that later
left the index) to avoid survivorship bias — that's a separate, still-open piece.
"""
from __future__ import annotations

import time

from app.core.logging import get_logger

logger = get_logger("data.universe")

# Anchor names referenced by exact suffix in research_stack / trend / momentum
# sleeves — always present so those sleeves keep finding their universe.
_ANCHORS = [
    "SPY.NYSE", "QQQ.NASDAQ", "TLT.NASDAQ", "GLD.NYSE",
    "AAPL.NASDAQ", "MSFT.NASDAQ", "NVDA.NASDAQ", "GOOGL.NASDAQ", "AMZN.NASDAQ", "META.NASDAQ",
    "TSLA.NASDAQ", "AVGO.NASDAQ", "NFLX.NASDAQ", "COST.NASDAQ", "ORCL.NYSE",
    "V.NYSE", "MA.NYSE", "JPM.NYSE", "UNH.NYSE", "LLY.NYSE",
    "XOM.NYSE", "XLE.NYSE", "XLK.NYSE", "XLF.NYSE", "XLV.NYSE", "XLY.NYSE", "XLI.NYSE",
    "JNJ.NYSE", "ABBV.NYSE", "MRK.NYSE", "PG.NYSE", "KO.NYSE", "WMT.NYSE", "HD.NYSE",
    "CAT.NYSE", "CVX.NYSE",
]

# Liquid extras used only if the live S&P 500 fetch fails — keeps breadth >> the
# anchor set even offline. Base tickers; suffixed to ".US" by get_universe.
_FALLBACK_EXTRA = [
    "ADBE", "CRM", "AMD", "INTC", "CSCO", "QCOM", "TXN", "IBM", "NOW", "INTU", "MU", "AMAT",
    "BAC", "WFC", "GS", "MS", "C", "BLK", "SCHW", "AXP", "SPGI", "CB", "PGR",
    "PFE", "TMO", "ABT", "DHR", "BMY", "AMGN", "GILD", "ISRG",
    "PEP", "MCD", "NKE", "SBUX", "LOW", "TGT", "MDLZ", "EL", "CL",
    "BA", "HON", "UNP", "GE", "LMT", "RTX", "DE", "EMR", "ETN",
    "COP", "SLB", "EOG", "PSX", "DIS", "CMCSA", "T", "VZ", "TMUS",
    "LIN", "NEE", "DUK", "SO", "PLD", "AMT",
]

_TTL = 24 * 3600  # constituents change slowly; refresh daily
_cache: tuple[list[str], float] | None = None


def _fetch_sp500_tickers() -> list[str]:
    """Current S&P 500 tickers via the datasets/s-and-p-500-companies GitHub CSV."""
    import csv
    from io import StringIO

    import httpx

    url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
    resp = httpx.get(
        url,
        headers={"User-Agent": "horizon-capital/0.2"},
        timeout=20.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    rows = list(csv.DictReader(StringIO(resp.text)))
    syms = [r["Symbol"] for r in rows if r.get("Symbol")]
    # CSV uses BRK.B; yfinance wants BRK-B.
    return [s.strip().replace(".", "-") for s in syms if s.strip()]


def get_universe(source: str = "sp500") -> list[str]:
    """Return the trading universe as suffixed symbols (e.g. ``AAPL.NASDAQ``).

    source="config" -> the static settings list; "sp500" -> dynamic constituents
    (anchors + S&P 500), with the bundled fallback if the fetch fails.
    """
    if source == "config":
        from app.config import settings
        out: list[str] = []
        for csv in (settings.us_symbols, settings.india_symbols, settings.crypto_symbols):
            out.extend(s.strip() for s in csv.split(",") if s.strip())
        return out

    global _cache
    if _cache is not None and time.monotonic() - _cache[1] < _TTL:
        return _cache[0]

    try:
        bases = _fetch_sp500_tickers()
        logger.info("universe_fetched", source="sp500", n=len(bases))
    except Exception as exc:
        logger.warning("universe_fetch_failed_using_fallback", error=str(exc))
        bases = _FALLBACK_EXTRA

    out = list(_ANCHORS)
    have = {a.split(".")[0] for a in _ANCHORS}
    for t in bases:
        if t and t not in have:
            out.append(f"{t}.US")
            have.add(t)

    _cache = (out, time.monotonic())
    return out


def _demo() -> None:
    cfg = get_universe("config")
    assert all("." in s for s in cfg), "config symbols should be suffixed"
    uni = get_universe("sp500")
    assert len(uni) >= len(_ANCHORS), "universe must be at least the anchors"
    assert "AAPL.NASDAQ" in uni, "anchor must be present"
    print(f"universe demo OK: config={len(cfg)} names, sp500={len(uni)} names")
    print("sample:", uni[:6], "...", uni[-3:])


if __name__ == "__main__":
    _demo()
