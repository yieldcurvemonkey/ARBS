import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import pandas as pd
import pyarrow.parquet as pq

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 100)

base = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"
ev = pd.read_parquet(base + r"\event_paths.parquet")
pl = pd.read_parquet(base + r"\placebo_paths.parquet")

print("EVENT SHAPE", ev.shape)
print("PLACEBO SHAPE", pl.shape)
print("\nEVENT COLUMNS")
for c in ev.columns:
    print("  ", c, ev[c].dtype)
print("\nPLACEBO COLUMNS")
for c in pl.columns:
    print("  ", c, pl[c].dtype)

print("\nEVENT HEAD")
print(ev.head(8).to_string())

print("\nrank values:", sorted(ev["rank"].unique()) if "rank" in ev.columns else "NO rank col")
print("offsets:", sorted(ev["offset_min"].unique()) if "offset_min" in ev.columns else "NO offset col")

md = pq.read_schema(base + r"\event_paths.parquet").metadata
print("\nEVENT PARQUET METADATA")
if md:
    for k, v in md.items():
        try:
            print("  ", k.decode(), "=", v.decode()[:400])
        except Exception:
            print("  ", k, "=", v[:200])
