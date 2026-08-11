"""Point probes behind the verification table. Read-only."""
from __future__ import annotations

import importlib.util
import math
import os
import sys
import warnings

os.environ["ARBS_SUPABASE_ENABLED"] = "0"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import probability as prob
from SDRUtils.stir_flow import confidence as frozen_conf


def rng(seed):
    return np.random.default_rng(seed)


print("### 1. constants")
for k in ("MIN_SEPARATION", "TAU_RECOVERY_TOLERANCE", "MAX_SE_LOG_TAU",
          "MEASURED_MIN_BUCKET_N", "MIN_BUCKET_N", "MEASURED_MIN_BUCKET_N_ANCHORED",
          "MIN_BUCKET_N_ANCHORED", "TRIM_MAD_K", "MAD_TO_SIGMA",
          "LEPTOKURTOSIS_Z", "SEPARATION_ALPHA", "DEAD_ZONE_DELTA"):
    print(f"    {k} = {getattr(prob, k)}")
print(f"    0.25/1.2816 = {0.25/1.2816:.6f}   0.25/1.6449 = {0.25/1.6449:.6f}")

print("\n### 2. the report test's fixture -- is h really below the floor?")
x = rng(29).normal(0.0, 0.2, 3000)
fit = prob.fit_mixture(x, bucket="FLAT", min_n=0)
floor = prob._h_floor(fit.s)
print(f"    flags={fit.flags}")
print(f"    h={fit.h!r} floor={floor!r} h<floor={fit.h < floor} h==floor={fit.h == floor}")
print(f"    h_used=max => {max(float(fit.h), floor)!r}; unfloored h would give "
      f"tau={fit.s**2/(2*fit.h):.6f} vs reported tau={fit.tau:.6f}")

print("\n### 3. a bucket whose h is STRICTLY below the floor (the review's SOFR|2Y shape)")
found = None
for seed in range(40):
    r = rng(1000 + seed)
    xx, _ = prob.simulate(b0=0.0, h=0.002, s=0.30, n=3000, rng=r)
    f = prob.fit_mixture(xx, bucket="TINYH", min_n=0)
    if f.h < prob._h_floor(f.s) and f.h > 0:
        found = f
        break
print(f"    found={found is not None}")
if found is not None:
    cal = prob.Calibration({"TINYH": found})
    row = cal.report().iloc[0]
    print(f"    separation={row['separation']:.6f} h_bps={row['h_bps']:.6g} "
          f"h_used_bps={row['h_used_bps']:.6g} tau={row['tau_bps']:.6g} flags={row['fit_flags']}")
    print(f"    tau from RAW h would be {row['s_bps']**2/(2*row['h_bps']):.6g} "
          f"-- the unfloored-report mutant is distinguishable here: "
          f"{row['h_used_bps'] != row['h_bps']}")

print("\n### 4. REPORT_COLUMNS covers every key the report builds")
cal = prob.Calibration({"A": fit})
rep = cal.report()
print(f"    n_cols={len(rep.columns)} REPORT_COLUMNS={len(prob.REPORT_COLUMNS)}")
print(f"    all-NaN columns (a dropped key shows up here): "
      f"{[c for c in rep.columns if rep[c].isna().all()]}")
print(f"    columns match: {list(rep.columns) == list(prob.REPORT_COLUMNS)}")

print("\n### 5. rolling_calibrations on an EMPTY frame / no candidate dates")
empty = prob.frame(np.array([]), venue="D2C", rate_index="SOFR",
                   structure="OUTRIGHT", tenor_band="2Y-3Y")
empty["as_of_date"] = pd.Series([], dtype="object")
try:
    prob.rolling_calibrations(empty)
    print("    returned normally (!)")
except Exception as e:
    print(f"    {type(e).__name__}: {str(e)[:160]}")

print("\n### 6. anchored fraction at h/s = 1, n = 400 -- would the OLD band still hold?")
n, s = 400, 0.20
h = 1.0 * s
stats = frozen_conf.TickStats(median_tick_bps=2 * h, disp_jns=None,
                              futures_tick_bps=0.25)
r = rng(4242)
anchored = 0
for _ in range(150):
    xx, _ = prob.simulate(b0=0.0, h=h, s=s, n=n, rng=r)
    f = prob.fit_mixture(xx, bucket="A", tick_stats=stats, min_n=prob.MIN_BUCKET_N_ANCHORED)
    anchored += prob.FIT_ANCHORED_H in f.flags
frac = anchored / 150
print(f"    anchored fraction = {frac:.3f}; old assertion 0.3<x<0.9 -> {0.3 < frac < 0.9}")

print("\n### 7. the FIT_IMPRECISE cell: se_log_tau vs the gate")
xx, _ = prob.simulate(b0=0.02, h=0.15, s=0.30, n=20_000, rng=rng(11))
f = prob.fit_mixture(xx, bucket="SIM")
print(f"    se_log_tau={f.se_log_tau:.6f} gate={prob.MAX_SE_LOG_TAU:.6f} "
      f"old_gate={0.25/1.2816:.6f} flags={f.flags}")

print("\n### 8. is the EM label-swap branch reachable? (poisoned module, 2000 fits)")
mut = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vmut",
                   "probability_labelswap_poison.py")
spec = importlib.util.spec_from_file_location("prob_poison", mut)
pp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pp)
hits = 0
r = rng(7)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    for i in range(2000):
        hh = float(10 ** r.uniform(-3, 0.5))
        ss = float(10 ** r.uniform(-2, 1))
        nn = int(r.integers(30, 1500))
        xx, _ = pp.simulate(b0=float(r.normal(0, 2)), h=hh, s=ss, n=nn, rng=r)
        if r.random() < 0.4:                      # contaminate / skew
            xx = np.concatenate([xx, r.standard_t(1.5, nn // 5) * ss * 20])
        try:
            pp.fit_mixture(xx, bucket="P", min_n=0)
        except AssertionError:
            hits += 1
        except Exception:
            pass
print(f"    label-swap branch entered on {hits} of 2000 randomised fits")
