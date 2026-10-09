# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-AECB5B5A50D4
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Free, point-in-time Indian (NSE) research data for the India strategy gate.

Three public sources, all cached under ~/.horizon-capital/india/ after first fetch:

  * PIT index membership — aditya-jha/nse-historical-membership (CC BY 4.0), an
    interval table (symbol, valid_from, valid_to) per index reconstructed from
    NSE/niftyindices press releases. Floor 2014-01-01; author rates it reliable
    from 2018-04, best-effort before ("drifts +/-2-13 names pre-2018").
  * NSE symbol-change log — nsearchives.nseindia.com symbolchange.csv (official),
    used to follow a historical symbol to the ticker yfinance knows today.
  * Prices — yfinance `<SYMBOL>.NS`, auto-adjusted (splits + dividends).

HONEST residual gap (same shape as the US harness): yfinance has no prices for
names that later delisted / merged, so they drop out. `coverage_table()`
quantifies that per index per year so the gate can refuse a window where the
survivor set is too thin (G4).

Usage:
    python scripts/india_data.py            # print coverage table, no strategy
"""
from __future__ import annotations

import io
import sys
import time
import warnings
from pathlib import Path

import httpx
import pandas as pd

CACHE = Path.home() / ".horizon-capital" / "india"
_MEMBERSHIP_URL = ("https://raw.githubusercontent.com/aditya-jha/nse-historical-membership/"
                   "main/index_history/data/index_membership_history.csv")
_SYMCHANGE_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
_FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36",
        "Accept": "*/*", "Referer": "https://www.nseindia.com/"}
_OHLCV = ["open", "high", "low", "close", "volume"]

# Non-stock instruments the India mapping needs (see the pre-registration doc).
ETFS = ["NIFTYBEES.NS", "JUNIORBEES.NS", "BANKBEES.NS", "GOLDBEES.NS", "LTGILTBEES.NS"]
INDICES = ["^NSEI"]


def _get(url: str, dest: Path, binary: bool = False) -> bytes:
    if dest.exists():
        return dest.read_bytes()
    r = httpx.get(url, headers=_HDR, timeout=60, follow_redirects=True)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return r.content


def load_membership() -> pd.DataFrame:
    raw = _get(_MEMBERSHIP_URL, CACHE / "index_membership_history.csv")
    df = pd.read_csv(io.BytesIO(raw), parse_dates=["valid_from", "valid_to"])
    df["index_name"] = df["index_name"].str.upper()
    return df[["index_name", "symbol", "valid_from", "valid_to"]]


def members_on(df: pd.DataFrame, index_name: str, date) -> set[str]:
    on = pd.Timestamp(date)
    sub = df[df["index_name"] == index_name.upper()]
    m = sub[(sub["valid_from"] <= on) & (sub["valid_to"].isna() | (sub["valid_to"] > on))]
    return set(m["symbol"])


def union_members(df: pd.DataFrame, index_name: str, start, end) -> set[str]:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    sub = df[df["index_name"] == index_name.upper()]
    m = sub[(sub["valid_from"] <= e) & (sub["valid_to"].isna() | (sub["valid_to"] > s))]
    return set(m["symbol"])


def load_symbol_changes() -> dict[str, str]:
    """old NSE symbol -> new NSE symbol (official log, latest change wins)."""
    raw = _get(_SYMCHANGE_URL, CACHE / "symbolchange.csv")
    df = pd.read_csv(io.BytesIO(raw), header=None, encoding="latin1",
                     names=["name", "old", "new", "date"])
    df["date"] = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce")
    df = df.dropna(subset=["old", "new"]).sort_values("date")
    out: dict[str, str] = {}
    for old, new in zip(df["old"].str.strip(), df["new"].str.strip()):
        out[old] = new
    return out


def resolve(symbol: str, changes: dict[str, str]) -> str:
    """Follow the rename chain to the symbol in use today (max 5 hops)."""
    seen, cur = set(), symbol
    while cur in changes and cur not in seen and len(seen) < 5:
        seen.add(cur)
        cur = changes[cur]
    return cur


def _normalize(df: pd.DataFrame) -> pd.DataFrame | None:
    df = df.dropna()
    df.columns = [str(c).lower() for c in df.columns]
    if not set(_OHLCV) <= set(df.columns) or len(df) < 2:
        return None
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out = df[_OHLCV].copy()
    out.index = idx.normalize()
    return out


def fetch_prices(tickers: list[str], chunk: int = 150) -> dict[str, pd.DataFrame]:
    """{yfinance ticker -> OHLCV} for every ticker Yahoo has, period=max, disk-cached."""
    import yfinance as yf
    warnings.filterwarnings("ignore")
    store = CACHE / "prices"
    store.mkdir(parents=True, exist_ok=True)
    out: dict[str, pd.DataFrame] = {}
    miss_file = store / "_missing.txt"
    known_missing = set(miss_file.read_text().split()) if miss_file.exists() else set()
    todo = []
    for t in tickers:
        f = store / (t.replace("^", "_IDX_").replace("&", "_AND_") + ".pkl")
        if f.exists():
            out[t] = pd.read_pickle(f)
        elif t not in known_missing:
            todo.append(t)
    for i in range(0, len(todo), chunk):
        batch = todo[i:i + chunk]
        raw = yf.download(" ".join(batch), period="max", interval="1d", auto_adjust=True,
                          group_by="ticker", progress=False, threads=True)
        for t in batch:
            try:
                sub = raw if len(batch) == 1 else raw[t]
                norm = _normalize(sub)
            except Exception:
                norm = None
            if norm is None or len(norm) < 30:
                known_missing.add(t)
                continue
            f = store / (t.replace("^", "_IDX_").replace("&", "_AND_") + ".pkl")
            norm.to_pickle(f)
            out[t] = norm
        time.sleep(1.0)
    miss_file.write_text("\n".join(sorted(known_missing)))
    return out


def load_rf_monthly(sid: str = "IRSTCI01INM156N") -> pd.Series | None:
    """India immediate interbank rate (% p.a., monthly, OECD MEI via FRED).

    2014 ~9%, 2020-21 ~4.3%, 2023-24 ~6.7% — a flat RF would misprice Sharpe in
    both windows, so the harness uses this series for RF and (minus a spread)
    for the yield on idle cash.
    """
    try:
        raw = _get(_FRED_URL.format(sid=sid), CACHE / f"fred_{sid}.csv")
        df = pd.read_csv(io.BytesIO(raw))
        df.columns = ["date", "v"]
        df["date"] = pd.to_datetime(df["date"])
        df["v"] = pd.to_numeric(df["v"], errors="coerce")
        return df.dropna().set_index("date")["v"] / 100.0
    except Exception:
        return None


def build_universe(start, end, indices=("NIFTY 50", "NIFTY 100", "NIFTY 500")):
    """Return (membership_df, {nse_symbol -> yf ticker}, prices{yf ticker -> df})."""
    mem = load_membership()
    changes = load_symbol_changes()
    syms: set[str] = set()
    for ix in indices:
        syms |= union_members(mem, ix, start, end)
    symmap = {s: resolve(s, changes) + ".NS" for s in sorted(syms)}
    tickers = sorted(set(symmap.values()) | set(ETFS) | set(INDICES))
    prices = fetch_prices(tickers)
    # A rename chain that yfinance doesn't know, but the OLD symbol still exists on Yahoo.
    retry = [s + ".NS" for s, t in symmap.items() if t not in prices and s + ".NS" != t]
    if retry:
        extra = fetch_prices(retry)
        for s, t in list(symmap.items()):
            if t not in prices and s + ".NS" in extra:
                symmap[s] = s + ".NS"
        prices.update(extra)
    return mem, symmap, prices


def coverage_table(mem, symmap, prices, start, end, indices=("NIFTY 50", "NIFTY 100", "NIFTY 500")):
    """Per index per year: members on Jun-30 vs members with a close within 7 days."""
    rows = []
    for ix in indices:
        for y in range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1):
            d = pd.Timestamp(year=y, month=6, day=30)
            if d < pd.Timestamp(start) or d > pd.Timestamp(end):
                d = pd.Timestamp(end) if d > pd.Timestamp(end) else pd.Timestamp(start)
            m = members_on(mem, ix, d)
            have = 0
            for s in m:
                t = symmap.get(s)
                if t in prices:
                    px = prices[t]["close"].loc[d - pd.Timedelta(days=7):d]
                    if len(px.dropna()):
                        have += 1
            rows.append({"index": ix, "year": y, "members": len(m), "with_price": have,
                         "coverage%": round(100 * have / len(m), 1) if m else float("nan")})
    return pd.DataFrame(rows)


def _selfcheck() -> None:
    ch = {"A": "B", "B": "C", "X": "Y", "Y": "X"}
    assert resolve("A", ch) == "C" and resolve("Q", ch) == "Q"
    assert resolve("X", ch) in ("X", "Y")  # cycle terminates
    mem = pd.DataFrame({"index_name": ["NIFTY 50"] * 3, "symbol": ["A", "B", "C"],
                        "valid_from": pd.to_datetime(["2014-01-01", "2014-01-01", "2015-06-01"]),
                        "valid_to": pd.to_datetime(["2015-06-01", None, None])})
    assert members_on(mem, "Nifty 50", "2015-01-01") == {"A", "B"}
    assert members_on(mem, "Nifty 50", "2015-06-01") == {"B", "C"}  # valid_to exclusive
    assert union_members(mem, "Nifty 50", "2014-06-01", "2016-01-01") == {"A", "B", "C"}
    assert union_members(mem, "Nifty 50", "2015-07-01", "2016-01-01") == {"B", "C"}
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
        sys.exit(0)
    start, end = "2014-01-01", "2026-09-30"
    mem, symmap, prices = build_universe(start, end)
    print(f"membership rows={len(mem)}; symbols in window={len(symmap)}; "
          f"tickers with prices={sum(1 for t in symmap.values() if t in prices)}")
    missing = sorted(s for s, t in symmap.items() if t not in prices)
    print(f"missing from yfinance ({len(missing)}): {missing[:40]}{' ...' if len(missing) > 40 else ''}")
    tab = coverage_table(mem, symmap, prices, start, end)
    print(tab.pivot(index="year", columns="index", values="coverage%").to_string())
    print(tab.pivot(index="year", columns="index", values="members").to_string())
    for t in ETFS + INDICES:
        if t in prices:
            print(f"{t:14s} {prices[t].index.min().date()} -> {prices[t].index.max().date()}")
    rf = load_rf_monthly()
    print("RF series:", None if rf is None else f"{rf.index.min().date()}..{rf.index.max().date()} mean={rf.mean():.3%}")
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token AECB5B5A50D4 - verify with scripts/authorship.py verify
