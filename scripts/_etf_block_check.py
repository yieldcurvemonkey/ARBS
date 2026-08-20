"""Do the MI01 month-turn blocks actually contain every index deletion date?

The backfill's MI01 layer is justified by two claims: that the month turn is the
structurally interesting window, and that every deletion event lands inside one.
The second is checkable and is checked here rather than assumed - a deletion date
outside every block is a hole in exactly the place the study cares about.
"""

import datetime
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from scripts.etf_intraday_backfill import month_turn_blocks, split_block  # noqa: E402

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

START = datetime.date(2021, 1, 1)
END = datetime.date(2026, 8, 20)

blocks = month_turn_blocks(START, END)
wins = [w for b in blocks for w in split_block(*b, width_days=5)]
print(f"blocks={len(blocks)}  windows={len(wins)}")
print("newest block:", blocks[0], " oldest block:", blocks[-1])
span_days = sum((b1 - b0).days for b0, b1 in blocks)
print(f"calendar days inside blocks: {span_days} of {(END - START).days} "
      f"({100 * span_days / (END - START).days:.0f}%)")

cal = pd.read_csv(DATA / "delcliff_deletion_calendar_20y.csv")
cal["event_date"] = pd.to_datetime(cal["event_date"]).dt.date
ev = cal[(cal["event_date"] >= START) & (cal["event_date"] <= END)]
inside = []
for d in ev["event_date"]:
    hit = any(b0 <= d <= b1 for b0, b1 in blocks)
    inside.append(hit)
ev = ev.assign(inside_block=inside)
print(f"\ndeletion events in window: {len(ev)}; inside a block: {int(ev['inside_block'].sum())}")
if not ev["inside_block"].all():
    print("OUTSIDE:")
    print(ev[~ev["inside_block"]].to_string(index=False))
ev.to_csv(DATA / "intraday_deletion_block_coverage.csv", index=False)
print("wrote", DATA / "intraday_deletion_block_coverage.csv")
