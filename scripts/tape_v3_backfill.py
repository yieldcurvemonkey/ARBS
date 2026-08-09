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

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

PYTHON = r"C:\Users\chris\anaconda3\envs\stir\python.exe"
DEFAULT_CACHE = r"C:\Users\chris\clee\ARBS\sdr_cache"


def trading_days(start: dt.date, end: dt.date) -> list[dt.date]:
    """US business days in [start, end], newest first."""
    idx = pd.date_range(
        start=start, end=end,
        freq=CustomBusinessDay(calendar=USFederalHolidayCalendar()),
    )
    return sorted((d.date() for d in idx), reverse=True)


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
    ap.add_argument("--ledger", default="tape_v3_backfill_ledger.jsonl")
    ap.add_argument("--cache-path", default=DEFAULT_CACHE)
    ap.add_argument("--retry-failed", action="store_true",
                    help="Second pass: run only the days marked failed.")
    args = ap.parse_args()

    ledger = Path(args.ledger)
    done = load_ledger(ledger)
    days = trading_days(
        dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    )

    if args.retry_failed:
        todo = [d for d in days if done.get(d.isoformat()) == "failed"]
    else:
        todo = [d for d in days if done.get(d.isoformat()) != "ok"]

    print(f"{len(todo)} day(s) to run of {len(days)} in range "
          f"({len(days) - len(todo)} already ok)")

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
        ok = proc.returncode == 0
        _append(ledger, {
            "date": iso,
            "status": "ok" if ok else "failed",
            "seconds": elapsed,
            "returncode": proc.returncode,
            "tail": proc.stderr.strip()[-400:] if not ok else "",
        })
        print(f"    {'ok' if ok else 'FAILED'} in {elapsed}s", flush=True)

    failed = [d for d, s in load_ledger(ledger).items() if s == "failed"]
    if failed:
        print(f"\n{len(failed)} day(s) failed: {sorted(failed)[:20]}")
        return 1
    print("\nall days ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
