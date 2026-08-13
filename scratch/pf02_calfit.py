"""Fix probe 2: make the parent-anchor route fire through Calibration.fit.

The leaf's immediate parent is the venue-dropped bucket (DEFAULT_POOLING_ORDER
drops venue_class first), so a frame with a big wide-spread D2C population and a
thin narrow-spread D2D population puts a 0.20 anchor on a child whose true h is
0.07.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import probability as prob


def build(n_child):
    rng = np.random.default_rng(5)
    parts = []
    x, _ = prob.simulate(b0=0.0, h=0.20, s=0.20, n=6000, rng=rng)
    parts.append(prob.frame(x, venue="D2C", rate_index="SOFR",
                            structure="OUTRIGHT", tenor_band="30Y+"))
    x, _ = prob.simulate(b0=0.0, h=0.07, s=0.20, n=n_child, rng=rng)
    parts.append(prob.frame(x, venue="D2D", rate_index="SOFR",
                            structure="OUTRIGHT", tenor_band="30Y+"))
    return pd.concat(parts, ignore_index=True)


for n_child in (450, 2000):
    cal = prob.Calibration.fit(build(n_child))
    key = prob.BucketKey("D2D", "SOFR", "OUTRIGHT", "STANDARD", "30Y+")
    leaf = cal.fits[key.label()]
    truth = 0.20 ** 2 / (2 * 0.07)
    print(f"n_child={n_child}")
    print(f"  leaf   n={leaf.n} min_n_req={leaf.min_n_required} h={leaf.h:.4f} "
          f"s={leaf.s:.4f} tau={leaf.tau:.4f} (truth {truth:.4f}) [{','.join(leaf.flags)}]")
    served = cal.for_key(key)
    print(f"  served bucket={served.bucket!r} pooled_from={served.pooled_from!r} "
          f"tau={served.tau:.4f} [{','.join(served.flags)}]")
    for lab in sorted(cal.fits):
        f = cal.fits[lab]
        if lab.count("|") >= 3:
            print(f"     {lab:70s} n={f.n:5d} h={f.h:.4f} tau={f.tau:8.4f} "
                  f"[{','.join(f.flags)}]")
