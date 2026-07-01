# Risk Overlay + Dual-Momentum Sleeve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise portfolio Sharpe above SPY (0.55) and cut maxDD below −25% on honest PIT data via a vol-target/trend-gate risk overlay and an Antonacci dual-momentum ETF sleeve, gated by a one-shot validation script that ships nothing unless it beats the current baseline.

**Architecture:** Pure-function overlay module in `app/quant/`, new `BaseSleeve` subclass, config-flagged wiring in `StrategyAgent` (overlay off by default until validation passes), and a self-contained validation script implementing the ship gate. Spec: `docs/superpowers/specs/2026-07-02-risk-overlay-dual-momentum-design.md`.

**Tech Stack:** Python 3.14 (targets ≥3.11), pandas/numpy, pytest (asyncio_mode=auto), ruff (line-length=100, `X | None` not `Optional`).

**Deviation from spec (approved rationale):** `trend_filter.py` is NOT deleted — `scripts/backtest_sleeves.py` and `scripts/validate_sleeves_oos.py` import it. It is unwired from the live agent and marked reference-only in the sleeves `__init__` docstring, same precedent as `gap_fade`.

**Working directory for all commands:** `horizon-capital/backend/` (inside the git repo rooted at `Horizon capital/`).

**Commit identity (user rule):** every commit uses `-c user.email=aaryanbaadkar71@gmail.com -c user.name=Aaryanxvi`, no Co-Authored-By trailer, never push.

---

### Task 1: Risk overlay module

**Files:**
- Create: `backend/app/quant/risk_overlay.py`
- Test: `backend/tests/test_risk_overlay.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_risk_overlay.py`:

```python
"""Risk overlay: vol targeting + trend gate. All paths fail-open to 1.0."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.quant.risk_overlay import (
    overlay_scalar,
    portfolio_returns,
    trend_gate,
    vol_target_scalar,
)


def _series(vals: list[float]) -> pd.Series:
    return pd.Series(vals, index=pd.bdate_range("2020-01-01", periods=len(vals)))


def test_vol_scalar_caps_at_one_when_vol_below_target():
    r = _series([0.0001] * 60)  # near-zero vol
    assert vol_target_scalar(r) == 1.0


def test_vol_scalar_cuts_when_vol_high():
    rng = np.random.default_rng(0)
    r = _series(list(rng.normal(0.0, 0.03, 60)))  # ~48% annualized
    s = vol_target_scalar(r, target=0.15)
    assert 0.0 < s < 1.0


def test_vol_scalar_fail_open_on_short_or_empty_history():
    assert vol_target_scalar(_series([0.01] * 5)) == 1.0
    assert vol_target_scalar(pd.Series(dtype=float)) == 1.0


def test_trend_gate_flips_at_sma():
    up = _series(list(np.linspace(100.0, 200.0, 250)))
    down = _series(list(np.linspace(200.0, 100.0, 250)))
    assert trend_gate(up) == 1.0
    assert trend_gate(down) == 0.0


def test_trend_gate_fail_open_on_short_history():
    assert trend_gate(_series([100.0] * 50)) == 1.0


def test_portfolio_returns_weighting():
    idx = pd.bdate_range("2020-01-01", periods=3)
    closes = pd.DataFrame({"A": [100.0, 110.0, 121.0], "B": [100.0, 100.0, 100.0]}, index=idx)
    r = portfolio_returns(closes, {"A": 0.5, "B": 0.5})
    assert abs(r.iloc[-1] - 0.05) < 1e-9


def test_overlay_scalar_composes_and_bounds():
    idx = pd.bdate_range("2019-01-01", periods=300)
    closes = pd.DataFrame(
        {"A": np.linspace(50.0, 150.0, 300), "B": np.linspace(30.0, 90.0, 300)}, index=idx
    )
    weights = {"A": 0.5, "B": 0.5}
    spy_up = pd.Series(np.linspace(100.0, 200.0, 300), index=idx)
    spy_down = pd.Series(np.linspace(200.0, 100.0, 300), index=idx)
    s = overlay_scalar(closes, weights, spy_up)
    assert 0.0 <= s <= 1.0
    assert overlay_scalar(closes, weights, spy_down) == 0.0  # gate kills it


def test_overlay_scalar_fail_open_on_missing_symbols():
    idx = pd.bdate_range("2019-01-01", periods=300)
    closes = pd.DataFrame({"A": np.linspace(50.0, 150.0, 300)}, index=idx)
    spy_up = pd.Series(np.linspace(100.0, 200.0, 300), index=idx)
    # weights reference only symbols absent from closes -> no returns -> 1.0 * gate
    assert overlay_scalar(closes, {"ZZZ": 1.0}, spy_up) == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_risk_overlay.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.quant.risk_overlay'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/quant/risk_overlay.py`:

```python
"""Portfolio risk overlay: vol targeting + 200d trend gate. Pure functions.

Parameters are LOCKED from published research and must not be tuned on any
test window afterward:
  - 15% vol target, 20d realized window: Moreira-Muir (2017), "Volatility-
    Managed Portfolios".
  - 200d SMA trend gate on the market index: Faber (2007), "A Quantitative
    Approach to Tactical Asset Allocation".

The overlay can only DE-RISK (scalar in [0, 1], never levers up). Every
degenerate input (short history, NaNs, missing symbols) fails OPEN to 1.0 —
i.e., falls back to current behavior, never crashes, never zeroes exposure
by accident.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252
VOL_TARGET = 0.15
VOL_WINDOW = 20
SMA_WINDOW = 200


def vol_target_scalar(
    returns: pd.Series, target: float = VOL_TARGET, window: int = VOL_WINDOW
) -> float:
    """min(1, target/realized) from the trailing ``window`` of daily returns."""
    r = returns.dropna()
    if len(r) < window:
        return 1.0
    vol = float(r.iloc[-window:].std() * np.sqrt(TRADING_DAYS))
    if not np.isfinite(vol) or vol <= 0.0:
        return 1.0
    return min(1.0, target / vol)


def trend_gate(index_close: pd.Series, sma_window: int = SMA_WINDOW) -> float:
    """1.0 when the index is at/above its SMA, else 0.0. Fail-open on short data."""
    c = index_close.dropna()
    if len(c) < sma_window:
        return 1.0
    return 1.0 if float(c.iloc[-1]) >= float(c.iloc[-sma_window:].mean()) else 0.0


def portfolio_returns(closes: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Daily returns of the weight-normalized basket (only symbols present)."""
    cols = [s for s in weights if s in closes.columns]
    if not cols:
        return pd.Series(dtype=float)
    w = pd.Series({s: weights[s] for s in cols})
    total = float(w.abs().sum())
    if total <= 0.0:
        return pd.Series(dtype=float)
    return (closes[cols].pct_change() * (w / total)).sum(axis=1)


def overlay_scalar(
    closes: pd.DataFrame,
    weights: dict[str, float],
    index_close: pd.Series,
    target: float = VOL_TARGET,
) -> float:
    """Combined exposure multiplier in [0, 1]: vol targeting x trend gate."""
    return vol_target_scalar(portfolio_returns(closes, weights), target) * trend_gate(index_close)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_risk_overlay.py -v`
Expected: 8 passed

- [ ] **Step 5: Lint and commit**

```bash
python -m ruff check app/quant/risk_overlay.py tests/test_risk_overlay.py
cd .. && git add backend/app/quant/risk_overlay.py backend/tests/test_risk_overlay.py
git -c user.email=aaryanbaadkar71@gmail.com -c user.name=Aaryanxvi commit -m "feat(quant): risk overlay - vol targeting + 200d trend gate, fail-open"
cd backend
```

---

### Task 2: Dual-momentum sleeve

**Files:**
- Create: `backend/app/agents/front_office/strategy/sleeves/dual_momentum.py`
- Modify: `backend/app/agents/front_office/strategy/sleeves/__init__.py`
- Test: `backend/tests/test_dual_momentum.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_dual_momentum.py`:

```python
"""DualMomentumSleeve: Antonacci GEM over asset-class ETFs."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.agents.front_office.strategy.sleeves.dual_momentum import DualMomentumSleeve

_FULL = {
    "SPY.NYSE": (100.0, 150.0),   # +50% — strongest risk asset
    "EFA.NYSE": (100.0, 110.0),
    "TLT.NASDAQ": (100.0, 105.0),
    "GLD.NYSE": (100.0, 108.0),
    "DBC.NYSE": (100.0, 90.0),
    "BIL.NYSE": (100.0, 102.0),
}


def _bars(trends: dict[str, tuple[float, float]], n: int = 300):
    idx = pd.bdate_range("2019-01-01", periods=n)
    out = {}
    for sym, (start, end) in trends.items():
        close = pd.Series(np.linspace(start, end, n), index=idx)
        out[sym] = pd.DataFrame(
            {"open": close, "high": close, "low": close, "close": close, "volume": 1e6},
            index=idx,
        )
    return out, idx[-1]


def test_gem_picks_strongest_risk_asset():
    bars, as_of = _bars(_FULL)
    sigs = DualMomentumSleeve().compute(bars, as_of)
    w = {s.symbol: s.target_weight for s in sigs}
    assert w["SPY.NYSE"] == 1.0
    assert all(v == 0.0 for k, v in w.items() if k != "SPY.NYSE")


def test_gem_falls_to_tlt_when_cash_beats_all():
    bars, as_of = _bars({
        "SPY.NYSE": (100.0, 95.0),
        "EFA.NYSE": (100.0, 96.0),
        "TLT.NASDAQ": (100.0, 99.0),
        "GLD.NYSE": (100.0, 97.0),
        "DBC.NYSE": (100.0, 90.0),
        "BIL.NYSE": (100.0, 104.0),   # cash wins -> defensive TLT
    })
    sigs = DualMomentumSleeve().compute(bars, as_of)
    w = {s.symbol: s.target_weight for s in sigs}
    assert w["TLT.NASDAQ"] == 1.0
    assert all(v == 0.0 for k, v in w.items() if k != "TLT.NASDAQ")


def test_gem_graceful_when_insufficient_history():
    bars, as_of = _bars({"SPY.NYSE": (100.0, 150.0)}, n=100)  # < 253 rows
    assert DualMomentumSleeve().compute(bars, as_of) == []


def test_gem_missing_cash_proxy_defaults_to_zero_threshold():
    trends = {k: v for k, v in _FULL.items() if k != "BIL.NYSE"}
    bars, as_of = _bars(trends)
    sigs = DualMomentumSleeve().compute(bars, as_of)
    w = {s.symbol: s.target_weight for s in sigs}
    assert w["SPY.NYSE"] == 1.0  # +50% > 0.0 threshold


def test_weights_sum_at_most_one_and_monthly_cadence():
    bars, as_of = _bars(_FULL)
    sleeve = DualMomentumSleeve()
    sigs = sleeve.compute(bars, as_of)
    assert sum(s.target_weight for s in sigs) <= 1.0 + 1e-9
    assert sleeve.rebalance_days == 21
    assert sleeve.name == "dual_momentum"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dual_momentum.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app...sleeves.dual_momentum'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/agents/front_office/strategy/sleeves/dual_momentum.py`:

```python
"""Dual-momentum sleeve: Antonacci GEM over asset-class ETFs.

Reference: Antonacci, "Dual Momentum Investing" (2014). Rule, verbatim, no
tuning:
  1. Rank risk assets (SPY, EFA, TLT, GLD, DBC) by 12-month return.
  2. If the top asset's 12m return beats the cash proxy's (BIL), hold it at
     100% of the sleeve.
  3. Otherwise hold the defensive asset (TLT).

ETF prices carry no survivorship bias, so free data validates this sleeve
honestly (see scripts/validate_overlay.py). Monthly cadence — the documented
GEM rebalance frequency.
"""
from __future__ import annotations

import pandas as pd

from app.agents.front_office.strategy.sleeves.base import BaseSleeve, SleeveSignal

_RISK_ASSETS = ["SPY.NYSE", "EFA.NYSE", "TLT.NASDAQ", "GLD.NYSE", "DBC.NYSE"]
_CASH_PROXY = "BIL.NYSE"
_DEFENSIVE = "TLT.NASDAQ"
_LOOKBACK = 252  # 12 months


class DualMomentumSleeve(BaseSleeve):
    name = "dual_momentum"
    target_weight = 0.30
    rebalance_days = 21  # monthly — GEM's documented cadence

    # StrategyAgent unions this into its fetch list so the ETFs always have bars
    # even when the trading universe (US_SYMBOLS / sp500) doesn't include them.
    UNIVERSE = frozenset(_RISK_ASSETS) | {_CASH_PROXY}

    def compute(
        self, bars: dict[str, pd.DataFrame], as_of: pd.Timestamp
    ) -> list[SleeveSignal]:
        def ret_12m(sym: str) -> float | None:
            df = bars.get(sym)
            if df is None:
                return None
            close = df.loc[:as_of]["close"]
            if len(close) < _LOOKBACK + 1:
                return None
            past = float(close.iloc[-_LOOKBACK])
            return float(close.iloc[-1]) / past - 1.0 if past > 0 else None

        rets = {s: r for s in _RISK_ASSETS if (r := ret_12m(s)) is not None}
        if not rets:
            return []

        top, top_ret = max(rets.items(), key=lambda kv: kv[1])
        cash_ret = ret_12m(_CASH_PROXY) or 0.0
        winner = top if top_ret > cash_ret else _DEFENSIVE
        if winner not in bars:
            return []  # defensive asset has no data — keep previous targets
        reason = f"GEM: top={top} {top_ret:+.1%} vs cash {cash_ret:+.1%} -> hold {winner}"

        return [
            SleeveSignal(symbol=s, target_weight=1.0 if s == winner else 0.0, reason=reason)
            for s in sorted(self.UNIVERSE)
            if s in bars or s == winner
        ]
```

- [ ] **Step 4: Export from the sleeves package**

In `backend/app/agents/front_office/strategy/sleeves/__init__.py`, add the import (alphabetical position, after `breadth_alpha`) and `__all__` entry, and update the module docstring's sleeve list:

```python
from app.agents.front_office.strategy.sleeves.dual_momentum import DualMomentumSleeve
```

Docstring: add `- ``dual_momentum``: Antonacci GEM across asset-class ETFs (monthly).` and change the `trend_filter` line to `- ``trend_filter``:   Faber 200d SMA gate on SPY. NOT used live — superseded by the portfolio-level overlay + dual momentum. Kept for reference scripts.`

`__all__` becomes:

```python
__all__ = [
    "BreadthAlphaSleeve",
    "DualMomentumSleeve",
    "GapFadeSleeve",
    "MomentumRankSleeve",
    "ResearchStackSleeve",
    "TrendFilterSleeve",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_dual_momentum.py -v`
Expected: 5 passed

- [ ] **Step 6: Lint and commit**

```bash
python -m ruff check app/agents/front_office/strategy/sleeves/ tests/test_dual_momentum.py
cd .. && git add backend/app/agents/front_office/strategy/sleeves/dual_momentum.py backend/app/agents/front_office/strategy/sleeves/__init__.py backend/tests/test_dual_momentum.py
git -c user.email=aaryanbaadkar71@gmail.com -c user.name=Aaryanxvi commit -m "feat(strategy): dual-momentum sleeve (Antonacci GEM over asset-class ETFs)"
cd backend
```

---

### Task 3: Config flags + StrategyAgent wiring

**Files:**
- Modify: `backend/app/config.py` (after `debate_min_strength`, ~line 226)
- Modify: `backend/app/agents/front_office/strategy/strategy_agent.py` (imports ~line 26, sleeve mix ~line 101, `_ensure_symbols` ~line 122, `_compute_target_weights` ~line 254)
- Modify: `horizon-capital/.env.example`
- Test: `backend/tests/test_strategy_overlay.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_strategy_overlay.py`:

```python
"""StrategyAgent wiring: new sleeve mix, ETF fetch union, overlay hook."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.agents.front_office.strategy.sleeves.dual_momentum import DualMomentumSleeve
from app.agents.front_office.strategy.strategy_agent import StrategyAgent
from app.config import settings
from app.core.memory_bus import MemoryBus


def _agent() -> StrategyAgent:
    return StrategyAgent(bus=MemoryBus())


def _spy_bars(start: float, end: float, n: int = 300) -> dict[str, pd.DataFrame]:
    idx = pd.bdate_range("2019-01-01", periods=n)
    close = pd.Series(np.linspace(start, end, n), index=idx)
    df = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1e6},
        index=idx,
    )
    return {"SPY.NYSE": df}


def test_live_mix_weights_sum_to_one():
    weights = {s.name: s.target_weight for s in _agent()._sleeves}
    assert weights == {
        "breadth_alpha": 0.30,
        "research_stack": 0.25,
        "dual_momentum": 0.30,
        "momentum_rank": 0.15,
    }
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_universe_includes_dual_momentum_etfs(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(
        "app.data_layer.universe.get_universe", lambda source: ["AAPL.NASDAQ"]
    )
    symbols = agent._ensure_symbols()
    assert DualMomentumSleeve.UNIVERSE <= set(symbols)
    assert "AAPL.NASDAQ" in symbols


def test_overlay_disabled_is_identity(monkeypatch):
    monkeypatch.setattr(settings, "overlay_enabled", False, raising=False)
    targets = {"SPY.NYSE": 0.5}
    assert _agent()._apply_overlay(targets, _spy_bars(100.0, 200.0)) == targets


def test_overlay_zeroes_exposure_in_downtrend(monkeypatch):
    monkeypatch.setattr(settings, "overlay_enabled", True, raising=False)
    out = _agent()._apply_overlay({"SPY.NYSE": 0.5}, _spy_bars(200.0, 100.0))
    assert out["SPY.NYSE"] == 0.0


def test_overlay_fail_open_without_spy(monkeypatch):
    monkeypatch.setattr(settings, "overlay_enabled", True, raising=False)
    bars = {k.replace("SPY.NYSE", "QQQ.NASDAQ"): v for k, v in _spy_bars(200.0, 100.0).items()}
    targets = {"QQQ.NASDAQ": 0.5}
    assert _agent()._apply_overlay(targets, bars) == targets
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_strategy_overlay.py -v`
Expected: FAIL — mix assertion mismatch, `AttributeError: ... no attribute '_apply_overlay'`, missing `overlay_enabled`

- [ ] **Step 3: Add config settings**

In `backend/app/config.py`, directly after `debate_min_strength: float = 0.0`, add:

```python
    # Portfolio risk overlay (Moreira-Muir vol targeting + Faber 200d trend gate).
    # Applied by StrategyAgent to aggregated sleeve weights. OFF by default until
    # the ship gate in scripts/validate_overlay.py passes. Fail-open: any missing
    # data means scalar 1.0 (today's behavior exactly).
    overlay_enabled: bool = False
    overlay_vol_target: float = 0.15
```

In `horizon-capital/.env.example`, next to the other strategy knobs, add:

```
# Portfolio risk overlay (vol targeting + 200d trend gate). Enable only after
# scripts/validate_overlay.py ship gate passes.
OVERLAY_ENABLED=false
OVERLAY_VOL_TARGET=0.15
```

- [ ] **Step 4: Rewire StrategyAgent**

In `backend/app/agents/front_office/strategy/strategy_agent.py`:

(a) Imports — replace the sleeves import block:

```python
from app.agents.front_office.strategy.sleeves import (
    BreadthAlphaSleeve,
    DualMomentumSleeve,
    MomentumRankSleeve,
    ResearchStackSleeve,
)
```

(b) Sleeve mix in `__init__` — replace the `self._sleeves` list and its comment:

```python
        # Live sleeve allocation. trend_filter removed — superseded by the
        # portfolio-level overlay (200d gate) + dual momentum, which cover the
        # same defensive mechanism. Weights sum to 1.0; tune freely.
        self._sleeves = [
            _weighted(BreadthAlphaSleeve(), 0.30),   # multi-signal top-K breadth
            _weighted(DualMomentumSleeve(), 0.30),   # GEM asset-class rotation
            _weighted(ResearchStackSleeve(), 0.25),  # HRP + Kelly + regime + quality
            _weighted(MomentumRankSleeve(), 0.15),   # 12-1 cross-sectional momentum
        ]
```

(c) `_ensure_symbols` — after `self._symbols = get_universe(...)`, union in the sleeve's ETFs:

```python
            # Dual-momentum ETFs must always have bars, whatever the universe.
            extra = sorted(DualMomentumSleeve.UNIVERSE - set(self._symbols))
            self._symbols.extend(extra)
```

(d) Overlay hook — at the end of `_compute_target_weights`, change `return combined` to `return self._apply_overlay(combined, bars)` and add the method:

```python
    def _apply_overlay(
        self, targets: dict[str, float], bars: dict[str, pd.DataFrame]
    ) -> dict[str, float]:
        """Scale aggregated weights by the risk-overlay exposure multiplier.

        Fail-open: overlay disabled, no targets, or no SPY bars -> unchanged.
        Freed weight is implicit cash; the drift check downstream turns overlay
        moves into normal rebalance signals.
        """
        if not settings.overlay_enabled or not targets:
            return targets
        spy = bars.get("SPY.NYSE") or bars.get("SPY")
        if spy is None:
            return targets
        from app.quant.risk_overlay import overlay_scalar

        closes = pd.DataFrame({s: df["close"] for s, df in bars.items()})
        scalar = overlay_scalar(
            closes, targets, spy["close"], target=settings.overlay_vol_target
        )
        if scalar >= 0.999:
            return targets
        logger.info("overlay_applied", scalar=round(scalar, 3))
        return {s: w * scalar for s, w in targets.items()}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_strategy_overlay.py -v`
Expected: 5 passed

- [ ] **Step 6: Run the full suite (regression)**

Run: `python -m pytest tests/ -q`
Expected: all pass (~400+). If a test asserts the OLD sleeve mix or TrendFilterSleeve in the live agent, update that test to the new mix — the new mix is the spec.

- [ ] **Step 7: Lint and commit**

```bash
python -m ruff check app/ tests/
cd .. && git add backend/app/config.py backend/app/agents/front_office/strategy/strategy_agent.py backend/tests/test_strategy_overlay.py .env.example
git -c user.email=aaryanbaadkar71@gmail.com -c user.name=Aaryanxvi commit -m "feat(strategy): wire dual-momentum sleeve + config-gated risk overlay, drop trend_filter from live mix"
cd backend
```

---

### Task 4: Validation script with ship gate

**Files:**
- Create: `backend/scripts/validate_overlay.py`

No unit tests — this is a research script (network + long runtime); the runnable check is the script itself. Reuses `metrics` and cost constants from `scripts/validate_pit.py` and `_mtm` from `scripts/validate_breadth.py`.

- [ ] **Step 1: Write the script**

Create `backend/scripts/validate_overlay.py`:

```python
"""Ship-gate validation: risk overlay + dual momentum vs baseline. ONE-SHOT.

Variants (identical costs: 1bp commission + 2bp slippage):
  PIT sample (S&P 500 point-in-time membership, 2018-2024, ~85% coverage):
    baseline    breadth engine exactly as validate_pit (must reproduce ~0.30 Sharpe)
    brd+ovl     breadth + overlay (vol target 15% + SPY 200d gate)
    momrank     12-1 momentum top-3 monthly on the PIT universe (blend component)
  ETF sample (SPY/EFA/TLT/GLD/DBC/BIL, no survivorship bias):
    spy         SPY buy-and-hold        (overlay counterpart, 2008-2017)
    spy+ovl     SPY + overlay           (overlay must not hurt here)
    gem         Antonacci dual momentum (2008-2017 and 2018-2024 reported)
  blend        0.30 brd+ovl + 0.30 gem + 0.15 momrank, renormalized (/0.75).
               research_stack (0.25) is NOT backtestable on free PIT data and is
               EXCLUDED from the blend proxy — stated, not hidden.

SHIP RULE (spec docs/superpowers/specs/2026-07-02-risk-overlay-dual-momentum-design.md):
  ship overlay   iff brd+ovl beats baseline on Sharpe AND maxDD (PIT)
                     AND spy+ovl Sharpe >= spy Sharpe (ETF 2008-2017)
  ship dual-mom  iff blend (no shipping decision on gem alone) beats baseline
                     on Sharpe AND maxDD (PIT) AND gem 2008-2017 Sharpe > 0
No parameter iteration on either window after the first run.

Usage: python -m scripts.validate_overlay [--start 2018-01-01 --end 2024-12-31]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data_layer.batch_bars import fetch_batch  # noqa: E402
from app.data_layer.pit_universe import members_on, union_members  # noqa: E402
from app.quant.multi_signal import score_universe, select_for_llm  # noqa: E402
from app.quant.risk_overlay import trend_gate, vol_target_scalar  # noqa: E402
from scripts.validate_breadth import _mtm  # noqa: E402
from scripts.validate_pit import (  # noqa: E402
    COMMISSION_BPS,
    GROSS,
    K,
    MIN_CONVICTION,
    REBAL,
    SLIPPAGE_BPS,
    metrics,
)

ETFS = ["SPY", "EFA", "TLT", "GLD", "DBC", "BIL"]
RISK_ETFS = ["SPY", "EFA", "TLT", "GLD", "DBC"]
MONTHLY = 21
MOMRANK_TOP = 3


def _overlay_scalar_at(equity: dict, spy_hist: pd.Series) -> float:
    """Overlay multiplier from the portfolio's own realized equity curve."""
    eq = pd.Series(equity)
    return vol_target_scalar(eq.pct_change()) * trend_gate(spy_hist)


def run_weights_backtest(closes, opens, calendar, capital, pick_fn, overlay=False):
    """Generic pending-order backtest: pick_fn(date, i) -> {sym: weight} | None.

    Weights execute at NEXT day's open with commission+slippage (same mechanics
    as validate_pit.run_backtest). With overlay=True the picked weights are
    scaled by the overlay multiplier computed as of the pick date.
    """
    cash = capital
    shares: dict[str, float] = {}
    pending: dict[str, float] | None = None
    equity: dict[pd.Timestamp, float] = {}

    for i, date in enumerate(calendar):
        if pending is not None:
            nav_open = _mtm(opens, shares, date, cash)
            if not np.isnan(nav_open):
                for s in set(list(shares) + list(pending)):
                    if s not in opens.columns or date not in opens.index:
                        continue
                    px = opens[s].get(date, np.nan)
                    if np.isnan(px) or px <= 0:
                        continue
                    tgt = nav_open * pending.get(s, 0.0) / px
                    delta = tgt - shares.get(s, 0.0)
                    if abs(delta * px) < nav_open * 0.002:
                        continue
                    buy = delta > 0
                    qty = abs(delta)
                    ex = px * (1 + SLIPPAGE_BPS / 1e4) if buy else px * (1 - SLIPPAGE_BPS / 1e4)
                    comm = qty * ex * COMMISSION_BPS / 1e4
                    if buy:
                        cost = qty * ex + comm
                        if cost > cash:
                            qty = max(0.0, (cash - comm) / ex)
                            if qty <= 0:
                                continue
                            cost = qty * ex + comm
                        cash -= cost
                        shares[s] = shares.get(s, 0.0) + qty
                    else:
                        cash += qty * ex - comm
                        shares[s] = shares.get(s, 0.0) - qty
            pending = None

        equity[date] = _mtm(closes, shares, date, cash)

        if i + 1 < len(calendar):
            picks = pick_fn(date, i)
            if picks is not None:
                if overlay and picks:
                    scal = _overlay_scalar_at(equity, closes["SPY"].loc[:date])
                    picks = {s: w * scal for s, w in picks.items()}
                pending = picks
    return pd.Series(equity)


def breadth_picks(closes, have):
    def pick(date, i):
        if i % REBAL != 0:
            return None
        elig = sorted(members_on(date) & have)
        if len(elig) < 10:
            return None
        cands = score_universe(closes[elig], date, market=closes.get("SPY"))
        sel = select_for_llm(cands, k=K, min_conviction=MIN_CONVICTION)
        return {c.symbol: GROSS / len(sel) for c in sel} if sel else {}
    return pick


def momrank_picks(closes, have):
    def pick(date, i):
        if i % MONTHLY != 0:
            return None
        elig = sorted(members_on(date) & have)
        if len(elig) < 10:
            return None
        hist = closes[elig].loc[:date]
        if len(hist) < 253:
            return None
        mom = (hist.iloc[-21] / hist.iloc[-252] - 1.0).dropna()
        top = mom[mom > 0].nlargest(MOMRANK_TOP)
        return {s: GROSS / len(top) for s in top.index} if len(top) else {}
    return pick


def gem_winner(closes: pd.DataFrame, date: pd.Timestamp) -> str | None:
    hist = closes.loc[:date]

    def r12(sym: str) -> float | None:
        c = hist[sym].dropna() if sym in hist.columns else pd.Series(dtype=float)
        if len(c) < 253:
            return None
        past = float(c.iloc[-252])
        return float(c.iloc[-1]) / past - 1.0 if past > 0 else None

    rets = {s: v for s in RISK_ETFS if (v := r12(s)) is not None}
    if not rets:
        return None
    top, top_ret = max(rets.items(), key=lambda kv: kv[1])
    cash = r12("BIL") or 0.0
    return top if top_ret > cash else "TLT"


def gem_picks(closes):
    def pick(date, i):
        if i % MONTHLY != 0:
            return None
        w = gem_winner(closes, date)
        return {w: GROSS} if w else None
    return pick


def hold_picks(symbol):
    def pick(date, i):
        return {symbol: GROSS} if i == 0 or i % MONTHLY == 0 else None
    return pick


def blend(curves: dict[str, pd.Series], weights: dict[str, float], capital: float) -> pd.Series:
    rets = pd.DataFrame({k: c.pct_change() for k, c in curves.items()}).dropna()
    w = pd.Series(weights)
    r = (rets * (w / w.sum())).sum(axis=1)
    return (1 + r).cumprod() * capital


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--capital", type=float, default=100_000.0)
    args = p.parse_args()

    # ---- PIT sample --------------------------------------------------------
    members = union_members(args.start, args.end)
    tickers = sorted(members | {"SPY"})
    print(f"PIT union: {len(members)} members; fetching {len(tickers)} tickers...")
    bars = asyncio.run(fetch_batch(tickers, period="10y"))
    have = {t for t in tickers if t in bars}
    print(f"Coverage: {len(have)}/{len(tickers)} ({len(have)/len(tickers)*100:.0f}%)")
    closes = pd.DataFrame({t: bars[t]["close"] for t in have}).sort_index()
    opens = pd.DataFrame({t: bars[t]["open"] for t in have}).sort_index()
    win = (closes.index >= pd.Timestamp(args.start)) & (closes.index <= pd.Timestamp(args.end))
    cal = closes.index[win]

    base = run_weights_backtest(closes, opens, cal, args.capital, breadth_picks(closes, have))
    brd_ovl = run_weights_backtest(
        closes, opens, cal, args.capital, breadth_picks(closes, have), overlay=True
    )
    momrank = run_weights_backtest(closes, opens, cal, args.capital, momrank_picks(closes, have))
    spy_pit = closes["SPY"].loc[cal[0]:cal[-1]]
    spy_pit = spy_pit / spy_pit.iloc[0] * args.capital

    # ---- ETF sample --------------------------------------------------------
    ebars = asyncio.run(fetch_batch(ETFS, period="20y"))
    ec = pd.DataFrame({t: ebars[t]["close"] for t in ETFS if t in ebars}).sort_index()
    eo = pd.DataFrame({t: ebars[t]["open"] for t in ETFS if t in ebars}).sort_index()
    cal_08_17 = ec.index[(ec.index >= "2008-01-01") & (ec.index <= "2017-12-31")]
    cal_18_24 = ec.index[(ec.index >= args.start) & (ec.index <= args.end)]

    spy_bh = run_weights_backtest(ec, eo, cal_08_17, args.capital, hold_picks("SPY"))
    spy_ovl = run_weights_backtest(ec, eo, cal_08_17, args.capital, hold_picks("SPY"), overlay=True)
    gem_early = run_weights_backtest(ec, eo, cal_08_17, args.capital, gem_picks(ec))
    gem_late = run_weights_backtest(ec, eo, cal_18_24, args.capital, gem_picks(ec))

    # ---- Blend proxy (research_stack excluded - not backtestable free) ------
    full = blend(
        {"brd_ovl": brd_ovl, "gem": gem_late.reindex(brd_ovl.index).ffill(), "momrank": momrank},
        {"brd_ovl": 0.30, "gem": 0.30, "momrank": 0.15},
        args.capital,
    )

    rows = [
        metrics(base, "baseline(PIT)"), metrics(brd_ovl, "brd+ovl(PIT)"),
        metrics(momrank, "momrank(PIT)"), metrics(spy_pit, "SPY(PIT)"),
        metrics(spy_bh, "spy 08-17"), metrics(spy_ovl, "spy+ovl 08-17"),
        metrics(gem_early, "gem 08-17"), metrics(gem_late, "gem 18-24"),
        metrics(full, "BLEND(PIT)"),
    ]
    m = {r["label"]: r for r in rows}

    ovl_pass = (
        m["brd+ovl(PIT)"]["Sharpe"] > m["baseline(PIT)"]["Sharpe"]
        and m["brd+ovl(PIT)"]["maxDD%"] > m["baseline(PIT)"]["maxDD%"]
        and m["spy+ovl 08-17"]["Sharpe"] >= m["spy 08-17"]["Sharpe"]
    )
    dm_pass = (
        m["BLEND(PIT)"]["Sharpe"] > m["baseline(PIT)"]["Sharpe"]
        and m["BLEND(PIT)"]["maxDD%"] > m["baseline(PIT)"]["maxDD%"]
        and m["gem 08-17"]["Sharpe"] > 0
    )

    print("\n========== SHIP GATE ==========")
    print(f"OVERLAY:  {'SHIP' if ovl_pass else 'DO NOT SHIP'}")
    print(f"DUAL-MOM: {'SHIP' if dm_pass else 'DO NOT SHIP'}")
    print(f"vs SPY:   blend Sharpe {m['BLEND(PIT)']['Sharpe']} vs SPY {m['SPY(PIT)']['Sharpe']}")
    print("===============================\n")
    print(f"{'variant':16s} {'CAGR%':>7s} {'vol%':>6s} {'Sharpe':>7s} {'maxDD%':>7s}")
    for r in rows:
        print(f"{r['label']:16s} {r['CAGR%']:>7} {r['vol%']:>6} {r['Sharpe']:>7} {r['maxDD%']:>7}")
    print("\nNOTE: blend excludes research_stack (25% live) - not backtestable on")
    print("free PIT data; weights renormalized over the remaining 75%.")
    print("PIT residual gap: delisted names lack free prices (~15%), inflating")
    print("absolute numbers slightly; variant-vs-baseline comparison unaffected.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports and lints cleanly**

Run: `python -c "import scripts.validate_overlay"` then `python -m ruff check scripts/validate_overlay.py`
Expected: no output / no errors

- [ ] **Step 3: Commit**

```bash
cd .. && git add backend/scripts/validate_overlay.py
git -c user.email=aaryanbaadkar71@gmail.com -c user.name=Aaryanxvi commit -m "feat(scripts): ship-gate validation for overlay + dual momentum"
cd backend
```

---

### Task 5: Full regression + lint

- [ ] **Step 1: Full test suite**

Run: `python -m pytest tests/ -q`
Expected: all pass (400+ incl. 18 new). Known pre-existing skips (hmmlearn/redis) are fine.

- [ ] **Step 2: Lint everything**

Run: `python -m ruff check app/ tests/ scripts/`
Expected: 0 errors

- [ ] **Step 3: Commit any stragglers**

```bash
cd .. && git status --short
# if anything intended remains: git add <files> && git -c user.email=aaryanbaadkar71@gmail.com -c user.name=Aaryanxvi commit -m "chore: regression fixes for overlay/dual-mom integration"
cd backend
```

---

### Task 6: Run the validation (ONE-SHOT) and act on the verdict

- [ ] **Step 1: Run**

Run: `python -m scripts.validate_overlay` (network-heavy: PIT membership + ~10y prices for ~800 tickers; minutes, needs internet)
Expected: report with SHIP GATE verdict at top. `baseline(PIT)` Sharpe must land near 0.30 (±0.05) — if it doesn't, STOP: the harness diverged from validate_pit; debug the harness, not the strategy.

- [ ] **Step 2: Act on verdict — no retuning allowed**

- Both SHIP → set `overlay_enabled: bool = True` default in `config.py`; keep sleeve mix as wired. Commit: `feat(strategy): enable risk overlay by default - ship gate passed`.
- Overlay only → enable overlay, revert sleeve mix to breadth .40/research .30/momrank .10 + restore TrendFilterSleeve .20 in the live mix. Commit accordingly.
- Dual-mom only → keep mix, leave `overlay_enabled=False`. Commit accordingly.
- Neither → revert live wiring (mix + flag) to pre-plan state, keep modules + script + tests (research artifacts). Report honestly.

- [ ] **Step 3: Save the report**

Paste the full script output into `docs/superpowers/specs/2026-07-02-risk-overlay-dual-momentum-design.md` under a new `## Validation results (2026-07-02)` section with the verdict. Commit: `docs: overlay/dual-mom validation results + ship decision`.

---

## Self-Review Notes

- Spec coverage: Component 1 → Task 1; Component 2 → Task 2; Component 3 → Task 3 (weights) with the trend_filter deviation documented in the header; Component 4 → Tasks 4+6; Component 5 → Tasks 1–3 tests + Task 5. Rollback → config flag (Task 3) + Task 6 verdict handling.
- Ship-gate criteria in Task 4 code mirror the spec's Success bar, including the second-sample "must not hurt" check (spy+ovl vs spy 2008–17).
- Type consistency: `overlay_scalar(closes, weights, index_close, target)` used identically in Task 1 tests, Task 3 hook; `DualMomentumSleeve.UNIVERSE` used in Task 2 impl and Task 3 tests/wiring.
