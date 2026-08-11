"""Stage 1 - what the LOCAL CurveStore actually holds for the two Citi minute assets.

Counts date partitions that contain at least one parquet file, and the row
count from each parquet FOOTER (metadata.num_rows), which is what
``density.day_density(with_gaps=False)`` reads. No curve payload is touched.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pyarrow.parquet as pq

from Caching.curve_store import CurveStore

ASSETS = ("USD-SOFR-1D-CITIVELOEXCELMIN", "USD-FEDFUNDS-1D-CITIVELOEXCELMIN")


def main() -> None:
    store = CurveStore.default()
    print(f"store base_dir = {store.base_dir}")
    rows = []
    for asset in ASSETS:
        # raw_partition_dir sanitises the asset name; ask it for the parent.
        probe = store.raw_partition_dir(asset, datetime.date(2000, 1, 1))
        asset_dir = probe.parent
        print(f"\n=== {asset} ===\n  dir = {asset_dir}  exists={asset_dir.exists()}")
        if not asset_dir.exists():
            continue
        days = []
        for entry in os.scandir(asset_dir):
            if not entry.is_dir() or not entry.name.startswith("date="):
                continue
            day = datetime.date.fromisoformat(entry.name.split("=", 1)[1])
            files = [e.path for e in os.scandir(entry.path) if e.name.endswith(".parquet")]
            if not files:
                continue
            n = sum(pq.ParquetFile(p).metadata.num_rows for p in files)
            days.append((day, n, len(files)))
        days.sort()
        df = pd.DataFrame(days, columns=["date", "n_snapshots", "n_files"])
        print(f"  days with >=1 parquet : {len(df)}")
        print(f"  span                  : {df['date'].min()} .. {df['date'].max()}")
        print(f"  days with 0 rows      : {int((df['n_snapshots'] == 0).sum())}")
        print(f"  total snapshots       : {int(df['n_snapshots'].sum()):,}")
        print(f"  snapshots/day p50/p90 : {df['n_snapshots'].median():.0f} / "
              f"{df['n_snapshots'].quantile(0.9):.0f}")
        print(f"  days >=800 snapshots  : {int((df['n_snapshots'] >= 800).sum())}")
        # coverage over the v3 tape span
        span = df[(df["date"] >= datetime.date(2024, 3, 1)) & (df["date"] <= datetime.date(2026, 8, 7))]
        print(f"  days inside tape span 2024-03-01..2026-08-07: {len(span)} "
              f"({int((span['n_snapshots'] >= 800).sum())} with >=800 snapshots)")
        out = f"C:/Users/chris/clee/ARBS-dd/scratch/out_coverage_{asset}.csv"
        df.to_csv(out, index=False)
        rows.append((asset, len(df), df["date"].min(), df["date"].max()))
    print("\n=== summary ===")
    for a, n, lo, hi in rows:
        print(f"  {a:38s} {n:5d} days  {lo} .. {hi}")


if __name__ == "__main__":
    main()
