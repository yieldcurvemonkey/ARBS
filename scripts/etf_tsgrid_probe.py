"""Probe the hourly intraday layer before building anything on it."""
from __future__ import annotations
import sys, time, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from RVUtils.ETFRebalance import intraday as itd

t0 = time.time()
uni = itd.universe()
print("universe", uni.shape, list(uni.columns))
print(uni.head(3).to_string())

fr = itd.hourly_frame("YIELD")
print("hourly frame", fr.shape, "load", round(time.time() - t0, 1), "s")
print("index", fr.index.min(), fr.index.max(), fr.index.dtype)
print("tz", getattr(fr.index, "tz", None))
fr = itd.drop_impossible(fr, "YIELD")
print("non-null cells", int(fr.notna().sum().sum()))

hrs = pd.Series(fr.index).dt.hour.value_counts().sort_index()
print("rows per stamp hour:")
print(hrs.to_string())

for ch in (10, 15, 16, 17):
    m = itd.ny_marks(fr, ch)
    print(f"clock {ch:02d}:00 -> stamp {itd.ny_stamp(ch)}: dates={len(m)} "
          f"bonds/day median={int(m.notna().sum(axis=1).median())} "
          f"first={m.index.min().date()} last={m.index.max().date()}")
print("elapsed", round(time.time() - t0, 1))
