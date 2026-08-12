"""Review probe: does a PARENT-bucket h earn FIT_ANCHORED_H and the 400 floor?"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import probability as prob

rng = np.random.default_rng(5)
parts = []
# a big, well separated parent level (rate_index=SOFR) plus a thin child band
for tb, n in [("1Y-2Y", 6000), ("2Y-3Y", 6000), ("30Y+", 450)]:
    x, _ = prob.simulate(b0=0.0, h=0.20, s=0.20, n=n, rng=rng)
    parts.append(prob.frame(x, venue="D2C", rate_index="SOFR",
                            structure="OUTRIGHT", tenor_band=tb))
df = pd.concat(parts, ignore_index=True)
cal = prob.Calibration.fit(df)

for label, f in sorted(cal.fits.items()):
    if "30Y+" in label or label == prob.GLOBAL_BUCKET or label.count("|") <= 1:
        print(f"  n={f.n:6d} min_n_req={f.min_n_required:4d} h={f.h:.4f} s={f.s:.4f} "
              f"tau={f.tau:7.3f} [{','.join(f.flags)}]  {label}")

key = prob.BucketKey("D2C", "SOFR", "OUTRIGHT", "STANDARD", "30Y+")
got = cal.for_key(key)
print(f"\n  for_key(30Y+) -> bucket={got.bucket!r} pooled_from={got.pooled_from!r} "
      f"n={got.n} min_n_req={got.min_n_required} flags={got.flags}")

exotic = prob.BucketKey("D2D", "FED_FUNDS", "FLY", "FOMC", "20Y-30Y")
ex = cal.for_key(exotic)
print(f"  for_key(exotic) -> bucket={ex.bucket!r} pooled_from={ex.pooled_from!r} "
      f"flags={ex.flags}   (test only asserts bucket==GLOBAL or POOLED in flags)")
