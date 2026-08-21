from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np
import pandas as pd

from RVUtils.ETFRebalance import holdings_panel as HP

pd.set_option("display.width", 200)

h = HP.load_holdings(["TLT"])
h = h.sort_values(["cusip", "date"])

fund = h.groupby("date", as_index=False).agg(total_par=("par", "sum"), shares_out=("shares_out", "first"))
fund["d_par"] = fund["total_par"].diff()
fund["d_shares"] = fund["shares_out"].diff()
fund["d_shares_fwd1"] = fund["d_shares"].shift(-1)
fund["d_shares_lag1"] = fund["d_shares"].shift(1)

ok = fund.dropna(subset=["d_par", "d_shares"])
print("fund-level sum(par) change vs same-day d_shares: corr =",
     np.corrcoef(ok["d_par"], ok["d_shares"])[0, 1], "n=", len(ok))

ok2 = fund.dropna(subset=["d_par", "d_shares_fwd1"])
print("fund-level sum(par) change(t) vs d_shares(t+1): corr =",
     np.corrcoef(ok2["d_par"], ok2["d_shares_fwd1"])[0, 1], "n=", len(ok2))

ok3 = fund.dropna(subset=["d_par", "d_shares_lag1"])
print("fund-level sum(par) change(t) vs d_shares(t-1): corr =",
     np.corrcoef(ok3["d_par"], ok3["d_shares_lag1"])[0, 1], "n=", len(ok3))

# now: does d_par(t) predict -d_par(t+1) (mechanical one-day reversal at fund level)?
fund["d_par_fwd1"] = fund["d_par"].shift(-1)
ok4 = fund.dropna(subset=["d_par", "d_par_fwd1"])
print("\nfund-level d_par(t) vs d_par(t+1): corr =",
     np.corrcoef(ok4["d_par"], ok4["d_par_fwd1"])[0, 1], "n=", len(ok4))

# per-cusip par-level (not per-share) reversal, to isolate mechanism from the ppc/shares algebra
h["d_par_cusip"] = h.groupby("cusip")["par"].diff()
h["d_par_cusip_fwd1"] = h.groupby("cusip")["d_par_cusip"].shift(-1)
okc = h.dropna(subset=["d_par_cusip", "d_par_cusip_fwd1"])
print("\nper-cusip RAW par change(t) vs change(t+1): corr =",
     np.corrcoef(okc["d_par_cusip"], okc["d_par_cusip_fwd1"])[0, 1], "n=", len(okc))

# is par itself revised/corrected the next file (i.e. does par(t+1) sometimes just equal par(t-1),
# a revert-then-correct pattern)?
h["par_lag2"] = h.groupby("cusip")["par"].shift(2)
same_as_2ago = (h["par"] == h["par_lag2"]).mean()
print("\nfraction of (cusip,date) rows where par == par two files ago:", same_as_2ago)

print("\n" + "="*70)
print("ALIGNED VERSION: shares_out(t) replaced by shares_out(t+1)")
print("="*70)
h2 = h.sort_values(["cusip", "date"]).copy()
fund_shares = h.groupby("date")["shares_out"].first().sort_index()
aligned_shares = fund_shares.shift(-1)  # tomorrow's file's shares count assigned to today
h2["shares_aligned"] = h2["date"].map(aligned_shares)
h2["ppc_aligned"] = h2["par"] / h2["shares_aligned"]
h2 = h2.sort_values(["cusip", "date"])
h2["d_ppc_aligned"] = h2.groupby("cusip")["ppc_aligned"].diff()
h2["active_dpar_aligned"] = h2["shares_aligned"] * h2["d_ppc_aligned"]

h2["d_ppc_aligned_fwd1"] = h2.groupby("cusip")["d_ppc_aligned"].shift(-1)
okc2 = h2.dropna(subset=["d_ppc_aligned", "d_ppc_aligned_fwd1"])
print("per-cusip d_ppc_aligned(t) vs d_ppc_aligned(t+1) corr:",
     np.corrcoef(okc2["d_ppc_aligned"], okc2["d_ppc_aligned_fwd1"])[0, 1], "n=", len(okc2))

# compare to unaligned
h["d_ppc_fwd1"] = h.groupby("cusip")["d_ppc" if "d_ppc" in h.columns else "par_per_share"].shift(-1) if "d_ppc" in h.columns else None
