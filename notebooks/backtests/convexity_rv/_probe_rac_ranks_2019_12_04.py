r"""Does the RAC screen reproduce Citi's 2019-12-04 RANK ORDER and its ratio?

The level offset is a known, documented property of this curve:
``test_citi_figure_7_levels_and_carry`` records "every level is uniformly ~0.8bp
more negative than Citi's ... on a SOFR curve this repo rebuilds from banked par
rates while Citi quoted its own. What matters is that the RANK ORDER is exact."

My 2019-12-04 measurement returned -0.81bp on levels -- the same offset, seven
months later and on fifteen pairs instead of eight, which is evidence it is a
stable curve-construction difference rather than an error. This probe tests the
thing the existing convention says actually matters, and builds the two columns
the first probe left NaN: 1y realized vol of the LONG forward rate, and the
BE/vol ratio that is the screen's decision statistic.

Workflow 4 turns on the ratio, and Citi publishes ABSOLUTE thresholds for it
(exit ~0.8, steepener >1.0). If our BE is systematically low, a fixed threshold
misfires -- so the question is whether to trade the level or the rank.
"""
from __future__ import annotations

import datetime as dt
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

import RVUtils.ConvexityRV.strat3_strikeless_vol as S3  # noqa: E402
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402

ASOF = dt.date(2019, 12, 4)
HIST_START = dt.date(2018, 11, 1)

PUB_CARRY = [-3.19, -4.16, -3.95, -3.95, -3.73, -3.82, -2.30, -2.09, -2.09,
             -1.87, -1.96, -0.77, -0.86, 0.43, 0.34]
PUB_BE = [4.14, 4.62, 3.93, 3.54, 3.40, 3.16, 4.23, 3.33, 2.90, 2.70, 2.49,
          1.98, 1.84, 0.00, 0.00]
PUB_RV = [4.22, 4.23, 4.16, 4.17, 4.08, 4.13, 4.23, 4.16, 4.17, 4.08, 4.13,
          4.08, 4.13, 4.08, 4.13]
PUB_RATIO = [0.98, 1.09, 0.95, 0.85, 0.83, 0.77, 1.00, 0.80, 0.70, 0.66, 0.60,
             0.49, 0.45, 0.00, 0.00]
PUB_LEVEL = [-6.77, -7.97, -11.33, -14.90, -14.99, -18.83, -9.18, -12.54,
             -16.11, -16.20, -20.04, -11.82, -15.65, -7.02, -10.85]

mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
pricer = mdp._get_curve(curve_name="USD-SOFR-1D", timestamp=ASOF)
scr = S3.screen_frame(pricer, S3.PAIRS_15, asof=ASOF)

# ---------------------------------------------------------------------------
# 1. Rank order -- the thing the existing convention says is the output
# ---------------------------------------------------------------------------
print("=== rank order, 15 pairs ===")
for name, ours, pub in (
    ("level_bp", scr["level_bp"].to_numpy(), np.array(PUB_LEVEL)),
    ("carry_1y_bp", scr["carry_1y_bp"].to_numpy(), np.array(PUB_CARRY)),
    ("be_daily", scr["be_daily_analytic"].to_numpy(), np.array(PUB_BE)),
):
    rho = spearmanr(ours, pub).statistic
    pear = np.corrcoef(ours, pub)[0, 1]
    off = float(np.mean(ours - pub))
    resid = (ours - pub) - off
    print(f"  {name:14} spearman {rho:6.4f}  pearson {pear:6.4f}  "
          f"offset {off:+7.3f}  resid sd after removing it {resid.std(ddof=1):6.3f}")

# ---------------------------------------------------------------------------
# 2. Build the realized vol the screen needs, on the LONG leg
# ---------------------------------------------------------------------------
longs = sorted({l for _s, l in S3.PAIRS_15})
print(f"\nbuilding {len(longs)} long-leg rate histories {HIST_START} .. {ASOF}")

dates = [d.date() for d in pd.bdate_range(HIST_START, ASOF)]
recs, failed = [], 0
for d in dates:
    try:
        px = mdp._get_curve(curve_name="USD-SOFR-1D", timestamp=d)
    except Exception:
        failed += 1
        continue
    row = {"date": pd.Timestamp(d)}
    for lab in longs:
        try:
            row[lab] = S3.leg_metrics(px, lab)["rate_bp"]
        except Exception:
            row[lab] = np.nan
    recs.append(row)

hist = pd.DataFrame(recs).set_index("date").sort_index()
print(f"  {len(hist)} dates built, {failed} unavailable, "
      f"NaN cells {int(hist.isna().sum().sum())}")

win = hist.loc[hist.index > pd.Timestamp(ASOF) - pd.DateOffset(years=1)]
rv = win.diff().std(ddof=1)
print("\n1y realized vol of the LONG forward rate, bp/day")
print(pd.DataFrame({"ours": rv.round(3),
                    "citi": pd.Series(dict(zip([l for _s, l in S3.PAIRS_15], PUB_RV)))
                    }).to_string())

# ---------------------------------------------------------------------------
# 3. The decision statistic
# ---------------------------------------------------------------------------
our_rv = np.array([rv[l] for _s, l in S3.PAIRS_15])
our_ratio = scr["be_daily_analytic"].to_numpy() / our_rv
pub_ratio = np.array(PUB_RATIO)

print("\n=== be_over_rv, the decision statistic ===")
out = pd.DataFrame({
    "pair": scr["pair"], "our_be": scr["be_daily_analytic"].round(3),
    "our_rv": our_rv.round(3), "our_ratio": our_ratio.round(3),
    "citi_ratio": pub_ratio, "diff": (our_ratio - pub_ratio).round(3),
})
print(out.to_string(index=False))
print(f"\n  spearman {spearmanr(our_ratio, pub_ratio).statistic:.4f}   "
      f"pearson {np.corrcoef(our_ratio, pub_ratio)[0, 1]:.4f}   "
      f"mean offset {np.mean(our_ratio - pub_ratio):+.3f}")

# What Citi's own decision would have been, on each set of numbers
print("\n=== the decision the screen exists to make ===")
for label, r in (("Citi", pub_ratio), ("ours", our_ratio)):
    cheap3 = [scr['pair'].iloc[i] for i in np.argsort(r)[:3]]
    print(f"  {label:5} three cheapest (lowest ratio): {cheap3}")
print("  Citi marks the three most attractive by each metric in red.")
