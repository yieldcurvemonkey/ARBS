"""VERIFY the measured claims the FIX added to the docstrings.

The fix justifies keeping LN_SIGMA_MAX = 6 as "the one bound allowed to bind"
with a specific measurement, and re-pins the KS test's bounds. Both are
checkable from the shipped table plus the offline frequency cache.

Claims under test:
  A. shipped table: 7 lognormal / 9 Pareto / 2 ties, worst gap 0.035,
     KS range 0.0698-0.2861 (test asserts >= 0.069 and <= 0.287)
  B. ln_degenerate == _ln_on_box_wall(mu, sigma, u, C) for all 18, 5 True
  C. V1 5y-10y at LN_SIGMA_MAX = 12: optimum (mu ~ -82.7, sigma ~ 9.15),
     multiplier 4.218 -> 4.804, better by ~0.45 of nll out of 779,525
  D. control cell V1 2y-5y "does not move by a digit" under the same test
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from SDRUtils.dealer_direction import imputation as imp  # noqa: E402

print("=== A. the KS/family claims, read off the shipped table")
ks_ln = [b.ks_lognormal for b in imp.CAP_BANDS]
ks_pa = [b.ks_pareto for b in imp.CAP_BANDS]
wins_ln = sum(a < b for a, b in zip(ks_ln, ks_pa))
wins_pa = sum(b < a for a, b in zip(ks_ln, ks_pa))
print(f"  lognormal wins {wins_ln}, pareto wins {wins_pa}, ties "
      f"{18 - wins_ln - wins_pa}   (docstring: 7 / 9 / 2)")
print(f"  KS lognormal range {min(ks_ln):.4f}-{max(ks_ln):.4f}; "
      f"pareto {min(ks_pa):.4f}-{max(ks_pa):.4f}   (test bound <= 0.287)")
print(f"  worst |gap| {max(abs(a - b) for a, b in zip(ks_ln, ks_pa)):.4f}   "
      f"(test bound < 0.036, docstring 0.035)")
print(f"  headroom on the test's upper KS bound: "
      f"{0.287 - max(max(ks_ln), max(ks_pa)):.4f}")

print("\n=== B. the detector reproduces every shipped ln_degenerate")
bad = 0
for b in imp.CAP_BANDS:
    u = b.cap / imp.THRESHOLD_DIVISOR
    got = imp._ln_on_box_wall(b.ln_mu, b.ln_sigma, u, b.cap)
    bad += got != b.ln_degenerate
    if got != b.ln_degenerate:
        print(f"  MISMATCH {b.vintage} {b.label}: detector {got} table {b.ln_degenerate}")
print(f"  mismatches {bad}; flagged cells "
      f"{[b.vintage + ' ' + b.label for b in imp.CAP_BANDS if b.ln_degenerate]}")

f = pd.read_csv(os.path.join(HERE, "partB_freq_cache.csv")).dropna(subset=["cell"])
m = f["cell"].str.split("|", expand=True)
f["vintage"], f["lo"], f["cap"] = m[0], m[1].astype(float), m[3].astype(float)
for c in ("notional", "n"):
    f[c] = f[c].astype(float)


def one_cell(vintage, lo, sigma_max):
    g = f[(f["vintage"] == vintage) & (f["lo"] == lo)]
    C = float(g["cap"].iloc[0])
    u = C / imp.THRESHOLD_DIVISOR
    cap_rows = g[g["is_capped"]]
    n_cap = float(cap_rows.loc[cap_rows["notional"] == C, "n"].sum())
    sub = g[~g["is_capped"]]
    x, w = sub["notional"].to_numpy(float), sub["n"].to_numpy(float)
    keep = (x >= u) & (x < C)
    x, w = x[keep], w[keep]
    old = imp.LN_SIGMA_MAX
    imp.LN_SIGMA_MAX = sigma_max
    try:
        mu, sg = imp.lognormal_censored_mle(x, w, u, C, n_cap)
        S = imp._suffstats(np.log(x), w)
        nll = imp._ln_negll([mu, np.log(sg)], S, np.log(u), np.log(C), n_cap)
        mult = imp.lognormal_mean_above(mu, sg, C) / C
    finally:
        imp.LN_SIGMA_MAX = old
    return mu, sg, mult, nll


for tag, vintage, lo, note in (
        ("C. V1 5y-10y (the worst pinned cell)", "V1", 5.25,
         "docstring: mu -82.7, sigma 9.15, mult 4.218 -> 4.804, 0.45 of 779,525"),
        ("D. V1 2y-5y (interior control)", "V1", 2.25,
         "docstring: does not move by a digit")):
    print(f"\n=== {tag}\n  {note}")
    for sm in (6.0, 12.0):
        mu, sg, mult, nll = one_cell(vintage, lo, sm)
        print(f"  LN_SIGMA_MAX={sm:5.1f}  mu {mu:10.3f}  sigma {sg:7.4f}  "
              f"mult {mult:7.4f}  nll {nll:.4f}")
