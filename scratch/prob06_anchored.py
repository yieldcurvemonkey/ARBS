"""Sets MIN_BUCKET_N_ANCHORED, and quantifies what the anchor is worth.

The unanchored grid (prob04) shows the mixture is not identifiable below
h/s ~ 1 at any tape-realistic n. This measures the same recovery when `h` is
supplied from outside, which is the whole reason the tick cross-check exists.

Two regimes are measured separately, because they are different claims:
  * PERFECT anchor  -- h is exactly right. Isolates the sample-size question.
  * BIASED anchor   -- h is 25% wrong, which is what a tick/2 proxy plausibly
                       is. Shows what a wrong anchor costs, so the tolerance in
                       crosscheck_against_tick can be defended.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils.dealer_direction import probability as prob
from SDRUtils.stir_flow.confidence import TickStats

pd.set_option("display.width", 200)
REPS = 200


def anchored_error(n, h, s, anchor_mult=1.0, reps=REPS, seed=17, q=0.90):
    rng = np.random.default_rng(seed)
    truth = s * s / (2 * h)
    errs = []
    for _ in range(reps):
        x, _ = prob.simulate(b0=0.0, h=h, s=s, n=n, rng=rng)
        # Force the anchored branch by handing the fit a tick, and make the
        # unanchored MLE irrelevant by driving the bucket through the
        # separation gate the same way a real thin bucket would be.
        b0, hh, ss, _flags = prob._anchored_decomposition(
            x[prob.trim_mask(x)], anchor_mult * h)
        errs.append(abs((ss * ss / (2 * hh)) / truth - 1.0))
    return float(np.quantile(errs, q))


for mult, tag in ((1.0, "PERFECT anchor"), (1.25, "anchor 25% HIGH"),
                  (0.75, "anchor 25% LOW")):
    print(f"\n=== {tag}: p90 |tau_hat/tau - 1| ===")
    rows = []
    for sep in (0.5, 0.75, 1.0, 1.5, 2.5):
        r = {"h/s": sep}
        for n in (50, 100, 200, 400, 800, 1600):
            r[n] = anchored_error(n, sep * 0.18, 0.18, anchor_mult=mult)
        rows.append(r)
    print(pd.DataFrame(rows).set_index("h/s").round(3).to_string())

print("\n=== end-to-end through fit_mixture, tick supplied ===")
rng = np.random.default_rng(5)
for sep in (0.5, 1.0):
    h, s = sep * 0.18, 0.18
    for n in (200, 400, 800):
        errs = []
        for _ in range(120):
            x, _ = prob.simulate(b0=0.0, h=h, s=s, n=n, rng=rng)
            f = prob.fit_mixture(x, bucket="A", tick_stats=TickStats(
                median_tick_bps=2 * h, disp_jns=None, futures_tick_bps=0.25))
            errs.append(abs(f.tau / (s * s / (2 * h)) - 1.0))
        print(f"  h/s={sep} n={n:5d}  p90={np.quantile(errs, .90):.3f} "
              f"p50={np.quantile(errs, .50):.3f}")
