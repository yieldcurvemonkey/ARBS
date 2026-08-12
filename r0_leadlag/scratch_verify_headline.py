"""Independent recomputation of R0's headline number via statsmodels.

Rebuilds the pooled dissemination-clock design through run_r0's own panel code, then
estimates it with statsmodels OLS + cov_type='cluster' instead of the hand-rolled
covariance, and forms sum(beta_k) by an explicit t_test rather than c'Vc. Two different
implementations of the same estimand.
"""
import os, sys
os.environ["ARBS_SUPABASE_ENABLED"] = "0"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
import statsmodels.api as sm

from run_r0 import (build_grid, make_design, x_series, FEAbsorber,
                    DECISION_BUCKETS, REGCOLS, LAGS, IPOS, INEG, DATA)

y = pd.read_parquet(os.path.join(DATA, "y_signed_volume.parquet"))
x = pd.read_parquet(os.path.join(DATA, "x_signed_dv01.parquet"))
grid = build_grid(y)
xs = x_series(x, grid, "diss", "all")
yv, M, keep = make_design(grid, xs)
sub = grid.loc[keep]
cl = pd.factorize(sub["session_date"])[0]
bcode = pd.factorize(sub["bucket"])[0]
bod = pd.factorize(sub["bin_of_day"])[0]
fe = FEAbsorber([bcode, bod])
Zy, ZX = fe.absorb(yv), fe.absorb(M)
print(f"n={len(Zy):,}  k={ZX.shape[1]}  clusters={len(np.unique(cl))}  k_fe={fe.k_fe}")

res = sm.OLS(Zy, ZX).fit(cov_type="cluster",
                         cov_kwds={"groups": cl, "use_correction": True, "df_correction": True})

cpos = np.zeros(ZX.shape[1]); cpos[IPOS] = 1.0
cneg = np.zeros(ZX.shape[1]); cneg[INEG] = 1.0
cdif = cpos - cneg
for lab, c in [("sum(beta_k, k<=-1)", cneg), ("sum(beta_k, k>=+1)", cpos),
               ("difference (pos-neg)", cdif)]:
    t = res.t_test(c)
    print(f"  {lab:24s} = {float(t.effect):+.5f}   SE {float(t.sd):.5f}   "
          f"t = {float(t.tvalue):+.4f}")
i0 = REGCOLS.index("x+0")
print(f"  beta_(k=0)               = {res.params[i0]:+.5f}   SE {res.bse[i0]:.5f}   "
      f"t = {res.tvalues[i0]:+.4f}")

print()
print("run_r0.py reported (out/r0_table.csv):")
t = pd.read_csv(os.path.join(HERE, "out", "r0_table.csv"))
r = t[(t.clock == "diss") & (t.scope == "pooled") & (t.split == "all")].iloc[0]
print(f"  sum(beta_k, k<=-1)       = {r.sum_beta_kneg:+.5f}   SE {r.se_cluster_kneg:.5f}"
      f"   t = {r.t_cluster_kneg:+.4f}")
print(f"  sum(beta_k, k>=+1)       = {r.sum_beta_kpos:+.5f}   SE {r.se_cluster_kpos:.5f}"
      f"   t = {r.t_cluster_kpos:+.4f}")
print(f"  difference (pos-neg)     = {r.diff_pos_minus_neg:+.5f}   SE {r.se_cluster_diff:.5f}"
      f"   t = {r.t_cluster_diff:+.4f}")

tp = res.t_test(cpos)
tn = res.t_test(cneg)

# Point estimates must match to machine precision. The SEs differ by exactly one known
# factor: run_r0 counts the absorbed fixed effects in the small-sample correction,
# (n-1)/(n-k-k_fe); statsmodels cannot see them and uses (n-1)/(n-k). run_r0 is therefore
# the slightly more conservative of the two. Predict the ratio and check it.
G, n, k, kfe = len(np.unique(cl)), len(Zy), ZX.shape[1], fe.k_fe
ratio = (((G / (G - 1)) * ((n - 1) / (n - k - kfe))) /
         ((G / (G - 1)) * ((n - 1) / (n - k)))) ** 0.5
print()
print(f"predicted SE ratio from the FE dof correction alone: {ratio:.6f}")
pt_ok = (abs(float(tp.effect) - r.sum_beta_kpos) < 1e-9
         and abs(float(tn.effect) - r.sum_beta_kneg) < 1e-9)
se_ok = (abs(float(tp.sd) * ratio / r.se_cluster_kpos - 1) < 2e-4
         and abs(float(tn.sd) * ratio / r.se_cluster_kneg - 1) < 2e-4)
print(f"  point estimates identical to 1e-9                     : {pt_ok}")
print(f"  SEs agree once the FE dof factor is applied (<2e-4 rel): {se_ok}")
print()
print(f"TWO INDEPENDENT IMPLEMENTATIONS AGREE: {pt_ok and se_ok}")
