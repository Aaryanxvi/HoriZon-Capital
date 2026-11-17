"""Desktop backtest API — run the bar-replay engine from the UI, list and reopen past runs.

Mounted at ``/api/desktop/backtest``. Runs go through ``BacktestEngine`` +
``BacktestBroker`` only: an in-memory simulated broker over ``ohlcv`` bars (Alpaca
market data as fallback). Nothing here touches orders, positions, cash, the KV store
or the bus. One run at a time, as a background task; results are JSON files under
``<data dir>/backtests``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app.backtesting.backtest_engine import BacktestEngine
from app.backtesting.backtest_metrics import BacktestMetrics
from app.backtesting.rule_strategies import STRATEGIES
from app.core.logging import get_logger
from app.quant.metrics_advanced import sortino_ratio

logger = get_logger("api.desktop_backtest")

router = APIRouter(prefix="/api/desktop/backtest", tags=["desktop"])


StrategyName = Literal["momentum", "mean_reversion", "volatility", "crisis"]
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")
_MIN_DATE = date(2000, 1, 1)


class RunRequest(BaseModel):
    strategy: StrategyName = "momentum"
    symbols: list[str] = Field(min_length=1, max_length=10)
    start: date
    end: date
    capital: float = Field(gt=0, le=1e10)

    @field_validator("symbols")
    @classmethod
    def _clean_symbols(cls, v: list[str]) -> list[str]:
        out = list(dict.fromkeys(s.strip().upper() for s in v))
        bad = [s for s in out if not _SYMBOL.match(s)]
        if bad:
            raise ValueError(f"invalid symbol(s): {', '.join(bad)}")
        return out

    @model_validator(mode="after")
    def _check_dates(self) -> RunRequest:
        if self.start < _MIN_DATE:
            raise ValueError(f"start must be on or after {_MIN_DATE}")
        if self.end > datetime.now(UTC).date():
            raise ValueError("end cannot be in the future")
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self


# --- storage ----------------------------------------------------------------

def _dir() -> Path:
    # Read at call time (not import) so tests' per-test HORIZON_DATA_DIR applies.
    base = Path(os.getenv("HORIZON_DATA_DIR", Path.home() / ".horizon-capital"))
    path = base / "backtests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save(run: dict) -> None:
    (_dir() / f"{run['id']}.json").write_text(json.dumps(run), encoding="utf-8")


def _load(run_id: str) -> dict | None:
    path = _dir() / f"{run_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ponytail: one run at a time, process-wide; a queue if anyone ever needs concurrent runs.
_active: dict[str, Any] = {"run": None, "task": None}


# --- execution --------------------------------------------------------------

async def _run_symbol(
    symbol: str, start: datetime, end: datetime, capital: float, strategy
) -> tuple[pd.Series, list[dict]]:
    engine = BacktestEngine(initial_capital=capital)
    bars = await engine._load_bars(symbol, start, end, "1d")  # DB / Alpaca IO stays on this loop
    if bars.empty:
        raise ValueError(f"no daily bars for {symbol} in {start.date()} → {end.date()}")

    async def _preloaded(*_a, **_k) -> pd.DataFrame:
        return bars

    engine._load_bars = _preloaded
    # The bar loop is sync CPU: run it on a worker thread with its own loop.
    result = await asyncio.to_thread(asyncio.run, engine.run(symbol, start, end, strategy))
    curve = pd.Series(result.equity_curve, index=[ts.date().isoformat() for ts in bars.index])
    curve = curve[~curve.index.duplicated(keep="last")]
    trades = [
        {
            "symbol": symbol,
            "date": t["timestamp"].date().isoformat(),
            "side": t["side"],
            "quantity": round(float(t["quantity"]), 4),
            "price": round(float(t["price"]), 4),
            "commission": round(float(t["commission"]), 4),
            "pnl": round(float(t["pnl"]), 2),
        }
        for t in result.trades
    ]
    return curve, trades


def _metrics(curve: pd.Series, trades: list[dict]) -> dict[str, float]:
    eq = curve.to_numpy(dtype=float)
    rets = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([])
    days = (date.fromisoformat(curve.index[-1]) - date.fromisoformat(curve.index[0])).days
    total = eq[-1] / eq[0] - 1 if len(eq) else 0.0
    cagr = (eq[-1] / eq[0]) ** (365.25 / days) - 1 if days > 0 and eq[0] > 0 else 0.0
    return {
        "total_return": round(float(total), 6),
        "cagr": round(float(cagr), 6),
        "sharpe": round(BacktestMetrics.sharpe_ratio(rets), 4),
        "sortino": round(sortino_ratio(rets), 4),
        "max_drawdown": round(BacktestMetrics.max_drawdown(eq), 6),
        "win_rate": round(BacktestMetrics.win_rate(trades), 4),
        "trades": len(trades),
        "round_trips": sum(1 for t in trades if t["side"] == "SELL"),
    }


async def _execute(run: dict) -> None:
    started = time.monotonic()
    try:
        start = datetime.fromisoformat(run["start"]).replace(tzinfo=UTC)
        end = datetime.fromisoformat(run["end"]).replace(hour=23, minute=59, second=59, tzinfo=UTC)
        strategy = STRATEGIES[run["strategy"]][0]
        per_symbol = run["capital"] / len(run["symbols"])

        curves, trades = [], []
        for sym in run["symbols"]:
            curve, sym_trades = await _run_symbol(sym, start, end, per_symbol, strategy)
            curves.append(curve)
            trades.extend(sym_trades)

        # Equal-weight book: each sleeve holds its cash until its first bar, then carries forward.
        book = pd.concat(curves, axis=1).sort_index().ffill().fillna(per_symbol).sum(axis=1)
        trades.sort(key=lambda t: t["date"])

        spy = await BacktestEngine()._load_bars("SPY", start, end, "1d")
        benchmark = (
            [{"date": ts.date().isoformat(), "close": float(c)} for ts, c in spy["close"].items()]
            if not spy.empty
            else []
        )

        run.update(
            status="done",
            equity=[{"date": d, "value": round(float(v), 2)} for d, v in book.items()],
            benchmark=benchmark,
            trades=trades,
            metrics=_metrics(book, trades),
            final_capital=round(float(book.iloc[-1]), 2),
        )
    except Exception as exc:  # surfaced to the UI as the run's error
        logger.warning("desktop_backtest_failed", run_id=run["id"], error=str(exc))
        run.update(status="error", error=str(exc))
    finally:
        run["elapsed_s"] = round(time.monotonic() - started, 2)
        run.pop("started_monotonic", None)
        _save(run)
        _active["run"] = None
        _active["task"] = None


# --- endpoints --------------------------------------------------------------

@router.get("/strategies")
async def strategies() -> dict[str, Any]:
    return {
        "strategies": [{"name": k, "description": v[1]} for k, v in STRATEGIES.items()],
        "max_symbols": 10,
        "min_date": _MIN_DATE.isoformat(),
    }


@router.post("/run", status_code=202)
async def start_run(req: RunRequest) -> dict[str, Any]:
    if _active["run"] is not None:
        raise HTTPException(409, f"backtest {_active['run']['id']} is still running")
    run = {
        "id": uuid.uuid4().hex[:12],
        "status": "running",
        "strategy": req.strategy,
        "symbols": req.symbols,
        "start": req.start.isoformat(),
        "end": req.end.isoformat(),
        "capital": req.capital,
        "created_at": datetime.now(UTC).isoformat(),
        "started_monotonic": time.monotonic(),
    }
    _active["run"] = run
    _active["task"] = asyncio.create_task(_execute(run))
    return {"id": run["id"], "status": "running"}


def _summary(run: dict) -> dict[str, Any]:
    keys = ("id", "status", "strategy", "symbols", "start", "end", "capital",
            "created_at", "elapsed_s", "error", "metrics", "final_capital")
    return {k: run.get(k) for k in keys}


def _with_elapsed(run: dict) -> dict[str, Any]:
    out = {k: v for k, v in run.items() if k != "started_monotonic"}
    if "started_monotonic" in run:
        out["elapsed_s"] = round(time.monotonic() - run["started_monotonic"], 1)
    return out


@router.get("/runs")
async def list_runs() -> dict[str, Any]:
    runs = []
    for path in _dir().glob("*.json"):
        try:
            runs.append(_summary(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    active = _active["run"]
    if active is not None:
        runs.insert(0, _summary(_with_elapsed(active)))
    return {"runs": runs, "active": active["id"] if active else None}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{12}", run_id):
        raise HTTPException(422, "invalid run id")
    active = _active["run"]
    if active is not None and active["id"] == run_id:
        return _with_elapsed(active)
    run = _load(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run
