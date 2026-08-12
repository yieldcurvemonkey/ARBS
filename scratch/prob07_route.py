"""Which routing rule? se-only vs (se OR n below the unanchored floor).

The se-only rule leaves a post-selection hole: at n below MIN_BUCKET_N a fit
that LOOKS precise can be a lucky draw, and the observed information does not
know it was selected. Measured here on both rules, at a perfect anchor and at
a 25%-low one (the direction that hurts).
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

REPS = 250


def run(n, sep, anchor_mult, force_anchor_below_floor):
    h, s = sep * 0.18, 0.18
    truth = s * s / (2 * h)
    rng = np.random.default_rng(303)
    errs, used = [], 0
    for _ in range(REPS):
        x, _ = prob.simulate(b0=0.0, h=h, s=s, n=n, rng=rng)
        xt = x[prob.trim_mask(x)]
        f = prob.fit_mixture(x, bucket="R")
        anchor = anchor_mult * h
        # `se_log_tau is None` is how the fit reports "I did not stand on my
        # own"; FIT_IMPRECISE is "I did, but not tightly enough".
        take = (f.se_log_tau is None) or (prob.FIT_IMPRECISE in f.flags)
        if force_anchor_below_floor and xt.size < prob.MIN_BUCKET_N:
            take = True
        if take:
            b0, hh, ss, _ = prob._anchored_decomposition(xt, anchor)
            tau = ss * ss / (2 * hh)
            used += 1
        else:
            tau = f.tau
        errs.append(abs(tau / truth - 1.0))
    return float(np.quantile(errs, 0.90)), used / REPS


rows = []
for sep in (0.75, 1.0, 1.5, 2.5):
    for n in (200, 400, 800):
        for mult, mtag in ((1.0, "exact"), (0.75, "25% low")):
            for force, ftag in ((False, "se-only"), (True, "se-or-floor")):
                p90, frac = run(n, sep, mult, force)
                rows.append(dict(sep=sep, n=n, anchor=mtag, rule=ftag,
                                 p90=round(p90, 3), anchored_frac=round(frac, 2)))
df = pd.DataFrame(rows)
pd.set_option("display.width", 220)
print(df.pivot_table(index=["sep", "n"], columns=["anchor", "rule"],
                     values="p90").round(3).to_string())
print()
print(df.pivot_table(index=["sep", "n"], columns=["anchor", "rule"],
                     values="anchored_frac").round(2).to_string())
