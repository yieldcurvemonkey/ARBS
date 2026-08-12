#!/usr/bin/env bash
# Re-run the reviewers' mutation battery against the fixed module + new pins.
# Usage: bash scratch/ladderfix_mutrun.sh <plugin> <mut1> <mut2> ...
cd /c/Users/chris/clee/ARBS-dd || exit 1
export ARBS_SUPABASE_ENABLED=0
export PYTHONPATH="C:/Users/chris/clee/ARBS-dd/scratch"
PLUG="$1"; shift
for m in "$@"; do
  out=$(DDREV_MUT="$m" C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest \
        tests/test_dealer_direction_ladder.py -q -p "$PLUG" 2>&1)
  line=$(printf '%s\n' "$out" | grep -E "^[0-9]+ (passed|failed)|passed|failed|error" | tail -1)
  if printf '%s' "$out" | grep -q "AssertionError: .*anchor not found"; then
    echo "ANCHOR PROBLEM  $m :: $(printf '%s' "$out" | grep -o 'anchor not found.*' | head -1)"
  else
    echo "$m :: $line"
  fi
done
