import pandas as pd, datetime, sys
from RVUtils.ETFRebalance.bond_panel import reference_frame
from MDP.ETFHoldings import store as etf_store

ref = reference_frame()
ref["cusip"] = ref["cusip"].astype(str).str.upper()
for c in ("066922477", "912810FT0"):
    r = ref[ref["cusip"] == c]
    print(c, "ref rows:", len(r))
    if len(r):
        print(r[["cusip", "label", "oi", "issue_date", "maturity_date", "cpn"]].to_string())

h = etf_store.load("TLT", start=datetime.date(2021, 1, 1))
h["CUSIP"] = h["CUSIP"].astype(str).str.upper()
for c in ("066922477", "912810FT0"):
    sub = h[h["CUSIP"] == c]
    print(c, "held on", sub["date"].nunique(), "dates",
          None if sub.empty else (sub["date"].min().date(), sub["date"].max().date()))
    if not sub.empty:
        print(sub.head(2).to_string())

# What are the 23 band bonds TLT never held?
u = pd.read_csv(r"C:\Users\chris\clee\ARBS-etf\notebooks\backtests\etf_rebalance\_data\intraday_universe.csv")
never = u[(~u["held_by_tlt"]) & (u["in_reference_band"])]
print("\nband-but-never-held:", len(never))
print(never[["cusip", "maturity_date", "issue_date", "coupon", "label"]].to_string())
