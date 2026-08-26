"""Discriminating check: is the 2019-07-01..07-05 imm3x4 level a curve-build artifact?

If 2y/5y do NOT jump ~70bp alongside imm3x4, the jump is a defect in the short end of the
curve build, not a real rate move.
"""
import sys
import pandas as pd

sys.path.append(r"C:\Users\chris\clee\ARBS")
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 40)

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
r = pd.read_parquet(OUT + r"\rates_daily.parquet")
print("rates_daily cols:", list(r.columns))
print("index:", r.index.name, r.index[0], "..", r.index[-1])
print()
w = r.loc["2019-06-24":"2019-07-15"]
print(w.to_string())
print()
print("=== day-over-day change in bp, same window ===")
print((r.diff() * 100).loc["2019-06-24":"2019-07-15"].round(2).to_string())
