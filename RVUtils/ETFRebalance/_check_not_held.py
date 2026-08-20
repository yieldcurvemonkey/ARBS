import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
import numpy as np
import pandas as pd
from MDP.ETFHoldings.universe import spec
from RVUtils.ETFRebalance import bond_panel as BP
from RVUtils.ETFRebalance import engine as EN
from RVUtils.ETFRebalance import float_panel as FP
from RVUtils.ETFRebalance import holdings_panel as HP
from RVUtils.ETFRebalance import signals as SIG
from MDP.ETFHoldings import store as HS

fund = "TLT"
sp = spec(fund)
panel = FP.asof_join(BP.load(), FP.load())
joined = HP.build([fund], panel=panel)
cov = HS.coverage(fund)
first_date = cov["first"].min()
valid_dates = set(pd.to_datetime(joined.loc[joined["ticker"] == fund, "date"].unique()))
cfg = EN.merge_config({"fund": fund, "universe": {"start": first_date.strftime("%Y-%m-%d")}})
uni, _ = EN.prepare_universe(cfg, joined=joined, panel=panel)
uni = uni[uni["date"].isin(valid_dates)].copy()

raw = SIG.REGISTRY["not_held"](uni)
print("raw not_held: n", raw.notna().sum(), "of", len(raw))
print("value counts (rounded):", raw.round(4).value_counts().head(10))
print("share of bond-days with held=False:", (~uni["held"].fillna(False)).mean())
z = SIG.cross_sectional_z(raw, uni["date"], robust=True)
print("z not_held: finite", np.isfinite(z).sum(), "of", len(z))
print(z.describe())
