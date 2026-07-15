# SDRUtils/_swappulse_scripts/backfill_stir_ladder.py
"""Backfill the dealer positioning ladder: projection, EOD marks, snapshots.

Phases:
  project  — project classified prints onto ladders + write ENTRY marks (resumable)
  marks    — EOD reval of open positions per date in [start, end]
  snapshot — print ladder + book P&L at an arbitrary intraday timestamp
Writes ONLY arbs_stir_ladder_prints_v1 / arbs_stir_book_marks_v1.
"""
from __future__ import annotations

import argparse
import datetime
import sys

import pandas as pd
import psycopg2
import pytz
from psycopg2.extras import execute_values as _execute_values

from SDRUtils._swappulse_scripts._stir_ladder_schema_v1 import (
    BOOK_MARKS_TABLE, LADDER_PRINTS_TABLE, ensure_schema,
)
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.stir_flow import book, config, ladder_state, unwinds
from SDRUtils.stir_flow.ladder import LADDER_COLUMNS, build_risk_models, project_unit
from SDRUtils.stir_flow.pricing import CurvePricer, snap_timestamp
from SDRUtils.stir_flow.trade_selection import (
    ALL_PKG_LEGS_SQL, ELIGIBLE_LEGS_SQL, build_units, is_excluded_unit,
)

NY = pytz.timezone("America/New_York")
MARK_COLUMNS = ["unit_key", "mark_ts", "mark_kind", "npv_usd", "pnl_since_entry_usd", "curve_name"]


def load_directions(conn, start, end) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT unit_key, trade_id, package_id, trade_type, rate_index_clean, "
        "classification_method, dealer_direction, p_flip, direction_confidence, "
        "curve_suspect_trade, structure_dv01, as_of_date "
        "FROM arbs_stir_direction_v1 "
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


def run_project_phase(conn, start, end, limit=0, dry_run=False) -> int:
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    directions = load_directions(conn, start, end)
    units = _load_units(conn, start, end)
    done = _already_projected(conn, start, end)
    todo = directions[~directions["unit_key"].isin(done)]
    todo = todo[todo["unit_key"].isin(units.keys())]
    if limit:
        todo = todo.head(limit)

    mdp = IRSwapsMDP(source=config.CURVE_SOURCE)
    stirf = STIRFutureMDP(source=config.CURVE_SOURCE)
    pricer = CurvePricer(mdp=mdp)
    n = 0
    # group by (curve, snapshot minute) so risk models build once per group
    metas = []
    for _, drow in todo.iterrows():
        u = units[drow["unit_key"]]
        first = u.legs.iloc[0]
        snap = snap_timestamp(first.get("original_execution_timestamp"),
                              first["execution_timestamp"])
        metas.append((config.CURVE_FOR[drow["rate_index_clean"]], snap, drow, u))
    metas.sort(key=lambda m: (m[0], m[1]))
    cache = {}
    ladder_rows, mark_rows = [], []
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
            print(f"PROJECT_ERROR {drow['unit_key']}: {exc}")
    if not dry_run:
        write_ladder_rows(conn, ladder_rows)
        write_mark_rows(conn, mark_rows)
    print(f"projected {n} units ({start}..{end})")
    return n


def run_marks_phase(conn, start, end, dry_run=False) -> int:
    prints = pd.read_sql(f"SELECT * FROM {LADDER_PRINTS_TABLE}", conn)
    if prints.empty:
        print("no projections; run project phase first")
        return 0
    directions = load_directions(conn, prints["as_of_date"].min(), end)
    dmap = {r["unit_key"]: r for r in directions.to_dict(orient="records")}
    units = _load_units(conn, prints["as_of_date"].min(), end)
    entries = pd.read_sql(
        f"SELECT unit_key, npv_usd FROM {BOOK_MARKS_TABLE} WHERE mark_kind = 'ENTRY'", conn)
    entry_marks = dict(zip(entries["unit_key"], entries["npv_usd"]))
    unw = unwinds.extract_unwind_events(conn, prints["as_of_date"].min(), end,
                                        set(prints["unit_key"]))
    pricer = CurvePricer()
    total = 0
    for d in pd.date_range(start, end, freq="B"):
        mark_date = d.date()
        eod_ts = NY.localize(datetime.datetime(mark_date.year, mark_date.month, mark_date.day, 17, 0))
        from SDRUtils.stir_flow.ladder_conventions import PROVISIONAL_HALF_LIVES_MIN
        open_df = book.open_positions(prints, unw, eod_ts, PROVISIONAL_HALF_LIVES_MIN)
        rows = book.eod_mark_rows(units, dmap, entry_marks, pricer, mark_date,
                                  list(open_df["unit_key"]))
        if not dry_run:
            write_mark_rows(conn, rows)
        total += len(rows)
        print(f"{mark_date}: {len(rows)} EOD marks")
    return total


def run_snapshot_phase(conn, snapshot_ts) -> None:
    ts = NY.localize(pd.Timestamp(snapshot_ts).to_pydatetime()) \
        if pd.Timestamp(snapshot_ts).tzinfo is None else pd.Timestamp(snapshot_ts)
    prints = pd.read_sql(f"SELECT * FROM {LADDER_PRINTS_TABLE}", conn)
    directions = load_directions(conn, prints["as_of_date"].min(), ts.date())
    dmap = {r["unit_key"]: r for r in directions.to_dict(orient="records")}
    units = _load_units(conn, prints["as_of_date"].min(), ts.date())
    entries = pd.read_sql(
        f"SELECT unit_key, npv_usd FROM {BOOK_MARKS_TABLE} WHERE mark_kind = 'ENTRY'", conn)
    unw = unwinds.extract_unwind_events(conn, prints["as_of_date"].min(), ts.date(),
                                        set(prints["unit_key"]))
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
    ap.add_argument("--pg-url", default=None)
    args = ap.parse_args()

    conn = psycopg2.connect(resolve_pg_url(args.pg_url))
    ensure_schema(conn)
    if args.phase == "project":
        run_project_phase(conn, args.start, args.end, args.limit, args.dry_run)
    elif args.phase == "marks":
        run_marks_phase(conn, args.start, args.end, args.dry_run)
    else:
        run_snapshot_phase(conn, args.snapshot_ts)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
