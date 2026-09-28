# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-C5BCE098BE6E
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Does a stronger model make a better trade gate? (paired, pre-registered)

The main experiment ran the debate panel on gpt-4o-mini and found its vetoes
indistinguishable from rejecting at the same rate at random. An obvious
objection is that the model was simply too weak. This script tests that
objection directly, on the same signals, changing exactly one variable.

Daily request limits allow ~62 debates on the stronger tier, which is far too
few for a portfolio path. So the measurement is not Sharpe. It is VETO SKILL,
which is far more sensitive per debate:

    veto skill = mean(forward return of trades the panel REJECTED)
               - mean(forward return of trades the panel APPROVED)

Both means are direction-signed, so a positive forward return on a rejected BUY
counts against the panel. A gate with real skill vetoes the worse trades, so
skill is NEGATIVE. A gate with no skill scores about zero. This uses every
debate as its own datapoint rather than compounding them into one equity curve,
which is why 62 debates can say something and 62 debates of portfolio path
cannot.

PRE-REGISTERED BEFORE THE STRONGER MODEL WAS CALLED
  H1  The stronger model has better (more negative) veto skill than the weaker
      one on the identical signal set.
  H2  The two models agree on fewer than 90% of verdicts, i.e. capability
      actually changes the decision rather than the wording.
  Decision rule: H1 is supported only if the stronger model's skill is at least
  0.5 percentage points more negative AND its own skill is negative. Anything
  else is reported as "capability did not help on this evidence".
  This result is reported whichever way it falls. No third model is tried.

Usage:
    python scripts/validate_model_capability.py --n 60 --model gpt-4.1-mini
    python scripts/validate_model_capability.py --selfcheck
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.validate_debate_ab import (  # noqa: E402
    PAPER_DIR,
    _NullBus,
    _cache_key,
    _signal_payload,
)

BASELINE_MODEL = "gpt-4o-mini"
SKILL_MARGIN = 0.5      # percentage points; pre-registered
AGREEMENT_CEILING = 90.0


def load_verdicts(path: Path) -> dict[tuple[str, str], dict]:
    """Latest usable verdict per (date, symbol)."""
    out: dict[tuple[str, str], dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("decision") not in ("APPROVED", "REJECTED"):
            continue
        out[(r["date"][:10], r["symbol"])] = r
    return out


def forward_returns(signals: list[dict], closes: pd.DataFrame,
                    opens: pd.DataFrame) -> dict[tuple[str, str], float]:
    """Direction-signed forward return per signal, over its holding horizon.

    Horizon closes at the next signal on the same symbol -- the same rule the
    counterfactual in the main harness uses, and for the same reason: a horizon
    that runs to the end of the window turns one 2018 decision into a six-year
    bet and swamps everything else.
    """
    by_symbol: dict[str, list[pd.Timestamp]] = {}
    for s in signals:
        by_symbol.setdefault(s["symbol"], []).append(pd.Timestamp(s["date"]))

    out: dict[tuple[str, str], float] = {}
    for s in signals:
        sym = s["symbol"]
        if sym not in opens.columns or sym not in closes.columns:
            continue
        fill = pd.Timestamp(s["fill_date"])
        if fill not in opens.index:
            continue
        entry = opens[sym].get(fill, np.nan)
        if np.isnan(entry) or entry <= 0:
            continue
        later = [d for d in by_symbol[sym] if d > pd.Timestamp(s["date"])]
        px = closes[sym].loc[:min(later)] if later else closes[sym]
        px = px.dropna()
        if px.empty:
            continue
        raw = float(px.iloc[-1] / entry - 1.0)
        # Sign by intent: a rising price is good for a BUY, bad for a SELL.
        out[(s["date"][:10], sym)] = raw * (1 if s["direction"] > 0 else -1)
    return out


def veto_skill(verdicts: dict, fwd: dict) -> dict:
    """Mean forward return of rejected minus approved. Negative = skill."""
    rej = [fwd[k] for k, v in verdicts.items()
           if v["decision"] == "REJECTED" and k in fwd]
    app = [fwd[k] for k, v in verdicts.items()
           if v["decision"] == "APPROVED" and k in fwd]
    if not rej or not app:
        return {"skill_pp": float("nan"), "n_rej": len(rej), "n_app": len(app),
                "mean_rej_pp": float("nan"), "mean_app_pp": float("nan")}
    mr, ma = float(np.mean(rej)) * 100, float(np.mean(app)) * 100
    return {"skill_pp": mr - ma, "n_rej": len(rej), "n_app": len(app),
            "mean_rej_pp": mr, "mean_app_pp": ma}


async def run_arm(signals: list[dict], model: str, cache: Path,
                  rpm: float) -> dict[tuple[str, str], dict]:
    from app.agents.debate.multi_model_debate import MultiModelDebateEngine
    from app.llm.provider_registry import provider_registry

    provider_registry.auto_register_from_settings()
    base = provider_registry.get_provider("openai")
    if base is None:
        raise SystemExit("OpenAI provider not registered; set OPENAI_API_KEY.")
    provider_registry._providers["openai"] = base.with_model(model)

    done = load_verdicts(cache)
    todo = [s for s in signals if (s["date"][:10], s["symbol"]) not in done]
    print(f"  {model}: {len(done)} cached, {len(todo)} to run "
          f"({len(todo) * 8} requests)")
    if not todo:
        return done

    engine = MultiModelDebateEngine(registry=provider_registry, bus=_NullBus(),
                                    max_rounds=2)
    interval = 8 * 60.0 / rpm if rpm else 0.0
    fh = cache.open("a", encoding="utf-8")
    try:
        for i, sig in enumerate(todo, 1):
            symbol, data = _signal_payload(sig, "blind")
            action = "BUY" if sig["direction"] > 0 else "SELL"
            t0 = time.perf_counter()
            res = await engine.run_debate(
                symbol=symbol, action=action, signal_data=data,
                regime=sig["features"].get("market regime (index vs its 200d SMA)"),
                sentiment=None, risk_metrics=None, allowed_providers=["openai"])
            failed = [a for a in res.arguments if a.argument.startswith("Error from ")]
            if failed:
                print(f"    [skip] {sig['symbol']} {sig['date'][:10]}: "
                      f"{failed[0].argument[:90]}")
            else:
                rec = {"key": _cache_key("blind", sig), "mode": "blind",
                       "model": model, "date": sig["date"], "symbol": sig["symbol"],
                       "decision": res.decision,
                       "consensus_score": res.consensus_score,
                       "for_count": res.for_count, "against_count": res.against_count,
                       "abstain_count": res.abstain_count,
                       "latency_ms": round((time.perf_counter() - t0) * 1000)}
                done[(sig["date"][:10], sig["symbol"])] = rec
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
            if i % 10 == 0:
                print(f"    ...{i}/{len(todo)}")
            if interval:
                await asyncio.sleep(interval)
    finally:
        fh.close()
    return done


async def amain() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=60)
    p.add_argument("--model", default="gpt-4.1-mini")
    p.add_argument("--rpm", type=float, default=55.0)
    args = p.parse_args()

    stream = json.loads((PAPER_DIR / "debate_ab_stream_2018_2024.json")
                        .read_text(encoding="utf-8"))
    signals = [r for r in stream if "targets_snapshot" not in r]
    top = sorted(signals, key=lambda s: -s["strength"])[:args.n]

    bars = pd.read_pickle(PAPER_DIR / "debate_ab_bars_2018_2024.pkl")
    closes = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).sort_index()
    fwd = forward_returns(signals, closes, opens)

    base_all = load_verdicts(PAPER_DIR / "debate_ab_verdicts_blind.jsonl")
    keys = [(s["date"][:10], s["symbol"]) for s in top]
    base = {k: v for k, v in base_all.items() if k in set(keys)}
    print(f"Baseline {BASELINE_MODEL}: {len(base)} of the top {args.n} signals judged")

    cache = PAPER_DIR / f"debate_ab_verdicts_capability_{args.model}.jsonl"
    strong = await run_arm(top, args.model, cache, args.rpm)

    shared = sorted(set(base) & set(strong))
    print(f"\nPaired on {len(shared)} signals judged by both models.")
    if len(shared) < 20:
        print("Too few pairs to report. Nothing shipped.")
        return

    b = {k: base[k] for k in shared}
    s = {k: strong[k] for k in shared}
    sb, ss = veto_skill(b, fwd), veto_skill(s, fwd)
    agree = sum(1 for k in shared if b[k]["decision"] == s[k]["decision"]) / len(shared) * 100
    ap_b = sum(1 for k in shared if b[k]["decision"] == "APPROVED") / len(shared) * 100
    ap_s = sum(1 for k in shared if s[k]["decision"] == "APPROVED") / len(shared) * 100

    print(f"\n{'':22s} {'approve%':>9s} {'rej fwd%':>9s} {'app fwd%':>9s} "
          f"{'veto skill':>11s}")
    for name, ap, st in ((BASELINE_MODEL, ap_b, sb), (args.model, ap_s, ss)):
        print(f"{name:22s} {ap:>8.1f}% {st['mean_rej_pp']:>8.2f}% "
              f"{st['mean_app_pp']:>8.2f}% {st['skill_pp']:>10.2f}pp")
    print(f"\nVerdict agreement between models: {agree:.1f}%")
    print("(veto skill negative = the panel rejected the worse trades)")

    h1 = (ss["skill_pp"] < 0) and (ss["skill_pp"] <= sb["skill_pp"] - SKILL_MARGIN)
    h2 = agree < AGREEMENT_CEILING
    print(f"\nPRE-REGISTERED H1 (stronger model has better veto skill, margin "
          f"{SKILL_MARGIN}pp): {'SUPPORTED' if h1 else 'NOT SUPPORTED'}")
    print(f"PRE-REGISTERED H2 (models disagree on >10% of verdicts): "
          f"{'SUPPORTED' if h2 else 'NOT SUPPORTED'}")
    if not h1:
        print("\nCapability did not help on this evidence. Reported as such; "
              "no third model is tried.")

    out = PAPER_DIR / "capability_summary.json"
    out.write_text(json.dumps({
        "n_paired": len(shared), "baseline_model": BASELINE_MODEL,
        "strong_model": args.model, "agreement_pct": agree,
        "approve_pct": {BASELINE_MODEL: ap_b, args.model: ap_s},
        "veto_skill": {BASELINE_MODEL: sb, args.model: ss},
        "h1_supported": bool(h1), "h2_supported": bool(h2),
    }, indent=1, default=float), encoding="utf-8")
    print(f"\nWrote {out}")


def _selfcheck() -> None:
    """Check the skill metric on constructed verdicts -- no data, no network."""
    fwd = {("d1", "A"): -0.10, ("d2", "B"): -0.20, ("d3", "C"): 0.15,
           ("d4", "D"): 0.25}
    # A perfect gate rejects both losers and approves both winners.
    perfect = {("d1", "A"): {"decision": "REJECTED"},
               ("d2", "B"): {"decision": "REJECTED"},
               ("d3", "C"): {"decision": "APPROVED"},
               ("d4", "D"): {"decision": "APPROVED"}}
    s = veto_skill(perfect, fwd)
    assert s["skill_pp"] < 0, s
    assert abs(s["skill_pp"] - (-15.0 - 20.0)) < 1e-9, s  # -15 mean rej, +20 app

    # An inverted gate rejects the winners: skill must flip sign.
    inverted = {k: {"decision": "APPROVED" if v["decision"] == "REJECTED"
                    else "REJECTED"} for k, v in perfect.items()}
    si = veto_skill(inverted, fwd)
    assert si["skill_pp"] == -s["skill_pp"], (s, si)

    # A gate with nothing on one side cannot be scored, and must say so rather
    # than return a misleading zero.
    one_sided = {("d1", "A"): {"decision": "REJECTED"}}
    assert np.isnan(veto_skill(one_sided, fwd)["skill_pp"])

    # Direction signing: a SELL whose price rose is a BAD outcome for the trade.
    sigs = [{"date": "2020-01-02T00:00:00", "fill_date": "2020-01-03T00:00:00",
             "symbol": "X", "direction": -1}]
    idx = pd.DatetimeIndex(pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]))
    px = pd.DataFrame({"X": [10.0, 10.0, 12.0]}, index=idx)
    f = forward_returns(sigs, px, px)
    assert f[("2020-01-02", "X")] < 0, f  # +20% price on a SELL scores negative
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        asyncio.run(amain())
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token C5BCE098BE6E - verify with scripts/authorship.py verify
