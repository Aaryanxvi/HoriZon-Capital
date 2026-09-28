#!/usr/bin/env bash
# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-B86FEB8FE63F
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
# Unattended finisher: wait for the debate arms, then assemble the paper.
#
# Waits for run_debate_ab_today.sh to print its completion marker, but not
# forever -- at DEADLINE_EPOCH it proceeds with whatever verdicts exist. That is
# safe because both arms run --undebated passthrough, under which un-debated
# signals trade on the quant signal exactly as the live cost gate releases them.
# A partial run is therefore the deployed configuration at lower coverage, not a
# broken experiment, and the coverage is printed into the paper.
#
# Assembly is idempotent, so a later re-run with more verdicts simply overwrites
# the same blocks with better numbers.
set -u

cd "$(dirname "$0")/.." || exit 1
LOG=/tmp/ab_today.log
DEADLINE_EPOCH=${DEADLINE_EPOCH:?set DEADLINE_EPOCH (date +%s of the cutoff)}
PAPER="../own research paper"

say () { echo "[$(date +%H:%M:%S)] $*"; }

say "watching for debate arms to finish (deadline $(date -d "@$DEADLINE_EPOCH" +%H:%M:%S 2>/dev/null || echo "$DEADLINE_EPOCH"))"

while :; do
  if grep -q "all arms complete" "$LOG" 2>/dev/null; then
    say "arms reported complete"
    break
  fi
  if [ "$(date +%s)" -ge "$DEADLINE_EPOCH" ]; then
    say "deadline reached -- assembling with whatever coverage exists"
    # This is Git Bash on Windows: pkill/pgrep are absent, and taskkill cannot
    # filter on a command line. Match the process through CIM instead, or the
    # arm keeps consuming quota while the paper is being assembled behind it.
    powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*validate_debate_ab*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" 2>/dev/null
    sleep 5
    break
  fi
  sleep 60
done

# ALWAYS re-derive both summaries from the cached verdicts, never reuse one an
# arm wrote itself. A long-running arm holds the module version it imported at
# launch, so a correctness fix landed mid-run (the counterfactual holding-horizon
# fix) would not be in the summary it emits. --limit 0 debates nothing and goes
# straight to analysis, so this costs zero provider requests and guarantees every
# number in the paper comes from the current code.
for mode in blind unblind; do
  say "deriving $mode summary from cached verdicts (0 new requests)"
  py -3.14 -u scripts/validate_debate_ab.py \
      --mode "$mode" --providers openai --openai-model gpt-4o-mini \
      --strongest 250 --undebated passthrough --limit 0 \
      2>&1 | grep -vE "^20[0-9]{2}-|possibly delisted|Failed download|^\['" | tail -24
done

say "assembling paper"
py -3.14 scripts/assemble_paper.py || say "ASSEMBLY FAILED -- paper left untouched"

say "validating LaTeX structure"
py -3.14 - "$PAPER/horizon_capital_paper_draft1.tex" <<'PY'
import collections, re, sys
t = open(sys.argv[1], encoding="utf-8").read()
b = collections.Counter(re.findall(r"\\begin\{(\w+\*?)\}", t))
e = collections.Counter(re.findall(r"\\end\{(\w+\*?)\}", t))
bad = [(k, b[k], e[k]) for k in set(b) | set(e) if b[k] != e[k]]
print("unbalanced environments:", bad or "none")
print("brace delta:", t.count("{") - t.count("}"))
left = t.count("& --- &") + t.count("& --- \\\\")
print("unfilled table placeholders:", left)
PY

say "done"
ls -la "$PAPER"/*.tex "$PAPER"/*.json 2>/dev/null
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token B86FEB8FE63F - verify with scripts/authorship.py verify
