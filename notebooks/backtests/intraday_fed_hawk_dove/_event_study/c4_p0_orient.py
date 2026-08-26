import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import pandas as pd
import numpy as np
import pyarrow.parquet as pq

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 100)

base = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove"
ev = pd.read_parquet(base + r"\_event_study\event_paths.parquet")
pl = pd.read_parquet(base + r"\_event_study\placebo_paths.parquet")
dl = pd.read_parquet(base + r"\_driver_analysis\panel_daily.parquet")

print("=== EVENT PATHS ===", ev.shape)
print(ev.dtypes)
print(ev.head(6).to_string())
print()
print("=== PLACEBO PATHS ===", pl.shape)
print(list(pl.columns))
print()
print("=== DAILY PANEL ===", dl.shape)
print(dl.dtypes)
print(dl.head(4).to_string())
print()
print("offsets:", sorted(ev["offset_min"].unique()))
print("ranks:", sorted(ev["rank"].unique()) if "rank" in ev.columns else "NO rank col")
print()
md = pq.read_table(base + r"\_event_study\event_paths.parquet").schema.metadata
for k, v in (md or {}).items():
    print("META", k.decode(), "=", v.decode()[:400])
