#!/usr/bin/env bash
# Parallel, resumable, deadline-bounded tie-out sweep.
#
# Sharding: `--every` picks the SAMPLE (stride over business days), `--shard/
# --nshards` splits that sample across worker processes. Running with
# `--every 3` alone gives a uniform 1-in-3 calendar sample; the remaining days
# are reachable later by re-running with a shifted start, and every day already
# written is skipped, so the sample grows into the full window rather than
# being redone.
#
# NEVER `conda run`: parallel invocations collide on a temp file and return
# empty output with exit code 0, a fake pass.
set -uo pipefail
PY="C:/Users/chris/anaconda3/envs/stir/python.exe"
REPO="C:/Users/chris/clee/ARBS-dd"
OUT="${OUT:-D:/tieout_cache}"
START="${START:-2026-01-12}"
END="${END:-2026-07-20}"
EVERY="${EVERY:-3}"
NSHARDS="${NSHARDS:-4}"
SOURCES="${SOURCES:-bar,citi}"
DEADLINE="${DEADLINE:-460}"
LOGD="$OUT/logs"
mkdir -p "$LOGD"

pids=()
for k in $(seq 0 $((NSHARDS - 1))); do
  (
    cd "$REPO" || exit 1
    export ARBS_SUPABASE_ENABLED=0
    "$PY" -u scratch/tieout_run.py --start "$START" --end "$END" \
      --out "$OUT" --sources "$SOURCES" --every "$EVERY" \
      --shard "$k" --nshards "$NSHARDS" --deadline-seconds "$DEADLINE" \
      --min-free-gb 1.2 --warm-jobs 6 \
      >> "$LOGD/shard-$k.log" 2>&1
  ) &
  pids+=($!)
done
rc=0
for p in "${pids[@]}"; do wait "$p" || rc=1; done
echo "--- batch finished rc=$rc ---"
for k in $(seq 0 $((NSHARDS - 1))); do
  echo "shard $k: $(grep -c ': done ' "$LOGD/shard-$k.log" 2>/dev/null || echo 0) days done, last:"
  grep -E ': (done|FAILED|ABORT)|SWEEP DONE|deadline' "$LOGD/shard-$k.log" 2>/dev/null | tail -2
done
echo "old=$(ls "$OUT/old" | grep -c parquet) bar=$(ls "$OUT/new_bar" | grep -c parquet) citi=$(ls "$OUT/new_citi" | grep -c parquet)"
df -k /c | tail -1
