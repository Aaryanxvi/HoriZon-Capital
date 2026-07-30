#!/usr/bin/env bash
# Sequential blind -> unblind -> final-analysis run, paced to the provider's
# request refill rate so the whole thing fits inside one day's quota.
#
# Both arms use --strongest, so the unblind set is a strict subset of the blind
# set and the two are directly pairable for the leakage table. Both use
# --undebated passthrough, which mirrors the live cost gate, so whatever has
# completed when the clock runs out is still a valid deployed-configuration
# result rather than a truncated one.
#
# Verdicts are cached, so re-running this script resumes rather than re-charges.
set -u

cd "$(dirname "$0")/.." || exit 1
PAPER="../own research paper"
RPM=6.5

run () {
  local mode=$1 n=$2
  echo "=== $(date +%H:%M:%S)  $mode arm, strongest $n ==="
  py -3.14 -u scripts/validate_debate_ab.py \
      --mode "$mode" --providers openai --openai-model gpt-4o-mini \
      --strongest "$n" --undebated passthrough --rpm "$RPM" --concurrency 1 \
      2>&1 | grep -vE "^20[0-9]{2}-|possibly delisted|Failed download|^\['|HTTP Error"
  echo "=== $(date +%H:%M:%S)  $mode arm done ==="
}

run blind 250
run unblind 60

echo "=== $(date +%H:%M:%S)  all arms complete ==="
ls -la "$PAPER"/debate_ab_table_*.tex 2>/dev/null || echo "(no table emitted)"
