"""End-to-end Calibration on the real legacy frame, and does tau actually move?

SHAPE EXERCISE (biased Barchart curve -- see prob01). What is being tested here
is the machinery at real scale and real bucket cardinality, not the numbers.
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
pd.set_option("display.width", 230)

df = pd.read_parquet(os.path.join(HERE, "prob01_devs.parquet"))
df = df.rename(columns={"spread_to_mid_bps": prob.DEVIATION_COL,
                        "rate_index_clean": "rate_index",
                        "trade_type": "structure"})
df["venue_class"] = "D2C"
tb = df.tenor_bucket.astype(str)
df["special_tenor_type"] = np.where(tb.str.startswith("FOMC_"), "FOMC",
                                    np.where(tb.str.startswith("IMM_"), "IMM",
                                             "STANDARD"))
df["tenor_band"] = tb.str.replace(r"^(FOMC_|IMM_)", "", regex=True)
df["as_of_date"] = pd.to_datetime(df.as_of_date).dt.date
print(f"rows {len(df):,}  full-key buckets "
      f"{df.groupby(list(prob.BUCKET_COLS)).ngroups}")

import pickle, time
CACHE = os.path.join(HERE, "prob10_cal.pkl")
if os.path.exists(CACHE):
    cal = pickle.load(open(CACHE, "rb"))
    print(f"Calibration: {len(cal.fits)} fits (cached)")
else:
    t0 = time.perf_counter()
    cal = prob.Calibration.fit(df)
    print(f"Calibration.fit: {len(cal.fits)} fits in {time.perf_counter()-t0:.1f}s")
    pickle.dump(cal, open(CACHE, "wb"))

rep = cal.report()
print("\nflag census across all fitted buckets:")
print(rep.fit_flags.value_counts().head(12).to_string())
print("\nlargest 12 buckets:")
cols = ["bucket", "n_trimmed", "b0_bps", "h_bps", "s_bps", "tau_bps",
        "dead_zone_bps", "excess_kurtosis_z", "fit_flags"]
print(rep.sort_values("n_trimmed", ascending=False)[cols].head(12)
      .round(3).to_string(index=False))

print("\n=== pooling: what actually serves each full key ===")
keys = df.groupby(list(prob.BUCKET_COLS)).size().sort_values(ascending=False)
served = []
for k, n in keys.items():
    f = cal.for_key(prob.BucketKey(*k))
    served.append(dict(n=n, pooled=f.pooled_from is not None,
                       donor=f.pooled_from or "self", tau=f.tau))
s = pd.DataFrame(served)
print(f"{len(s)} keys; pooled {s.pooled.mean():.1%}; "
      f"share of PRINTS served by their own bucket "
      f"{s.loc[~s.pooled, 'n'].sum() / s.n.sum():.1%}")

print("\n=== 5. TIME VARIATION: does tau move? ===")
big = df[(df.rate_index == "SOFR") & (df.tenor_band == "2Y")
         & (df.special_tenor_type == "STANDARD")]
big = big.assign(month=pd.to_datetime(big.as_of_date).dt.to_period("M"))
fits = []
for m, g in big.groupby("month"):
    if len(g) < 300:
        continue
    f = prob.fit_mixture(g[prob.DEVIATION_COL].to_numpy(), bucket=str(m))
    fits.append(f)
    print(f"  {m}  n={f.n_trimmed:5d}  b0={f.b0:+.3f}  h={f.h:.4f} "
          f"s={f.s:.3f}  tau={f.tau:8.3f}  se={f.se_log_tau}  "
          f"{','.join(x for x in f.flags if x != prob.FIT_OK)}")
usable = [f for f in fits if f.se_log_tau]
print(f"fits with a usable standard error: {len(usable)}/{len(fits)}")
if len(usable) >= 2:
    print(prob.tau_stability(usable))
else:
    print("tau_stability cannot run: the legacy curve refuses every month, so "
          "no month has a standard error. Reported, not worked around.")
    taus = np.array([f.tau for f in fits])
    print(f"  raw tau spread across months: min {taus.min():.3f} "
          f"max {taus.max():.3f} ratio {taus.max()/taus.min():.2f}")
    b0s = np.array([f.b0 for f in fits])
    print(f"  b0 across months: min {b0s.min():+.3f} max {b0s.max():+.3f} "
          f"range {b0s.max()-b0s.min():.3f} bp")

print("\n=== rolling calibration, no lookahead ===")
sub = df[df.rate_index == "SOFR"]
w = prob.rolling_calibrations(sub, window_days=45, min_gap_days=1, step_days=20)
print(f"{len(w)} calibration dates")
for as_of, (lo, hi, c) in list(w.items())[:4]:
    assert hi < as_of
    print(f"  classify {as_of}: window [{lo} .. {hi}]  {len(c.fits)} fits")
