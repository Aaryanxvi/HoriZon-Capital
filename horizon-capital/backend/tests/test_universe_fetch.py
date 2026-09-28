# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-C7BF7DAD175A
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""S&P 500 universe fetch parses the GitHub CSV and falls back cleanly on error."""

import httpx

import app.data_layer.universe as universe_mod
from app.data_layer.universe import _fetch_sp500_tickers, get_universe

_CSV_TEXT = "Symbol,Security\nAAPL,Apple\nBRK.B,Berkshire\n"


class _StubResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


def test_sp500_fetch_parses_csv(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        captured["headers"] = headers
        return _StubResponse(_CSV_TEXT)

    monkeypatch.setattr(httpx, "get", fake_get)

    tickers = _fetch_sp500_tickers()

    assert captured["headers"].get("User-Agent")
    assert tickers == ["AAPL", "BRK-B"]


def test_get_universe_fallback_on_error(monkeypatch):
    def fake_get(*args, **kwargs):
        raise httpx.ConnectError("x")

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(universe_mod, "_cache", None)

    result = get_universe("sp500")

    monkeypatch.setattr(universe_mod, "_cache", None)

    assert "SPY.NYSE" in result
    assert len(result) > 30
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token C7BF7DAD175A - verify with scripts/authorship.py verify
