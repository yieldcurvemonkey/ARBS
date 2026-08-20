"""Which day's share-count change lines up with which day's par change?

``holdings_panel``'s own docstring records that a $5.7bn par move on 2026-08-07 was followed
by a 10% share-count rise "into the next session". If the two series are offset by a day,
a naive same-day pro-rata basket is measured against the wrong scaling factor and every bit
of the mismatch is scored as manager DISCRETION. So the lag is measured, not assumed.
"""
from __future__ import annotations
import os
import numpy as np, pandas as pd

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_data")
h = pd.read_parquet(os.path.join(DATA, "raw_holdings_TLT_TLH.parquet"))
h["date"] = pd.to_datetime(h["date"])

for TKR in ("TLT", "TLH"):
    d = h[h["ticker"] == TKR]
    par = d.pivot_table(index="date", columns="cusip", values="par", aggfunc="sum").fillna(0.0)
    sh = d.groupby("date")["shares_out"].first().reindex(par.index)
    f = sh.pct_change()

    dpar = par.diff()
    prev = par.shift()
    gross = dpar.abs().sum(axis=1)

    print(f"\n=== {TKR} ===  {len(par)} documents, {int((f.abs()>=0.02).sum())} flow days >=2%")
    for lag in (-1, 0, 1):
        ff = f.shift(-lag)                 # lag=+1 -> the share change stamped the NEXT day
        pro = prev.mul(ff, axis=0)
        resid = (dpar - pro).abs().sum(axis=1)
        m = (f.abs() >= 0.02) & np.isfinite(resid) & (gross > 0)
        expl = 1.0 - (resid[m] / gross[m])
        print(f"  lag {lag:+d}: median share of gross par move explained by a pro-rata "
              f"scaling = {expl.median()*100:6.1f}%   (n={int(m.sum())})")
