"""Multi-day driver for the STIR dealer-direction backfill.

Days are independent, so a fresh full-history backfill parallelizes cleanly
across a process pool. Calibration (`run_calibration`) is computed ONCE for the
window and passed to every day worker (it is classify-date independent), so it
is not recomputed per day. Each worker opens its own DB connection and its own
`IRSwapsMDP` (via `CurvePricer`) and runs the same warm+classify+write path as
the single-day CLI -- so the per-day output is byte-for-byte identical to the
sequential backfill (the classifier is deterministic; see the bit-identical
harness).

Concurrency note (Barchart 429): total concurrent Barchart fetches ~=
``day_jobs * warm_jobs``. Keep the product modest (defaults 3*4 = 12) to stay
clear of the rate-limit storm on ``BARCHART_STIRF-RL``.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._stir_flow_schema_v1 import ensure_schema
from SDRUtils._swappulse_scripts.backfill_stir_direction import (
    run_calibration, run_classification, write_tick_rows,
)
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.stir_flow.daylog import day_log


def _classify_one_day(job):
    """Picklable process-pool worker: warm+classify+write one date.

    ``job`` = (date_iso, stats_records, warm_jobs, dry_run, pg_url).
    Returns a small summary dict (never the full rows -> cheap to pickle back).
    """
    date_iso, stats_records, warm_jobs, dry_run, pg_url, log_dir = job
    stats = pd.DataFrame(stats_records) if stats_records else pd.DataFrame()
    with day_log(log_dir, f"classify-{date_iso}"):
        conn = psycopg2.connect(pg_url or resolve_pg_url())
        try:
            rows = run_classification(conn, date_iso, stats, dry_run=dry_run,
                                      warm_jobs=warm_jobs)
            summary = {}
            if rows:
                summary = pd.DataFrame(rows)["dealer_direction"].value_counts().to_dict()
            return {"date": date_iso, "n": len(rows), "summary": summary, "error": None}
        except Exception as exc:  # isolate a bad day; keep the rest of the range going
            import traceback
            traceback.print_exc()
            return {"date": date_iso, "n": 0, "summary": {}, "error": repr(exc)}
        finally:
            conn.close()


def _dates(start, end):
    return [d.date().isoformat() for d in pd.date_range(start, end, freq="D")]


def run_range(start, end, *, day_jobs=3, warm_jobs=4, calib_start=None,
              calib_end=None, calib_mode="ticks-only", dry_run=False,
              pg_url=None, executor_factory=None, log_dir=None):
    """Classify every date in [start, end] across a process pool.

    ``executor_factory`` lets tests inject a serial/mock executor; production
    uses ``ProcessPoolExecutor``.
    """
    dates = _dates(start, end)
    url = pg_url or resolve_pg_url()

    conn = psycopg2.connect(url)
    ensure_schema(conn)
    stats = run_calibration(conn, calib_start or start, calib_end or end, calib_mode)
    if not dry_run:
        write_tick_rows(conn, stats)
    conn.close()
    stats_records = stats.to_dict("records") if len(stats) else []

    jobs = [(d, stats_records, warm_jobs, dry_run, url, log_dir) for d in dates]
    results = []
    if executor_factory is None:
        executor_factory = lambda: ProcessPoolExecutor(max_workers=day_jobs)
    with executor_factory() as ex:
        futs = {ex.submit(_classify_one_day, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            tag = "ERROR " + r["error"] if r["error"] else str(r["summary"])
            print(f"[{r['date']}] {r['n']} units  {tag}")
    results.sort(key=lambda r: r["date"])
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--day-jobs", type=int, default=3)
    ap.add_argument("--warm-jobs", type=int, default=4)
    ap.add_argument("--calib-start")
    ap.add_argument("--calib-end")
    ap.add_argument("--calib-mode", choices=["ticks-only", "full"], default="ticks-only")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log-dir", default=None,
                    help="write one log file per classified day")
    args = ap.parse_args()
    results = run_range(
        args.start, args.end, day_jobs=args.day_jobs, warm_jobs=args.warm_jobs,
        calib_start=args.calib_start, calib_end=args.calib_end,
        calib_mode=args.calib_mode, dry_run=args.dry_run, log_dir=args.log_dir,
    )
    n_err = sum(1 for r in results if r["error"])
    total = sum(r["n"] for r in results)
    print(f"\nrange done: {len(results)} days, {total} units, {n_err} day-errors")
    return 1 if n_err else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
