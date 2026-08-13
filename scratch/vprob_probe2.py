"""Probe 2: the h_used_bps fixture, report column coverage, EM reachability."""
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

from SDRUtils.dealer_direction import probability as prob
from SDRUtils.stir_flow import confidence as frozen_conf

rng = np.random.default_rng

print("### A. a TICK-ANCHORED bucket: h from the lattice, s from a wide sample")
x, _ = prob.simulate(b0=-0.48, h=0.02, s=1.20, n=4000, rng=rng(3))
stats = frozen_conf.TickStats(median_tick_bps=0.04, disp_jns=None,
                              futures_tick_bps=0.25)
fit = prob.fit_mixture(x, bucket="ANCH", tick_stats=stats, min_n=0)
floor = prob._h_floor(fit.s)
print(f"    flags={fit.flags}")
print(f"    h={fit.h:.6g}  s={fit.s:.6g}  floor=0.05*s={floor:.6g}  "
      f"h<floor={fit.h < floor}")
row = prob.Calibration({"ANCH": fit}).report().iloc[0]
print(f"    report: separation={row['separation']:.4f} h_bps={row['h_bps']:.6g} "
      f"h_used_bps={row['h_used_bps']:.6g} tau={row['tau_bps']:.6g}")
print(f"    tau from RAW h = {row['s_bps']**2/(2*row['h_bps']):.6g}  "
      f"-> unfloored-report mutant IS distinguishable here: "
      f"{row['h_used_bps'] != row['h_bps']}")
print(f"    the shipped test's assertion on THIS row would be: "
      f"tau == s^2/(2*h_used) -> "
      f"{math.isclose(row['tau_bps'], row['s_bps']**2/(2*row['h_used_bps']), rel_tol=1e-9)}")

print("\n### B. report column coverage on a fit with every field populated")
xr, _ = prob.simulate(b0=0.0, h=0.45, s=0.18, n=4000, rng=rng(311))
rich = prob.fit_mixture(xr, bucket="RICH",
                        tick_stats=frozen_conf.TickStats(
                            median_tick_bps=0.9, disp_jns=0.5,
                            futures_tick_bps=0.25))
rep = prob.Calibration({"RICH": rich}).report()
nan_cols = [c for c in rep.columns if rep[c].isna().all()]
print(f"    columns={len(rep.columns)}  all-NaN columns={nan_cols}")
print(f"    flags={rich.flags}")

print("\n### C. is the EM label-swap branch reachable?")
mut = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vmut",
                   "probability_labelswap_poison.py")
spec = importlib.util.spec_from_file_location("prob_poison", mut)
pp = importlib.util.module_from_spec(spec)
sys.modules["prob_poison"] = pp
spec.loader.exec_module(pp)
hits = fails = 0
r = rng(7)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    for _ in range(2000):
        hh = float(10 ** r.uniform(-3, 0.5))
        ss = float(10 ** r.uniform(-2, 1))
        nn = int(r.integers(30, 1500))
        xx, _ = pp.simulate(b0=float(r.normal(0, 2)), h=hh, s=ss, n=nn, rng=r)
        if r.random() < 0.4:
            xx = np.concatenate([xx, r.standard_t(1.5, max(nn // 5, 2)) * ss * 20])
        try:
            pp.fit_mixture(xx, bucket="P", min_n=0)
        except AssertionError:
            hits += 1
        except Exception:
            fails += 1
print(f"    label-swap branch entered on {hits} of 2000 randomised fits "
      f"({fails} fits raised something else)")

print("\n### D. direct _em calls with a NEGATIVE-h start (is the guard live at all?)")
xd, _ = pp.simulate(b0=0.0, h=0.30, s=0.20, n=2000, rng=rng(21))
for h0 in (-0.3, -0.01):
    try:
        out = pp._em(xd, 0.0, h0, 0.20, 200, 1e-11)
        print(f"    h0={h0}: no swap, returned h={out[2]:.4g}/{out[1]:.4g}")
    except AssertionError:
        print(f"    h0={h0}: swap branch REACHED (so the guard is live for "
              f"negative starts -- fit_mixture just never supplies one)")
