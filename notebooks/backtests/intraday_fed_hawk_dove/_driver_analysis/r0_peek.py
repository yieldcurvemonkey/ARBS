import sys, json
sys.path.append(r"C:\Users\chris\clee\ARBS")
import pandas as pd, numpy as np

D = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
p = pd.read_parquet(D + r"\panel_daily.parquet")
print("PANEL shape", p.shape)
print("cols:", list(p.columns))
print(p.dtypes)
print(p.head(3).to_string())
print("...")
print(p.tail(3).to_string())

print("\n--- rates_daily ---")
r = pd.read_parquet(D + r"\rates_daily.parquet")
print(r.shape, list(r.columns))
print(r.head(3).to_string())

print("\n--- rates_diagnostic ---")
rd = pd.read_parquet(D + r"\rates_diagnostic.parquet")
print(rd.shape, list(rd.columns))

print("\n--- results json top-level keys ---")
with open(D + r"\variance_ratio_results.json") as f:
    j = json.load(f)
def walk(o, pre="", depth=0):
    if depth > 2: return
    if isinstance(o, dict):
        for k in list(o.keys())[:60]:
            print(" " * depth * 2, pre + k, type(o[k]).__name__)
            walk(o[k], "", depth + 1)
walk(j)
