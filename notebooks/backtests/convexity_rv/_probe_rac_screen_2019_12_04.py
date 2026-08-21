r"""Does `screen_frame` reproduce Citi's 2019-12-04 screen it was never fitted to?

`strat3_strikeless_vol.screen_frame` is tied out to Citi's Figure 7, close
2019-05-08, eight pairs. The 05-Dec-2019 note *Taking profits on delta-hedged
15y5y/20y10y flatteners* prints the SAME eight columns for all FIFTEEN pairs on a
different date -- 120 USD cells. If the machinery reproduces those, the
risk-adjusted-carry signal is trustworthy out of sample and workflow 4 can be
built straight on top of it.

Offline: the Citi curve store must serve 2019-12-04.
"""
from __future__ import annotations

import datetime as dt
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import RVUtils.ConvexityRV.strat3_strikeless_vol as S3  # noqa: E402
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402

ASOF = dt.date(2019, 12, 4)

# Citi Figure 1, close 12/4/2019, USD. Column order matches S3.PAIRS_15 exactly.
PUB = {
    "level_bp":     [-6.77, -7.97, -11.33, -14.90, -14.99, -18.83, -9.18, -12.54,
                     -16.11, -16.20, -20.04, -11.82, -15.65, -7.02, -10.85],
    "zs_1y":        [0.55, 0.68, 0.43, 0.46, 0.13, 0.37, 0.12, -0.91, -0.37,
                     -1.65, -0.42, -2.08, -0.54, -2.22, -0.89],
    "zs_3y":        [1.38, 1.48, 1.28, 1.28, 1.07, 1.20, 0.98, 0.70, 0.76, 0.52,
                     0.70, 0.38, 0.58, 0.02, 0.13],
    "zs_full":      [1.08, 1.03, 0.97, 0.95, 0.80, 0.80, 0.71, 0.64, 0.62, 0.49,
                     0.50, 0.27, 0.25, -0.33, -0.29],
    "carry_1y_bp":  [-3.19, -4.16, -3.95, -3.95, -3.73, -3.82, -2.30, -2.09,
                     -2.09, -1.87, -1.96, -0.77, -0.86, 0.43, 0.34],
    "be_daily":     [4.14, 4.62, 3.93, 3.54, 3.40, 3.16, 4.23, 3.33, 2.90, 2.70,
                     2.49, 1.98, 1.84, 0.00, 0.00],
    "rlzd_vol_bp":  [4.22, 4.23, 4.16, 4.17, 4.08, 4.13, 4.23, 4.16, 4.17, 4.08,
                     4.13, 4.08, 4.13, 4.08, 4.13],
    "be_over_rv":   [0.98, 1.09, 0.95, 0.85, 0.83, 0.77, 1.00, 0.80, 0.70, 0.66,
                     0.60, 0.49, 0.45, 0.00, 0.00],
}

# ---------------------------------------------------------------------------
# 0. Internal consistency of the PUBLISHED table -- check the answer key first
# ---------------------------------------------------------------------------
print("=== published table, self-consistency (no repo code involved) ===")
longs = [l for _s, l in S3.PAIRS_15]
by_long: dict[str, set] = {}
for lab, v in zip(longs, PUB["rlzd_vol_bp"]):
    by_long.setdefault(lab, set()).add(v)
bad = {k: v for k, v in by_long.items() if len(v) > 1}
print(f"  realized vol keyed on the LONG leg: "
      f"{'CONFIRMED' if not bad else f'VIOLATED {bad}'}  ({len(by_long)} distinct longs)")

ratio = np.array(PUB["be_daily"]) / np.array(PUB["rlzd_vol_bp"])
print(f"  be/rv recomputed vs printed: max abs diff {np.max(np.abs(ratio - PUB['be_over_rv'])):.4f}")
zero_be = [i for i, c in enumerate(PUB["carry_1y_bp"]) if c >= 0]
print(f"  BE is zero exactly where carry >= 0: "
      f"{all(PUB['be_daily'][i] == 0.0 for i in zero_be)}  (rows {zero_be})")

# ---------------------------------------------------------------------------
# 1. Our own screen on the same date
# ---------------------------------------------------------------------------
mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
pricer = mdp._get_curve(curve_name="USD-SOFR-1D", timestamp=ASOF)
print(f"\ncurve id={pricer.id()}  ref={pricer.reference_date()}")

hist_start = dt.date(2000, 1, 3)
lab_all = S3.leg_labels(S3.PAIRS_15)
print(f"legs needed: {len(lab_all)} -> {lab_all}")

scr = S3.screen_frame(pricer, S3.PAIRS_15, asof=ASOF)
print(f"\nscreen_frame returned {scr.shape}")
print(scr.columns.tolist())

cols = [("level_bp", "level_bp"), ("carry_1y_bp", "carry_1y_bp"),
        ("be_daily", "be_daily_analytic"), ("rlzd_vol_bp", "rlzd_vol_bp"),
        ("be_over_rv", "be_over_rv")]
out = pd.DataFrame({"pair": scr["pair"]})
for pub_key, col in cols:
    if col not in scr.columns:
        print(f"  MISSING COLUMN {col}")
        continue
    out[f"pub_{pub_key}"] = PUB[pub_key]
    out[f"our_{pub_key}"] = scr[col].to_numpy()
    out[f"d_{pub_key}"] = out[f"our_{pub_key}"] - out[f"pub_{pub_key}"]

pd.set_option("display.width", 250, "display.max_columns", 60)
print(out.to_string(index=False, float_format=lambda x: f"{x:8.3f}"))

print("\n=== summary ===")
for pub_key, col in cols:
    if f"d_{pub_key}" not in out:
        continue
    d = out[f"d_{pub_key}"].to_numpy(dtype=float)
    ok = np.isfinite(d)
    print(f"  {pub_key:14} n={ok.sum():2d}  mean {np.nanmean(d):+8.4f}  "
          f"median {np.nanmedian(d):+8.4f}  maxabs {np.nanmax(np.abs(d)):8.4f}  "
          f"corr {np.corrcoef(out[f'our_{pub_key}'][ok], out[f'pub_{pub_key}'][ok])[0, 1]:.4f}")
