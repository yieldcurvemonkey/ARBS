"""Smoke test: does the O<n>/CT<n> alias resolve and produce a yield spread timeseries?"""

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime  # noqa: E402

import pandas as pd  # noqa: E402

from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP  # noqa: E402
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery  # noqa: E402
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue  # noqa: E402
from TB.FixedRateBondsTB import FixedRateBondsTB  # noqa: E402

pd.set_option("display.width", 250)

SRC = os.getenv("FRB_SOURCE", "USTS_FEDINVEST_WSJ_LIVE-QL")

# --- 1. alias resolution only, no pricing -----------------------------------------
from MDP.FixedRateBonds.FixedRateBondsMDP import _filter_and_rank_ref_df  # noqa: E402
from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import (  # noqa: E402
    update_reference_data,
)

ref = update_reference_data(source="fiscaldata", force_refresh=False)
print("ref rows", len(ref), "cols", list(ref.columns))
for d in (datetime.date(2010, 6, 15), datetime.date(2018, 6, 15), datetime.date(2025, 6, 16)):
    r = _filter_and_rank_ref_df(ref, d)
    print(f"\n--- {d} : {len(r)} active ---")
    print(r.groupby("oi")["rank"].max().to_string())

# how deep does each tenor go, on a recent date?
d = datetime.date(2025, 6, 16)
r = _filter_and_rank_ref_df(ref, d)
for oi in ("2-Year", "3-Year", "5-Year", "7-Year", "10-Year", "20-Year", "30-Year"):
    sub = r[r["oi"] == oi].nsmallest(7, "rank")
    print(f"\n{oi}:")
    print(sub[["rank", "cusip", "cpn", "issue_date", "maturity_date"]].to_string(index=False))

# --- 2. does the query resolve? ---------------------------------------------------
for tok in ("CT10", "O10", "OO10", "OOO10", "Ox410"):
    q = FixedRateBondQuery(cusip=tok, value=FixedRateBondValue.YTM)
    try:
        qe = q.resolve_query(d, None)
        print(f"{tok:8s} -> {qe.cusip!r}  structure={qe.structure.name}")
    except Exception as exc:
        print(f"{tok:8s} -> FAILED {type(exc).__name__}: {exc}")

print("\n-- two-leg --")
for tok in ("O10/CT10", "OO10/CT10", "OOO10/O10"):
    q = FixedRateBondQuery(cusip=tok, value=FixedRateBondValue.YTM)
    try:
        qe = q.resolve_query(d, None)
        print(f"{tok:12s} -> {qe.cusip!r} structure={qe.structure.name} skw={qe.structure_kwargs}")
    except Exception as exc:
        print(f"{tok:12s} -> FAILED {type(exc).__name__}: {exc}")

# --- 3. timeseries ----------------------------------------------------------------
mdp = FixedRateBondsMDP(source=SRC)
tb = FixedRateBondsTB(mdp, show_tqdm=False)
q = FixedRateBondQuery(cusip="O10/CT10", value=FixedRateBondValue.YTM)
df = tb.get_timeseries(
    start=datetime.date(2024, 1, 2), end=datetime.date(2024, 2, 15), queries=[q], n_jobs=4
)
print("\n=== O10/CT10 YTM timeseries ===")
print(df.shape, list(df.columns))
print(df.head(12).to_string())
print(df.tail(5).to_string())
