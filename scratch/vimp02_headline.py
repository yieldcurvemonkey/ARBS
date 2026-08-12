"""VERIFY: is IMPUTED_DV01_SHARE = 0.1597 measured, or typed?

vimp01 recomputed 0.1626 from the freq cache and the module says 0.1597. Before
believing either, validate the recomputation against a KNOWN answer: the same
arithmetic at LN_MU_SLACK = 30 must return the OLD shipped 0.1541. If it does
not, my weighting is not the module's and the 0.1626 means nothing.

Two candidate DV01 weightings are tried, because the module's own docstring
names two populations (the 67,619-leg calibration set and the 68,945-leg
production one): the freq cache's ``sum_dv01``, and the per-cell weights in
``partB_final_imputation_Cdiv4.csv`` which is what the review used.
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from SDRUtils.dealer_direction import imputation as imp  # noqa: E402

f = pd.read_csv(os.path.join(HERE, "partB_freq_cache.csv")).dropna(subset=["cell"])
m = f["cell"].str.split("|", expand=True)
f["vintage"] = m[0]
for c, src in (("lo", m[1]), ("hi", m[2]), ("cap", m[3])):
    f[c] = src.astype(float)
for c in ("notional", "n", "sum_t", "sum_dv01"):
    f[c] = f[c].astype(float)

cdiv4 = pd.read_csv(os.path.join(HERE, "partB_final_imputation_Cdiv4.csv"))
print("Cdiv4 columns:", list(cdiv4.columns))

COLS = ["vintage", "lo", "cap", "notional", "is_capped", "n"]
tot = float(f["sum_dv01"].sum())
capped = f[f["is_capped"]].groupby(["vintage", "lo"])["sum_dv01"].sum()

for slack, known in ((30.0, "HEAD 0.1541"), (150.0, "shipped 0.1597")):
    imp.LN_MU_SLACK = slack
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        fits = imp.fit_frequency_table(f[COLS])
    ex = sum((v.multiplier - 1.0) * float(capped.get(k, 0.0))
             for k, v in fits.items())
    print(f"slack {slack:5g}: freq-cache sum_dv01 weighting -> "
          f"{ex/(tot+ex):.4f}   k={1+ex/float(capped.sum()):.4f}   [{known}]")
imp.LN_MU_SLACK = 150.0
