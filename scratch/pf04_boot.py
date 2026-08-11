"""Fix probe 4: bootstrap skip rates, and the p90/SE relation on real fits."""
from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from SDRUtils.dealer_direction import probability as prob

# --- how often does a bootstrap replicate fail to produce an SE? -----------
for n in (1, 3, 60, 120, 400):
    rng = np.random.default_rng(3)
    fails = 0
    for _ in range(60):
        x, _ = prob.simulate(b0=0.0, h=0.18, s=0.18, n=n, rng=rng)
        f = prob.fit_mixture(x, bucket="BOOT")
        fails += not f.se_log_tau
    print(f"  n={n:4d}: {fails}/60 replicate fits have no se_log_tau")

# --- what does the CURRENT _bootstrap_q_pvalue return with q_obs = 0? ------
for n in (1, 60):
    fits = [prob.MixtureFit(f"P{i}", n, n, 0.0, 0.18, 0.18, 0.0, se_log_tau=0.2)
            for i in range(3)]
    p = prob._bootstrap_q_pvalue(fits, 0.0, reps=40, seed=3)
    print(f"  n_trimmed={n}: q_obs=0 -> p={p:.4f}   (must be 1.0)")

# --- the p90 of |log tau error| against the analytic SE --------------------
rng = np.random.default_rng(1009)
logtaus, ses = [], []
for _ in range(300):
    x, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=800, rng=rng)
    f = prob.fit_mixture(x, bucket="SE")
    if f.se_log_tau:
        logtaus.append(math.log(f.tau))
        ses.append(f.se_log_tau)
lt = np.asarray(logtaus)
truth = math.log(0.18 ** 2 / (2 * 0.25))
p90_abs = float(np.quantile(np.abs(lt - truth), 0.90))
med_se = float(np.median(ses))
print(f"\n  kept {len(lt)}/300 fits; median se={med_se:.4f}; "
      f"p90 |log tau - truth| = {p90_abs:.4f}; ratio = {p90_abs / med_se:.4f} "
      f"(1.6449 if the error is normal, 1.2816 under the coded constant)")
