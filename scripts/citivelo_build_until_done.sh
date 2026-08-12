#!/usr/bin/env bash
# Build every fetched day into the CurveStore, repeatedly, until a pass adds
# nothing.
#
# WHY REPEAT: one `build` enumerates its task list ONCE, at the start. Day files
# that land while it runs - and on a multi-hour build they do, because fetching
# is faster than solving - are not in that list and sit unbuilt until someone
# notices.
#
# WHY THE WAIT IS NOT pgrep: `pgrep -f` cannot see native Windows process
# command lines from Git Bash. A first version used it, concluded nothing was
# running while a four-hour build was mid-flight, and started a SECOND pool on
# the same day partitions - two writers racing `write_day` over the same files.
# Process checks here go through Python/psutil, which sees what Windows sees.
set -u
REPO="C:/Users/chris/clee/ARBS-snap"
PY="C:/Users/chris/anaconda3/envs/stir/python.exe"
CURVES="${CITIVELO_BUILD_CURVES:-USD-FEDFUNDS-1D,USD-SOFR-1D}"
LOCK="$REPO/logs/.build_chain.lock"
cd "$REPO" || exit 1
export ARBS_SUPABASE_ENABLED=0

# A single writer, enforced. Two chains would be as bad as a chain racing a
# manual build.
if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "another chain holds $LOCK; exiting"; exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

others_building() {
  # Match only a PYTHON process actually running the builder. Matching on the
  # command-line text alone matches the OBSERVER too: a `Get-CimInstance ... |
  # Where-Object { $_.CommandLine -like '*deep_intraday_warm.py*build*' }`
  # carries both strings in its own command line, so every status check made the
  # chain believe a build was in flight and it waited forever. Measured: still
  # "waiting" four minutes after the last builder exited.
  "$PY" -c "
import os, sys, psutil
skip = {os.getpid(), $$}
for p in psutil.process_iter(['pid','name','cmdline']):
    try:
        if p.info['pid'] in skip: continue
        if (p.info['name'] or '').lower() not in ('python.exe','pythonw.exe'): continue
        cl = p.info['cmdline'] or []
        if len(cl) < 2: continue
        if any('deep_intraday_warm.py' in a for a in cl) and 'build' in cl:
            sys.exit(0)
    except Exception:
        continue
sys.exit(1)
"
}

echo "waiting for any in-flight build to finish  $(date '+%F %T')"
while others_building; do sleep 60; done

for pass in 1 2 3 4 5 6; do
  echo "=== pass $pass  $(date '+%F %T') ==="
  before=$(find "$HOME/AppData/Local/ARBS/Cache/curve_store/raw" -name '*.parquet' -path '*CITIVELOEXCELMIN*' 2>/dev/null | wc -l)
  "$PY" -u scripts/citivelo_deep_intraday_warm.py --curves "$CURVES" build --workers 6
  after=$(find "$HOME/AppData/Local/ARBS/Cache/curve_store/raw" -name '*.parquet' -path '*CITIVELOEXCELMIN*' 2>/dev/null | wc -l)
  echo "pass $pass added $((after - before)) day partition(s)  $(date '+%F %T')"
  # A pass that adds nothing is the only honest stop condition: it means every
  # fetched day is solved, whatever the reason.
  if [ "$after" -le "$before" ]; then
    echo "=== nothing added; chain done after pass $pass ==="; break
  fi
done
echo "=== chain finished $(date '+%F %T') ==="
