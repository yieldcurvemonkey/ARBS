from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np
import pandas as pd

from MDP.ETFHoldings import store as holdings_store
from RVUtils.ETFRebalance import bond_panel as BP
from RVUtils.ETFRebalance import float_panel as FP
from RVUtils.ETFRebalance import holdings_panel as HP

pd.set_option("display.width", 220)

TICKERS = ["TLT", "TLH", "GOVT", "IEF", "IEI"]

for t in TICKERS:
    cov = holdings_store.coverage(t)
    print(t, "coverage:")
    print(cov.to_string(index=False))
    print()

print("=" * 80)
h = HP.load_holdings(["TLT"])
print("TLT holdings rows:", len(h), "dates:", h["date"].nunique())
print(h.head())
print(h[["par", "shares_out", "par_per_share"]].describe())

# check date gaps
dates = np.sort(h["date"].unique())
diffs = np.diff(dates).astype("timedelta64[D]").astype(int)
print("date diffs (days) value_counts:")
print(pd.Series(diffs).value_counts().sort_index())

# check a single cusip's d(par_per_share) scale
sample_cusip = h.groupby("cusip")["date"].count().idxmax()
sc = h[h["cusip"] == sample_cusip].sort_values("date")
sc = sc.assign(d_ppc=sc["par_per_share"].diff())
print(f"\nsample cusip {sample_cusip}, n={len(sc)}")
print(sc[["date", "par", "shares_out", "par_per_share", "d_ppc"]].tail(20).to_string())
print("\nd_ppc describe (nonzero):")
print(sc.loc[sc["d_ppc"].abs() > 0, "d_ppc"].describe())
print("\nfraction of days d_ppc == 0 exactly:", (sc["d_ppc"] == 0).mean())
print("fraction of days d_ppc abs < 1e-9:", (sc["d_ppc"].abs() < 1e-9).mean())
