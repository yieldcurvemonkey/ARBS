"""How much is the M46 survivor actually worth?

M46 rewrites `_normal_mass`'s `lo >= 0` branch into the algebraically identical
form the docstring says it is avoiding, so the question is not whether the
mutant is wrong -- it is -- but whether it is wrong by more than a double can
represent. A survivor that moves the answer by 1e-16 is a near-equivalent
mutant and no test should be asked to catch it; a survivor that moves it by
1e-9 is a real hole. Measured, not argued.
"""
from __future__ import annotations

import importlib.util
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ["ARBS_SUPABASE_ENABLED"] = "0"
HERE = os.path.dirname(os.path.abspath(__file__))
_SQRT2 = math.sqrt(2.0)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


src = open(os.path.join(HERE, "cur_upfront.py"), encoding="utf-8").read()
OLD = ("    if lo >= 0.0:\n        return 0.5 * (math.erfc(lo / _SQRT2) - "
       "math.erfc(hi / _SQRT2))")
NEW = ("    if lo >= 0.0:\n        return 0.5 * (math.erfc(-hi / _SQRT2) - "
       "math.erfc(-lo / _SQRT2))")
assert src.count(OLD) == 1
open(os.path.join(HERE, "_m46_upfront.py"), "w", encoding="utf-8").write(
    src.replace(OLD, NEW))
cur = load(os.path.join(HERE, "cur_upfront.py"), "up_cur46")
m46 = load(os.path.join(HERE, "_m46_upfront.py"), "up_m46")

print("=== A. the two formulas on their own, lo >= 0 ===")
worst = (0.0, None)
for lo in np.linspace(0.0, 8.9, 90):
    for hi in np.linspace(float(lo) + 1e-6, 9.0, 60):
        a = 0.5 * (math.erfc(lo / _SQRT2) - math.erfc(hi / _SQRT2))
        b = 0.5 * (math.erfc(-hi / _SQRT2) - math.erfc(-lo / _SQRT2))
        e = abs(a - b)
        if e > worst[0]:
            worst = (e, (float(lo), float(hi), a, b))
print(f"  max |stable - cancelling| = {worst[0]:.3e} at lo={worst[1][0]:.3f} "
      f"hi={worst[1][1]:.3f}  ({worst[1][2]:.6e} vs {worst[1][3]:.6e})")
print("  relative error there: "
      f"{worst[0] / max(worst[1][2], 1e-300):.3e}")

print()
print("=== B. does it reach p_marginalised? ===")
rng = np.random.default_rng(451)
worst_p = (0.0, None)
for _ in range(4000):
    dev = float(rng.uniform(-8.0, 8.0))
    u = float(rng.uniform(0.0, 8.0))
    tau = float(rng.uniform(0.5, 11.0))
    s = float(rng.uniform(0.05, 1.0))
    b0 = float(rng.uniform(-0.3, 0.3))
    a = cur.p_marginalised(dev, u, tau, mid_sigma_bps=s, bias_bps=b0)
    b = m46.p_marginalised(dev, u, tau, mid_sigma_bps=s, bias_bps=b0)
    e = abs(a - b)
    if e > worst_p[0]:
        worst_p = (e, (dev, u, tau, s, b0, a, b))
print(f"  max |p_current - p_M46| over 4,000 draws = {worst_p[0]:.3e}")
if worst_p[1]:
    print(f"  at dev={worst_p[1][0]:+.4f} u={worst_p[1][1]:.4f} "
          f"tau={worst_p[1][2]:.4f} s={worst_p[1][3]:.4f}")
print("  double-precision floor on a probability near 0.5: "
      f"{np.spacing(0.5):.3e}")

print()
print("=== C. the regime the docstring names: a saturated tail (beta large) ===")
# beta = s/tau large => reach = 40/beta small => hi_sat well below hi = 9, so
# `_normal_mass(hi_sat, hi)` is called with lo = hi_sat >> 0.
for s, tau in ((1.0, 0.02), (1.0, 0.01), (0.8, 0.005)):
    beta = s / tau
    dev = 0.0
    a = cur.p_marginalised(dev, 3.0, tau, mid_sigma_bps=s)
    b = m46.p_marginalised(dev, 3.0, tau, mid_sigma_bps=s)
    print(f"  beta={beta:8.1f} reach={40.0 / beta:.4f}  p_cur={a:.17f} "
          f"p_m46={b:.17f}  diff={abs(a - b):.3e}")
