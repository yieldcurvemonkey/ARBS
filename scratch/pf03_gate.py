"""Fix probe 3: what does tightening MAX_SE_LOG_TAU to the p90 of |N(0,1)| do?

0.25/1.2816 = 0.1951 (coded) vs 0.25/1.6449 = 0.1520 (the p90 of an ABSOLUTE
relative error). Measures (a) that 1.6449 is the right constant, (b) the
se_log_tau of every fit the existing tests assert flags on.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from scipy import stats as sps

from SDRUtils.dealer_direction import probability as prob
from SDRUtils.stir_flow import confidence as frozen_conf

rng = np.random.default_rng(0)
z = np.abs(rng.standard_normal(4_000_000))
print(f"empirical p90 |Z| = {np.quantile(z, 0.90):.4f}   "
      f"norm.ppf(0.95) = {sps.norm.ppf(0.95):.4f}   coded 1.2816 = {sps.norm.ppf(0.90):.4f}")
print(f"coded MAX_SE_LOG_TAU = {prob.MAX_SE_LOG_TAU:.4f}, "
      f"corrected = {prob.TAU_RECOVERY_TOLERANCE / sps.norm.ppf(0.95):.4f}")

new_gate = prob.TAU_RECOVERY_TOLERANCE / float(sps.norm.ppf(0.95))

print("\ntest_recovers_known_parameters, n=20_000, se_log_tau of each cell:")
for b0, h, s in [(0.00, 0.25, 0.15), (-0.48, 0.25, 0.20),
                 (0.02, 0.15, 0.30), (0.10, 0.60, 0.10)]:
    x, _ = prob.simulate(b0=b0, h=h, s=s, n=20_000, rng=np.random.default_rng(11))
    f = prob.fit_mixture(x, bucket="SIM")
    print(f"  h/s={h / s:4.2f} se={f.se_log_tau!r} flags={f.flags} "
          f"would_flag_imprecise={f.se_log_tau is None or f.se_log_tau > new_gate}")

print("\nrouting fractions under the corrected gate (simulated by hand):")


def anchored_fraction(h, s, n, reps, seed, gate):
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(reps):
        x, _ = prob.simulate(b0=0.0, h=h, s=s, n=n, rng=rng)
        xt = x[prob.trim_mask(x)]
        f = prob.fit_mixture(x, bucket="A", tick_stats=frozen_conf.TickStats(
            median_tick_bps=2 * h, disp_jns=None, futures_tick_bps=0.25))
        # replicate the routing decision with the corrected gate
        mc = prob.moment_estimates(xt)
        lept = mc.significantly_leptokurtic
        unsep = (f.separation_pvalue or 1.0) > prob.SEPARATION_ALPHA or (
            f.h_mle is not None and f.s_mle is not None
            and f.h_mle < prob.MIN_SEPARATION * f.s_mle)
        se = None if unsep else prob._se_log_tau(xt, f.b0, f.h_mle, f.s_mle)
        imprecise = se is None or se > gate
        hits += bool(lept or unsep or imprecise)
    return hits / reps


for label, gate in (("coded 0.1951", prob.MAX_SE_LOG_TAU), ("corrected 0.1520", new_gate)):
    a = anchored_fraction(0.18, 0.18, prob.MIN_BUCKET_N_ANCHORED, 150, 211, gate)
    w = anchored_fraction(0.45, 0.18, 400, 60, 213, gate)
    print(f"  {label}: anchored frac at h/s=1.0,n=400 = {a:.3f} (test wants 0.3-0.9); "
          f"at h/s=2.5,n=400 = {w:.3f} (test wants 0)")
