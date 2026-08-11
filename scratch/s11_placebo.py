"""Is the 58.6% agreement in the full-termination band signal, or the shape of
the ratio distribution?

Placebo: keep every pair's repriced value |f| and its original-print inference,
but give it ANOTHER pair's fee-to-value ratio. The marginal distribution of
U/|f| is preserved exactly; only the pairing is destroyed. If the real number
sits inside the placebo distribution, the agreement is structural and the
measurement carries no information about direction.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import lineage as lin

out = pd.read_csv(r"C:/Users/chris/clee/ARBS-dd/scratch/out_direction_agreement.csv")
both = out.dropna(subset=["original_dealer_sign", "unwind_dealer_sign", "npv_pay", "ratio"])
both = both[both["orig_dev_bp"].abs() <= 25.0]
band = both[(both["ratio"] - 1).abs() <= 0.20].reset_index(drop=True)
print(f"on-market pairs {len(both)}   full-termination band {len(band)}")


def agreement_from(npv, ratio, orig):
    u = np.abs(npv) * ratio
    sign = np.array([lin.unwind_dealer_sign(f, x) for f, x in zip(npv, u)])
    called = (sign != 0) & (orig != 0)
    return float((sign[called] == -orig[called]).mean()), int(called.sum())


for name, d in (("ALL on-market", both), ("full-termination band", band)):
    npv = d["npv_pay"].to_numpy()
    ratio = d["ratio"].to_numpy()
    orig = d["original_dealer_sign"].to_numpy().astype(int)
    real, n = agreement_from(npv, ratio, orig)
    se = (real * (1 - real) / n) ** 0.5
    print(f"\n{name}: n={n}  agreement={real:.4f}  "
          f"95% CI [{real - 1.96 * se:.3f}, {real + 1.96 * se:.3f}]  "
          f"(coin flip inside CI: {real - 1.96 * se <= 0.5 <= real + 1.96 * se})")

    rng = np.random.default_rng(0)
    draws = []
    for _ in range(2000):
        draws.append(agreement_from(npv, rng.permutation(ratio), orig)[0])
    draws = np.array(draws)
    print(f"  placebo (ratio reshuffled, 2000 draws): mean={draws.mean():.4f} "
          f"sd={draws.std():.4f}  p5={np.percentile(draws, 5):.3f} "
          f"p95={np.percentile(draws, 95):.3f}")
    print(f"  real number's placebo percentile: {100 * (draws < real).mean():.1f}%")

# the mechanism behind the sub-50% overall number, stated as a testable claim:
# when U << |f| the rule degenerates to sign(mid_now - R), and the original's
# own call is sign(R - mid_exec) -- so a static curve forces DISAGREEMENT.
print("\n=== the partial-notional artifact, checked directly ===")
d = both.copy()
d["degenerate"] = d["ratio"] < 0.5
d["static_curve_forces_disagree"] = np.sign(d["orig_dev_bp"]) == np.sign(
    d["fixed_rate_pct"] - (d["orig_mid_pct"]))
for lab, sub in d.groupby("degenerate"):
    a = lin.direction_agreement(sub)
    print(f"  ratio<0.5 = {lab}: n={a['n_called']}  agreement={a['agreement']:.3f}")
