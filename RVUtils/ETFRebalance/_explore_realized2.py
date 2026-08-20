from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np
import pandas as pd

from RVUtils.ETFRebalance import bond_panel as BP
from RVUtils.ETFRebalance import float_panel as FP
from RVUtils.ETFRebalance import holdings_panel as HP

pd.set_option("display.width", 220)

h = HP.load_holdings(["TLT"])
h = h.sort_values(["cusip", "date"])
h["d_par"] = h.groupby("cusip")["par"].diff()
h["d_ppc"] = h.groupby("cusip")["par_per_share"].diff()

print("overall fraction d_par == 0 exactly:", (h["d_par"] == 0).mean())
print("overall fraction d_par abs < 1:", (h["d_par"].abs() < 1).mean())
print("overall fraction d_ppc == 0 exactly:", (h["d_ppc"] == 0).mean())

flows = HP.flag_flow_days(h.assign(ticker="TLT"), threshold=0.02)
print("\nflow day count (2% threshold):", flows["is_flow_day"].sum(), "of", len(flows))
print(flows[flows["is_flow_day"]][["date", "d_shares", "flow_pct"]].tail(20).to_string())

print("\nflow_pct describe:")
print(flows["flow_pct"].describe())
for thr in (0.005, 0.01, 0.02, 0.05):
    print(f"  |flow_pct|>={thr}: {(flows['flow_pct'].abs() >= thr).mean()*100:.2f}% of days")

# merge free float
panel = FP.asof_join(BP.load(), FP.load())
panel["date"] = pd.to_datetime(panel["date"])
ff = panel[["date", "cusip", "free_float", "ttm"]].drop_duplicates(["date", "cusip"])
hm = h.merge(ff, on=["date", "cusip"], how="left")
hm["active_dpar"] = hm["shares_out"] * hm["d_ppc"]
hm["active_pct_float_bp"] = hm["active_dpar"] / hm["free_float"] * 1e4

print("\nactive_pct_float_bp describe (all days, all cusips):")
print(hm["active_pct_float_bp"].describe(percentiles=[.01, .05, .25, .5, .75, .95, .99]))

# split flow vs non-flow days
fl = flows.set_index("date")["is_flow_day"]
hm["is_flow_day"] = hm["date"].map(fl)
print("\nby flow-day flag:")
print(hm.groupby("is_flow_day")["active_pct_float_bp"].describe(percentiles=[.5, .9, .99]).to_string())

# materiality: fraction of cells with |active_pct_float_bp| > 1bp, > 5bp
for thr in (1, 5, 10, 25):
    print(f"|active_pct_float_bp|>{thr}bp: {(hm['active_pct_float_bp'].abs() > thr).mean()*100:.2f}% of cells "
          f"(non-flow only: {(hm.loc[hm['is_flow_day']==False,'active_pct_float_bp'].abs() > thr).mean()*100:.2f}%)")
