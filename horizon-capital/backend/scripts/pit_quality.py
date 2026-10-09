# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-1303982F63BC
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Point-in-time quality (QMJ) from SEC XBRL companyfacts -- free, filed-date aware.

Why: `app.quant.quality` reads CURRENT yfinance fundamentals, so every backtest stubs
the quality tilt to zero (look-ahead otherwise). SEC's companyfacts API returns every
XBRL fact a company ever filed, each tagged with the date it was FILED. Restricting to
facts filed on or before the decision date gives genuinely point-in-time fundamentals,
back to mid-2009 when XBRL became mandatory for large filers. Before that the score is
0 -- identical to the stub -- and that is disclosed, not hidden.

Same five components and the same cross-sectional z-score composite as
`cross_section_quality`, so the tilt weight (_QUALITY_WEIGHT = 0.20) means the same
thing. Beta comes from the bar data (already point-in-time), not from SEC.

Cache: ~/.horizon-capital/sec_facts/ (one JSON per CIK; SEC asks for <10 req/s and a
descriptive User-Agent, both honoured).

Usage:
    python scripts/pit_quality.py --selfcheck      # no network
    python scripts/pit_quality.py AAPL MSFT JPM     # print as-of scores for a few dates
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

_UA = {"User-Agent": "HorizonCapital research aaryanbaadkar71@gmail.com"}
_CACHE = Path.home() / ".horizon-capital" / "sec_facts"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

_NI = ("NetIncomeLoss",)
_GP = ("GrossProfit",)
_REVENUE = ("Revenues", "SalesRevenueNet",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueGoodsNet", "RevenuesNetOfInterestExpense")
_EQUITY = ("StockholdersEquity",
           "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")
_LIAB = ("Liabilities",)
_ASSETS = ("Assets",)


def _get_json(url: str, cache_file: Path) -> dict:
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    time.sleep(0.15)  # SEC fair-use: stay well under 10 requests/second
    return data


def _frame(facts: dict, concept: str) -> pd.DataFrame | None:
    """(filed, start, end, val) rows for one us-gaap concept in USD."""
    c = facts.get("us-gaap", {}).get(concept)
    if not c:
        return None
    rows = c.get("units", {}).get("USD")
    if not rows:
        return None
    df = pd.DataFrame(rows)
    if "start" not in df:
        df["start"] = pd.NaT
    for col in ("filed", "end", "start"):
        df[col] = pd.to_datetime(df[col])
    return df[["filed", "start", "end", "val"]]


def _annual(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Keep full-fiscal-year duration facts (10-K values, 350-380 day spans)."""
    if df is None:
        return None
    d = df.dropna(subset=["start"])
    span = (d["end"] - d["start"]).dt.days
    d = d[(span > 350) & (span < 380)]
    return d if not d.empty else None


def _latest(df: pd.DataFrame | None, as_of: pd.Timestamp) -> pd.Series | None:
    """Most recent period-end among facts FILED on or before as_of."""
    if df is None:
        return None
    d = df[df["filed"] <= as_of]
    if d.empty:
        return None
    return d.sort_values(["end", "filed"]).iloc[-1]


def _zscores(vals: dict[str, float], sign: int) -> dict[str, float]:
    """Same convention as app.quant.quality.cross_section_quality.collect."""
    clean = {s: v for s, v in vals.items() if v is not None and np.isfinite(v)}
    if len(clean) < 2:
        return {}
    arr = np.array(list(clean.values()), dtype=float)
    mean, sd = arr.mean(), arr.std(ddof=1)
    if sd == 0:
        return {s: 0.0 for s in clean}
    return {s: sign * (v - mean) / sd for s, v in clean.items()}


class PITQuality:
    """Per-ticker XBRL facts, queried as of a date using only what was filed by then."""

    def __init__(self, tickers: list[str], facts_override: dict[str, dict] | None = None):
        self.tickers = list(tickers)
        self._facts: dict[str, dict] = {}
        if facts_override is not None:
            self._facts = dict(facts_override)
        else:
            cmap = {v["ticker"].upper(): int(v["cik_str"]) for v in
                    _get_json(_TICKERS_URL, _CACHE / "company_tickers.json").values()}
            for t in self.tickers:
                cik = cmap.get(t.upper())
                if cik is None:
                    continue
                try:
                    self._facts[t] = _get_json(_FACTS_URL.format(cik=cik),
                                               _CACHE / f"CIK{cik:010d}.json")["facts"]
                except Exception:
                    continue
        self._fy: dict[str, dict[str, pd.DataFrame | None]] = {}
        self._inst: dict[str, dict[str, pd.DataFrame | None]] = {}
        for t, f in self._facts.items():
            self._fy[t] = {k: _annual(_frame(f, k)) for k in _NI + _GP + _REVENUE}
            self._inst[t] = {k: _frame(f, k) for k in _EQUITY + _LIAB + _ASSETS}

    @property
    def covered(self) -> list[str]:
        return sorted(self._facts)

    def _first(self, table: dict, concepts: tuple[str, ...], as_of) -> pd.Series | None:
        for k in concepts:
            row = _latest(table.get(k), as_of)
            if row is not None:
                return row
        return None

    def raw(self, ticker: str, as_of: pd.Timestamp) -> dict[str, float | None]:
        """ROE, gross margin, earnings growth, liabilities/equity as of a date."""
        out: dict[str, float | None] = {"roe": None, "gm": None, "eg": None, "de": None}
        if ticker not in self._facts:
            return out
        fy, inst = self._fy[ticker], self._inst[ticker]
        ni = self._first(fy, _NI, as_of)
        eq = self._first(inst, _EQUITY, as_of)
        if ni is not None and eq is not None and eq["val"] > 0:
            out["roe"] = float(ni["val"] / eq["val"])
        gp = self._first(fy, _GP, as_of)
        rev = self._first(fy, _REVENUE, as_of)
        if gp is not None and rev is not None and rev["val"] > 0:
            out["gm"] = float(gp["val"] / rev["val"])
        if ni is not None:
            tbl = fy.get("NetIncomeLoss")
            prev = tbl[(tbl["filed"] <= as_of)
                       & ((ni["end"] - tbl["end"]).dt.days.between(340, 390))]
            if not prev.empty:
                p = prev.sort_values("filed").iloc[-1]["val"]
                if p > 0:
                    out["eg"] = float(ni["val"] / p - 1.0)
        liab = self._first(inst, _LIAB, as_of)
        if liab is None:
            assets = self._first(inst, _ASSETS, as_of)
            if assets is not None and eq is not None:
                liab = pd.Series({"val": assets["val"] - eq["val"]})
        if liab is not None and eq is not None and eq["val"] > 0:
            out["de"] = float(liab["val"] / eq["val"])
        return out

    def scores(self, tickers: list[str], as_of: pd.Timestamp,
               betas: dict[str, float] | None = None) -> dict[str, float]:
        """Cross-sectional composite in the exact shape of cross_section_quality."""
        raw = {t: self.raw(t, as_of) for t in tickers}
        betas = betas or {}
        z = [
            _zscores({t: r["roe"] for t, r in raw.items()}, +1),
            _zscores({t: r["gm"] for t, r in raw.items()}, +1),
            _zscores({t: r["eg"] for t, r in raw.items()}, +1),
            _zscores({t: r["de"] for t, r in raw.items()}, -1),
            _zscores({t: betas.get(t) for t in tickers}, -1),
        ]
        return {t: float(np.mean([zz.get(t, 0.0) for zz in z])) for t in tickers}


def _selfcheck() -> None:
    """Filed-date discipline and z-score shape, on constructed facts (no network)."""
    def fact(start, end, val, filed):
        return {"start": start, "end": end, "val": val, "filed": filed,
                "fy": 2020, "fp": "FY", "form": "10-K"}

    def inst(end, val, filed):
        return {"end": end, "val": val, "filed": filed, "fy": 2020, "fp": "FY", "form": "10-K"}

    a = {"us-gaap": {
        "NetIncomeLoss": {"units": {"USD": [
            fact("2018-01-01", "2018-12-31", 100.0, "2019-02-15"),
            fact("2019-01-01", "2019-12-31", 150.0, "2020-02-15"),
            fact("2018-01-01", "2018-12-31", 100.0, "2020-02-15"),  # comparative
            fact("2019-10-01", "2019-12-31", 40.0, "2020-02-15"),   # a quarter: ignored
        ]}},
        "StockholdersEquity": {"units": {"USD": [
            inst("2018-12-31", 1000.0, "2019-02-15"), inst("2019-12-31", 1200.0, "2020-02-15")]}},
        "GrossProfit": {"units": {"USD": [fact("2019-01-01", "2019-12-31", 300.0, "2020-02-15")]}},
        "Revenues": {"units": {"USD": [fact("2019-01-01", "2019-12-31", 600.0, "2020-02-15")]}},
        "Liabilities": {"units": {"USD": [inst("2019-12-31", 600.0, "2020-02-15")]}},
    }}
    b = {"us-gaap": {
        "NetIncomeLoss": {"units": {"USD": [fact("2019-01-01", "2019-12-31", -10.0, "2020-03-01")]}},
        "StockholdersEquity": {"units": {"USD": [inst("2019-12-31", 500.0, "2020-03-01")]}},
        "Assets": {"units": {"USD": [inst("2019-12-31", 2000.0, "2020-03-01")]}},
    }}
    q = PITQuality(["A", "B"], facts_override={"A": a, "B": b})

    # Before anything was filed: nothing known (the stub value).
    assert q.raw("A", pd.Timestamp("2019-01-31")) == {"roe": None, "gm": None, "eg": None, "de": None}
    # Between filings: only the FY2018 10-K is visible, even though FY2019 ENDED already.
    r = q.raw("A", pd.Timestamp("2020-01-31"))
    assert abs(r["roe"] - 100.0 / 1000.0) < 1e-12, r
    assert r["eg"] is None and r["gm"] is None, r
    # After the FY2019 10-K: growth = 150/100 - 1, margin 0.5, leverage 0.5.
    r = q.raw("A", pd.Timestamp("2020-02-15"))
    assert abs(r["roe"] - 0.125) < 1e-12 and abs(r["eg"] - 0.5) < 1e-12, r
    assert abs(r["gm"] - 0.5) < 1e-12 and abs(r["de"] - 0.5) < 1e-12, r
    # Liabilities fallback = assets - equity; negative NI -> ROE negative, growth undefined.
    r = q.raw("B", pd.Timestamp("2020-03-01"))
    assert abs(r["de"] - 3.0) < 1e-12 and r["roe"] < 0 and r["eg"] is None, r
    # Composite: A is the higher-quality name on every available axis.
    s = q.scores(["A", "B"], pd.Timestamp("2020-06-30"), betas={"A": 1.0, "B": 1.5})
    assert s["A"] > 0 > s["B"], s
    assert abs(s["A"] + s["B"]) < 1e-9, s  # z-scores of a pair are symmetric
    # Unknown ticker: zeros, never an exception.
    assert q.scores(["A", "ZZZ"], pd.Timestamp("2020-06-30"))["ZZZ"] == 0.0
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        names = [a for a in sys.argv[1:] if not a.startswith("-")] or ["AAPL", "MSFT", "JPM"]
        q = PITQuality(names)
        print("covered:", q.covered)
        for d in ("2009-01-02", "2010-01-04", "2015-01-02", "2020-01-02", "2024-01-02"):
            ts = pd.Timestamp(d)
            print(d, {t: {k: (round(v, 3) if v is not None else None)
                          for k, v in q.raw(t, ts).items()} for t in names})
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 1303982F63BC - verify with scripts/authorship.py verify
