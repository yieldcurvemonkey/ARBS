"""Is a spline change moving the SIGNAL, or just cascading through the argmax?

Run this before drawing any conclusion from a trade-set Jaccard across fits. Measured on S0 vs
S3 (knots slid 1.25y): Jaccard 0.045 but corr(s2c) 0.983 and Spearman 0.944 — the signal barely
moved and the book was rewritten anyway, because selection is a hard top-N over ~173 near-tied
candidates and 0.26bp of perturbation reorders it.


Trade-set Jaccard cannot tell those apart: selection is a hard argmax over ~173 near-tied
candidates a day, so an arbitrarily small ranking change can rewrite the whole book. The
discriminating measurement is the s2c VALUES themselves.

    corr high  -> the signal survives; the churn is the argmax cascade (a selection-design flaw)
    corr low   -> the residual genuinely differs; the signal is reading the fit
"""
import os, sys, logging
os.environ.setdefault("ARBS_SUPABASE_ENABLED","0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-rvx")
import numpy as np, pandas as pd
logging.basicConfig(level=logging.ERROR)
from pathlib import Path
from BT.gss_fly.data import build_curve_panel, ust_business_days, spline_config_id
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-rvx/scripts")
from gss_grid import spline_variants
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
days = ust_business_days("2024-09-02","2026-01-02")
sv = spline_variants()
p0 = build_curve_panel(days, mdp, cache_path=Path("notebooks/data/gss_fly/panel_cached"),
                       show_progress=False, spline_config=sv["S0_jpm"])
p3 = build_curve_panel(days, mdp, cache_path=Path("notebooks/data/gss_fly/panel_cached"),
                       show_progress=False, spline_config=sv["S3_shift"])
a, b = p0.s2c, p3.s2c
cols = a.columns.intersection(b.columns); idx = a.index.intersection(b.index)
A, B = a.loc[idx, cols], b.loc[idx, cols]
print(f"S2C: overlap {A.shape[0]} dates x {A.shape[1]} bonds", flush=True)

per_date = []
for t in idx:
    x, y = A.loc[t].to_numpy(float), B.loc[t].to_numpy(float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() > 10 and x[m].std() > 0 and y[m].std() > 0:
        per_date.append(np.corrcoef(x[m], y[m])[0,1])
pd_ = np.array(per_date)
print(f"S2C: per-date cross-sectional corr(s2c_S0, s2c_S3): "
      f"median {np.median(pd_):.4f}  p05 {np.percentile(pd_,5):.4f}  p95 {np.percentile(pd_,95):.4f}", flush=True)

x = A.to_numpy(float).ravel(); y = B.to_numpy(float).ravel()
m = np.isfinite(x) & np.isfinite(y)
print(f"S2C: pooled corr {np.corrcoef(x[m], y[m])[0,1]:.4f}   "
      f"mean|diff| {np.mean(np.abs(x[m]-y[m])):.4f}bp   sd(S0) {x[m].std():.4f}bp", flush=True)

# does the RANK of richness survive? that is what the fly selection actually consumes
rk = []
for t in idx:
    s0, s3 = A.loc[t].dropna(), B.loc[t].dropna()
    common = s0.index.intersection(s3.index)
    if len(common) > 10:
        rk.append(s0[common].rank().corr(s3[common].rank(), method="spearman"))
rk = np.array(rk)
print(f"S2C: per-date SPEARMAN rank corr: median {np.median(rk):.4f}  p05 {np.percentile(rk,5):.4f}", flush=True)
print("S2CDONE", flush=True)
