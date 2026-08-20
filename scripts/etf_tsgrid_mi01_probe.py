"""How expensive is the MI01 minute layer to read offline, and what does it cover?"""
from __future__ import annotations
import pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np, pandas as pd
from RVUtils.ETFRebalance import intraday as itd
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

uni = itd.universe()
ids = list(uni["isin"].astype(str))
q = CitiVeloQuotes(offline=True)

t0 = time.time()
sub = ids[:8]
fr = q.frame([f"RATES.BOND.{i}.YIELD" for i in sub], "MI01")
print("8 tags:", fr.shape, f"{time.time()-t0:.1f}s")
print("index", fr.index.min(), fr.index.max())
d = pd.Series(fr.index).dt.normalize()
print("dates covered:", d.nunique())
months = pd.Series(fr.index).dt.to_period("M").value_counts().sort_index()
print("rows per month (first 12):"); print(months.head(12).to_string())
# which days of month?
dom = pd.Series(fr.index).dt.day.value_counts().sort_index()
print("distinct days-of-month present:", sorted(dom.index.tolist()))
t1 = time.time()
fr2 = q.frame([f"RATES.BOND.{i}.YIELD" for i in ids], "MI01")
print("all 97 tags:", fr2.shape, f"{time.time()-t1:.1f}s",
      f"{fr2.memory_usage(deep=True).sum()/1e6:.0f} MB")
