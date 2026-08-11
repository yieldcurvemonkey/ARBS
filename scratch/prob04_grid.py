"""The measurement MIN_BUCKET_N is set from.

Recovery of ``tau`` across (sample size x separation h/s), and the pooling-order
ranking. Prints; writes CSVs next to itself.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils.dealer_direction import probability as prob

HERE = os.path.dirname(os.path.abspath(__file__))
pd.set_option("display.width", 200)

print("=== recovery grid: p90 |tau_hat/tau - 1| ===")
g = prob.recovery_grid(reps=150, seed=17)
g.to_csv(os.path.join(HERE, "prob04_recovery_grid.csv"), index=False)
piv90 = g.pivot(index="n", columns="separation", values="p90_rel_err")
piv50 = g.pivot(index="n", columns="separation", values="p50_rel_err")
print("\np90:\n" + piv90.round(3).to_string())
print("\np50:\n" + piv50.round(3).to_string())

tol = prob.TAU_RECOVERY_TOLERANCE
print(f"\ntolerance = {tol}")
for sep in piv90.columns:
    col = piv90[sep]
    ok = col[col <= tol]
    print(f"  separation h/s={sep}: smallest n inside tolerance = "
          f"{int(ok.index.min()) if len(ok) else 'none in grid'}")

print("\n=== pooling-order ranking on the LEGACY deviations (shape exercise) ===")
df = pd.read_parquet(os.path.join(HERE, "prob01_devs.parquet"))
df = df.rename(columns={"spread_to_mid_bps": prob.DEVIATION_COL,
                        "rate_index_clean": "rate_index",
                        "trade_type": "structure"})
df["venue_class"] = "D2C"          # the legacy universe is D2C-only by filter
df["special_tenor_type"] = np.where(
    df.tenor_bucket.astype(str).str.startswith("FOMC_"), "FOMC",
    np.where(df.tenor_bucket.astype(str).str.startswith("IMM_"), "IMM", "STANDARD"))
df["tenor_band"] = df.tenor_bucket.astype(str)
print(prob.rank_bucket_dimensions(df).to_string(index=False))
