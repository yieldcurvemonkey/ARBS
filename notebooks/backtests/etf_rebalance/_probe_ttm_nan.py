"""Is an index member the fund does NOT hold silently dropped from the ladder?

``with_active_weight`` outer-joins the benchmark to the holdings precisely so that a bond
in the index the fund does not own reads as maximally underweight. But
``benchmark_weights`` returns no ``ttm`` column -- ttm arrives from the HOLDINGS side of
the join -- so those rows carry ttm = NaN, and everything downstream that keys on ttm
(``HP.ladder`` via ``bucket_index``, ``engine.prepare_universe``'s band filter) drops them.
"""
from __future__ import annotations
import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                      "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                "..", "..", "..")))
import numpy as np, pandas as pd

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_data")
act = pd.read_parquet(os.path.join(DATA, "fundfig_active_TLT.parquet"))

nh = act["in_index"] & ~act["held"]
print("in-index-not-held rows:", int(nh.sum()), "of", len(act))
print("  ... of which ttm is NaN:", int(act.loc[nh, "ttm"].isna().sum()))
print("held rows with NaN ttm:", int(act.loc[act['held'], 'ttm'].isna().sum()))

# how much index weight is lost per date
per = act.assign(lost=np.where(act["ttm"].isna(), act["w_i"].fillna(0.0), 0.0)) \
         .groupby("date").agg(w_i_lost=("lost", "sum"),
                              n_lost=("ttm", lambda s: int(s.isna().sum())))
per = per[per.index.isin(act.loc[act["held"], "date"].unique())]
print("\nindex weight dropped by the NaN-ttm hole, per date:")
print((per["w_i_lost"] * 100).describe(percentiles=[.1, .5, .9, .99]).round(2).to_string())
print("\nn index members dropped, per date:")
print(per["n_lost"].describe(percentiles=[.1, .5, .9, .99]).round(2).to_string())
print("\nshare of dates losing >1%% of the index:",
      round(float((per["w_i_lost"] > 0.01).mean()) * 100, 1), "%")

# ttm is recoverable exactly from maturity_date, which the panel carries for every bond
from RVUtils.ETFRebalance import bond_panel as BP
p = BP.load()
p["date"] = pd.to_datetime(p["date"]); p["cusip"] = p["cusip"].astype(str)
fix = act.merge(p[["date", "cusip", "ttm"]].rename(columns={"ttm": "ttm_panel"}),
                on=["date", "cusip"], how="left")
print("\nrecoverable from the panel:",
      int(fix.loc[fix["ttm"].isna() & nh.values, "ttm_panel"].notna().sum()),
      "of", int((fix["ttm"].isna() & nh.values).sum()))
ok = fix["ttm"].notna() & fix["ttm_panel"].notna()
print("agreement where both exist: max |diff| =", float((fix.loc[ok, "ttm"] - fix.loc[ok, "ttm_panel"]).abs().max()))
