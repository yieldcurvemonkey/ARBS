#!/usr/bin/env bash
# Full-window dealer-ladder backfill: classify -> project -> EOD marks, month by month.
#
# WHY MONTHLY CHUNKS WITH A TRAILING CALIBRATION WINDOW
# -----------------------------------------------------
# backfill_stir_direction_range computes the tick calibration ONCE per invocation
# and hands the same stats to every day-worker. A single window spanning the whole
# study would therefore let data from AFTER a classified day set that day's
# p_flip, direction_confidence and curve_suspect_trade -- and the ladder's default
# "expected" weighting consumes p_flip. So each chunk classifies one calendar month
# against a calibration window that ends the day BEFORE the chunk starts. p_flip at
# day d then depends only on data before d, which is what makes G1's no-lookahead
# audit cover the confidence layer and not just the visibility stamps.
#
# CONCURRENCY
# -----------
# The phases have different bottlenecks, so they get different fan-outs.
# CLASSIFY is vendor-bound: Barchart's intraday origin allows ~55 requests per
# rolling minute and its limiter is scoped per fetch call, not per process, so
# concurrency multiplies straight through it. Each curve-day now costs ~60 requests
# via the bulk warm path (it was ~28,700), and 2 day-workers x 2 curves keeps the
# sustained rate under the ceiling. PROJECT touches no vendor once the CurveStore is
# warm -- profiled at 0.84 s per snapshot, essentially all rateslib instrument
# construction and solving -- so it fans out wider.
#
# SERFF_BASIS is deliberately NOT projected (no --with-basis). Profiled per
# snapshot: MEETING 0.11 s, FUTURES 0.24 s, FED_FUNDS 0.49 s, SERFF_BASIS 13.81 s
# -- 94% of the cost, because it is the one space still needing ~60 vendor pricer
# fetches per snapshot. Including it means 74-109 min per day instead of 4-8. The
# plan makes SERFF_BASIS conditioning-only and bars it from being a test target,
# and BT/dealer_ladder/controls.basis_bp is a better conditioner anyway.
#
# RESUMABILITY
# ------------
# Every phase is idempotent: the classifier upserts on unit_key, the projection
# skips unit_keys already present unless --rewrite, and marks upsert on
# (unit_key, mark_ts). Re-running a chunk after a failure is safe. Per-day logs land
# in $LOG_DIR so a killed run leaves its diagnostics behind.
set -uo pipefail

PY="${PY:-C:/Users/chris/anaconda3/envs/stir/python.exe}"
REPO="${REPO:-C:/Users/chris/clee/ARBS-ladder}"
LOG_DIR="${LOG_DIR:-$REPO/notebooks/logs/dealer_ladder_backfill}"
DAY_JOBS="${DAY_JOBS:-2}"                    # classify: vendor-bound
PROJECT_DAY_JOBS="${PROJECT_DAY_JOBS:-4}"    # project: pure CPU once warm
MARKS_DAY_JOBS="${MARKS_DAY_JOBS:-3}"
WARM_JOBS="${WARM_JOBS:-8}"
PHASES="${PHASES:-classify project marks}"

mkdir -p "$LOG_DIR"
cd "$REPO" || exit 1
export ARBS_SUPABASE_ENABLED=0     # curve writes stay LOCAL; only the flow/ladder
                                   # tables are written, and those go via psycopg2

# chunk: <classify_start> <classify_end> <calib_start> <calib_end>
CHUNKS=(
  "2026-01-12 2026-01-31 2025-12-12 2026-01-11"
  "2026-02-01 2026-02-28 2026-01-01 2026-01-31"
  "2026-03-01 2026-03-31 2026-02-01 2026-02-28"
  "2026-04-01 2026-04-30 2026-03-01 2026-03-31"
  "2026-05-01 2026-05-31 2026-04-01 2026-04-30"
  "2026-06-01 2026-06-30 2026-05-01 2026-05-31"
  "2026-07-01 2026-07-29 2026-06-01 2026-06-30"
)

overall_rc=0
for chunk in "${CHUNKS[@]}"; do
  set -- $chunk
  CS="$1"; CE="$2"; KS="$3"; KE="$4"
  tag="${CS}_${CE}"
  echo "=============================================================="
  echo "CHUNK $tag  (calibration $KS..$KE)  $(date '+%Y-%m-%d %H:%M:%S')"
  echo "=============================================================="

  if [[ " $PHASES " == *" classify "* ]]; then
    echo "-- classify $CS..$CE"
    "$PY" -u -m SDRUtils._swappulse_scripts.backfill_stir_direction_range \
      --start "$CS" --end "$CE" --calib-start "$KS" --calib-end "$KE" \
      --day-jobs "$DAY_JOBS" --warm-jobs "$WARM_JOBS" \
      --log-dir "$LOG_DIR" --purge-stale-vintage \
      > "$LOG_DIR/chunk-classify-$tag.log" 2>&1
    rc=$?
    echo "   classify rc=$rc  $(date '+%H:%M:%S')"
    [[ $rc -ne 0 ]] && overall_rc=$rc
  fi

  if [[ " $PHASES " == *" project "* ]]; then
    echo "-- project $CS..$CE"
    "$PY" -u -m SDRUtils._swappulse_scripts.backfill_stir_ladder \
      --phase project --start "$CS" --end "$CE" \
      --day-jobs "$PROJECT_DAY_JOBS" --warm-jobs "$WARM_JOBS" \
      --log-dir "$LOG_DIR" --rewrite \
      > "$LOG_DIR/chunk-project-$tag.log" 2>&1
    rc=$?
    echo "   project rc=$rc  $(date '+%H:%M:%S')"
    [[ $rc -ne 0 ]] && overall_rc=$rc
  fi

  if [[ " $PHASES " == *" marks "* ]]; then
    echo "-- marks $CS..$CE"
    "$PY" -u -m SDRUtils._swappulse_scripts.backfill_stir_ladder \
      --phase marks --start "$CS" --end "$CE" \
      --day-jobs "$MARKS_DAY_JOBS" --log-dir "$LOG_DIR" --rewrite \
      > "$LOG_DIR/chunk-marks-$tag.log" 2>&1
    rc=$?
    echo "   marks rc=$rc  $(date '+%H:%M:%S')"
    [[ $rc -ne 0 ]] && overall_rc=$rc
  fi
done

echo "=============================================================="
echo "BACKFILL DONE rc=$overall_rc  $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================================="
exit $overall_rc
