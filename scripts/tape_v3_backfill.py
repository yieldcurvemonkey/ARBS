"""Resumable, ledger-first backfill of the ARBS v3 tape.

Runs newest-first so the front end becomes correct within the first hour
rather than the last. Safe to order descending: cross-day enrichment
resolves from raw DTCC data fetched one day *forward*, never from earlier
tape days in the database, so no day depends on one not yet written.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from SDRUtils._swappulse_scripts import _tape_tables as tt
from SDRUtils._swappulse_scripts.ingest_usdswaps import get_db_connection_string

PYTHON = r"C:\Users\chris\anaconda3\envs\stir\python.exe"
DEFAULT_CACHE = r"C:\Users\chris\clee\ARBS\sdr_cache"
# Absolute, not relative-to-CWD: a relative default silently starts a FRESH
# ledger when invoked from the wrong directory, turning a resume into a
# full restart. Anchored to the worktree root (this file's grandparent),
# not to a single hardcoded worktree name.
DEFAULT_LEDGER = str(Path(__file__).resolve().parent.parent / "tape_v3_backfill_ledger.jsonl")

# v2 has no seam constant -- ARBS never writes it, only reads it here as
# the ground truth for which days actually have data. Named locally,
# matching scripts/tape_v3_parity_check.py's convention.
V2_LEGS_TABLE = "arbs_usd_swap_tape_legs_v2"


def _engine() -> Engine:
    return create_engine(get_db_connection_string())


def target_days(engine: Engine, start: dt.date, end: dt.date) -> list[dt.date]:
    """The actual target day set: every day v2 has legs for, newest first.

    NOT a calendar guess. USFederalHolidayCalendar wrongly excluded real
    trading days that have data in v2 (2024-10-14 Columbus Day, 2026-07-03
    July 4 observed) and wrongly included days with no data anywhere
    (Good Fridays 2024-03-29, 2025-04-18) -- both lists happened to total
    611 days, which is how the mismatch hid. Reading ground truth from
    v2, the same source the acceptance check uses, removes both classes
    of error and is what makes the zero-row `ok` rule below provably
    safe: a day with genuinely no data anywhere was never in the target
    set to begin with, so it can never become a permanent, unrepairable
    "failed" entry.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT DISTINCT as_of_date FROM {V2_LEGS_TABLE} "
                "WHERE as_of_date >= :start AND as_of_date <= :end "
                "ORDER BY as_of_date DESC"
            ),
            {"start": start, "end": end},
        )
        return [r[0] for r in rows]


def v3_row_count(engine: Engine, as_of: dt.date) -> int:
    """Rows v3 actually holds for a day -- the ground truth `ok` requires.

    A day's subprocess can exit 0 and still have written nothing: DTCC
    503s, the fetcher swallows it and returns an empty frame, and the
    pipeline legitimately writes zero rows and stamps its own run
    'success' regardless. Return code alone cannot tell that apart from
    a real success -- it already didn't: six days in the live run
    (2026-07-22, 07-23, 07-24, 07-27, 07-28, 07-29) were recorded `ok`
    with zero rows in v3 against thousands of rows each in v2.
    """
    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT count(*) FROM {tt.LEGS_TABLE} WHERE as_of_date = :d"),
            {"d": as_of},
        ).scalar_one()


def load_ledger(path: Path) -> dict[str, str]:
    """Map date -> last recorded status. Missing file means nothing done."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        out[rec["date"]] = rec["status"]
    return out


def _append(path: Path, rec: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)
    ap.add_argument("--cache-path", default=DEFAULT_CACHE)
    ap.add_argument("--retry-failed", action="store_true",
                    help="Second pass: run only the days marked failed.")
    args = ap.parse_args()

    ledger = Path(args.ledger)
    done = load_ledger(ledger)
    engine = _engine()
    days = target_days(
        engine, dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    )

    if args.retry_failed:
        todo = [d for d in days if done.get(d.isoformat()) == "failed"]
    else:
        todo = [d for d in days if done.get(d.isoformat()) != "ok"]

    already_ok = sum(1 for d in days if done.get(d.isoformat()) == "ok")
    print(f"{len(todo)} day(s) to run of {len(days)} in range "
          f"({already_ok} already ok)")

    for i, d in enumerate(todo, 1):
        iso = d.isoformat()
        print(f"[{i}/{len(todo)}] {iso}", flush=True)
        t0 = time.time()
        proc = subprocess.run(
            [PYTHON, "-m", "SDRUtils._swappulse_scripts.run_usdswaps_pipeline",
             "backfill", "--date", iso, "--cache-path", args.cache_path],
            capture_output=True, text=True,
        )
        elapsed = round(time.time() - t0, 1)
        rows = v3_row_count(engine, d)
        # A day that exits 0 but wrote zero rows is NOT ok: DTCC 503s get
        # swallowed into an empty frame and the pipeline stamps its own
        # run 'success' regardless. Without this check such a day is
        # permanently unrepairable -- --retry-failed only ever selects
        # status == "failed".
        ok = proc.returncode == 0 and rows > 0
        _append(ledger, {
            "date": iso,
            "status": "ok" if ok else "failed",
            "seconds": elapsed,
            "returncode": proc.returncode,
            "rows": rows,
            "tail": proc.stderr.strip()[-400:] if not ok else "",
        })
        print(f"    {'ok' if ok else 'FAILED'} in {elapsed}s, {rows} row(s)", flush=True)

    # Scoped to the requested range, not the whole ledger: a day can be
    # absent from the ledger entirely (process killed before it was ever
    # attempted) and that is just as incomplete as an explicit "failed" --
    # scanning the ledger alone is blind to it.
    final = load_ledger(ledger)
    not_ok = [d.isoformat() for d in days if final.get(d.isoformat()) != "ok"]
    if not_ok:
        print(f"\n{len(not_ok)} day(s) not ok: {sorted(not_ok)[:20]}")
        return 1
    print("\nall days ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
