#!/usr/bin/env bash
# Close the two dataset holes left by the 2026-07-30 lock incident, then PROVE it closed.
#
# WHAT IS MISSING AND WHY
#   May 2026   -- everything. Its classify died on an ensure_schema DDL timeout (a research
#                 connection of mine sat idle-in-transaction holding AccessShareLock), and
#                 then project and marks each exited 0 in thirteen seconds because there
#                 was nothing to work on. An empty month exits zero.
#   April 2026 -- EOD marks only. Its marks phase died the same way. ENTRY marks come from
#                 the projection phase, which succeeded, so 9,916 of those are already
#                 correct and must not be rewritten.
#
# WHY NO CODE CHANGES FIRST
#   The obvious fix -- make ensure_schema skip DDL that is already applied -- edits a file
#   in VINTAGE_SOURCES, which changes code_vintage from 468474ca6f84. That would split the
#   dataset across two vintages and make the next --purge-stale-vintage delete every month
#   already completed. So this runs on the UNCHANGED code, and the rows it writes carry the
#   same vintage as the rest. The ensure_schema fix is batched for the next cycle.
#
# RUN IT ONLY AFTER THE MAIN BACKFILL HAS FINISHED. Sequentially, one phase at a time:
# running two things at once against this database is what caused the incident.
set -u

REPO="/c/Users/chris/clee/ARBS-ladder"
PY="C:/Users/chris/anaconda3/envs/stir/python.exe"
LOGS="$REPO/notebooks/logs/dealer_ladder_remediation"
CAL_START="2026-04-01"; CAL_END="2026-04-30"     # trailing calibration for May
mkdir -p "$LOGS"
cd "$REPO" || exit 1
export ARBS_SUPABASE_ENABLED=0

vintage() {
  "$PY" -c "import sys; sys.path.insert(0,'.'); from SDRUtils.stir_flow.vintage import code_vintage; print(code_vintage())"
}

EXPECTED_VINTAGE="468474ca6f84"
GOT=$(vintage)
echo "code_vintage = $GOT (expected $EXPECTED_VINTAGE)"
if [ "$GOT" != "$EXPECTED_VINTAGE" ]; then
  echo "ABORT: the vintage has changed. Writing now would mix vintages, and the next"
  echo "       --purge-stale-vintage would delete the months already completed."
  echo "       Either restore the code or plan a full re-classification."
  exit 3
fi

# ---- nothing may be holding a lock on the tables we are about to write
echo
echo "== checking for blocking sessions before touching anything"
"$PY" - <<'PYCHK'
import sys, warnings
sys.path.insert(0, ".")
warnings.simplefilter("ignore")
import pandas as pd
from BT.dealer_ladder import data
conn = data.connect()          # autocommits, so this check cannot itself block anything
try:
    q = """SELECT count(*) AS n FROM pg_stat_activity
           WHERE datname = current_database() AND pid <> pg_backend_pid()
             AND state = 'idle in transaction'
             AND age(now(), xact_start) > interval '30 seconds'"""
    n = int(pd.read_sql(q, conn)["n"].iloc[0])
    print(f"  long idle-in-transaction sessions: {n}")
    sys.exit(4 if n else 0)
finally:
    conn.close()
PYCHK
if [ $? -ne 0 ]; then
  echo "ABORT: something is sitting idle in transaction. That is exactly what broke the"
  echo "       backfill: a held AccessShareLock starves the ALTER TABLE of its"
  echo "       AccessExclusiveLock until the 2-minute statement_timeout kills the phase."
  exit 4
fi

run() {                        # run <label> <phase> <start> <end> [extra...]
  local label=$1 phase=$2 start=$3 end=$4; shift 4
  echo
  echo "== $label  ($phase $start..$end)  $(date '+%H:%M:%S')"
  "$PY" -u -m SDRUtils._swappulse_scripts.backfill_stir_ladder \
      --phase "$phase" --start "$start" --end "$end" \
      --log-dir "$LOGS" "$@" > "$LOGS/$label.log" 2>&1
  local rc=$?
  echo "   rc=$rc  $(date '+%H:%M:%S')"
  tail -2 "$LOGS/$label.log"
  return $rc
}

# ---- 1. May, all three phases, in order.
#      Flags and day-job counts copied from backfill_dealer_ladder_window.sh so the
#      remediated month is produced exactly as the others were -- same calibration
#      convention (a window ending the day BEFORE the chunk starts, so p_flip is never
#      calibrated on the days being classified) and the same concurrency.
echo
echo "== may-classify  $(date '+%H:%M:%S')"
"$PY" -u -m SDRUtils._swappulse_scripts.backfill_stir_direction_range \
    --start 2026-05-01 --end 2026-05-31 \
    --calib-start "$CAL_START" --calib-end "$CAL_END" \
    --day-jobs 2 --warm-jobs 8 --log-dir "$LOGS" --purge-stale-vintage \
    > "$LOGS/may-classify.log" 2>&1
echo "   rc=$?  $(date '+%H:%M:%S')"; tail -2 "$LOGS/may-classify.log"

run may-project project 2026-05-01 2026-05-31 --day-jobs 4 --warm-jobs 8 --rewrite
run may-marks   marks   2026-05-01 2026-05-31 --day-jobs 3 --rewrite

# ---- 2. April EOD marks ONLY. --rewrite deletes and rewrites the window's rows, which for
#         the marks phase means the EOD marks; ENTRY marks come from the projection phase
#         and April's 9,916 of those are already correct.
run april-marks marks 2026-04-01 2026-04-30 --day-jobs 3 --rewrite

# ---- 3. the proof. Enumerates sessions from the TRADING CALENDAR, so a month that is
#         simply absent cannot pass by exiting zero.
echo
echo "== coverage --strict over the full window  $(date '+%H:%M:%S')"
"$PY" scripts/dealer_ladder_coverage.py \
    --start 2026-01-12 --end 2026-07-29 \
    --out "$LOGS/coverage_full.md" --strict
rc=$?
echo "coverage --strict rc=$rc"
if [ $rc -ne 0 ]; then
  echo
  echo "STILL INCOMPLETE. The anomalies above name the sessions to re-run; the dataset is"
  echo "not done until this exits 0."
else
  echo "DATASET COMPLETE: every trading session classified, projected and marked,"
  echo "under a single code vintage."
fi
exit $rc
