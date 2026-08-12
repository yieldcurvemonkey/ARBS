"""How much does ONE Calibration.fit cost, and how many buckets is it fitting?

`publish` has spent 45 minutes on 22 rolling fits and that number decides the
full-window plan, so it is measured rather than estimated.
"""
from __future__ import annotations

import os
import pathlib
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils.dealer_direction import probability as P  # noqa: E402

CACHE = pathlib.Path(r"D:\ddfe_cache")
COLS = ["as_of_date", "rule", "deviation_bps", "venue_class", "rate_index",
        "kind", "special_tenor_type", "tenor_band", "failure"]

days = sorted(p.stem for p in CACHE.joinpath("units").glob("*.parquet")
              if ".tmp" not in p.stem)
days = [d for d in days if "2024-03-01" <= d <= "2024-06-28"][-60:]
print(f"window: {days[0]} .. {days[-1]}  ({len(days)} days)")

parts = []
for day in days:
    df = pd.read_parquet(CACHE / "units" / f"{day}.parquet", columns=COLS)
    df = df[(df["rule"] == "RATE_VS_MID") & df["failure"].isna()
            & df["deviation_bps"].notna()]
    parts.append(df.drop(columns=["failure", "rule"]))
win = pd.concat(parts, ignore_index=True).rename(columns={"kind": "structure"})
win["as_of_date"] = pd.to_datetime(win["as_of_date"]).dt.date
print(f"rows: {len(win):,}")

keys = win.groupby(list(P.BUCKET_COLS), observed=True).size()
print(f"distinct BucketKeys: {len(keys):,}")
print(f"  with >= {P.MIN_BUCKET_N} rows: {int((keys >= P.MIN_BUCKET_N).sum())}")
print(f"  rows in those: {int(keys[keys >= P.MIN_BUCKET_N].sum()):,} "
      f"of {int(keys.sum()):,}")
print("\ntop 10 buckets by n:")
print(keys.sort_values(ascending=False).head(10).to_string())

t0 = time.perf_counter()
cal = P.Calibration.fit(win)
dt = time.perf_counter() - t0
n_fits = len(cal._fits) if hasattr(cal, "_fits") else len(vars(cal).get("fits", {}))
print(f"\nONE Calibration.fit: {dt:.1f}s over {n_fits} fitted buckets "
      f"({dt / max(n_fits, 1) * 1000:.0f} ms/bucket)")

for n_days, label in ((112, "the smoke window"), (609, "the full tape")):
    n_fits_total = n_days // 5
    print(f"  {label}: ~{n_fits_total} rolling fits -> "
          f"{n_fits_total * dt / 60:.0f} min uncontended")
