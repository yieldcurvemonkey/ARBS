"""Drop cached computed-timeseries rows so they get recomputed.

Needed because the computed cache is read *before* the curve store
(``TimeseriesBuilder._read_irs_computed_cache_rows``). Quarantining a bad
snapshot in the store, or rebuilding it outright, changes nothing a caller sees
until the rows derived from it are gone: a warm rerun of an affected query
returns entirely from ``data/ts`` without touching a single raw node.

Purging is cheap and safe. The curve store is the source of truth, so anything
removed here is recomputed on the next query -- roughly 15s for a quarter of
hourly data on one curve.

Dry-run by default. Pass ``--apply`` to delete.

Selecting what to purge
-----------------------
Symbols longer than 48 characters are stored under a truncated directory name
plus a hash (``_sanitize_symbol``), so ``IRS::BARCHART_STIRF-RL::<curve>::<query
fingerprint>`` lands in ``asset=IRS__BARCHART_STIRF-RL__<digest>``. The curve
name is not recoverable from the directory. Two ways to select:

* ``--symbol`` -- exact, repeatable, resolved through the store's own path
  helper. Precise, but you need the query fingerprint.
* ``--dir-contains`` -- substring of the sanitised directory name, e.g.
  ``IRS__BARCHART_STIRF-RL__``. Over-broad (it takes every query against that
  source) but correct: everything it removes is recomputed on demand.

Examples
--------
    python scripts/purge_computed_timeseries.py --list

    # everything derived from BARCHART_STIRF IRS curves over the window
    python scripts/purge_computed_timeseries.py \
        --dir-contains IRS__BARCHART_STIRF-RL__ \
        --start 2026-06-30 --end 2026-07-30

    python scripts/purge_computed_timeseries.py \
        --dir-contains IRS__BARCHART_STIRF-RL__ \
        --start 2026-06-30 --end 2026-07-30 --apply

Concurrency
-----------
A live kernel usually holds a write lock on ``computed_ts.duckdb``. The Parquet
purge still runs; the DuckDB mirror is reported as skipped and the script tells
you to re-run once the lock clears. Do not delete Parquet partitions while a
process is actively writing the same symbol.
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _partition_days(symbol_dir: Path, start: datetime.date | None, end: datetime.date | None) -> list[Path]:
    out = []
    for part in sorted(symbol_dir.glob("date=*")):
        try:
            day = datetime.date.fromisoformat(part.name.split("=", 1)[1])
        except ValueError:
            continue
        if start and day < start:
            continue
        if end and day > end:
            continue
        out.append(part)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir-contains", help="substring of the sanitised symbol DIRECTORY name")
    p.add_argument("--symbol", action="append", default=[], help="exact symbol (repeatable)")
    p.add_argument("--list", action="store_true", help="list symbol directories and exit")
    p.add_argument("--start", help="first calendar date to purge, YYYY-MM-DD")
    p.add_argument("--end", help="last calendar date to purge, YYYY-MM-DD")
    p.add_argument("--base-dir", help="computed-timeseries base dir (defaults to <repo>/data/ts)")
    p.add_argument("--apply", action="store_true", help="actually delete (default is a dry run)")
    args = p.parse_args(argv)

    from Caching.computed_timeseries_store import default_computed_timeseries_base_dir
    from Caching.timeseries_cache import _resolve_symbol_dir

    base = Path(args.base_dir) if args.base_dir else Path(default_computed_timeseries_base_dir())
    if not base.is_dir():
        print(f"No computed-timeseries store at {base}", file=sys.stderr)
        return 2

    if args.list:
        dirs = sorted(d for d in base.glob("asset=*") if d.is_dir())
        print(f"{len(dirs)} symbol director(ies) under {base}:")
        for d in dirs:
            n = len(list(d.glob("date=*")))
            print(f"  {d.name}  ({n} partitions)")
        return 0

    if not args.dir_contains and not args.symbol:
        print("Give --dir-contains or --symbol (or --list).", file=sys.stderr)
        return 2

    start = datetime.date.fromisoformat(args.start) if args.start else None
    end = datetime.date.fromisoformat(args.end) if args.end else None

    needle = args.dir_contains or ""
    symbol_dirs = []
    if needle:
        symbol_dirs += [d for d in base.glob("asset=*") if d.is_dir() and needle in d.name]
    for sym in args.symbol:
        d = _resolve_symbol_dir(base, sym)
        if d.is_dir():
            symbol_dirs.append(d)
        else:
            print(f"note: no directory for symbol {sym!r} (looked at {d.name})", file=sys.stderr)
    symbol_dirs = sorted(set(symbol_dirs))
    if not symbol_dirs:
        print(f"No symbol directories under {base} matched.", file=sys.stderr)
        return 2

    total_parts = total_bytes = 0
    plan: list[tuple[Path, int, int]] = []
    for sym_dir in sorted(symbol_dirs):
        parts = _partition_days(sym_dir, start, end)
        size = sum(f.stat().st_size for part in parts for f in part.rglob("*") if f.is_file())
        plan.append((sym_dir, len(parts), size))
        total_parts += len(parts)
        total_bytes += size

    print(f"store: {base}")
    print(f"match: dir~{needle!r} + {len(args.symbol)} exact symbol(s)   range: {start or '(all)'} .. {end or '(all)'}")
    for sym_dir, n, size in plan:
        print(f"  {sym_dir.name}: {n} partition(s), {size / 1e6:.1f} MB")
    print(f"TOTAL: {len(plan)} symbol(s), {total_parts} partition(s), {total_bytes / 1e6:.1f} MB")

    if not args.apply:
        print("\nDRY RUN -- nothing deleted. Re-run with --apply.")
        return 0

    removed = 0
    for sym_dir, _, _ in plan:
        for part in _partition_days(sym_dir, start, end):
            shutil.rmtree(part, ignore_errors=True)
            removed += 1
    print(f"\ndeleted {removed} Parquet partition(s)")

    # DuckDB mirror. Serves reads on its own, so stale rows there would keep the
    # poisoned values alive even with the Parquet gone.
    db_path = base / "computed_ts.duckdb"
    if not db_path.exists():
        print("no DuckDB mirror present")
        return 0
    try:
        import duckdb

        con = duckdb.connect(str(db_path))
    except Exception as exc:
        print(f"\nWARNING: DuckDB mirror is locked ({exc.__class__.__name__}); Parquet purged but the "
              f"mirror still holds these rows.\n"
              f"         Close the kernel holding {db_path} and re-run with --apply.")
        return 1
    try:
        where = ["symbol LIKE ?"]
        params: list[object] = [f"%{needle}%" if needle else "%"]
        if start:
            where.append("ts >= ?")
            params.append(datetime.datetime.combine(start, datetime.time.min))
        if end:
            where.append("ts < ?")
            params.append(datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min))
        clause = " AND ".join(where)
        n = con.execute(f"SELECT count(*) FROM computed_timeseries WHERE {clause}", params).fetchone()[0]
        con.execute(f"DELETE FROM computed_timeseries WHERE {clause}", params)
        print(f"deleted {n} DuckDB row(s)")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
