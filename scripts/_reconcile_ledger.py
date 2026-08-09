"""Reconcile the v3 backfill ledger against what actually landed in the database.

The pre-fix runner recorded a day as `ok` on returncode 0 even when it wrote
zero rows (DTCC 503 -> fetcher swallows -> empty frame -> pipeline legitimately
writes nothing and exits 0). Those entries are unreachable: the default resume
skips `ok`, and `--retry-failed` selects only `failed`.

This appends a corrective `failed` record for every `ok` day that has no rows in
v3. The ledger is append-only and last-record-wins, so the correction sticks.

Read-only against the database. Run only when no backfill process is writing the
ledger.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from SDRUtils._swappulse_scripts import _tape_tables as tt
from SDRUtils._swappulse_scripts.ingest_usdswaps import get_db_connection_string

LEDGER = Path(r"C:\Users\chris\clee\ARBS-v3\tape_v3_backfill_ledger.jsonl")


def main() -> int:
    rows = [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]
    last: dict[str, str] = {}
    for r in rows:
        last[r["date"]] = r["status"]
    ok_days = sorted(d for d, s in last.items() if s == "ok")
    print(f"ledger entries: {len(rows)}  distinct days: {len(last)}  marked ok: {len(ok_days)}")

    engine = create_engine(get_db_connection_string())
    with engine.connect() as conn:
        counts = {
            str(r[0]): r[1]
            for r in conn.execute(
                text(f"SELECT as_of_date, count(*) FROM {tt.LEGS_TABLE} GROUP BY 1")
            )
        }

    bogus = [d for d in ok_days if counts.get(d, 0) == 0]
    print(f"marked ok but ZERO rows in v3: {len(bogus)}")
    for d in bogus:
        print(f"   {d}")

    if not bogus:
        print("nothing to correct")
        return 0

    with LEDGER.open("a", encoding="utf-8") as fh:
        for d in bogus:
            fh.write(json.dumps({
                "date": d,
                "status": "failed",
                "seconds": 0,
                "returncode": 0,
                "rows": 0,
                "tail": "RECONCILED: pre-fix runner recorded ok with zero rows written",
            }) + "\n")
    print(f"appended {len(bogus)} corrective 'failed' records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
