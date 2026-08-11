"""Pin MIN_BUCKET_N on a statistic that is stable across seeds.

The p90 tau error at h/s = 1 is BIMODAL: most draws separate cleanly and a
minority refuse (tau forced to the no-information limit, ~20x). So the p90
sits exactly on the boundary between the two masses near n = 400, and it moved
0.319 -> 20.258 between two seeds. The refusal RATE is the underlying quantity
and it is smooth; the floor is where it becomes small.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils.dealer_direction import probability as prob

REPS = 500
rows = []
for sep in (0.75, 1.0, 1.25, 1.5):
    h, s = sep * 0.18, 0.18
    truth = s * s / (2 * h)
    for n in (200, 400, 600, 800, 1200, 1600):
        rng = np.random.default_rng(909)
        refuse, errs = 0, []
        for _ in range(REPS):
            x, _ = prob.simulate(b0=0.0, h=h, s=s, n=n, rng=rng)
            f = prob.fit_mixture(x, bucket="F", min_n=0)
            refuse += prob.FIT_UNSEPARATED in f.flags
            errs.append(abs(f.tau / truth - 1.0))
        e = np.asarray(errs)
        rows.append(dict(sep=sep, n=n, refusal=refuse / REPS,
                         p90_all=float(np.quantile(e, .90)),
                         p90_kept=float(np.quantile(e[e < 5], .90)) if (e < 5).any() else np.nan))
df = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print("refusal rate (FIT_UNSEPARATED):")
print(df.pivot(index="n", columns="sep", values="refusal").round(3).to_string())
print("\np90 over ALL draws:")
print(df.pivot(index="n", columns="sep", values="p90_all").round(3).to_string())
print("\np90 over the draws that did NOT refuse:")
print(df.pivot(index="n", columns="sep", values="p90_kept").round(3).to_string())
