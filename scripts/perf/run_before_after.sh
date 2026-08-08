#!/usr/bin/env bash
# Before/after, back to back, on an otherwise idle machine.
#
#   bash scripts/perf/run_before_after.sh <python.exe> <ref-worktree> <perf-worktree>
#
# The two worktrees must differ ONLY by this branch's changes, and the bench
# script must be present in both (it is untracked in the reference one).
set -u

PY="${1:?python}"
REF="${2:?reference worktree at main}"
PERF="${3:?this branch's worktree}"

run() {
  local label="$1" dir="$2" bench="$3" n="$4"
  echo
  echo "--- ${label} :: ${bench} n=${n}"
  ( cd "$dir" && ARBS_SUPABASE_ENABLED=0 "$PY" -W ignore scripts/perf/citivelo_read_path_bench.py \
      --bench "$bench" -n "$n" 2>&1 | grep -E "^\[|^ {4}" )
}

for bench in components single bulk pricing timeseries eod; do
  case "$bench" in
    timeseries) n=841 ;;
    components) n=100 ;;
    *)          n=200 ;;
  esac
  run "BEFORE" "$REF"  "$bench" "$n"
  run "AFTER " "$PERF" "$bench" "$n"
done

echo
echo "--- AFTER only: what the batch and the reader cost now"
run "AFTER " "$PERF" "read_strategy" 60
run "AFTER " "$PERF" "swaptions" 40

echo
echo "--- AFTER with the opt-in fixings shortcut"
( cd "$PERF" && ARBS_SUPABASE_ENABLED=0 ARBS_RL_OMIT_UNUSED_FIXINGS=1 \
    "$PY" -W ignore scripts/perf/citivelo_read_path_bench.py --bench pricing -n 200 2>&1 | grep -E "^\[" )
( cd "$PERF" && ARBS_SUPABASE_ENABLED=0 ARBS_RL_OMIT_UNUSED_FIXINGS=1 \
    "$PY" -W ignore scripts/perf/citivelo_read_path_bench.py --bench timeseries -n 841 2>&1 | grep -E "^\[" )
