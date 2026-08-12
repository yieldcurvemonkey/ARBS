"""Why do the shipped mids differ from dd06's on some of the F-15 legs?

Candidates, in the order they are cheap to rule out:
  H1  a different pricing CLOCK. dd06 used ``snap_timestamp(orig, exec)``; the
      shipped module uses ``snapshot.pricing_timestamp``, which routes a
      non-NEW_TRADE row to #30. Those are different instants by construction.
  H2  a different snapped instant for the same clock (rounding / tz).
  H3  the same instant serving a different curve.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from dd_measure import LEG_COLS, connect, read_sql, unit_from_leg
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils.dealer_direction import snapshot
from SDRUtils.stir_flow.pricing import snap_timestamp

pd.set_option("display.width", 300)
pd.set_option("display.max_columns", 40)


def main() -> None:
    prev = pd.read_csv("C:/Users/chris/clee/ARBS-dd/scratch/out_bias200.csv")
    prev = prev[prev["mid_pct"].notna()]
    ids = [str(t) for t in prev["trade_id"]]
    conn = connect()
    rows = read_sql(conn, f"SELECT {LEG_COLS} FROM {LEGS_TABLE} l "
                          f"WHERE l.trade_id = ANY(%(ids)s)", {"ids": ids})
    conn.close()

    recs = []
    for _, r in rows.iterrows():
        old = pd.Timestamp(snap_timestamp(r["original_execution_timestamp"],
                                          r["execution_timestamp"]))
        _, new, field = unit_from_leg(r)
        recs.append({
            "trade_id": str(r["trade_id"]),
            "lifecycle": r["lifecycle_type"],
            "clock_field": field,
            "old_snap": old.tz_convert(snapshot.NY).strftime("%Y-%m-%d %H:%M"),
            "new_snap": pd.Timestamp(new).tz_convert(snapshot.NY).strftime("%Y-%m-%d %H:%M"),
            "same_snap": pd.Timestamp(old) == pd.Timestamp(new),
            "exec_eq_event": (pd.Timestamp(r["execution_timestamp"])
                              == pd.Timestamp(r["event_timestamp"])),
            "delta_s": (pd.Timestamp(new) - pd.Timestamp(old)).total_seconds(),
        })
    d = pd.DataFrame(recs)
    print(f"snaps that differ: {int((~d['same_snap']).sum())} / {len(d)}")
    print("\nby lifecycle_type and clock field:")
    print(d.groupby(["lifecycle", "clock_field", "same_snap"]).size().to_string())
    diff = d[~d["same_snap"]]
    if len(diff):
        print("\nthe differing rows:")
        print(diff.head(20).to_string(index=False))
        print(f"\ndelta seconds: min {diff['delta_s'].min():.0f} "
              f"median {diff['delta_s'].median():.0f} max {diff['delta_s'].max():.0f}")


if __name__ == "__main__":
    main()
