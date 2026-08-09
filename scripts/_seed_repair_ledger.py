"""Seed a separate ledger so the repair pass runs ONLY the failed days.

The main backfill is still running and appending to the primary ledger; two
processes appending to one file risk interleaving a partial line. So the repair
pass gets its own ledger, pre-marked `ok` for every day in the window that is
already good, leaving only the genuinely failed days to run.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text

from SDRUtils._swappulse_scripts import _tape_tables as tt
from SDRUtils._swappulse_scripts.ingest_usdswaps import get_db_connection_string

MAIN = Path(r"C:\Users\chris\clee\ARBS-v3\tape_v3_backfill_ledger.jsonl")
REPAIR = Path(r"C:\Users\chris\clee\ARBS-v3\tape_v3_repair_ledger.jsonl")
START, END = date(2026, 7, 3), date(2026, 7, 29)


def main() -> int:
    last: dict[str, str] = {}
    for line in MAIN.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            last[r["date"]] = r["status"]

    engine = create_engine(get_db_connection_string())
    with engine.connect() as conn:
        window = [
            str(r[0])
            for r in conn.execute(
                text(
                    "SELECT DISTINCT as_of_date FROM arbs_usd_swap_tape_legs_v2 "
                    "WHERE as_of_date >= :s AND as_of_date <= :e ORDER BY as_of_date"
                ),
                {"s": START, "e": END},
            )
        ]
        counts = {
            str(r[0]): r[1]
            for r in conn.execute(
                text(
                    f"SELECT as_of_date, count(*) FROM {tt.LEGS_TABLE} "
                    "WHERE as_of_date >= :s AND as_of_date <= :e GROUP BY 1"
                ),
                {"s": START, "e": END},
            )
        }

    # A day is genuinely good only if it has rows. Anything else must run.
    todo = [d for d in window if counts.get(d, 0) == 0]
    seeded = [d for d in window if counts.get(d, 0) > 0]

    with REPAIR.open("w", encoding="utf-8") as fh:
        for d in seeded:
            fh.write(json.dumps({
                "date": d, "status": "ok", "seconds": 0, "returncode": 0,
                "rows": counts[d], "tail": "SEEDED: already populated, skipped by repair pass",
            }) + "\n")

    print(f"window {START}..{END}: {len(window)} v2 days")
    print(f"seeded ok (already populated): {len(seeded)}")
    print(f"WILL RUN ({len(todo)}): {todo}")
    for d in todo:
        print(f"   {d}  v3 rows now = {counts.get(d, 0)}  (ledger says {last.get(d, 'absent')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
