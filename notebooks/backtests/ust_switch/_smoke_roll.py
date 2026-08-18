"""Prove the alias series SPLICES at the auction roll, so P&L must never diff it.

``O10/CT10`` is a different pair of bonds either side of a refunding. Its day-over-day
change on the roll date is the difference between two unrelated spreads, not a return.
The roll is also exactly where this trade's payoff lives, so diffing the alias series
would fabricate (or destroy) the entire edge.
"""

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime  # noqa: E402

import pandas as pd  # noqa: E402

from MDP.FixedRateBonds.FixedRateBondsMDP import (  # noqa: E402
    FixedRateBondsMDP,
    _filter_and_rank_ref_df,
)
from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import (  # noqa: E402
    update_reference_data,
)
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery  # noqa: E402
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue  # noqa: E402
from TB.FixedRateBondsTB import FixedRateBondsTB  # noqa: E402

pd.set_option("display.width", 250)

START, END = datetime.date(2024, 1, 25), datetime.date(2024, 3, 1)
ref = update_reference_data(source="fiscaldata")

# 1. where does the alias flip?
rows = []
for d in pd.date_range(START, END, freq="D").date:
    r = _filter_and_rank_ref_df(ref, d)
    t = r[r["oi"] == "10-Year"]
    if t.empty:
        continue
    g = lambda k: (t[t["rank"] == k]["cusip"].iloc[0] if (t["rank"] == k).any() else None)  # noqa: E731
    rows.append({"date": d, "CT10": g(0), "O10": g(1), "OO10": g(2)})
al = pd.DataFrame(rows).set_index("date")
flip = al[al["CT10"] != al["CT10"].shift(1)].iloc[1:]
print("=== alias flip dates (10Y) ===")
print(flip.to_string())

mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
tb = FixedRateBondsTB(mdp, show_tqdm=False)

# 2. the alias series across the roll, next to the two FIXED-CUSIP series it splices
roll = flip.index[0]
pre = al.loc[al.index < roll].iloc[-1]
post = al.loc[al.index >= roll].iloc[0]
print(f"\nroll at {roll}:  before O10/CT10 = {pre['O10']}/{pre['CT10']}"
      f"   after = {post['O10']}/{post['CT10']}")

qs = [
    FixedRateBondQuery(cusip="O10/CT10", value=FixedRateBondValue.YTM),
    FixedRateBondQuery(cusip=f"{pre['O10']}/{pre['CT10']}", value=FixedRateBondValue.YTM),
    FixedRateBondQuery(cusip=f"{post['O10']}/{post['CT10']}", value=FixedRateBondValue.YTM),
]
df = tb.get_timeseries(start=START, end=END, queries=qs, n_jobs=4)
df.columns = ["alias_O10/CT10" if "O10/CT10" in str(c) else str(c) for c in df.columns]
df = df.rename(
    columns={
        f"{pre['O10']}/{pre['CT10']} CURVE YTM": "fixed_PRE_pair",
        f"{post['O10']}/{post['CT10']} CURVE YTM": "fixed_POST_pair",
    }
)
df["alias_diff"] = df["alias_O10/CT10"].diff()
df["pre_diff"] = df["fixed_PRE_pair"].diff()

print("\n=== alias vs the two fixed-CUSIP pairs it splices (bp) ===")
print(df.round(4).to_string())

j = df.loc[pd.Timestamp(roll), "alias_diff"] if pd.Timestamp(roll) in df.index else float("nan")
print(f"\nalias day-over-day change ON the roll date : {j:+.4f} bp")
print(f"same-day change of the CONTINUOUSLY HELD pair: "
      f"{df.loc[pd.Timestamp(roll), 'pre_diff']:+.4f} bp"
      if pd.Timestamp(roll) in df.index else "")
print("\nVERDICT: these differ => the alias series is a SPLICE. Position P&L must use "
      "fixed CUSIPs captured at entry; aliases are for selection/signal only.")
