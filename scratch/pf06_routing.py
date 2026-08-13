"""Fix probe 6: the routing fractions the two anchor tests assert, measured
against the FIXED module (corrected MAX_SE_LOG_TAU, no parent route)."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from SDRUtils.dealer_direction import probability as prob
from SDRUtils.stir_flow import confidence as frozen_conf

print(f"MAX_SE_LOG_TAU = {prob.MAX_SE_LOG_TAU:.4f}")

# test_the_anchored_floor_reproduces_too_and_is_genuinely_lower
h, s, n = 0.18, 0.18, prob.MIN_BUCKET_N_ANCHORED
rng = np.random.default_rng(211)
errs, anchored = [], 0
for _ in range(150):
    x, _ = prob.simulate(b0=0.0, h=h, s=s, n=n, rng=rng)
    stats = frozen_conf.TickStats(median_tick_bps=2 * h, disp_jns=None,
                                  futures_tick_bps=0.25)
    fit = prob.fit_mixture(x, bucket="A", tick_stats=stats)
    anchored += prob.FIT_ANCHORED_H in fit.flags
    errs.append(abs(fit.tau / (s * s / (2 * h)) - 1.0))
print(f"  h/s=1.0 n=400: anchored {anchored}/150 = {anchored / 150:.3f} "
      f"(test band 0.3-0.9), p90 tau err {float(np.quantile(errs, 0.90)):.3f} "
      f"(tolerance {prob.TAU_RECOVERY_TOLERANCE})")

# test_a_well_separated_bucket_ignores_the_anchor_and_keeps_its_own_mle
rng = np.random.default_rng(213)
h, s = 0.45, 0.18
stats = frozen_conf.TickStats(median_tick_bps=2 * h, disp_jns=None,
                              futures_tick_bps=0.25)
used = sum(prob.FIT_ANCHORED_H in prob.fit_mixture(
    prob.simulate(b0=0.0, h=h, s=s, n=400, rng=rng)[0],
    bucket="W", tick_stats=stats).flags for _ in range(60))
print(f"  h/s=2.5 n=400: anchored {used}/60 (test wants 0)")

# ...and at the separations in between, so the band is a measurement
for sep in (1.25, 1.5, 2.0):
    rng = np.random.default_rng(217)
    hh = sep * 0.18
    st = frozen_conf.TickStats(median_tick_bps=2 * hh, disp_jns=None,
                               futures_tick_bps=0.25)
    k = sum(prob.FIT_ANCHORED_H in prob.fit_mixture(
        prob.simulate(b0=0.0, h=hh, s=0.18, n=400, rng=rng)[0],
        bucket="M", tick_stats=st).flags for _ in range(60))
    print(f"  h/s={sep}: anchored {k}/60 = {k / 60:.3f}")
