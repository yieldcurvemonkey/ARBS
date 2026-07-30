"""Close whatever is actually missing from the dealer-ladder dataset, then prove it closed.

Replaces a hand-written checklist, deliberately. A script that re-runs "May and 2026-06-09"
fixes what I happened to remember at the time it was written; by the time it runs, the set
of gaps has moved. So the gaps are DISCOVERED by asking the database which trading sessions
are missing, and the same query is the acceptance test.

Three kinds of gap, each needing a different phase:

  * no direction rows      -> classify, then project, then marks
  * direction but no ladder -> project, then marks
  * ladder but no EOD marks -> marks only

Known instances at the time of writing (2026-07-30): May 2026 lost every phase when its
classify died on a DDL lock timeout; 2026-06-09 (a Tuesday) lost its classify to a tape-query
statement timeout; April 2026 has correct ENTRY marks from its projection phase but zero EOD
marks. All three are found by the query rather than named here.

WHY NO CODE FIX FIRST. The obvious repair -- make `ensure_schema` skip DDL already applied --
edits a file in `VINTAGE_SOURCES`, changing `code_vintage` from 468474ca6f84. That would mix
vintages and make the next `--purge-stale-vintage` delete every completed month. So this runs
on UNCHANGED code and refuses to start if the vintage has moved.

    conda run -n stir python scripts/dealer_ladder_remediate.py --dry-run
    conda run -n stir python scripts/dealer_ladder_remediate.py
"""
from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402

PY = sys.executable
EXPECTED_VINTAGE = "468474ca6f84"
WINDOW = (datetime.date(2026, 1, 12), datetime.date(2026, 7, 29))
LOGS = os.path.join(REPO, "notebooks", "logs", "dealer_ladder_remediation")

GAPS_SQL = """
SELECT d.day,
       coalesce(dir.n, 0)   AS direction_rows,
       coalesce(lad.n, 0)   AS ladder_rows,
       coalesce(eod.n, 0)   AS eod_marks
FROM (SELECT %(days)s::date[] AS _) x
CROSS JOIN LATERAL unnest(x._) AS d(day)
LEFT JOIN (SELECT as_of_date::date AS day, count(*) n FROM arbs_stir_direction_v1
           WHERE as_of_date BETWEEN %(start)s AND %(end)s GROUP BY 1) dir USING (day)
LEFT JOIN (SELECT as_of_date::date AS day, count(*) n FROM arbs_stir_ladder_prints_v1
           WHERE as_of_date BETWEEN %(start)s AND %(end)s GROUP BY 1) lad USING (day)
LEFT JOIN (SELECT (mark_ts AT TIME ZONE 'America/New_York')::date AS day, count(*) n
           FROM arbs_stir_book_marks_v1 WHERE mark_kind = 'EOD'
             AND (mark_ts AT TIME ZONE 'America/New_York')::date
                 BETWEEN %(start)s AND %(end)s GROUP BY 1) eod USING (day)
ORDER BY d.day
"""


def _vintage() -> str:
    from SDRUtils.stir_flow.vintage import code_vintage
    return code_vintage()


def _orchestrator_running() -> bool:
    """Is the main backfill still going?

    Running this script alongside it would fight for the same rows: a `--rewrite` project
    phase here deletes the window the orchestrator is mid-way through writing. Worse, the
    gap list would be wrong by construction -- a month the orchestrator has not reached yet
    looks identical to a month that failed, so the script would dutifully "remediate" work
    that was never attempted.

    Matched on the WRITER processes, not on the orchestrating shell's name. Two earlier
    versions matched a command-line substring and both were wrong for the same underlying
    reason -- any process whose command line merely MENTIONS the target matches it:

      1. the first matched `backfill_dealer_ladder_window` without a name filter, so the
         PowerShell process running the query matched itself;
      2. the second added `Name -eq 'bash.exe'`, and then the shell LAUNCHING this script
         matched, because the git commit message in that same command line happened to
         quote the string while describing bug (1).

    So the check now looks for the python processes that actually write rows -- the
    `backfill_stir_direction*` / `backfill_stir_ladder` modules. Those are unambiguous, and
    they are what would genuinely conflict. Safe against self-match because this runs ONCE
    at startup, before this script spawns any phase of its own.
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process | Where-Object { "
             "$_.Name -eq 'python.exe' -and "
             "$_.CommandLine -match '-m\\s+SDRUtils\\._swappulse_scripts\\.backfill_stir' "
             "} | Measure-Object).Count"],
            capture_output=True, text=True, timeout=60)
        return int((out.stdout or "0").strip() or 0) > 0
    except Exception:
        return False          # cannot tell -> do not block; the vintage/lock guards remain


def _blocking_sessions(conn) -> int:
    q = """SELECT count(*) AS n FROM pg_stat_activity
           WHERE datname = current_database() AND pid <> pg_backend_pid()
             AND state = 'idle in transaction'
             AND age(now(), xact_start) > interval '30 seconds'"""
    return int(pd.read_sql(q, conn)["n"].iloc[0])


def find_gaps(conn):
    from BT.dealer_ladder import data
    days = [pd.Timestamp(d).date() for d in data.trading_days(WINDOW)]
    df = pd.read_sql(GAPS_SQL, conn,
                     params={"days": days, "start": WINDOW[0], "end": WINDOW[1]})
    df["needs"] = [
        "classify" if r.direction_rows == 0
        else ("project" if r.ladder_rows == 0
              else ("marks" if r.eod_marks == 0 else ""))
        for r in df.itertuples()]
    return df


def _month_ranges(days) -> list:
    """[(year, month, first_missing, last_missing)] — the SPAN of missing days per month.

    Not the whole month. June needs one day (2026-06-09) and re-running the other twenty
    costs about two and a half hours of classify and project for nothing.

    Narrowing is safe because every phase is idempotent over a range: classify upserts on
    `unit_key`, and project and marks are invoked with `--rewrite`, which deletes the
    window's rows before rewriting them. So a span that happens to include already-good
    days rewrites them identically rather than corrupting them.

    The CALIBRATION window still comes from the month (see ``_calib``), not from the span,
    so a single-day re-run is calibrated exactly as the original month-long chunk was.
    Narrowing the range without pinning the calibration would give the repaired day a
    different `p_flip` from its neighbours, which is the one way this optimisation could
    have gone wrong.
    """
    out = {}
    for d in days:
        key = (d.year, d.month)
        lo, hi = out.get(key, (d, d))
        out[key] = (min(lo, d), max(hi, d))
    return [(y, m, lo, hi) for (y, m), (lo, hi) in sorted(out.items())]


def _month_bounds(y, m):
    start = datetime.date(y, m, 1)
    end = (datetime.date(y + (m == 12), (m % 12) + 1, 1) - datetime.timedelta(days=1))
    return max(start, WINDOW[0]), min(end, WINDOW[1])


def _calib(y, m):
    """The trailing calibration window: the whole previous month.

    Matches backfill_dealer_ladder_window.sh, where calibration always ends the day BEFORE
    the classified range starts -- so p_flip is never calibrated on the days being
    classified. Reproducing a month with a different calibration window would give it
    subtly different p_flip values from its neighbours.
    """
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    return _month_bounds(py, pm)


def run(label, args_, dry) -> int:
    os.makedirs(LOGS, exist_ok=True)
    cmd = [PY, "-u", "-m"] + args_
    print(f"\n== {label}  {time.strftime('%H:%M:%S')}")
    print("   " + " ".join(cmd[3:]))
    if dry:
        return 0
    log = os.path.join(LOGS, f"{label}.log")
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.call(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=REPO)
    print(f"   rc={rc}  {time.strftime('%H:%M:%S')}")
    with open(log, encoding="utf-8", errors="replace") as fh:
        tail = fh.read().strip().splitlines()[-2:]
    for line in tail:
        print(f"   | {line[:150]}")
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report the gaps and the commands, change nothing")
    ap.add_argument("--skip-coverage", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="proceed even if the main backfill still appears to be running")
    args = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if _orchestrator_running() and not args.force:
        for line in (
            "ABORT: the main backfill is still running.",
            "       Its --rewrite phases and this script would delete each other's rows,",
            "       and a month it has not reached yet is indistinguishable from a month",
            "       that failed -- so the gap list would be wrong by construction.",
            "       Wait for it to finish, or pass --force if you are certain.",
        ):
            print(line, file=sys.stderr)
        return 5

    got = _vintage()
    print(f"code_vintage = {got} (expected {EXPECTED_VINTAGE})")
    if got != EXPECTED_VINTAGE:
        print("ABORT: the vintage has moved. Writing now would mix vintages, and the next\n"
              "       --purge-stale-vintage would delete the months already completed.",
              file=sys.stderr)
        return 3

    from BT.dealer_ladder import data
    conn = data.connect()
    try:
        blocking = _blocking_sessions(conn)
        print(f"long idle-in-transaction sessions: {blocking}")
        if blocking and not args.dry_run:
            print("ABORT: something is idle in transaction. A held AccessShareLock starves\n"
                  "       ALTER TABLE of its AccessExclusiveLock until the 2-minute\n"
                  "       statement_timeout kills the phase -- this is what cost May.",
                  file=sys.stderr)
            return 4
        gaps = find_gaps(conn)
    finally:
        conn.close()

    todo = gaps[gaps["needs"] != ""]
    print(f"\n{len(gaps)} trading sessions in window; {len(todo)} incomplete")
    if todo.empty:
        print("nothing to remediate")
        return 0
    print(todo.to_string(index=False))

    need_classify = [r.day for r in todo.itertuples() if r.needs == "classify"]
    need_project = [r.day for r in todo.itertuples() if r.needs in ("classify", "project")]
    need_marks = [r.day for r in todo.itertuples() if r.needs in
                  ("classify", "project", "marks")]

    rc_all = 0
    # classify per MONTH, because the tick calibration is computed once per invocation and
    # a per-day call would recompute it 20 times and could pick a different window
    for y, m, s, e in _month_ranges(need_classify):
        ks, ke = _calib(y, m)
        rc_all |= run(f"classify-{y}-{m:02d}", [
            "SDRUtils._swappulse_scripts.backfill_stir_direction_range",
            "--start", str(s), "--end", str(e),
            "--calib-start", str(ks), "--calib-end", str(ke),
            "--day-jobs", "2", "--warm-jobs", "8", "--log-dir", LOGS,
            "--purge-stale-vintage"], args.dry_run)

    for y, m, s, e in _month_ranges(need_project):
        rc_all |= run(f"project-{y}-{m:02d}", [
            "SDRUtils._swappulse_scripts.backfill_stir_ladder", "--phase", "project",
            "--start", str(s), "--end", str(e), "--day-jobs", "4", "--warm-jobs", "8",
            "--log-dir", LOGS, "--rewrite"], args.dry_run)

    for y, m, s, e in _month_ranges(need_marks):
        # --rewrite on the marks phase deletes only mark_kind='EOD', so ENTRY marks
        # written by the projection phase survive untouched
        rc_all |= run(f"marks-{y}-{m:02d}", [
            "SDRUtils._swappulse_scripts.backfill_stir_ladder", "--phase", "marks",
            "--start", str(s), "--end", str(e), "--day-jobs", "3",
            "--log-dir", LOGS, "--rewrite"], args.dry_run)

    if args.dry_run or args.skip_coverage:
        return 0

    print(f"\n== coverage --strict  {time.strftime('%H:%M:%S')}")
    rc = subprocess.call(
        [PY, os.path.join(REPO, "scripts", "dealer_ladder_coverage.py"),
         "--start", str(WINDOW[0]), "--end", str(WINDOW[1]),
         "--out", os.path.join(LOGS, "coverage_full.md"), "--strict"], cwd=REPO)
    print(f"coverage --strict rc={rc}")
    if rc:
        print("STILL INCOMPLETE — the anomalies name what to re-run. Re-running this script\n"
              "is safe and idempotent: it re-discovers the gaps rather than repeating a plan.")
    else:
        print("DATASET COMPLETE: every trading session classified, projected and marked,\n"
              "under a single code vintage.")
    return rc or rc_all


if __name__ == "__main__":
    raise SystemExit(main())
