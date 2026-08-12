"""Fix probe 7: re-run prob05_real's known-answer sections against the FIXED
module (no DB, no writes) -- does the rewritten docstring claim hold?

Claim under test: the F-20 b0 table is NOT an external check, because every one
of those buckets takes ROBUST_SCALE_FALLBACK, where b0 := median(trimmed).
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import probability as prob

HERE = os.path.dirname(os.path.abspath(__file__))
df = pd.read_parquet(os.path.join(HERE, "prob01_devs.parquet"))
df["x"] = df["spread_to_mid_bps"].astype(float)

rv = df[df.classification_method == "RATE_VS_MID"]
f = prob.fit_mixture(rv.x.to_numpy(), bucket="RATE_VS_MID")
print(f"RATE_VS_MID n={len(rv)} raw median {rv.x.median():+.4f} "
      f"fitted b0 {f.b0:+.4f} tau {f.tau:.4f} [{','.join(f.flags)}]")

print("\nF-20 gradient, and what the fit actually did to produce it:")
F20 = {"3M": -0.136, "1Y": -0.246, "2Y": -0.524, "3Y": -1.237,
       "IMM_1Y": -5.57, "IMM_2Y": -6.84, "IMM_3Y": -6.83}
for tb, expect in F20.items():
    g = df[(df.rate_index_clean == "SOFR") & (df.tenor_bucket == tb)]
    if g.empty:
        continue
    x = g.x.to_numpy()
    fit = prob.fit_mixture(x, bucket=tb)
    kept = x[prob.trim_mask(x)]
    print(f"  {tb:8s} n={len(g):5d} F-20 {expect:+7.3f} raw med "
          f"{np.median(x):+7.3f} fitted b0 {fit.b0:+7.3f} "
          f"trimmed med {np.median(kept):+7.3f} "
          f"b0==trimmed_median={np.isclose(fit.b0, np.median(kept))} "
          f"[{','.join(fit.flags)}]")

print("\nflag census over all buckets with n >= 300 (no tick stats):")
rows = []
for (idx, tb), g in df.groupby(["rate_index_clean", "tenor_bucket"]):
    if len(g) < 300:
        continue
    fit = prob.fit_mixture(g.x.to_numpy(), bucket=f"{idx}|{tb}")
    rows.append(dict(bucket=f"{idx}|{tb}", n=len(g),
                     fallback=prob.FIT_ROBUST_FALLBACK in fit.flags,
                     anchored=prob.FIT_ANCHORED_H in fit.flags,
                     imprecise=prob.FIT_IMPRECISE in fit.flags,
                     flags=",".join(fit.flags)))
b = pd.DataFrame(rows)
print(f"  buckets={len(b)}  ROBUST_SCALE_FALLBACK={b.fallback.sum()}  "
      f"H_FROM_INDEPENDENT_ESTIMATE={b.anchored.sum()}  "
      f"TAU_SE_ABOVE_TOLERANCE={b.imprecise.sum()}")
print(b.flags.value_counts().to_string())
