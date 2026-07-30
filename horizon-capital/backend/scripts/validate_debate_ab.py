"""Pre-registered A/B: does the LLM debate gate earn its place? (paper Sec. VII)

Replays the PRODUCTION sleeve mix over PIT data and asks the REAL
``MultiModelDebateEngine`` to rule on every signal the live StrategyAgent would
have emitted. Two arms share one identical signal stream, one identical fill
model, and one identical set of debate verdicts:

  Arm A (no gate)  every signal executes            <- the published production mix
  Arm B (gate on)  only APPROVED signals execute; a rejected signal leaves that
                   symbol at its previous target weight (the gate vetoes the
                   TRADE, entries and exits alike -- same as live)

Why a replay and not a live forward test: the pre-registered metrics include
Sharpe, max drawdown and turnover, which need hundreds of trades. Live paper
trading emits a handful per week. The replay buys statistical power; the price
is hindsight leakage, which we measure rather than assume away:

  --mode blind    (PRIMARY)     ticker and date are withheld. Debaters see only
                                numeric features. An LLM cannot recall "AAPL in
                                March 2020" from "momentum pct 0.81, below 200d".
  --mode unblind  (SENSITIVITY) real ticker + as-of date in the prompt. The
                                blind-vs-unblind gap IS the leakage estimate.

PRE-REGISTERED, fixed before any LLM was called:
  * SANITY GATE. Arm A must reproduce the published production mix within
    +/-0.02 Sharpe (0.77) and +/-1.0 pt maxDD (-18.0%). If it does not, this
    harness is not replaying the published system and NO result ships.
  * ACCEPTANCE. The gate earns a permanent place iff Arm B Sharpe >= Arm A
    Sharpe AND counterfactual P&L of rejected trades is non-positive (i.e. the
    vetoed trades would not have made money). Otherwise it reverts to advisory.
  * An adverse verdict is reported, not rerun with different settings.

Debate verdicts are cached to JSONL keyed by (mode, date, symbol, delta-weight),
so a crashed or rate-limited run resumes without paying for the same debate
twice, and both arms provably consume the same verdicts.

Usage:
    python scripts/validate_debate_ab.py --dry-run          # count signals, $0
    python scripts/validate_debate_ab.py --mode blind
    python scripts/validate_debate_ab.py --mode unblind
    python scripts/validate_debate_ab.py --selfcheck        # no data/network
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data_layer.batch_bars import fetch_batch  # noqa: E402
from app.data_layer.pit_universe import members_on, union_members  # noqa: E402
from app.data_layer.universe import _ANCHORS, get_universe  # noqa: E402
from scripts.validate_breadth import _mtm  # noqa: E402

# The published attribution harness is the reference implementation for the
# replay: same sleeve construction, same PIT config, same production weights.
# Reused rather than re-derived so the two cannot drift.
from scripts.validate_sleeve_attribution import (  # noqa: E402
    LIVE_CFG,
    _base,
    _loo_weights,
    _make_sleeves,
    _targets,
    metrics,
)

COMMISSION_BPS = 1.0
SLIPPAGE_BPS = 2.0
TRADING_DAYS = 252
RF = 0.04
MIN_TRADE_NAV = 0.002

# Live StrategyAgent constants, mirrored exactly (strategy_agent.py).
MIN_WEIGHT_DELTA = 0.005          # 50 bps -- below this no SIGNAL is emitted
STRENGTH_SCALE = 0.5              # strength = min(|dw| / 0.5, 1.0)

# Rate-limit handling. A debate lost to a tokens-per-minute cap is a gap, not a
# verdict, and gaps fail closed -- so retry rather than let throttling bias the
# gate toward rejection.
RETRIES = 5
BACKOFF_BASE = 8.0                # seconds; 8, 16, 32, 64 between attempts

# The production mix == the published mix minus breadth_alpha, renormalized:
# research .500 / trend .333 / momrank .167. Derived, not retyped, so it stays
# identical to the arm that produced Table I.
PROD_WEIGHTS = _loo_weights("breadth_alpha")

# Pre-registered sanity gate (Table I, "Production mix" row).
REF_SHARPE, REF_MAXDD = 0.77, -18.0
SHARPE_TOL, MAXDD_TOL = 0.02, 1.0

# ROOT is backend/, so the paper sits one level up beside it -- NOT two, which
# would land outside the inner repo.
PAPER_DIR = ROOT.parent / "own research paper"

# USD per 1M tokens (input, output), for the run-cost PROJECTION only. List
# prices as of 2026-07; verify against the provider's billing page before
# trusting a number here -- this is a budget guard, not an invoice.
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
    "claude-sonnet-4-20250514": (3.00, 15.00),
}


def project_cost(verdicts: dict[str, dict], mode: str, total_signals: int) -> str:
    """Extrapolate full-run cost from the debates actually paid for so far.

    Token counts are estimated from character length (~4 chars/token) because
    the provider wrappers return text only. Treat the figure as +/-30%.
    """
    done = [r for r in verdicts.values()
            if r.get("mode") == mode and r.get("decision") in ("APPROVED", "REJECTED")]
    if not done:
        return "no completed debates yet -- cannot project"

    in_tok = sum(r.get("prompt_chars", 0) for r in done) / 4
    out_tok = sum(r.get("output_chars", 0) for r in done) / 4
    # Split the token spend across the providers that actually argued.
    per_debate_in, per_debate_out = in_tok / len(done), out_tok / len(done)

    lines = [f"Cost projection from {len(done)} completed debates "
             f"(~{per_debate_in:,.0f} in / {per_debate_out:,.0f} out tokens each):"]
    models = done[-1].get("models", {})
    if not models:
        return "\n".join(lines + ["  model ids not recorded -- rerun to project"])

    share = 1.0 / len(models)
    total = 0.0
    for name, model in sorted(models.items()):
        p_in, p_out = PRICES.get(model, (0.0, 0.0))
        if not p_in and not p_out:
            lines.append(f"  {name:8s} {model:26s} unknown pricing -- excluded")
            continue
        cost = (per_debate_in * share * p_in + per_debate_out * share * p_out) / 1e6
        full = cost * total_signals
        total += full
        lines.append(f"  {name:8s} {model:26s} ${cost * 1000:.4f}/1k debates "
                     f"-> ${full:.2f} for all {total_signals}")
    lines.append(f"  PROJECTED FULL RUN (this mode): ${total:.2f}  "
                 f"(both modes ~${total * 2:.2f}) -- estimate, +/-30%")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Null bus -- the debate engine publishes lifecycle messages; in a harness there
# is no subscriber, and a real queue would grow to ~10 msgs x thousands of
# debates for nobody to read.
# ----------------------------------------------------------------------------

class _NullBus:
    async def publish(self, message) -> None:  # noqa: ANN001, D102
        return None


# ----------------------------------------------------------------------------
# Phase 1 -- signal stream (no LLM, deterministic)
# ----------------------------------------------------------------------------

def _features(closes: pd.DataFrame, spy_col: str, symbol: str,
              date: pd.Timestamp) -> dict[str, str]:
    """Blind-safe numeric context for one symbol at one date.

    Deliberately contains no ticker, no date, no price level -- an LLM must not
    be able to identify the asset or the era from these numbers alone.
    """
    out: dict[str, str] = {}
    if symbol not in closes.columns:
        return out
    px = closes[symbol].loc[:date].dropna()
    if len(px) < 260:
        return out

    # 12-1 momentum (skip the most recent month), the sleeve's own signal.
    mom = px.iloc[-21] / px.iloc[-252] - 1.0
    # Rank it against every symbol priced on this date -> scale-free percentile.
    row = closes.loc[:date]
    if len(row) >= 252:
        peers = (row.iloc[-21] / row.iloc[-252] - 1.0).dropna()
        pct = float((peers < mom).mean()) if len(peers) > 10 else float("nan")
    else:
        pct = float("nan")

    rets = px.pct_change().dropna()
    vol20 = float(rets.tail(20).std() * np.sqrt(TRADING_DAYS))
    sma200 = float(px.tail(200).mean())
    dd = float(px.iloc[-1] / px.tail(252).max() - 1.0)

    spy = closes[spy_col].loc[:date].dropna()
    spy_rets = spy.pct_change().dropna()
    joined = pd.concat([rets.tail(60), spy_rets.tail(60)], axis=1).dropna()
    corr = float(joined.iloc[:, 0].corr(joined.iloc[:, 1])) if len(joined) > 30 else float("nan")
    regime = "RISK_ON" if len(spy) >= 200 and spy.iloc[-1] > spy.tail(200).mean() else "RISK_OFF"

    out["12-1 momentum (cross-sectional percentile)"] = (
        "n/a" if np.isnan(pct) else f"{pct:.2f}"
    )
    out["price vs 200d SMA"] = f"{px.iloc[-1] / sma200 - 1.0:+.1%}"
    out["realized vol (20d, annualized)"] = f"{vol20:.1%}"
    out["drawdown from 52w high"] = f"{dd:.1%}"
    out["60d return correlation to market index"] = (
        "n/a" if np.isnan(corr) else f"{corr:.2f}"
    )
    out["market regime (index vs its 200d SMA)"] = regime
    return out


def build_signal_stream(bars, closes, opens, calendar, config_universe, spy_col):
    """Replay the production mix and record every SIGNAL live would emit.

    Sleeve targets are a pure function of bars and date -- they do not depend on
    the portfolio. That is what lets both arms consume a byte-identical signal
    stream even after their holdings diverge, which is the whole premise of the
    experiment.
    """
    sleeves = _make_sleeves(PROD_WEIGHTS)
    cache: dict[str, list] = {}
    last_emitted: dict[str, float] = {}
    stream: list[dict] = []

    for i, date in enumerate(calendar):
        if i % 5 != 0 or i + 1 >= len(calendar):
            continue

        if LIVE_CFG["universe"] == "pit":
            elig = members_on(date)
            view = {s: df for s, df in bars.items() if s in _ANCHORS or _base(s) in elig}
        else:
            view = {s: df for s, df in bars.items() if s in config_universe}
        h = LIVE_CFG["hist"]
        view = {s: df.loc[:date].tail(h) if h else df.loc[:date] for s, df in view.items()}
        view = {s: df for s, df in view.items() if len(df) > 2}

        targets = _targets(sleeves, cache, view, date, i, LIVE_CFG["cap"])

        # Mirror _emit_signals_from_targets: union of new and previously held
        # targets (so exits are emitted), sells first, biggest delta first.
        union = set(targets) | set(last_emitted)
        ordered = sorted(
            union,
            key=lambda s: (
                (d := targets.get(s, 0.0) - last_emitted.get(s, 0.0)) >= 0,
                -abs(d),
            ),
        )
        for symbol in ordered:
            new_w = targets.get(symbol, 0.0)
            old_w = last_emitted.get(symbol, 0.0)
            dw = new_w - old_w
            if abs(dw) < MIN_WEIGHT_DELTA:
                continue
            stream.append({
                "bar_index": i,
                "date": date.isoformat(),
                "fill_date": calendar[i + 1].isoformat(),
                "symbol": symbol,
                "direction": 1 if dw > 0 else -1,
                "strength": min(abs(dw) / STRENGTH_SCALE, 1.0),
                "target_weight": new_w,
                "previous_weight": old_w,
                "features": _features(closes, spy_col, symbol, date),
            })
            last_emitted[symbol] = new_w

        # Snapshot the full target vector so the executor never recomputes it.
        stream.append({"bar_index": i, "date": date.isoformat(),
                       "targets_snapshot": dict(targets)})

    return stream


# ----------------------------------------------------------------------------
# Phase 2 -- debates (LLM, cached, concurrent)
# ----------------------------------------------------------------------------

def _prompt_chars(symbol: str, action: str, signal_data: dict, regime: str | None,
                  arguments: list) -> int:
    """Total input characters billed across both rounds of one debate.

    Round 1: the shared context prompt + one role prompt, per debater.
    Round 2: the same, plus round 1's transcript appended for every debater.
    """
    from app.agents.debate.debate_engine import DEBATER_ROLES, _build_user_prompt

    base = len(_build_user_prompt(symbol, action, signal_data, regime, None, None))
    roles = sum(len(p) for p in DEBATER_ROLES.values())
    n = len(DEBATER_ROLES)
    r1 = base * n + roles
    transcript = sum(len(a.argument[:500]) + 80 for a in arguments if a.round_number == 1)
    r2 = (base + transcript) * n + roles if any(a.round_number == 2 for a in arguments) else 0
    return r1 + r2


def subsample(signals: list[dict], n: int) -> list[dict]:
    """Evenly-spaced deterministic subsample, preserving chronological spread.

    Deterministic so the unblind arm debates exactly the signals the blind arm
    already ruled on, making the two directly pairable. Evenly spaced rather
    than "first N" so the sample spans the whole 2018-2024 window instead of
    just its first months.
    """
    if n >= len(signals):
        return signals
    step = len(signals) / n
    return [signals[int(i * step)] for i in range(n)]


def _cache_key(mode: str, sig: dict) -> str:
    raw = f"{mode}|{sig['date']}|{sig['symbol']}|{sig['target_weight']:.6f}|" \
          f"{sig['previous_weight']:.6f}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _signal_payload(sig: dict, mode: str) -> tuple[str, dict]:
    """Build the (symbol, signal_data) the debate engine sees.

    Blind mode substitutes a neutral alias and withholds the date; unblind adds
    both back. Everything else is identical, so the two arms differ in exactly
    one variable.
    """
    features = dict(sig["features"])
    if mode == "unblind":
        features["as-of date"] = sig["date"][:10]
        symbol = sig["symbol"]
    else:
        symbol = "ASSET (identity withheld)"
    return symbol, {
        "signal_id": _cache_key(mode, sig),
        "strength": round(sig["strength"], 3),
        "strategy_name": "sleeve_system",
        "target_price": None,
        "stop_loss": None,
        "target_weight": round(sig["target_weight"], 4),
        "previous_weight": round(sig["previous_weight"], 4),
        "features": features,
    }


async def run_debates(signals: list[dict], mode: str, concurrency: int,
                      cache_path: Path, limit: int | None,
                      model_overrides: dict[str, str],
                      only: list[str] | None = None) -> dict[str, dict]:
    """Debate every signal once; return {cache_key: verdict record}."""
    from app.agents.debate.multi_model_debate import MultiModelDebateEngine
    from app.llm.provider_registry import provider_registry

    provider_registry.auto_register_from_settings()
    available = provider_registry.list_available()
    if not available:
        raise SystemExit(
            "No LLM providers registered. Set OPENAI_API_KEY / GOOGLE_API_KEY / "
            "ANTHROPIC_API_KEY in backend/.env, then re-run."
        )
    # Pin exact model ids -- the paper has to name the models that produced the
    # result, and cheaper tiers keep a 8k-call run affordable.
    for name, model in model_overrides.items():
        base = provider_registry.get_provider(name)
        if base is not None:
            provider_registry._providers[name] = base.with_model(model)
    # Restricting providers is a correctness control, not a preference: a
    # provider that is registered but out of quota fails every call, and the
    # engine turns a failed call into an ABSTAIN. Excluding it outright beats
    # letting a dead vendor abstain its way through the experiment.
    if only:
        unknown = [n for n in only if n not in available]
        if unknown:
            raise SystemExit(f"--providers {unknown} not registered (have {available})")
        available = only
    models = {n: getattr(provider_registry.get_provider(n), "model", "?") for n in available}
    print(f"Providers: {', '.join(f'{n} ({m})' for n, m in sorted(models.items()))}")

    cached: dict[str, dict] = {}
    if cache_path.exists():
        with cache_path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # ERROR records are failures, not verdicts -- drop them so the
                # signal is retried instead of permanently failing closed.
                if rec.get("decision") == "ERROR":
                    cached.pop(rec["key"], None)
                    continue
                cached[rec["key"]] = rec
        print(f"Resuming: {len(cached)} usable debates cached in {cache_path.name}")

    todo = [s for s in signals if _cache_key(mode, s) not in cached]
    if limit is not None:
        todo = todo[:limit]
    print(f"Debates to run: {len(todo)} (of {len(signals)} signals)")
    if not todo:
        return cached

    engine = MultiModelDebateEngine(registry=provider_registry, bus=_NullBus(), max_rounds=2)
    sem = asyncio.Semaphore(concurrency)
    done = 0
    lock = asyncio.Lock()
    fh = cache_path.open("a", encoding="utf-8")

    async def one(sig: dict) -> None:
        nonlocal done
        key = _cache_key(mode, sig)
        symbol, signal_data = _signal_payload(sig, mode)
        action = "BUY" if sig["direction"] > 0 else "SELL"
        regime = sig["features"].get("market regime (index vs its 200d SMA)")
        # Token-per-minute limits are transient, so a debate lost to one is not
        # a result -- it is a gap that would fail closed and bias Arm B toward
        # rejection. Retry with backoff, holding the semaphore slot so the
        # wait also throttles the run instead of hammering a limited endpoint.
        rec: dict | None = None
        for attempt in range(RETRIES):
            rec = await attempt_debate(sig, key, symbol, signal_data, action, regime)
            if rec["decision"] != "ERROR":
                break
            if attempt < RETRIES - 1:
                async with sem:
                    await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
        assert rec is not None
        async with lock:
            cached[key] = rec
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            done += 1
            if done % 25 == 0 or done == len(todo):
                errs = sum(1 for r in cached.values() if r.get("decision") == "ERROR")
                print(f"  ...{done}/{len(todo)} debates ({errs} still failing)")

    async def attempt_debate(sig: dict, key: str, symbol: str, signal_data: dict,
                             action: str, regime: str | None) -> dict:
        async with sem:
            t0 = time.perf_counter()
            try:
                res = await engine.run_debate(
                    symbol=symbol,
                    action=action,
                    signal_data=signal_data,
                    regime=regime,
                    sentiment=None,
                    risk_metrics=None,
                    allowed_providers=available,
                )
            except Exception as exc:  # provider outage, quota, parse blowup
                rec = {"key": key, "mode": mode, "date": sig["date"],
                       "symbol": sig["symbol"], "decision": "ERROR",
                       "error": str(exc)[:300]}
            else:
                # The engine converts a failed provider call into an ABSTAIN
                # vote. A rate-limited call would therefore look like a debater
                # genuinely declining to judge, and abstentions count toward
                # neither side -- so a quota error would silently reshape the
                # consensus. Refuse any debate containing one; it stays
                # uncached and is retried on the next run.
                failed = [a for a in res.arguments if a.argument.startswith("Error from ")]
                if failed:
                    rec = {"key": key, "mode": mode, "date": sig["date"],
                           "symbol": sig["symbol"], "decision": "ERROR",
                           "error": f"{len(failed)}/{len(res.arguments)} provider calls "
                                    f"failed: {failed[0].argument[:160]}"}
                else:
                    rec = {
                        "key": key, "mode": mode, "date": sig["date"],
                        "symbol": sig["symbol"], "action": action,
                        "decision": res.decision,
                        "consensus_score": res.consensus_score,
                        "for_count": res.for_count,
                        "against_count": res.against_count,
                        "abstain_count": res.abstain_count,
                        "rounds": res.rounds,
                        "providers": res.providers_used,
                        "models": models,
                        "llm_calls": len(res.arguments),
                        "latency_ms": round((time.perf_counter() - t0) * 1000),
                        # Character counts feed the cost projection. Round 2
                        # carries round 1's transcript, so input is charged
                        # roughly twice.
                        "prompt_chars": _prompt_chars(symbol, action, signal_data,
                                                      regime, res.arguments),
                        "output_chars": sum(len(a.argument) for a in res.arguments),
                        "votes": [
                            {"role": a.role, "provider": a.provider,
                             "round": a.round_number, "vote": a.vote,
                             "confidence": a.confidence}
                            for a in res.arguments
                        ],
                    }
        return rec

    try:
        await asyncio.gather(*(one(s) for s in todo))
    finally:
        fh.close()
    return cached


# ----------------------------------------------------------------------------
# Phase 3 -- execution A/B (identical fill model, mirrors the attribution run)
# ----------------------------------------------------------------------------

def execute(stream: list[dict], verdicts: dict[str, dict] | None, mode: str,
            closes: pd.DataFrame, opens: pd.DataFrame, calendar: pd.DatetimeIndex,
            capital: float):
    """Replay one arm. ``verdicts=None`` -> Arm A (every signal executes).

    Arm B applies a signal only on an APPROVED verdict; a rejected signal leaves
    that symbol pinned at its previous target, which is what a binding gate does
    to entries and exits alike. Missing/ERROR verdicts fail CLOSED (rejected),
    matching the live engine's no-provider semantics.
    """
    by_bar: dict[int, dict] = {}
    for rec in stream:
        slot = by_bar.setdefault(rec["bar_index"], {"signals": [], "snapshot": {}})
        if "targets_snapshot" in rec:
            slot["snapshot"] = rec["targets_snapshot"]
        else:
            slot["signals"].append(rec)

    effective: dict[str, float] = {}
    cash, shares = capital, {}
    pending: dict[str, float] | None = None
    equity: dict[pd.Timestamp, float] = {}
    gross_samples: list[float] = []
    traded_notional = 0.0
    n_fills = 0
    rejected: list[dict] = []

    for i, date in enumerate(calendar):
        if pending is not None:
            nav_open = _mtm(opens, shares, date, cash)
            if not np.isnan(nav_open):
                deltas = []
                for s in set(list(shares) + list(pending)):
                    if s not in opens.columns or date not in opens.index:
                        continue
                    px = opens[s].get(date, np.nan)
                    if np.isnan(px) or px <= 0:
                        continue
                    tgt = nav_open * pending.get(s, 0.0) / px
                    d = tgt - shares.get(s, 0.0)
                    if abs(d * px) >= nav_open * MIN_TRADE_NAV:
                        deltas.append((s, px, d))
                # Sells first so proceeds fund the buys (live ordering).
                for s, px, d in sorted(deltas, key=lambda t: t[2]):
                    buy, qty = d > 0, abs(d)
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
                    traded_notional += qty * ex
                    n_fills += 1
            pending = None

        nav = _mtm(closes, shares, date, cash)
        equity[date] = nav
        if not np.isnan(nav) and nav > 0:
            gross_samples.append((nav - cash) / nav)

        slot = by_bar.get(i)
        if slot is None:
            continue
        for sig in slot["signals"]:
            if verdicts is None:
                effective[sig["symbol"]] = sig["target_weight"]
                continue
            rec = verdicts.get(_cache_key(mode, sig))
            if rec is not None and rec.get("decision") == "APPROVED":
                effective[sig["symbol"]] = sig["target_weight"]
            else:
                rejected.append({**sig, "verdict": (rec or {}).get("decision", "MISSING")})
        # Symbols the sleeves dropped entirely and that carry no live weight.
        pending = {s: w for s, w in effective.items() if w > 0}

    eq = pd.Series(equity).dropna()
    avg_gross = float(np.mean(gross_samples)) if gross_samples else 0.0
    years = len(eq) / TRADING_DAYS if len(eq) else 1.0
    # Turnover: one-way traded notional per year as a multiple of average equity.
    turnover = traded_notional / (eq.mean() * years) if len(eq) and years > 0 else 0.0
    return eq, avg_gross, {"fills": n_fills, "turnover": turnover, "rejected": rejected}


# ----------------------------------------------------------------------------
# Phase 4 -- counterfactual P&L of vetoed trades
# ----------------------------------------------------------------------------

def counterfactual_pnl(rejected: list[dict], closes: pd.DataFrame,
                       opens: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict:
    """What the vetoed trades would have earned, in NAV percentage points.

    Each rejected signal is a weight change ``dw`` that never happened. Its
    counterfactual contribution is ``dw x forward return`` from the fill bar
    (t+1 open) to the next signal on that symbol -- the horizon the position
    would actually have been held for. Positive total = the gate cost money.
    """
    next_signal: dict[str, list[pd.Timestamp]] = {}
    for sig in rejected:
        next_signal.setdefault(sig["symbol"], []).append(pd.Timestamp(sig["date"]))

    total = 0.0
    wins = 0
    counted = 0
    detail: list[dict] = []
    for sig in rejected:
        sym = sig["symbol"]
        if sym not in opens.columns or sym not in closes.columns:
            continue
        fill = pd.Timestamp(sig["fill_date"])
        if fill not in opens.index:
            continue
        entry = opens[sym].get(fill, np.nan)
        if np.isnan(entry) or entry <= 0:
            continue
        # Hold until the next signal on this symbol, else to the end of the run.
        later = [d for d in next_signal[sym] if d > pd.Timestamp(sig["date"])]
        exit_date = min(later) if later else calendar[-1]
        px = closes[sym].loc[:exit_date].dropna()
        if px.empty:
            continue
        fwd = float(px.iloc[-1] / entry - 1.0)
        dw = sig["target_weight"] - sig["previous_weight"]
        contrib = dw * fwd
        total += contrib
        counted += 1
        if contrib > 0:
            wins += 1
        detail.append({
            "date": sig["date"][:10], "symbol": sym,
            "action": "BUY" if dw > 0 else "SELL",
            "dw_pct": dw * 100, "fwd_ret_pct": fwd * 100,
            "contrib_pct": contrib * 100,
            "held_to": str(exit_date.date()),
        })
    return {
        "total_pct": total * 100,
        "counted": counted,
        "win_rate": (wins / counted * 100) if counted else 0.0,
        "detail": detail,
    }


def print_examples(cf: dict, n: int = 6) -> None:
    """Show the individual vetoes that moved the number most, both directions.

    An aggregate counterfactual hides whether the gate made a few large correct
    calls or many small wrong ones. These are the trades a reader will want to
    check by hand.
    """
    detail = cf.get("detail", [])
    if not detail:
        print("\n(no rejected trades with price coverage to show)")
        return
    ranked = sorted(detail, key=lambda d: d["contrib_pct"])

    def block(title: str, rows: list[dict]) -> None:
        print(f"\n{title}")
        print(f"  {'date':11s} {'symbol':14s} {'act':4s} {'dweight':>8s} "
              f"{'fwd ret':>9s} {'NAV impact':>11s}  held to")
        for d in rows:
            print(f"  {d['date']:11s} {d['symbol']:14s} {d['action']:4s} "
                  f"{d['dw_pct']:+7.2f}% {d['fwd_ret_pct']:+8.1f}% "
                  f"{d['contrib_pct']:+10.2f}%  {d['held_to']}")

    block(f"Gate's best calls -- vetoed trades that WOULD have lost money "
          f"(top {n}):", ranked[:n])
    block(f"Gate's worst calls -- vetoed trades that WOULD have made money "
          f"(top {n}):", list(reversed(ranked[-n:])))


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------

def placebo_arms(stream: list[dict], signals: list[dict], mode: str,
                 reject_rate: float, closes: pd.DataFrame, opens: pd.DataFrame,
                 calendar: pd.DatetimeIndex, capital: float,
                 trials: int = 25) -> dict:
    """Arm C: gates that reject at Arm B's rate but choose at random.

    A gate that vetoes 40% of trades mechanically cuts exposure and turnover,
    and in a bull sample that alone can move Sharpe. So "Arm B beat Arm A" does
    not establish that the LLM chose *well* -- only that it traded less. This
    control holds the rejection RATE fixed and destroys the CHOICE, using a
    deterministic hash per trial so the result is reproducible without an RNG.

    Arm B is only evidence of judgment if it beats this distribution.
    """
    sharpes: list[float] = []
    fills: list[int] = []
    for trial in range(trials):
        fake: dict[str, dict] = {}
        for sig in signals:
            key = _cache_key(mode, sig)
            # Deterministic pseudo-random accept/reject at the target rate.
            h = int(hashlib.sha1(f"{trial}|{key}".encode()).hexdigest()[:8], 16)
            approve = (h % 10_000) / 10_000.0 >= reject_rate
            fake[key] = {"decision": "APPROVED" if approve else "REJECTED", "mode": mode}
        eq, gross, info = execute(stream, fake, mode, closes, opens, calendar, capital)
        sharpes.append(metrics(eq, "placebo", gross)["Sharpe"])
        fills.append(info["fills"])
    arr = np.array(sharpes)
    return {
        "trials": trials,
        "reject_rate": reject_rate,
        "sharpe_mean": float(arr.mean()),
        "sharpe_std": float(arr.std()),
        "sharpe_p5": float(np.percentile(arr, 5)),
        "sharpe_p95": float(np.percentile(arr, 95)),
        "fills_mean": float(np.mean(fills)),
        "sharpes": sharpes,
    }


def _vote_stats(verdicts: dict[str, dict], mode: str) -> dict:
    recs = [r for r in verdicts.values() if r.get("mode") == mode]
    ok = [r for r in recs if r.get("decision") in ("APPROVED", "REJECTED")]
    votes = [v for r in ok for v in r.get("votes", [])]
    by_role: dict[str, dict[str, int]] = {}
    by_provider: dict[str, dict[str, int]] = {}
    for v in votes:
        by_role.setdefault(v["role"], {}).setdefault(v["vote"], 0)
        by_role[v["role"]][v["vote"]] += 1
        by_provider.setdefault(v["provider"], {}).setdefault(v["vote"], 0)
        by_provider[v["provider"]][v["vote"]] += 1
    lat = [r["latency_ms"] for r in ok if "latency_ms" in r]
    calls = sum(r.get("llm_calls", 0) for r in ok)
    # Provider disagreement: debates where FOR and AGAINST were both cast.
    split = sum(1 for r in ok if r.get("for_count", 0) > 0 and r.get("against_count", 0) > 0)
    return {
        "debates": len(ok),
        "errors": len(recs) - len(ok),
        "approved": sum(1 for r in ok if r["decision"] == "APPROVED"),
        "rejected": sum(1 for r in ok if r["decision"] == "REJECTED"),
        "median_latency_ms": int(np.median(lat)) if lat else 0,
        "llm_calls": calls,
        "disagreement_pct": (split / len(ok) * 100) if ok else 0.0,
        "by_role": by_role,
        "by_provider": by_provider,
    }


def emit_latex(a: dict, b: dict, cf: dict, stats: dict, mode: str) -> str:
    """Table VI body rows, ready to paste into the paper verbatim."""
    pct = r"\%"
    rej = stats["rejected"] / stats["debates"] * 100 if stats["debates"] else 0.0
    eol = r"\\"
    return "\n".join([
        f"% --- paste into Table \\ref{{tab:abtest}} (mode={mode}) ---",
        f"Trades executed & {a['fills']} & {b['fills']} {eol}",
        f"Rejection rate & n/a & {rej:.1f}{pct} {eol}",
        f"Counterfactual P\\&L of rejections & n/a & {cf['total_pct']:+.2f}{pct} {eol}",
        f"CAGR & {a['CAGR%']:.1f}{pct} & {b['CAGR%']:.1f}{pct} {eol}",
        f"Volatility & {a['vol%']:.1f}{pct} & {b['vol%']:.1f}{pct} {eol}",
        f"Sharpe ratio & {a['Sharpe']:.2f} & {b['Sharpe']:.2f} {eol}",
        f"Max drawdown & ${a['maxDD%']:.1f}{pct}$ & ${b['maxDD%']:.1f}{pct}$ {eol}",
        f"Turnover ($\\times$ NAV/yr) & {a['turnover']:.2f} & {b['turnover']:.2f} {eol}",
    ])


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

async def amain() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--mode", choices=("blind", "unblind"), default="blind")
    p.add_argument("--concurrency", type=int, default=6)
    p.add_argument("--limit", type=int, default=None,
                   help="cap debates this run (pilot / budget control); resumes later")
    p.add_argument("--dry-run", action="store_true",
                   help="build the signal stream and stop -- no LLM calls, no cost")
    p.add_argument("--openai-model", default=None,
                   help="pin the OpenAI model (default gpt-4o; gpt-4o-mini is ~15x cheaper)")
    p.add_argument("--gemini-model", default=None,
                   help="pin the Gemini model (default gemini-2.0-flash)")
    p.add_argument("--providers", default=None,
                   help="comma-separated subset to debate with, e.g. 'openai'. "
                        "Use to exclude a registered-but-out-of-quota provider, "
                        "whose failed calls would otherwise register as ABSTAIN.")
    p.add_argument("--sample", type=int, default=None,
                   help="debate a deterministic evenly-spaced subsample of N "
                        "signals. For the unblind sensitivity arm, which is a "
                        "PAIRED comparison against blind and does not need full "
                        "coverage. Never use for the primary (blind) arm: its "
                        "Arm B is a portfolio path, and un-debated signals fail "
                        "closed.")
    args = p.parse_args()
    model_overrides = {k: v for k, v in
                       (("openai", args.openai_model), ("gemini", args.gemini_model))
                       if v}

    from app.agents.front_office.strategy.sleeves import momentum_rank
    momentum_rank._TOP_N = 3  # validated top-3, pinned for every arm

    config_universe = get_universe("config")
    pit = union_members(args.start, args.end)
    anchor_bases = {_base(a) for a in _ANCHORS}
    tickers = list(_ANCHORS) + sorted(t for t in pit if t not in anchor_bases)
    print(f"Fetching {len(tickers)} tickers (PIT union + anchors), 10y daily...")
    bars = await fetch_batch(tickers, period="10y")
    print(f"Coverage: {len(bars)}/{len(tickers)} (missing = mostly delisted; known gap)")

    closes = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).sort_index()
    spy_col = "SPY.NYSE" if "SPY.NYSE" in closes.columns else "SPY"
    win = (closes.index >= pd.Timestamp(args.start)) & (closes.index <= pd.Timestamp(args.end))
    cal = closes.index[win]

    print(f"\nProduction mix weights: { {k: round(v, 3) for k, v in PROD_WEIGHTS.items()} }")
    print("Building signal stream (no LLM)...")
    stream = build_signal_stream(bars, closes, opens, cal, config_universe, spy_col)
    signals = [r for r in stream if "targets_snapshot" not in r]
    print(f"Signals the live StrategyAgent would emit: {len(signals)}")
    print(f"Full debate cost: {len(signals)} debates x 8 LLM calls = "
          f"{len(signals) * 8} calls")

    PAPER_DIR.mkdir(exist_ok=True)
    (PAPER_DIR / "debate_ab_signals.json").write_text(
        json.dumps(signals[:50], indent=1), encoding="utf-8")

    # Arm A first -- it is also the pre-registered sanity gate, and it costs $0.
    eq_a, gross_a, info_a = execute(stream, None, args.mode, closes, opens, cal, args.capital)
    m_a = metrics(eq_a, "Arm A (no gate)", gross_a)
    m_a.update(info_a)
    print(f"\nArm A: CAGR {m_a['CAGR%']}%  vol {m_a['vol%']}%  Sharpe {m_a['Sharpe']}  "
          f"maxDD {m_a['maxDD%']}%  gross {m_a['avgGross%']}%  fills {info_a['fills']}")
    sharpe_ok = abs(m_a["Sharpe"] - REF_SHARPE) <= SHARPE_TOL
    dd_ok = abs(m_a["maxDD%"] - REF_MAXDD) <= MAXDD_TOL
    print(f"SANITY GATE vs published production mix "
          f"(Sharpe {REF_SHARPE}, maxDD {REF_MAXDD}%): "
          f"{'PASS' if sharpe_ok and dd_ok else 'FAIL'}")
    if not (sharpe_ok and dd_ok):
        print("Arm A does not reproduce the published mix. The replay is not the "
              "published system -- STOP. No LLM calls made, nothing ships.")
        return

    if args.dry_run:
        print("\n--dry-run: stopping before any LLM call.")
        return

    cache_path = PAPER_DIR / f"debate_ab_verdicts_{args.mode}.jsonl"
    only = [s.strip() for s in args.providers.split(",")] if args.providers else None
    to_debate = subsample(signals, args.sample) if args.sample else signals
    if args.sample:
        print(f"Subsampling {len(to_debate)} of {len(signals)} signals "
              f"(paired sensitivity arm -- no publishable Arm B from this run)")
    verdicts = await run_debates(to_debate, args.mode, args.concurrency, cache_path,
                                 args.limit, model_overrides, only)

    stats = _vote_stats(verdicts, args.mode)
    missing = sum(1 for s in signals if _cache_key(args.mode, s) not in verdicts)

    print("\n" + project_cost(verdicts, args.mode, len(signals)))

    if missing:
        pct = missing / len(signals) * 100
        print(f"\n[WARN] {missing} of {len(signals)} signals ({pct:.1f}%) have no "
              f"verdict. Un-debated signals FAIL CLOSED, so Arm B below is NOT a "
              f"scaled-down version of the full result -- it is mostly forced "
              f"rejections. Re-run without --limit to complete; verdicts already "
              f"paid for are cached and will not be re-charged.")

    eq_b, gross_b, info_b = execute(stream, verdicts, args.mode, closes, opens, cal,
                                    args.capital)
    m_b = metrics(eq_b, "Arm B (gate on)", gross_b)
    m_b.update(info_b)
    cf = counterfactual_pnl(info_b["rejected"], closes, opens, cal)

    print(f"\n{'arm':22s} {'CAGR%':>7s} {'vol%':>6s} {'Sharpe':>7s} {'maxDD%':>7s} "
          f"{'gross%':>7s} {'fills':>6s} {'turn':>6s}")
    for m in (m_a, m_b):
        print(f"{m['label']:22s} {m['CAGR%']:>7} {m['vol%']:>6} {m['Sharpe']:>7} "
              f"{m['maxDD%']:>7} {m['avgGross%']:>7} {m['fills']:>6} "
              f"{m['turnover']:>6.2f}")

    print(f"\nDebate gate ({args.mode} mode):")
    print(f"  debates          {stats['debates']}  (errors {stats['errors']})")
    print(f"  approved         {stats['approved']}")
    print(f"  rejected         {stats['rejected']} "
          f"({stats['rejected'] / stats['debates'] * 100 if stats['debates'] else 0:.1f}%)")
    print(f"  disagreement     {stats['disagreement_pct']:.1f}% of debates split FOR/AGAINST")
    print(f"  median latency   {stats['median_latency_ms']} ms")
    print(f"  total LLM calls  {stats['llm_calls']}")
    print("  votes by role:")
    for role, tally in sorted(stats["by_role"].items()):
        print(f"    {role:10s} {tally}")
    print("  votes by provider:")
    for prov, tally in sorted(stats["by_provider"].items()):
        print(f"    {prov:10s} {tally}")

    print(f"\nCounterfactual P&L of vetoed trades: {cf['total_pct']:+.2f}% of NAV "
          f"across {cf['counted']} rejections ({cf['win_rate']:.1f}% would have been "
          f"profitable)")
    print_examples(cf)

    share = info_b["fills"] / info_a["fills"] * 100 if info_a["fills"] else 0.0
    print(f"\nArm B placed {info_b['fills']} fills vs Arm A's {info_a['fills']} "
          f"({share:.0f}% of the trading), turnover {info_b['turnover']:.2f}x vs "
          f"{info_a['turnover']:.2f}x NAV/yr.")
    print(f"Ending NAV: Arm A ${eq_a.iloc[-1]:,.0f}, Arm B ${eq_b.iloc[-1]:,.0f} "
          f"(both from ${args.capital:,.0f})")

    # Arm C: does the gate beat trading-less-at-random?
    rate = stats["rejected"] / stats["debates"] if stats["debates"] else 0.0
    print(f"\nRunning {25} placebo gates at Arm B's {rate:.1%} rejection rate "
          f"(random choice, no LLM)...")
    pl = placebo_arms(stream, signals, args.mode, rate, closes, opens, cal, args.capital)
    beat = sum(1 for s in pl["sharpes"] if m_b["Sharpe"] > s)
    p_emp = 1 - beat / pl["trials"]
    placebo_verdict = ("judgment adds beyond trading less" if p_emp <= 0.05
                       else "NOT distinguishable from simply trading less")
    print(f"Arm C (random gate, same rate): Sharpe {pl['sharpe_mean']:.2f} "
          f"+/- {pl['sharpe_std']:.2f}  [p5 {pl['sharpe_p5']:.2f}, "
          f"p95 {pl['sharpe_p95']:.2f}]  avg fills {pl['fills_mean']:.0f}")
    print(f"Arm B beats {beat}/{pl['trials']} random gates "
          f"(empirical p = {p_emp:.2f}) -- {placebo_verdict}")

    # Pre-registered acceptance criterion.
    passes = m_b["Sharpe"] >= m_a["Sharpe"] and cf["total_pct"] <= 0
    verdict = ("PASS -- gate earns a permanent place in the autonomous pipeline"
               if passes else "FAIL -- gate reverts to advisory-only")
    print("\nPRE-REGISTERED ACCEPTANCE "
          f"(Sharpe_B >= Sharpe_A AND counterfactual <= 0): {verdict}")

    # A table built on incomplete verdict coverage would misrepresent the gate.
    # Withhold it rather than let a pilot's numbers reach the paper by accident.
    if missing > len(signals) * 0.01:
        print("\nTable withheld: verdict coverage is incomplete, so these Arm B "
              "numbers are diagnostics only and must not be published. "
              "Complete the run to emit the table.")
        return

    latex = emit_latex(m_a, m_b, cf, stats, args.mode)
    print("\n" + latex)
    (PAPER_DIR / f"debate_ab_table_{args.mode}.tex").write_text(latex + "\n", encoding="utf-8")
    print(f"\nWrote {PAPER_DIR / f'debate_ab_table_{args.mode}.tex'}")


def _selfcheck() -> None:
    """Runnable check of the arm logic -- no data, no network, no LLM."""
    cal = pd.DatetimeIndex(pd.date_range("2020-01-01", periods=4, freq="D"))
    px = pd.DataFrame({"X": [10.0, 10.0, 20.0, 20.0]}, index=cal)

    sig = {"bar_index": 0, "date": cal[0].isoformat(), "fill_date": cal[1].isoformat(),
           "symbol": "X", "direction": 1, "strength": 0.4,
           "target_weight": 0.2, "previous_weight": 0.0, "features": {}}
    stream = [sig, {"bar_index": 0, "date": cal[0].isoformat(), "targets_snapshot": {"X": 0.2}}]

    # Arm A executes the signal; Arm B with a REJECTED verdict does not.
    _, _, a = execute(stream, None, "blind", px, px, cal, 100_000.0)
    assert a["fills"] == 1, a
    rej = {_cache_key("blind", sig): {"decision": "REJECTED", "mode": "blind"}}
    _, _, b = execute(stream, rej, "blind", px, px, cal, 100_000.0)
    assert b["fills"] == 0, b
    assert len(b["rejected"]) == 1

    # A missing verdict must fail CLOSED, not silently execute.
    _, _, c = execute(stream, {}, "blind", px, px, cal, 100_000.0)
    assert c["fills"] == 0 and c["rejected"][0]["verdict"] == "MISSING", c

    # An APPROVED verdict executes exactly like Arm A.
    ok = {_cache_key("blind", sig): {"decision": "APPROVED", "mode": "blind"}}
    _, _, d = execute(stream, ok, "blind", px, px, cal, 100_000.0)
    assert d["fills"] == a["fills"], (d, a)

    # Counterfactual: vetoed +20% weight into a name that doubled = +20% * 100%.
    cf = counterfactual_pnl(b["rejected"], px, px, cal)
    assert abs(cf["total_pct"] - 20.0) < 1e-6, cf
    assert cf["counted"] == 1 and cf["win_rate"] == 100.0
    # Per-trade detail must reconstruct the aggregate, or the examples shown to
    # a reader would not be the trades that produced the headline number.
    assert len(cf["detail"]) == 1, cf["detail"]
    d = cf["detail"][0]
    assert d["symbol"] == "X" and d["action"] == "BUY", d
    assert abs(d["fwd_ret_pct"] - 100.0) < 1e-6, d      # 10.0 -> 20.0
    assert abs(d["contrib_pct"] - 20.0) < 1e-6, d
    assert abs(sum(x["contrib_pct"] for x in cf["detail"]) - cf["total_pct"]) < 1e-9

    # Blinding must not leak the ticker or the date; unblind must carry both.
    blind_sym, blind_data = _signal_payload(
        {**sig, "features": {"realized vol (20d, annualized)": "18.0%"}}, "blind")
    assert "X" not in blind_sym and "date" not in json.dumps(blind_data).lower(), blind_data
    unblind_sym, unblind_data = _signal_payload(sig, "unblind")
    assert unblind_sym == "X" and unblind_data["features"]["as-of date"] == "2020-01-01"

    # Cache keys separate the two modes so verdicts can never cross-contaminate.
    assert _cache_key("blind", sig) != _cache_key("unblind", sig)

    # Placebo gates must hit the requested rejection rate and be reproducible,
    # or the control cannot separate "chose well" from "traded less".
    many = [{**sig, "date": f"2020-01-{d:02d}T00:00:00", "symbol": f"S{d}"}
            for d in range(1, 29)]
    r1 = placebo_arms(stream, many, "blind", 0.5, px, px, cal, 100_000.0, trials=2)
    r2 = placebo_arms(stream, many, "blind", 0.5, px, px, cal, 100_000.0, trials=2)
    assert r1["sharpes"] == r2["sharpes"], "placebo must be deterministic"
    # Rate 0.0 approves everything, so it must match Arm A's fill count exactly.
    all_ok = placebo_arms(stream, [sig], "blind", 0.0, px, px, cal, 100_000.0, trials=1)
    assert all_ok["fills_mean"] == a["fills"], (all_ok, a)
    none_ok = placebo_arms(stream, [sig], "blind", 1.0, px, px, cal, 100_000.0, trials=1)
    assert none_ok["fills_mean"] == 0.0, none_ok

    # Subsampling is deterministic and spans the window, so the unblind arm
    # debates exactly the signals blind already ruled on (paired comparison).
    pool = [{"i": i} for i in range(100)]
    s1, s2 = subsample(pool, 10), subsample(pool, 10)
    assert s1 == s2, "subsample must be deterministic"
    assert [d["i"] for d in s1] == list(range(0, 100, 10)), s1
    assert s1[-1]["i"] > 80, "sample must reach the end of the window"
    assert subsample(pool, 500) == pool, "n >= len returns everything"

    # Cost projection: 4M input chars = 1M tokens, priced at $0.15/M for
    # gpt-4o-mini, so 10 debates -> $0.15, and 1000 signals -> $15.00.
    priced = {"k": {"mode": "blind", "decision": "APPROVED",
                    "prompt_chars": 400_000, "output_chars": 0,
                    "models": {"openai": "gpt-4o-mini"}}}
    proj = project_cost({f"k{i}": {**priced["k"]} for i in range(10)}, "blind", 1000)
    assert "$15.00" in proj, proj
    # Two providers split the same token spend, so the total is unchanged.
    two = {**priced["k"], "models": {"openai": "gpt-4o-mini", "gemini": "gemini-2.0-flash"}}
    proj2 = project_cost({f"k{i}": dict(two) for i in range(10)}, "blind", 1000)
    assert "$12.50" in proj2, proj2  # (0.15 + 0.10) / 2 * 100 tok/debate * 1000
    # No completed debates must not crash or fabricate a number.
    assert "cannot project" in project_cost({}, "blind", 1000)

    # Production weights are the published mix, derived not retyped.
    assert abs(PROD_WEIGHTS["research_stack"] - 0.5) < 1e-9, PROD_WEIGHTS
    assert abs(PROD_WEIGHTS["trend_filter"] - 1 / 3) < 1e-9, PROD_WEIGHTS
    assert abs(PROD_WEIGHTS["momentum_rank"] - 1 / 6) < 1e-9, PROD_WEIGHTS
    assert "breadth_alpha" not in PROD_WEIGHTS

    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        asyncio.run(amain())
