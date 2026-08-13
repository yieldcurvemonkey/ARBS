"""Stage 6b - is the +0.02 bp median distinguishable from zero?

A median of +0.021 bp inside an IQR 0.27 bp wide looks like zero, but "looks
like" is not a measurement. Two tests that do not assume a distribution:

  * a bootstrap confidence interval on the median (25,000 resamples, fixed seed
    and a positional draw over a stable row order - the CSV is written once and
    read in file order, so the seed actually reproduces);
  * a sign test on the count above mid, which is the statistic the direction
    call actually consumes. If prints straddle mid evenly, the share above mid
    is 50 %, and a convention bias shows up here before it shows up in a median.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

CSV = "C:/Users/chris/clee/ARBS-dd/scratch/out_bias200.csv"


def main() -> None:
    df = pd.read_csv(CSV)
    d = df["diff_bp"].dropna().to_numpy()
    n = len(d)
    print(f"n = {n}")
    print(f"median          {np.median(d):+.4f} bp")
    print(f"mean            {d.mean():+.4f} bp   (sd {d.std(ddof=1):.4f})")
    print(f"trimmed mean 10% {stats.trim_mean(d, 0.1):+.4f} bp")

    rng = np.random.default_rng(20260811)
    boot = np.median(rng.choice(d, size=(25_000, n), replace=True), axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f"bootstrap 95% CI on the median: [{lo:+.4f}, {hi:+.4f}] bp "
          f"-> {'INCLUDES zero' if lo <= 0 <= hi else 'EXCLUDES zero'}")

    n_pos = int((d > 0).sum())
    p = stats.binomtest(n_pos, n, 0.5).pvalue
    print(f"sign test: {n_pos}/{n} above mid ({n_pos/n:.1%}), "
          f"two-sided p = {p:.3f} -> "
          f"{'not distinguishable from a fair straddle' if p > 0.05 else 'SKEWED'}")

    w = stats.wilcoxon(d).pvalue
    print(f"Wilcoxon signed-rank vs 0: p = {w:.3f}")

    # How big would a bias have to be to matter? Anything inside the band where
    # prints actually sit is a band where the SIGN flips.
    for band in (0.02, 0.05, 0.10, 0.25):
        print(f"  prints within +/-{band:.2f} bp of mid: {(np.abs(d) <= band).mean():5.1%} "
              f"- a median offset of {band:.2f} bp would re-sign roughly half of them")


if __name__ == "__main__":
    main()
