"""Build the unwind-lineage sidecar over a date range. Resumable, and loud.

    python scripts/build_dd_lineage_store.py build --start 2026-06-01 --end 2026-07-20
    python scripts/build_dd_lineage_store.py build --trailing-days 90
    python scripts/build_dd_lineage_store.py report --start 2026-05-13 --end 2026-08-10
    python scripts/build_dd_lineage_store.py slices --day 2026-06-16 --sample 60

Two phases, deliberately separate:

1. **fetch** each business day's cumulative DTCC zip into the unfiltered raw
   cache. This is the resumable unit and the only phase that touches the
   network.
2. **resolve** over the UNION of everything cached, then write one lineage
   partition per target day. Resolution is not per-day: a termination on D can
   point at a MODI from D-3 that points at the NEWT from D-40, and resolving a
   day against only its own frame manufactures broken chains.

Zero rows on a day is an **abort**, never a skip. A backfill in this repo once
recorded days as ``ok`` on exit code 0 while the upstream returned an empty
frame, and six days of data were destroyed.

Exit codes: **0** = every day this pass took on is on disk with rows in it;
**2** = a day failed. Under ``--limit N`` a 0 does NOT mean the whole range is
built -- the pass reports how many target days remain and the next one to do, and
resume picks them up. A driver should loop until "nothing to do", not until 0.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils.dealer_direction import lineage as lin

#: Bumped when the RESOLVER changes, so a store holding two vintages is
#: visible in the ledger instead of being inferred from row counts. v2 added
#: SELF_POINTER; v1 resolved a self-pointing row to itself and called it a hit.
#: v3 changes resolver OUTPUT and a v2 partition is not comparable to a v3 one:
#: a walk that ends ON a self-pointer is now TERMINAL_SELF_POINTER instead of
#: RESOLVED_RAW_ONLY (30 rows in the measured week, so `resolved` falls), a
#: chain that finishes in exactly `max_hops` hops now resolves instead of
#: reporting MAX_HOPS with its reach-back discarded, and a non-numeric pointer
#: is UNRESOLVED instead of MISSING_IN_RANGE.
CODE_VINTAGE = "dd_lineage_v3"


def business_days(start: datetime.date, end: datetime.date) -> list:
    return [d.date() for d in pd.date_range(
        start=start, end=end, freq=CustomBusinessDay(calendar=USFederalHolidayCalendar()))]


def target_days(args) -> list:
    """The requested window, plus the trailing window, as one sorted set.

    The two are unioned rather than run separately so resume, the target-set
    check and the resolution universe all see the same day list.
    """
    days = set()
    if args.start and args.end:
        days |= set(business_days(datetime.date.fromisoformat(args.start),
                                  datetime.date.fromisoformat(args.end)))
    if args.trailing_days:
        end = (datetime.date.fromisoformat(args.as_of) if args.as_of
               else datetime.date.today() - datetime.timedelta(days=1))
        days |= set(business_days(end - datetime.timedelta(days=int(args.trailing_days)), end))
    return sorted(days)


# --------------------------------------------------------------------------
# the tape side: read-only, and only ever read
# --------------------------------------------------------------------------

def _tape_conn():
    import psycopg2

    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    conn = psycopg2.connect(resolve_pg_url())
    conn.set_session(readonly=True)          # belt and braces: this job never writes
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '300s'")
    return conn


def tape_exec_ts_lookup(conn, *, chunk=4000):
    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

    def lookup(ids):
        ids = [str(i) for i in ids if i]
        out = {}
        if not ids:
            return out
        with conn.cursor() as cur:
            for i in range(0, len(ids), chunk):
                cur.execute(
                    f"SELECT trade_id, min(execution_timestamp) FROM {LEGS_TABLE} "
                    "WHERE trade_id = ANY(%s) GROUP BY trade_id", (ids[i:i + chunk],))
                out.update({r[0]: r[1] for r in cur.fetchall() if r[1] is not None})
        return out

    return lookup


def tape_id_range(conn):
    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

    with conn.cursor() as cur:
        cur.execute(f"SELECT min(trade_id::bigint), max(trade_id::bigint) FROM {LEGS_TABLE} "
                    "WHERE trade_id ~ '^[0-9]+$'")
        lo, hi = cur.fetchone()
    return (int(lo), int(hi)) if lo is not None else None


# --------------------------------------------------------------------------
# phase 1
# --------------------------------------------------------------------------

def fetch_days(days, *, root, force=False, zip_source=None) -> dict:
    """Cache each day's unfiltered zip. Raises on the first empty day."""
    counts = {}
    for d in days:
        path = lin.raw_day_path(d, root=root)
        cached = path.exists() and not force
        t0 = time.perf_counter()
        df = lin.fetch_raw_day(d, root=root, force=force, zip_source=zip_source)
        if df.empty:
            raise lin.EmptyDTCCDay(f"{d}: cumulative file parsed to zero rows")
        counts[d] = len(df)
        print(f"  raw {d}  rows={len(df):>7,}  {'cached' if cached else 'fetched'}"
              f"  {time.perf_counter() - t0:5.1f}s", flush=True)
    return counts


# --------------------------------------------------------------------------
# phase 2
# --------------------------------------------------------------------------

def resolve_and_write(days, *, root, store, use_tape=True) -> dict:
    universe = sorted(set(days) | set(_cached_raw_days(root)))
    raw = lin.load_raw_days(universe, root=root)
    if raw.empty:
        raise lin.EmptyDTCCDay("the raw cache holds no rows for any requested day")
    print(f"  resolution universe: {len(raw):,} rows over {len(universe)} cached days", flush=True)

    conn = lookup = id_range = None
    if use_tape:
        conn = _tape_conn()
        lookup = tape_exec_ts_lookup(conn)
        id_range = tape_id_range(conn)
        print(f"  tape trade_id range: {id_range}", flush=True)
    try:
        t0 = time.perf_counter()
        resolved = lin.resolve_lineage(raw, exec_ts_lookup=lookup, tape_id_range=id_range)
        print(f"  resolved {len(resolved):,} pointer rows in {time.perf_counter() - t0:.1f}s",
              flush=True)
    finally:
        if conn is not None:
            conn.close()

    written = {}
    resolved["file_date"] = pd.to_datetime(resolved["file_date"]).dt.date
    for d in days:
        part = resolved[resolved["file_date"] == d]
        n = store.write_day(d, part)          # raises EmptyLineageDay on zero rows
        store.record(d, rows=n, code_vintage=CODE_VINTAGE,
                     resolved=int(part["status"].isin(lin.RESOLVED_STATUSES).sum()),
                     # A day written by a `--limit` pass is resolved against a
                     # smaller universe than a later pass would give it, and
                     # `days_needing_work` never revisits it. Recorded so a
                     # store whose statuses were decided on different universes
                     # is visible rather than inferred.
                     universe_days=len(universe))
        written[d] = n
        print(f"  lineage {d}  rows={n:>6,}", flush=True)
    return written


def _cached_raw_days(root) -> list:
    base = lin.store_root(root) / lin.RAW_SUBDIR
    if not base.exists():
        return []
    return sorted(datetime.date.fromisoformat(p.stem) for p in base.rglob("*.parquet"))


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_build(args) -> int:
    days = target_days(args)
    if not days:
        print("no days requested", file=sys.stderr)
        return 2
    store = lin.LineageStore(root=args.root)
    todo = days if args.force else store.days_needing_work(days)
    print(f"target {len(days)} business days {days[0]} .. {days[-1]}; "
          f"{len(todo)} outstanding (resume is keyed to the target set, not the ledger)",
          flush=True)
    if not todo:
        print("nothing to do", flush=True)
        return 0
    if args.limit:
        todo = todo[:int(args.limit)]
        print(f"limited to {len(todo)} days this pass", flush=True)

    try:
        fetch_days(todo, root=args.root, force=args.force)
    except lin.EmptyDTCCDay as exc:
        print(f"FAIL fetch: {exc}", file=sys.stderr)
        return 2
    try:
        written = resolve_and_write(todo, root=args.root, store=store, use_tape=not args.no_tape)
    except lin.EmptyLineageDay as exc:
        print(f"FAIL resolve: {exc}", file=sys.stderr)
        return 2

    # (a zero-row day cannot reach here: `write_day` raises EmptyLineageDay and
    # `resolve_and_write` propagates it, which the handler above turns into a 2.)
    print(f"\nwrote {sum(written.values()):,} lineage rows over {len(written)} days",
          flush=True)
    # The target-set check again, AFTER writing: a day that reported rows but
    # left no file on disk is the failure mode the ledger cannot see. Scoped to
    # THIS pass's days -- `--limit` is the documented chunking mode ("days per
    # pass; resume handles the rest"), so checking the full range would make
    # every successful chunked pass exit 2 and any unattended driver read its
    # own chunking as a hard failure.
    still = store.days_needing_work(todo)
    if still:
        print(f"FAIL: {len(still)} day(s) still have no rows on disk: {still[:10]}",
              file=sys.stderr)
        return 2
    remaining = store.days_needing_work(days)
    if remaining:
        print(f"{len(remaining)} day(s) of the target range remain for a later pass; "
              f"next is {remaining[0]}", flush=True)
    return 0


def cmd_report(args) -> int:
    store = lin.LineageStore(root=args.root)
    days = target_days(args) or store.covered_days()
    if not days:
        print("store is empty and no range was given", file=sys.stderr)
        return 2
    df = store.read_range(min(days), max(days))
    if df.empty:
        print("store is empty for that range", file=sys.stderr)
        return 2
    import json

    summary = lin.coverage_summary(df)
    print(json.dumps(summary, indent=1, default=str))

    term = df[df["action_type"] == "TERM"]
    if len(term):
        # Two different numbers, and confusing them overstates the flippable
        # population by 4x: "resolved" is "the walk found an original at all",
        # "tape-resolved" is "that original is a row you can join to".
        res = term["status"].isin(lin.RESOLVED_STATUSES)
        tap = term["status"] == lin.ST_RESOLVED_TAPE
        print(f"\nTERM rows {len(term):,}  resolved to ANY original {int(res.sum()):,} = "
              f"{100 * res.mean():.1f}%  |  resolved to a TAPE row {int(tap.sum()):,} = "
              f"{100 * tap.mean():.1f}%")
        print(term.groupby("event_type")["status"].value_counts().unstack(fill_value=0).to_string())
    return 0


def cmd_slices(args) -> int:
    """Time the slice enumeration before promising the measured clock at scale."""
    day = datetime.date.fromisoformat(args.day)
    total = int(args.total)
    seqs = (list(range(1, total + 1)) if args.full
            else list(range(1, total + 1, max(1, total // int(args.sample)))) [:int(args.sample)])
    t0 = time.perf_counter()
    try:
        pubs = lin.fetch_slice_publications(day, seqs, workers=int(args.workers))
    except lin.EmptyDTCCDay as exc:
        # Every slice unreadable. Reported as a failure, not as "this day has no
        # measured clock" -- the two are indistinguishable in the output.
        print(f"FAIL slices: {exc}", file=sys.stderr)
        return 2
    dt = time.perf_counter() - t0
    n = len(seqs)
    print(f"{n} slices in {dt:.1f}s at {args.workers} workers = {dt / n:.2f}s/slice; "
          f"{len(pubs):,} distinct ids")
    print(f"extrapolated full day ({total} slices): {dt / n * total / 60:.1f} min")
    if not pubs.empty and lin.EVENT_TS in pubs.columns:
        ev = pd.to_datetime(pubs[lin.EVENT_TS], utc=True, errors="coerce")
        lag = (pd.to_datetime(pubs["published_at"], utc=True) - ev).dt.total_seconds() / 60
        sub = pubs.assign(lag_min=lag)
        fisn = sub["UPI FISN"] if "UPI FISN" in sub.columns else pd.Series("", index=sub.index)
        newt = sub[(sub[lin.ACTION] == "NEWT") & (fisn == "NA/Swap OIS USD")]
        print(f"\npublication lag (min), NEWT / NA/Swap OIS USD, n={len(newt)}:")
        if len(newt):
            print(newt["lag_min"].describe(percentiles=[.5, .9, .95]).round(2).to_string())
        print("\nby action type:")
        print(sub.groupby(lin.ACTION)["lag_min"].describe(percentiles=[.5, .95])
              [["count", "50%", "95%", "max"]].round(2).to_string())
    if args.out:
        pubs.to_parquet(args.out, index=False)
        print("wrote", args.out)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=None, help=f"store root (env {lin.STORE_ROOT_ENV})")
    sub = p.add_subparsers(dest="cmd", required=True)

    def _range_args(sp):
        sp.add_argument("--start")
        sp.add_argument("--end")
        sp.add_argument("--trailing-days", type=int, default=0)
        sp.add_argument("--as-of", default=None, help="anchor for --trailing-days")

    b = sub.add_parser("build")
    _range_args(b)
    b.add_argument("--force", action="store_true", help="refetch and rewrite days already held")
    b.add_argument("--limit", type=int, default=0, help="days per pass; resume handles the rest")
    b.add_argument("--no-tape", action="store_true",
                   help="skip the tape lookup (statuses stay RESOLVED_RAW_ONLY / UNRESOLVED)")
    b.set_defaults(func=cmd_build)

    r = sub.add_parser("report")
    _range_args(r)
    r.set_defaults(func=cmd_report)

    s = sub.add_parser("slices")
    s.add_argument("--day", required=True)
    s.add_argument("--sample", type=int, default=60)
    # Measured by bisection, not taken from the listing: a day's sequence ends
    # at 1,896-1,969 on the three days probed. The listing's ~1,333 is a rolling
    # 24 h window and stopping there covers only 73.7% of a day.
    s.add_argument("--total", type=int, default=2000)
    s.add_argument("--full", action="store_true")
    s.add_argument("--workers", type=int, default=8)
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_slices)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
