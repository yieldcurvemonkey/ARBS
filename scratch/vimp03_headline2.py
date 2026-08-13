"""VERIFY (cont): the headline on the module's OWN DV01 weighting.

vimp02 showed the freq-cache ``sum_dv01`` weighting is 28bp high in level at
both slacks while moving by exactly the same +0.0056 -- so it is the right
sensitivity on the wrong base. The base the module used is
``partB_final_imputation_Cdiv4.csv``: per-cell ``tot_dv01`` and ``exc_dv01_ln``.

Validate on the known answer first: the csv's own stored multipliers must give
0.1541 / 0.2721 / the old per-bucket dict. Only then swap in the refitted
multipliers and read off the new headline.
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from SDRUtils.dealer_direction import imputation as imp  # noqa: E402

d = pd.read_csv(os.path.join(HERE, "partB_final_imputation_Cdiv4.csv"))
print(d[["vintage", "lo", "cap", "tot_dv01", "exc_dv01_ln", "ln_mult",
         "cap_share", "coarse"]].to_string(index=False))

d["coarse"] = d["coarse"].str.replace(r"^\d+\.\s*", "", regex=True)
TOT = float(d["tot_dv01"].sum())


def headline(mult_by_key, tag):
    """share = excess / (tot + excess), excess = (k-1) * capped-at-cap dv01."""
    # capped-at-cap dv01 per cell, recovered from the stored excess and mult
    capdv = d["exc_dv01_ln"] / (d["ln_mult"] - 1.0)
    ex = np.array([(mult_by_key[(v, lo)] - 1.0) * cd
                   for v, lo, cd in zip(d["vintage"], d["lo"], capdv)])
    tot_ex = float(ex.sum())
    out = {"overall": tot_ex / (TOT + tot_ex),
           "k": 1.0 + tot_ex / float(capdv.sum()),
           "c": float(capdv.sum()) / TOT}
    for bk in ("<=2y", "2-10y", "10-30y", ">30y"):
        m = (d["coarse"] == bk).to_numpy()
        out[bk] = float(ex[m].sum()) / (float(d.loc[m, "tot_dv01"].sum())
                                        + float(ex[m].sum()))
    print(f"\n--- {tag}")
    print(f"  overall {out['overall']:.4f}  c {out['c']:.4f}  k {out['k']:.4f}")
    for bk in ("<=2y", "2-10y", "10-30y", ">30y"):
        print(f"    {bk:7s} {out[bk]:.4f}")
    return out


stored = {(v, lo): m for v, lo, m in zip(d["vintage"], d["lo"], d["ln_mult"])}
headline(stored, "TOOL VALIDATION: the csv's own stored multipliers "
                 "(HEAD says 0.1541; buckets .2177/.1659/.0917/.0818)")

f = pd.read_csv(os.path.join(HERE, "partB_freq_cache.csv")).dropna(subset=["cell"])
m = f["cell"].str.split("|", expand=True)
f["vintage"] = m[0]
for c, src in (("lo", m[1]), ("hi", m[2]), ("cap", m[3])):
    f[c] = src.astype(float)
for c in ("notional", "n"):
    f[c] = f[c].astype(float)
COLS = ["vintage", "lo", "cap", "notional", "is_capped", "n"]

for slack in (30.0, 150.0):
    imp.LN_MU_SLACK = slack
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        fits = imp.fit_frequency_table(f[COLS])
    headline({k: v.multiplier for k, v in fits.items()},
             f"refit at LN_MU_SLACK={slack:g}")
imp.LN_MU_SLACK = 150.0
print(f"\nshipped: IMPUTED_DV01_SHARE={imp.IMPUTED_DV01_SHARE} "
      f"CAPPED_AT_CAP_DV01_SHARE={imp.CAPPED_AT_CAP_DV01_SHARE} "
      f"EFFECTIVE_MULTIPLIER={imp.EFFECTIVE_MULTIPLIER}")
print(f"         IMPUTED_SHARE_BY_BUCKET={imp.IMPUTED_SHARE_BY_BUCKET}")
