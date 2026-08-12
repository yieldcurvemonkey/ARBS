"""Review probe: trace the sign by hand, and size the b0 seam. Read-only."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import probability as prob

HERE = os.path.dirname(os.path.abspath(__file__))

print("=== A. worked example, OUTRIGHT, rate rule, b0 = 0 ===")
traded_pct, mid_pct = 5.0050, 5.0000
P_t = conv.structure_price([traded_pct], conv.OUTRIGHT, 1, conv.RULE_RATE)
P_m = conv.structure_price([mid_pct], conv.OUTRIGHT, 1, conv.RULE_RATE)
x = P_t - P_m
fit = prob.MixtureFit("EX", 5000, 5000, b0=0.0, h=0.25, s=0.15, loglik=0.0)
call = prob.direction_probability(x, fit)
print(f"  P_traded {P_t:.4f} bp  P_mid {P_m:.4f} bp  x = {x:+.4f} bp")
print(f"  tau = s^2/2h = {fit.tau:.6f} bp   p = {call.p:.6f}   2p-1 = {call.signed_weight:+.6f}")
print(f"  conv.dealer_side(x) = {conv.dealer_side(x):+d}  (DEALER_RECEIVED={conv.DEALER_RECEIVED})")
print(f"  dealer_received_signs = {conv.dealer_received_signs(conv.OUTRIGHT, 1, conv.RULE_RATE, conv.dealer_side(x))}")
print(f"  RL_DELTA_TO_FUTURES_EQ = {conv.RL_DELTA_TO_FUTURES_EQ}  ->  received leg, "
      f"raw rl delta < 0, delta_dv01 = -1 * (<0) > 0  [convention holds]")

print("\n=== B. CURVE, rate rule ===")
Pc_t = conv.structure_price([4.90, 5.00], conv.CURVE, 2, conv.RULE_RATE)
Pc_m = conv.structure_price([4.90, 4.99], conv.CURVE, 2, conv.RULE_RATE)
xc = Pc_t - Pc_m
print(f"  x = {xc:+.4f} bp -> dealer_side {conv.dealer_side(xc):+d}, "
      f"legs {conv.dealer_received_signs(conv.CURVE, 2, conv.RULE_RATE, conv.dealer_side(xc))}, "
      f"p = {prob.p_customer_paid(xc, fit):.6f}")

print("\n=== C. the b0 seam: p and conv.dealer_side disagree whenever x is between 0 and b0 ===")
biased = prob.MixtureFit("B", 5000, 5000, b0=-0.4836, h=0.25, s=0.15, loglik=0.0)
for dev in (-0.60, -0.30, -0.20, -0.05, 0.0, 0.10):
    p = prob.p_customer_paid(dev, biased)
    ds = conv.dealer_side(dev)
    p_side = 1 if p > 0.5 else (-1 if p < 0.5 else 0)
    print(f"  x={dev:+.2f}  p={p:.4f} -> side {p_side:+d} | conv.dealer_side -> {ds:+d}"
          f"   {'DISAGREE' if p_side and ds and p_side != ds else ''}")

devs = pd.read_parquet(os.path.join(HERE, "prob01_devs.parquet"))
rv = devs[devs.classification_method == "RATE_VS_MID"]["spread_to_mid_bps"].astype(float)
b0 = -0.4836
band = ((rv > b0) & (rv < 0)).mean()
print(f"  real RATE_VS_MID rows with b0 < x < 0 (b0 = {b0}): {band:.1%} of {len(rv):,}")

print("\n=== D. MAX_SE_LOG_TAU: p90 of |N(0,sigma)| is 1.6449 sigma, not 1.2816 ===")
from scipy.stats import norm
print(f"  norm.ppf(0.90)            = {norm.ppf(0.90):.4f}   <- the constant used")
print(f"  p90 of |Z| = norm.ppf(0.95) = {norm.ppf(0.95):.4f}   <- what abs() error needs")
z = np.abs(np.random.default_rng(0).normal(size=2_000_000))
print(f"  empirical p90 of |Z|       = {np.quantile(z, 0.90):.4f}")
print(f"  MAX_SE_LOG_TAU as coded    = {prob.MAX_SE_LOG_TAU:.4f}")
print(f"  MAX_SE_LOG_TAU as derived  = {prob.TAU_RECOVERY_TOLERANCE / norm.ppf(0.95):.4f}"
      f"  ({prob.MAX_SE_LOG_TAU / (prob.TAU_RECOVERY_TOLERANCE / norm.ppf(0.95)) - 1:+.1%})")

print("\n=== E. _bootstrap_q_pvalue: skipped reps still count in the denominator ===")


def instrumented(fits, reps, seed):
    rng = np.random.default_rng(seed)
    h = float(np.median([f.h for f in fits]))
    s = float(np.median([f.s for f in fits]))
    b0_ = float(np.median([f.b0 for f in fits]))
    ns = [f.n_trimmed for f in fits]
    skipped = 0
    for _ in range(reps):
        ys = []
        for n in ns:
            xx, _ = prob.simulate(b0=b0_, h=h, s=s, n=n, rng=rng)
            f = prob.fit_mixture(xx, bucket="BOOT")
            if not f.se_log_tau:
                continue
            ys.append(math.log(f.tau))
        if len(ys) < 2:
            skipped += 1
    return skipped


rng = np.random.default_rng(7)
fits = []
for _ in range(4):
    xx, _ = prob.simulate(b0=0.0, h=0.135, s=0.18, n=400, rng=rng)   # h/s = 0.75
    f = prob.fit_mixture(xx, bucket="P", min_n=0)
    if f.se_log_tau:
        fits.append(f)
print(f"  usable input fits: {len(fits)}")
if len(fits) >= 2:
    sk = instrumented(fits, reps=60, seed=5)
    print(f"  bootstrap reps skipped by `if len(ys) < 2: continue`: {sk}/60")
    print(f"  p-value denominator used by the code: reps+1 = 61 (skipped reps counted as 'not worse')")
    st = prob.tau_stability(fits, method="bootstrap", reps=60, seed=5)
    print(f"  reported p = {st.p_value:.4f}  moves={st.moves}")
print(f"  floor of the p-value when EVERY rep is skipped: 1/(reps+1) = {1/61:.4f} < alpha=0.05"
      f"  -> moves=True from zero valid replicates")

print("\n=== F. rolling_calibrations silently returns {} ===")
rng = np.random.default_rng(3)
frames = []
for d in pd.bdate_range("2026-01-01", periods=10):
    xx, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=20, rng=rng)
    fr = prob.frame(xx, venue="D2C", rate_index="SOFR", structure="OUTRIGHT",
                    tenor_band="2Y-3Y")
    fr["as_of_date"] = d.date()
    frames.append(fr)
small = pd.concat(frames, ignore_index=True)
out = prob.rolling_calibrations(small, window_days=20, min_gap_days=1)
print(f"  {len(small)} rows over {small.as_of_date.nunique()} days -> "
      f"{len(out)} calibrations, no exception, no warning: {out!r}")
