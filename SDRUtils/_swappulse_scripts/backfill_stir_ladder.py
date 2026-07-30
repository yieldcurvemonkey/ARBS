# SDRUtils/_swappulse_scripts/backfill_stir_ladder.py
"""Backfill the dealer positioning ladder: projection, EOD marks, snapshots.

Phases:
  project  — project classified prints onto ladders + write ENTRY marks (resumable)
  marks    — EOD reval of open positions per date in [start, end]
  snapshot — print ladder + book P&L at an arbitrary intraday timestamp
Writes ONLY arbs_stir_ladder_prints_v1 / arbs_stir_book_marks_v1.

Scale notes (added for the full ~6-month backfill):

- Curve acquisition dominates, exactly as in the classifier, and the projection
  needs the SAME (curve, snapped minute) set the classifier used. So the project
  phase pre-warms concurrently via ``stir_flow.curve_warm`` instead of building
  curves lazily one leg at a time.
- Days are independent, so both project and marks have a process-pool range
  driver. Keep ``day_jobs * warm_jobs`` modest: total concurrent Barchart
  fetches, and ``BARCHART_STIRF-RL`` rate-limits hard.
- The marks phase loads prints PER DAY, not the whole table. At 17:00 ET the
  3-half-life cutoff admits only prints from that same session (non-block
  270min => after 12:30 ET; block 720min => after 05:00 ET), so a whole-table
  read was both unnecessary and quadratic in window length.
- ``--rewrite`` deletes the window's rows before writing. Needed whenever a
  convention changes: upsert alone would leave rows keyed on buckets the new
  code no longer emits.
"""
from __future__ import annotations

import argparse
import datetime
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
import psycopg2
import pytz
from psycopg2.extras import execute_values as _execute_values

from SDRUtils._swappulse_scripts._stir_ladder_schema_v1 import (
    BOOK_MARKS_TABLE, LADDER_PRINTS_TABLE, ensure_schema,
)
from SDRUtils._swappulse_scripts._stir_flow_schema_v1 import DIRECTION_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.stir_flow import book, config, curve_warm, ladder_state, unwinds
from SDRUtils.stir_flow.daylog import day_log
from SDRUtils.stir_flow.ladder import LADDER_COLUMNS, build_risk_models, project_unit
from SDRUtils.stir_flow.ladder_conventions import PROVISIONAL_HALF_LIVES_MIN
from SDRUtils.stir_flow.pricing import CurvePricer, snap_timestamp
from SDRUtils.stir_flow.trade_selection import (
    ALL_PKG_LEGS_SQL, ELIGIBLE_LEGS_SQL, build_units, is_excluded_unit,
)
from SDRUtils.stir_flow.vintage import code_vintage

NY = pytz.timezone("America/New_York")
MARK_COLUMNS = ["unit_key", "mark_ts", "mark_kind", "npv_usd", "pnl_since_entry_usd",
                "curve_name", "code_vintage"]


def load_directions(conn, start, end) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT unit_key, trade_id, package_id, trade_type, rate_index_clean, "
        "classification_method, dealer_direction, p_flip, direction_confidence, "
        "curve_suspect_trade, structure_dv01, as_of_date "
        f"FROM {DIRECTION_TABLE} "
        "WHERE as_of_date BETWEEN %(s)s AND %(e)s "
        "AND dealer_direction IN ('PAID', 'RECEIVED')",
        conn, params={"s": start, "e": end},
    )


def _load_units(conn, start, end):
    eligible = pd.read_sql(ELIGIBLE_LEGS_SQL, conn, params={"start": start, "end": end})
    pkg_ids = sorted(set(eligible.loc[eligible["n_package_legs"].fillna(1) > 1,
                                      "package_id"].dropna()))
    all_legs = eligible.head(0)
    if pkg_ids:
        all_legs = pd.read_sql(ALL_PKG_LEGS_SQL, conn, params={"package_ids": pkg_ids})
    units = [u for u in build_units(eligible, all_legs) if is_excluded_unit(u.legs) is None]
    return {u.unit_key: u for u in units}


def _already_projected(conn, start, end) -> set:
    df = pd.read_sql(
        f"SELECT DISTINCT unit_key FROM {LADDER_PRINTS_TABLE} "
        "WHERE as_of_date BETWEEN %(s)s AND %(e)s",
        conn, params={"s": start, "e": end},
    )
    return set(df["unit_key"])


def delete_projections(conn, start, end) -> tuple:
    """Drop the window's ladder rows and their ENTRY marks. Returns (n_rows, n_marks)."""
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {BOOK_MARKS_TABLE} WHERE mark_kind = 'ENTRY' AND unit_key IN "
            f"(SELECT unit_key FROM {DIRECTION_TABLE} "
            "WHERE as_of_date BETWEEN %(s)s AND %(e)s)",
            {"s": start, "e": end})
        n_marks = cur.rowcount
        cur.execute(
            f"DELETE FROM {LADDER_PRINTS_TABLE} WHERE as_of_date BETWEEN %(s)s AND %(e)s",
            {"s": start, "e": end})
        n_rows = cur.rowcount
    conn.commit()
    return n_rows, n_marks


def delete_eod_marks(conn, start, end) -> int:
    """Drop EOD marks stamped inside [start, end] (ET calendar dates)."""
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {BOOK_MARKS_TABLE} WHERE mark_kind = 'EOD' AND "
            "(mark_ts AT TIME ZONE 'America/New_York')::date BETWEEN %(s)s AND %(e)s",
            {"s": start, "e": end})
        n = cur.rowcount
    conn.commit()
    return n


def write_ladder_rows(conn, rows):
    if not rows:
        return
    sql = (
        f"INSERT INTO {LADDER_PRINTS_TABLE} ({', '.join(LADDER_COLUMNS)}) VALUES %s "
        f"ON CONFLICT (unit_key, bucket_space, bucket_key) DO UPDATE SET "
        + ", ".join(f"{c} = EXCLUDED.{c}" for c in LADDER_COLUMNS
                    if c not in ("unit_key", "bucket_space", "bucket_key"))
    )
    with conn.cursor() as cur:
        _execute_values(cur, sql, [tuple(r.get(c) for c in LADDER_COLUMNS) for r in rows])
    conn.commit()


def write_mark_rows(conn, rows):
    if not rows:
        return
    sql = (
        f"INSERT INTO {BOOK_MARKS_TABLE} ({', '.join(MARK_COLUMNS)}) VALUES %s "
        f"ON CONFLICT (unit_key, mark_ts) DO UPDATE SET "
        + ", ".join(f"{c} = EXCLUDED.{c}" for c in MARK_COLUMNS
                    if c not in ("unit_key", "mark_ts"))
    )
    with conn.cursor() as cur:
        _execute_values(cur, sql, [tuple(r.get(c) for c in MARK_COLUMNS) for r in rows])
    conn.commit()


def run_project_phase(conn, start, end, limit=0, dry_run=False, warm_jobs=8,
                      warm=True, rewrite=False) -> dict:
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    if rewrite and not dry_run:
        n_rows, n_marks = delete_projections(conn, start, end)
        print(f"rewrite: deleted {n_rows} ladder rows + {n_marks} ENTRY marks "
              f"({start}..{end})")

    directions = load_directions(conn, start, end)
    units = _load_units(conn, start, end)
    done = set() if rewrite else _already_projected(conn, start, end)
    todo = directions[~directions["unit_key"].isin(done)]
    todo = todo[todo["unit_key"].isin(units.keys())]
    if limit:
        todo = todo.head(limit)

    mdp = IRSwapsMDP(source=config.CURVE_SOURCE)
    stirf = STIRFutureMDP(source=config.CURVE_SOURCE)
    pricer = CurvePricer(mdp=mdp)

    # group by (curve, snapshot minute) so risk models build once per group
    metas = []
    for _, drow in todo.iterrows():
        u = units[drow["unit_key"]]
        first = u.legs.iloc[0]
        snap = snap_timestamp(first.get("original_execution_timestamp"),
                              first["execution_timestamp"])
        metas.append((config.CURVE_FOR[drow["rate_index_clean"]], snap, drow, u))
    metas.sort(key=lambda m: (m[0], m[1]))

    if warm and metas:
        demand = {(cn, snap) for cn, snap, _d, _u in metas}
        wr = curve_warm.warm_pricer(pricer, demand, max_workers=warm_jobs)
        print(f"warmed curves: built={wr['built']} reused={wr['reused']} "
              f"failed={wr['failed']} (demand={len(demand)})")

    cache = {}
    ladder_rows, mark_rows = [], []
    n = 0
    errors = {}
    for curve_name, snap, drow, u in metas:
        try:
            key = (curve_name, snap)
            if key not in cache:
                h = pricer.handle(curve_name, snap)
                cache[key] = build_risk_models(
                    curve_name, h, snap, stirf,
                    include_basis=(drow["rate_index_clean"] == "FED_FUNDS"))
            rows, entry = project_unit(u, drow.to_dict(), cache[key], pricer, curve_name, snap)
            ladder_rows.extend(rows)
            mark_rows.append(entry)
            n += 1
            if len(ladder_rows) >= 2000 and not dry_run:
                write_ladder_rows(conn, ladder_rows)
                write_mark_rows(conn, mark_rows)
                ladder_rows, mark_rows = [], []
        except Exception as exc:  # noqa: BLE001 per-unit isolation
            tag = f"{type(exc).__name__}: {str(exc)[:120]}"
            errors[tag] = errors.get(tag, 0) + 1
            print(f"PROJECT_ERROR {drow['unit_key']}: {exc}")
    if not dry_run:
        write_ladder_rows(conn, ladder_rows)
        write_mark_rows(conn, mark_rows)
    print(f"projected {n}/{len(metas)} units ({start}..{end}) vintage={code_vintage()}")
    if errors:
        print(f"project error histogram: {errors}")
    return {"projected": n, "eligible": len(metas), "errors": errors}


def run_marks_phase(conn, start, end, dry_run=False, rewrite=False) -> int:
    """EOD marks for every business day in [start, end], loading prints per day."""
    if rewrite and not dry_run:
        print(f"rewrite: deleted {delete_eod_marks(conn, start, end)} EOD marks")
    pricer = CurvePricer()
    total = 0
    for d in pd.date_range(start, end, freq="B"):
        total += _marks_for_day(conn, d.date(), pricer, dry_run=dry_run)
    return total


def _marks_for_day(conn, mark_date, pricer, dry_run=False) -> int:
    """One session's EOD marks. Only same-session prints can still be open at 17:00 ET.

    The open-position test is the 3-half-life EWMA cutoff, i.e. 270min for
    non-block and 720min for block prints, so loading [mark_date-1, mark_date]
    is strictly more than needed and keeps memory flat in window length.
    """
    lo = mark_date - datetime.timedelta(days=1)
    prints = pd.read_sql(
        f"SELECT * FROM {LADDER_PRINTS_TABLE} WHERE as_of_date BETWEEN %(s)s AND %(e)s",
        conn, params={"s": lo, "e": mark_date})
    if prints.empty:
        print(f"{mark_date}: no projections in window; skipped")
        return 0
    directions = load_directions(conn, lo, mark_date)
    dmap = {r["unit_key"]: r for r in directions.to_dict(orient="records")}
    units = _load_units(conn, lo, mark_date)
    entries = pd.read_sql(
        f"SELECT unit_key, npv_usd FROM {BOOK_MARKS_TABLE} "
        "WHERE mark_kind = 'ENTRY' AND unit_key = ANY(%(keys)s)",
        conn, params={"keys": list(prints["unit_key"].unique())})
    entry_marks = dict(zip(entries["unit_key"], entries["npv_usd"]))
    unw = unwinds.extract_unwind_events(conn, lo, mark_date, set(prints["unit_key"]))

    eod_ts = NY.localize(datetime.datetime(mark_date.year, mark_date.month,
                                           mark_date.day, 17, 0))
    open_df = book.open_positions(prints, unw, eod_ts, PROVISIONAL_HALF_LIVES_MIN)
    rows = book.eod_mark_rows(units, dmap, entry_marks, pricer, mark_date,
                              list(open_df["unit_key"]))
    if not dry_run:
        write_mark_rows(conn, rows)
    print(f"{mark_date}: {len(rows)} EOD marks (open={len(open_df)})")
    return len(rows)


# ----------------------------- range drivers --------------------------------
def _project_one_day(job):
    date_iso, warm_jobs, dry_run, rewrite, pg_url, log_dir = job
    with day_log(log_dir, f"project-{date_iso}"):
        conn = psycopg2.connect(pg_url or resolve_pg_url())
        try:
            res = run_project_phase(conn, date_iso, date_iso, dry_run=dry_run,
                                    warm_jobs=warm_jobs, rewrite=rewrite)
            return {"date": date_iso, "error": None, **res}
        except Exception as exc:  # isolate a bad day; keep the range going
            import traceback
            traceback.print_exc()
            return {"date": date_iso, "projected": 0, "eligible": 0, "errors": {},
                    "error": repr(exc)}
        finally:
            conn.close()


def _marks_one_day(job):
    date_iso, dry_run, rewrite, pg_url, log_dir = job
    with day_log(log_dir, f"marks-{date_iso}"):
        conn = psycopg2.connect(pg_url or resolve_pg_url())
        try:
            if rewrite and not dry_run:
                delete_eod_marks(conn, date_iso, date_iso)
            n = _marks_for_day(conn, pd.Timestamp(date_iso).date(), CurvePricer(),
                               dry_run=dry_run)
            return {"date": date_iso, "marks": n, "error": None}
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return {"date": date_iso, "marks": 0, "error": repr(exc)}
        finally:
            conn.close()


def run_range(phase, start, end, *, day_jobs=3, warm_jobs=4, dry_run=False,
              rewrite=False, pg_url=None, executor_factory=None, business_days=True,
              log_dir=None):
    """Fan a phase out across independent days in a process pool."""
    url = pg_url or resolve_pg_url()
    freq = "B" if business_days else "D"
    dates = [d.date().isoformat() for d in pd.date_range(start, end, freq=freq)]
    if phase == "project":
        worker = _project_one_day
        jobs = [(d, warm_jobs, dry_run, rewrite, url, log_dir) for d in dates]
    elif phase == "marks":
        worker = _marks_one_day
        jobs = [(d, dry_run, rewrite, url, log_dir) for d in dates]
    else:
        raise ValueError(f"range driver supports project|marks, not {phase!r}")

    if executor_factory is None:
        def executor_factory():
            return ProcessPoolExecutor(max_workers=day_jobs)

    results = []
    with executor_factory() as ex:
        futs = {ex.submit(worker, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            if r["error"]:
                print(f"[{r['date']}] ERROR {r['error']}")
            elif phase == "project":
                print(f"[{r['date']}] projected {r['projected']}/{r['eligible']}"
                      + (f" errors={r['errors']}" if r["errors"] else ""))
            else:
                print(f"[{r['date']}] {r['marks']} EOD marks")
    results.sort(key=lambda r: r["date"])
    return results


def run_snapshot_phase(conn, snapshot_ts) -> None:
    ts = NY.localize(pd.Timestamp(snapshot_ts).to_pydatetime()) \
        if pd.Timestamp(snapshot_ts).tzinfo is None else pd.Timestamp(snapshot_ts)
    lo = (ts.date() - datetime.timedelta(days=1))
    prints = pd.read_sql(
        f"SELECT * FROM {LADDER_PRINTS_TABLE} WHERE as_of_date BETWEEN %(s)s AND %(e)s",
        conn, params={"s": lo, "e": ts.date()})
    if prints.empty:
        print(f"no projections in {lo}..{ts.date()}; run the project phase first")
        return
    directions = load_directions(conn, lo, ts.date())
    dmap = {r["unit_key"]: r for r in directions.to_dict(orient="records")}
    units = _load_units(conn, lo, ts.date())
    entries = pd.read_sql(
        f"SELECT unit_key, npv_usd FROM {BOOK_MARKS_TABLE} "
        "WHERE mark_kind = 'ENTRY' AND unit_key = ANY(%(keys)s)",
        conn, params={"keys": list(prints["unit_key"].unique())})
    unw = unwinds.extract_unwind_events(conn, lo, ts.date(), set(prints["unit_key"]))
    snap = book.book_snapshot(units, dmap, prints, unw, CurvePricer(), ts,
                              entry_marks=dict(zip(entries["unit_key"], entries["npv_usd"])))
    for space, series in snap.ladders.items():
        print(f"\n== {space} ladder @ {ts} (dealer dv01, + = long fut-equiv) ==")
        print(series.round(0).to_string())
    print(f"\ngross book P&L:    {snap.gross_pnl_usd:,.0f}")
    print(f"residual book P&L: {snap.residual_pnl_usd:,.0f}")
    print(f"open positions:    {len(snap.per_unit)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["project", "marks", "snapshot"], required=True)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--snapshot-ts")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rewrite", action="store_true",
                    help="delete the window's rows before writing (convention changes)")
    ap.add_argument("--warm-jobs", type=int, default=8,
                    help="thread pool size for concurrent curve warming")
    ap.add_argument("--no-warm", action="store_true")
    ap.add_argument("--day-jobs", type=int, default=0,
                    help=">0 fans days out across a process pool (project|marks)")
    ap.add_argument("--pg-url", default=None)
    ap.add_argument("--log-dir", default=None,
                    help="write one log file per day per phase (range mode)")
    args = ap.parse_args()

    if args.phase in ("project", "marks") and not (args.start and args.end):
        ap.error(f"--phase {args.phase} requires --start and --end")
    if args.phase == "snapshot" and not args.snapshot_ts:
        ap.error("--phase snapshot requires --snapshot-ts")

    print(f"code_vintage = {code_vintage()}")
    if args.day_jobs and args.phase in ("project", "marks"):
        conn = psycopg2.connect(resolve_pg_url(args.pg_url))
        ensure_schema(conn)
        conn.close()
        results = run_range(args.phase, args.start, args.end, day_jobs=args.day_jobs,
                            warm_jobs=args.warm_jobs, dry_run=args.dry_run,
                            rewrite=args.rewrite, pg_url=args.pg_url,
                            log_dir=args.log_dir)
        n_err = sum(1 for r in results if r["error"])
        print(f"\nrange done: {len(results)} days, {n_err} day-errors")
        return 1 if n_err else 0

    conn = psycopg2.connect(resolve_pg_url(args.pg_url))
    ensure_schema(conn)
    if args.phase == "project":
        run_project_phase(conn, args.start, args.end, args.limit, args.dry_run,
                          warm_jobs=args.warm_jobs, warm=not args.no_warm,
                          rewrite=args.rewrite)
    elif args.phase == "marks":
        run_marks_phase(conn, args.start, args.end, args.dry_run, rewrite=args.rewrite)
    else:
        run_snapshot_phase(conn, args.snapshot_ts)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
