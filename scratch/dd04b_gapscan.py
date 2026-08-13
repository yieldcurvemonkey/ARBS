"""Find the sharpest in-session gap, so D3 separates the two policies convincingly.

2024-03-28's largest interior gap is only 4 minutes, which does separate a 60 s
bound from a 2 h one but does not make the point vividly. This scans the stored
SOFR days inside the tape span for the largest gap that is entirely INSIDE Citi's
published session (an overnight or weekend gap would prove nothing).
"""
from __future__ import annotations

import datetime
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from Caching.curve_store import CurveStore
from MDP.IRSwaps.CITIVELO_EXCEL.citi_session import publishes
from MDP.IRSwaps.CITIVELO_EXCEL.density import day_density

ASSET = "USD-SOFR-1D-CITIVELOEXCELMIN"
CURVE = "USD-SOFR-1D"


def main() -> None:
    store = CurveStore.default()
    asset_dir = store.raw_partition_dir(ASSET, datetime.date(2000, 1, 1)).parent
    days = sorted(
        datetime.date.fromisoformat(e.name.split("=", 1)[1])
        for e in os.scandir(asset_dir)
        if e.is_dir() and e.name.startswith("date=")
    )
    days = [d for d in days if datetime.date(2024, 3, 1) <= d <= datetime.date(2026, 8, 7)]
    print(f"scanning {len(days)} stored SOFR days for the largest in-session gap")

    best = []
    for d in days:
        dens = day_density(store, ASSET, d)
        if not dens.present or dens.max_gap_s is None or dens.max_gap_s <= 120:
            continue
        best.append((dens.max_gap_s, d))
    best.sort(reverse=True)
    print(f"{len(best)} days with a gap over 2 minutes; top 15 by max gap:")
    for g, d in best[:15]:
        print(f"  {d}  max gap {g/60:6.1f} min  ({int(day_density(store, ASSET, d).n_snapshots)} snapshots)")

    # Locate the widest gap whose midpoint is a published minute.
    for g, d in best[:40]:
        frame = store.read_raw_day(ASSET, d)
        stamps = pd.to_datetime(pd.Series(frame["timestamp_utc"]), utc=True).sort_values().reset_index(drop=True)
        diffs = stamps.diff()
        order = diffs.fillna(pd.Timedelta(0)).sort_values(ascending=False).index
        for i in order[:5]:
            a, b = stamps.iloc[i - 1], stamps.iloc[i]
            mid = (a + (b - a) / 2).floor("1min")
            if publishes(CURVE, a) and publishes(CURVE, b) and publishes(CURVE, mid):
                print(f"\nBEST IN-SESSION GAP: {d}  {a} -> {b}  "
                      f"({(b-a).total_seconds()/60:.0f} min)")
                print(f"  probe instant (ET): {mid.tz_convert('America/New_York')}")
                return


if __name__ == "__main__":
    main()
