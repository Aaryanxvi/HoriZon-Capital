# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-B8C876BD7CED
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Fill the paper's pending tables and results prose from the harness outputs.

Reads the artifacts the validation harnesses write next to the paper and
substitutes them into the LaTeX source, so no number is retyped by hand between
a run and the manuscript:

  debate_ab_summary_blind.json     Arm A/B/C metrics, gate stats, counterfactual
  debate_ab_summary_unblind.json   the paired sensitivity arm (optional)
  debate_ab_verdicts_*.jsonl       per-debate verdicts, joined for the leakage table
  deflated_sharpe_table.tex        PSR / DSR rows

Every substitution targets an exact placeholder block and asserts it was found,
so a change to the manuscript that moves a table surfaces as a failure here
rather than as a silently unfilled row in the PDF.

Idempotent: re-running after a longer run overwrites the same blocks with the
newer numbers.

Usage:
    python scripts/assemble_paper.py
    python scripts/assemble_paper.py --selfcheck
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPER_DIR = ROOT.parent / "own research paper"
TEX = PAPER_DIR / "horizon_capital_paper_draft1.tex"

PCT = r"\%"
EOL = r"\\"


def _sub_block(text: str, name: str, new: str) -> str:
    """Replace the body between ``% BEGIN:name`` and ``% END:name``.

    Marker-delimited rather than matching the placeholder text itself, so the
    script is idempotent: it can be re-run after a longer run and will overwrite
    its own previous output. Matching literal ``---`` rows would work exactly
    once and then fail, which is the worst possible failure mode for something
    that runs unattended and may need a second pass.
    """
    begin, end = f"% BEGIN:{name}", f"% END:{name}"
    i, j = text.find(begin), text.find(end)
    assert i != -1 and j != -1 and j > i, f"{name}: markers not found in paper"
    return text[:i + len(begin)] + "\n" + new + "\n" + text[j:]


def _sub_once(text: str, old: str, new: str, what: str) -> str:
    """Replace one occurrence; tolerate it already being gone (idempotent)."""
    n = text.count(old)
    assert n <= 1, f"{what}: expected at most 1 match, found {n}"
    return text.replace(old, new) if n else text


def load_pairs(mode: str) -> dict[tuple[str, str], dict]:
    """Latest usable verdict per (date, symbol) for one mode.

    Keyed on the trade rather than the cache key, because the cache key embeds
    the mode and the whole point of the leakage table is to join across modes.
    """
    path = PAPER_DIR / f"debate_ab_verdicts_{mode}.jsonl"
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


def leakage_rows() -> tuple[str, dict]:
    """Paired blind-vs-unblind verdict comparison on identical signals."""
    blind, unblind = load_pairs("blind"), load_pairs("unblind")
    shared = sorted(set(blind) & set(unblind))

    def approval(recs: list[dict]) -> float:
        return (sum(1 for r in recs if r["decision"] == "APPROVED") / len(recs) * 100
                if recs else 0.0)

    def consensus(recs: list[dict]) -> float:
        return sum(r.get("consensus_score", 0.0) for r in recs) / len(recs) if recs else 0.0

    b = [blind[k] for k in shared]
    u = [unblind[k] for k in shared]
    agree = (sum(1 for k in shared if blind[k]["decision"] == unblind[k]["decision"])
             / len(shared) * 100 if shared else 0.0)
    stats = {"paired": len(shared), "blind_approval": approval(b),
             "unblind_approval": approval(u), "agreement": agree,
             "blind_consensus": consensus(b), "unblind_consensus": consensus(u)}

    # With no unblinded arm there is nothing to pair, and every cell would
    # render as 0.0% -- indistinguishable in print from a measured result of
    # zero. Say plainly that it was not run instead.
    if not shared:
        rows = (r"\multicolumn{3}{c}{\emph{Not run --- the unblinded "
                r"sensitivity arm did not complete.}} \\")
        return rows, stats

    rows = "\n".join([
        f"Debates (paired) & {len(shared)} & {len(shared)} {EOL}",
        f"Approval rate & {stats['blind_approval']:.1f}{PCT} & "
        f"{stats['unblind_approval']:.1f}{PCT} {EOL}",
        f"Verdict agreement with blinded & n/a & {agree:.1f}{PCT} {EOL}",
        f"Mean consensus score & {stats['blind_consensus']:.3f} & "
        f"{stats['unblind_consensus']:.3f} {EOL}",
    ])
    return rows, stats


def abtest_rows(s: dict) -> str:
    a, b, c = s["arm_a"], s["arm_b"], s["arm_c"]
    g, cf = s["gate"], s["counterfactual"]
    rej = g["rejected"] / g["debates"] * 100 if g["debates"] else 0.0
    return "\n".join([
        f"Trades executed & {a['fills']} & {b['fills']} & {c['fills_mean']:.0f} {EOL}",
        f"Rejection rate & n/a & {rej:.1f}{PCT} & {rej:.1f}{PCT} {EOL}",
        f"Counterfactual P\\&L of rejections & n/a & {cf['total_pct']:+.2f}{PCT} & n/a {EOL}",
        f"CAGR & {a['CAGR%']:.1f}{PCT} & {b['CAGR%']:.1f}{PCT} & --- {EOL}",
        f"Volatility & {a['vol%']:.1f}{PCT} & {b['vol%']:.1f}{PCT} & --- {EOL}",
        f"Sharpe ratio & {a['Sharpe']:.2f} & {b['Sharpe']:.2f} & "
        f"{c['sharpe_mean']:.2f} $\\pm$ {c['sharpe_std']:.2f} {EOL}",
        f"Max drawdown & ${a['maxDD%']:.1f}{PCT}$ & ${b['maxDD%']:.1f}{PCT}$ & --- {EOL}",
        f"Turnover ($\\times$ NAV/yr) & {a['turnover']:.2f} & {b['turnover']:.2f} & "
        f"--- {EOL}",
    ])


def results_prose(s: dict, leak: dict | None) -> str:
    a, b, c, g = s["arm_a"], s["arm_b"], s["arm_c"], s["gate"]
    cf = s["counterfactual"]
    d_sharpe = b["Sharpe"] - a["Sharpe"]
    direction = ("improved" if d_sharpe > 0.005 else
                 "reduced" if d_sharpe < -0.005 else "left essentially unchanged")
    beat_null = c["p_empirical"] <= 0.05
    cf_sign = "cost" if cf["total_pct"] > 0 else "saved"

    parts = [
        f"The panel judged {s['signals_debated']} of {s['signals_total']} signals "
        f"({s['weight_coverage_pct']:.0f}\\% of all traded weight), matching the "
        f"live cost gate's strongest-first budget; the remainder traded "
        f"un-debated. Of the debates, {g['approved']} concluded "
        f"\\textsc{{approved}} and {g['rejected']} \\textsc{{rejected}}, a "
        f"rejection rate of "
        f"{g['rejected'] / g['debates'] * 100 if g['debates'] else 0:.1f}\\%. "
        f"The panel was not a rubber stamp: {g['disagreement_pct']:.0f}\\% of "
        f"debates split \\textsc{{for}} against \\textsc{{against}}. Median "
        f"gate latency was {g['median_latency_ms'] / 1000:.1f}~s per decision "
        f"across {g['llm_calls']:,} model calls.",

        f"Table~\\ref{{tab:abtest}} reports the outcome. Binding the gate "
        f"{direction} the Sharpe ratio ({a['Sharpe']:.2f} to {b['Sharpe']:.2f}) "
        f"and moved maximum drawdown from ${a['maxDD%']:.1f}\\%$ to "
        f"${b['maxDD%']:.1f}\\%$, while cutting turnover from "
        f"{a['turnover']:.2f}$\\times$ to {b['turnover']:.2f}$\\times$ NAV per "
        f"year. Ending NAV was \\${s['nav_end']['arm_a']:,.0f} ungated against "
        f"\\${s['nav_end']['arm_b']:,.0f} gated, from "
        f"\\${s['nav_end']['initial']:,.0f}. The counterfactual P\\&L of the "
        f"vetoed trades was {cf['total_pct']:+.2f}\\% of NAV across "
        f"{cf['counted']} rejections, of which {cf['win_rate']:.0f}\\% would "
        f"have been profitable --- that is, the vetoes {cf_sign} money in "
        f"aggregate.",

        f"\\textbf{{Against a rate-matched random gate.}} Arm~C rejects at the "
        f"same {g['rejected'] / g['debates'] * 100 if g['debates'] else 0:.1f}\\% "
        f"rate but chooses at random. Over {c['trials']} trials it returned a "
        f"Sharpe of {c['sharpe_mean']:.2f} $\\pm$ {c['sharpe_std']:.2f} "
        f"(5th--95th percentile {c['sharpe_p5']:.2f}--{c['sharpe_p95']:.2f}). "
        f"Arm~B beat {c['beat']} of {c['trials']} random gates, an empirical "
        f"$p$ of {c['p_empirical']:.2f}. "
        + ("The panel's choices therefore add information beyond the mechanical "
           "effect of trading less."
           if beat_null else
           "On this evidence the gate's effect is \\emph{not} distinguishable "
           "from simply trading less, which is the more parsimonious "
           "explanation and the one we adopt."),
    ]

    if leak and leak["paired"]:
        gap = abs(leak["unblind_approval"] - leak["blind_approval"])
        parts.append(
            f"\\textbf{{Hindsight leakage.}} On {leak['paired']} paired signals "
            f"judged both ways (Table~\\ref{{tab:leak}}), the unblinded panel "
            f"approved {leak['unblind_approval']:.1f}\\% against the blinded "
            f"panel's {leak['blind_approval']:.1f}\\%, agreeing on "
            f"{leak['agreement']:.1f}\\% of individual verdicts. "
            + ("The small gap indicates the panel was reasoning from the "
               "supplied features rather than recalling outcomes, which is the "
               "assumption the blinded arm relies on."
               if gap < 10 else
               "The gap is material, indicating that revealing the security's "
               "identity does shift the panel's judgement; the blinded arm is "
               "therefore the one we report, and the unblinded figures should "
               "be read as contaminated."))

    verdict = (
        "Under the criterion fixed in Sec.~\\ref{sec:aitest} --- arm~B's "
        "risk-adjusted return at least equal to arm~A's \\emph{and} "
        "non-positive counterfactual P\\&L on rejections --- the gate "
        + ("\\textbf{passes}, and retains its binding role in the autonomous "
           "pipeline."
           if s["acceptance_pass"] else
           "\\textbf{fails}, and reverts to advisory-only. We report this "
           "adverse result as pre-registered. The debate layer retains value "
           "as an auditable record of why each trade was permitted, but on "
           "this evidence it does not earn authority over execution."))
    parts.append(verdict)
    return "\n\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="blind", help="which arm fills Table VI")
    ap.parse_args()

    summary_path = PAPER_DIR / "debate_ab_summary_blind.json"
    assert summary_path.exists(), (
        f"{summary_path.name} not found -- the blind arm has not finished. "
        f"Nothing assembled.")
    s = json.loads(summary_path.read_text(encoding="utf-8"))
    leak_rows, leak = leakage_rows()
    tex = TEX.read_text(encoding="utf-8")

    tex = _sub_block(tex, "abtest-rows", abtest_rows(s))
    tex = _sub_block(tex, "leak-rows", leak_rows)
    # The results prose was generated once and has since been rewritten by hand;
    # its markers are gone deliberately. Regenerating would overwrite the edited
    # text with the template, so only fill it if the markers are still present.
    if "% BEGIN:abtest-prose" in tex:
        tex = _sub_block(tex, "abtest-prose", results_prose(s, leak))
    else:
        print("  (results prose is hand-edited; leaving it alone)")

    # Title: no longer a pending draft.
    tex = _sub_once(tex,
                    "{\\large --- Draft 1 (LLM-integration experiment pending, "
                    "Sec.~\\ref{sec:aitest}) ---}}",
                    "}", "title draft marker")

    TEX.write_text(tex, encoding="utf-8")
    print(f"Assembled {TEX.name}")
    print(f"  Table VI  from {summary_path.name} "
          f"({s['signals_debated']}/{s['signals_total']} signals debated)")
    print(f"  Table VII from {leak['paired']} paired blind/unblind verdicts")
    print(f"  acceptance: {'PASS' if s['acceptance_pass'] else 'FAIL'}; "
          f"placebo: {s['placebo_verdict']}")
    remaining = tex.count("& --- &") + tex.count("--- \\\\")
    print(f"  remaining '---' placeholders in tables: {remaining}")


def _selfcheck() -> None:
    """Check row rendering and prose branching -- no files touched."""
    s = {
        "signals_total": 1015, "signals_debated": 250, "weight_coverage_pct": 51.0,
        "arm_a": {"CAGR%": 15.9, "vol%": 15.3, "Sharpe": 0.78, "maxDD%": -18.0,
                  "avgGross%": 78.0, "fills": 1867, "turnover": 12.72},
        "arm_b": {"CAGR%": 17.0, "vol%": 14.0, "Sharpe": 0.85, "maxDD%": -15.0,
                  "avgGross%": 70.0, "fills": 1500, "turnover": 9.0},
        "arm_c": {"sharpe_mean": 0.79, "sharpe_std": 0.03, "sharpe_p5": 0.74,
                  "sharpe_p95": 0.84, "fills_mean": 1502.0, "trials": 25,
                  "beat": 25, "p_empirical": 0.0},
        "gate": {"debates": 250, "approved": 150, "rejected": 100,
                 "disagreement_pct": 40.0, "median_latency_ms": 4670,
                 "llm_calls": 2000},
        "counterfactual": {"total_pct": -3.2, "counted": 100, "win_rate": 45.0},
        "nav_end": {"arm_a": 280000.0, "arm_b": 300000.0, "initial": 100000.0},
        "acceptance_pass": True, "placebo_verdict": "judgment adds",
    }
    # An unpaired leakage table must announce itself, never render as zeros
    # that read like a measured null result. Checked against whatever verdicts
    # are actually on disk, so it covers both the pre- and post-unblind states.
    lrows, lstats = leakage_rows()
    if lstats["paired"] == 0:
        assert "Not run" in lrows, lrows
        assert "0.0" not in lrows, "unpaired table must not render zero rates"
    else:
        assert lrows.count(r"\\") == 4, lrows
        for line in lrows.splitlines():
            assert line.replace(r"\&", "").count("&") == 2, line

    rows = abtest_rows(s)
    assert rows.count(r"\\") == 8, rows
    # Every row must carry three data columns (four fields) for the 4-col table.
    for line in rows.splitlines():
        assert line.replace(r"\&", "").count("&") == 3, line

    prose = results_prose(s, {"paired": 60, "blind_approval": 60.0,
                              "unblind_approval": 62.0, "agreement": 88.0,
                              "blind_consensus": 0.6, "unblind_consensus": 0.61})
    assert "improved" in prose and "passes" in prose, prose[:400]
    assert "add information beyond" in prose
    assert "reasoning from the" in prose  # small leakage gap branch

    # Adverse branches must actually render the adverse language.
    s2 = {**s, "acceptance_pass": False,
          "arm_b": {**s["arm_b"], "Sharpe": 0.70},
          "arm_c": {**s["arm_c"], "p_empirical": 0.40, "beat": 15}}
    p2 = results_prose(s2, {"paired": 60, "blind_approval": 40.0,
                            "unblind_approval": 75.0, "agreement": 55.0,
                            "blind_consensus": 0.5, "unblind_consensus": 0.7})
    assert "reduced" in p2 and "fails" in p2 and "advisory-only" in p2, p2[:400]
    # The word "not" carries LaTeX emphasis in the rendered sentence, so match
    # the surrounding claim rather than the raw phrase.
    assert "distinguishable" in p2 and "trading less" in p2, \
        "failed placebo must say so plainly"
    assert "parsimonious" in p2, p2[-400:]
    assert "contaminated" in p2, "large leakage gap must be called out"
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token B8C876BD7CED - verify with scripts/authorship.py verify
