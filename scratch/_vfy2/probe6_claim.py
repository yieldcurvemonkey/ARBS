"""Adversarial stress on the fix's headline claim.

`classify`'s new docstring asserts that where `dealer_sign` and `signed_weight`
disagree the row is always FLAG_SIGN_FRAGILE, measured on a 282,240-point grid
of sigma 0.05-1.0 and tau 0.5-11. Those are the ranges the tests parametrise
too, so the claim and its evidence share a domain. This searches OUTSIDE it --
tau down to 1e-3, sigma down to 1e-4, both populations, near-tie deviations --
because an unflagged disagreement is the exact failure the fix says it removed.
"""
from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ["ARBS_SUPABASE_ENABLED"] = "0"
HERE = os.path.dirname(os.path.abspath(__file__))

spec = importlib.util.spec_from_file_location("up_c", os.path.join(HERE, "cur_upfront.py"))
cur = importlib.util.module_from_spec(spec)
sys.modules["up_c"] = cur
spec.loader.exec_module(cur)

rng = np.random.default_rng(2026)
DV01 = 1000.0
cases = []
for _ in range(120000):
    lc = bool(rng.integers(0, 2))
    pop = cur.POPULATION_LIFECYCLE if lc else cur.POPULATION_FLOW
    tau_bps = float(10 ** rng.uniform(-3, 1.1))          # 0.001 .. 12.6 bp
    sig = float(10 ** rng.uniform(-4, 0.3))              # 0.0001 .. 2.0 bp
    dev = float(rng.normal(0, 2.0))
    # put U near the |dev| boundary half the time: that is where z ~ 0
    if rng.random() < 0.5:
        u_bps = abs(dev) * float(rng.uniform(0.95, 1.05))
    else:
        u_bps = abs(float(rng.normal(0, 3.0)))
    bias = float(rng.normal(0, 0.2))
    t = cur.TauUpfront(tau_bps=tau_bps, bias_bps=bias, half_spread_bps=0.1,
                       sigma_bps=sig, n=500, population=pop)
    try:
        c = cur.classify(npv_pay=-dev * DV01, upfront=u_bps * DV01,
                         structure_dv01=DV01, mid_sigma_bps=sig, tau=t,
                         is_lifecycle=lc)
    except ValueError:
        continue
    if c.dealer_sign == 0 or c.signed_weight is None:
        continue
    cases.append((c, dev, u_bps, tau_bps, sig, bias, lc))

dis = [x for x in cases if x[0].dealer_sign * x[0].signed_weight < 0]
unf = [x for x in dis if cur.FLAG_SIGN_FRAGILE not in x[0].flags]
print(f"decisive rows      : {len(cases)}")
print(f"disagreements      : {len(dis)} ({len(dis) / max(len(cases), 1):.3%})")
print(f"UNFLAGGED          : {len(unf)}")
if unf:
    unf.sort(key=lambda x: -abs(x[0].signed_weight))
    for c, dev, u, tau, sig, bias, lc in unf[:5]:
        print(f"  dev={dev:+.5f} u_bps={u:.5f} tau={tau:.5f} sigma={sig:.6f} "
              f"bias={bias:+.4f} lifecycle={lc} -> dealer_sign={c.dealer_sign:+d} "
              f"signed_weight={c.signed_weight:+.5f} z={c.residual_bps:+.5f} "
              f"flags={c.flags}")
print(f"max |signed_weight| on a disagreement: "
      f"{max((abs(x[0].signed_weight) for x in dis), default=0):.4f}")

print()
print("p outside [0, 1] anywhere in that search? "
      f"{any(not (0.0 <= x[0].p <= 1.0) for x in cases)}")
print("p exactly 0 or 1 (saturated to a certainty): "
      f"{sum(1 for x in cases if x[0].p in (0.0, 1.0))}")
