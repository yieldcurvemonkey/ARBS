import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import pandas as pd
import numpy as np

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 100)

D = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"

ev = pd.read_parquet(D + r"\event_paths.parquet")
pl = pd.read_parquet(D + r"\placebo_paths.parquet")

print("=== event_paths columns ===")
for c in ev.columns:
    print(f"  {c:28s} {str(ev[c].dtype):20s} nnull={ev[c].isna().sum()}")
print()
print("shape", ev.shape)
print()
print("=== placebo columns ===")
print(list(pl.columns))
print("shape", pl.shape)
print()
print("=== head ===")
print(ev.head(8).to_string())
print()
print("=== offsets ===")
print(sorted(ev["offset_min"].unique()) if "offset_min" in ev.columns else "NO offset_min")
print()
print("=== rank values ===")
rc = [c for c in ev.columns if "rank" in c.lower()]
print(rc)
for c in rc:
    print(c, sorted(ev[c].dropna().unique())[:12])
print()
print("=== speaker-ish columns ===")
for c in ev.columns:
    if ev[c].dtype == object:
        print(f"  {c}: nuniq={ev[c].nunique()}  sample={ev[c].dropna().unique()[:5]}")
