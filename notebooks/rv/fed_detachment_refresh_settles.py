"""Refetch and MERGE the SR3 settles this study needs. Plain process only.

Run:  python notebooks/rv/fed_detachment_refresh_settles.py

Writes to the STUDY-LOCAL cache, never the shared ``BT/serff`` one, and unions
every fetch into what is already there -- a Barchart answer that comes back
short must cost nothing.
"""
import datetime
import pathlib
import sys

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fed_detachment_prices as P

START = datetime.date(2018, 5, 7)
END = datetime.date(2026, 8, 21)
MAX_RANK = 4


def main() -> int:
    print("seed:", P.seed_local_cache(), flush=True)
    fridays = pd.date_range(START, END, freq="W-FRI")
    rmap = P.build_rank_map([d.date() for d in fridays], MAX_RANK)
    syms = sorted({s for c in rmap.columns for s in rmap[c].unique()})
    print(f"refetching {len(syms)} contracts", flush=True)

    report = P.refresh_settles(
        datetime.date(2018, 1, 1),
        datetime.date.today(),
        syms,
        show_progress=False,
    )
    pd.set_option("display.width", 200)
    print(report.to_string(index=False), flush=True)
    shrunk = report[report["status"] == "shrunk_ignored"]
    print(f"\nfetches that came back SHORT and were unioned rather than trusted: {len(shrunk)}",
          flush=True)
    if len(shrunk):
        print(shrunk.to_string(index=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
