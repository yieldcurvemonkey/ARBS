"""Probe 6: two of my own diagnostics disagree, so neither is quotable yet.

Probe 4's run detector said the ON leg was frozen at 2.5000 for 64 consecutive
days from 2019-08-23. Probe 5b said the same stretch carries 77 DISTINCT values.
Both cannot be true. This prints the raw series so the report quotes a measured
fact rather than whichever probe happened to run last -- and if the run detector
is the thing that is wrong, that matters, because it is mine.
"""
from __future__ import annotations

import pathlib
import sys

import pandas as pd

sys.stdout.reconfigure(line_buffering=True)

OUT = pathlib.Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests"
                   r"\intraday_fed_hawk_dove\_driver_analysis")
C_ON = "USD-SOFR-1D 1d OUTRIGHT RATE"

r = pd.read_parquet(OUT / "rates_daily.parquet")
r.index = pd.to_datetime(r.index)
on = r[C_ON].sort_index().loc["2019-07-01":"2019-12-01"]

print(f"n={len(on)}  distinct={on.nunique()}  "
      f"distinct rounded to 4dp={on.round(4).nunique()}")
print(f"min={on.min():.6f}  max={on.max():.6f}")
print(f"days where |diff| < 1e-9      : {int((on.diff().abs() < 1e-9).sum())}")
print(f"days where |diff| < 1e-4 (0.01bp): {int((on.diff().abs() < 1e-4).sum())}")
print(f"days where |diff| < 1e-3 (0.1bp) : {int((on.diff().abs() < 1e-3).sum())}")
print("\nvalue counts rounded to 4dp:")
print(on.round(4).value_counts().head(10).to_string())
print("\nthe raw series, full precision:")
print(on.apply(lambda x: f"{x:.8f}").to_string())
