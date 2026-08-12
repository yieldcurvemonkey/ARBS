"""Same quadrature check at the parameters the module says it measured:
tau_upfront 3.8 bp (flow), mid sigma 0.25 bp, fee a few bp.
"""
import math
import numpy as np
from SDRUtils.dealer_direction import upfront as up


def ref(dev, u, tau, s):
    x = np.linspace(dev - 12 * s, dev + 12 * s, 400001)
    w = np.exp(-0.5 * ((x - dev) / s) ** 2) / (s * math.sqrt(2 * math.pi))
    e = np.where(x >= 0, x - u, x + u)
    p = 1.0 / (1.0 + np.exp(-np.clip(e / tau, -500, 500)))
    return float(np.trapezoid(w * p, x))


TAU, S = 3.8, 0.25
for u in (2.0, 5.0):
    print(f"\nu = {u} bp, tau = {TAU} bp, s = {S} bp")
    print(f"{'dev':>7} {'dev/s':>6} {'GH(40)':>10} {'ref':>10} {'err':>9} "
          f"{'sw GH':>9} {'sw ref':>9}")
    for dev in (0.0, 0.01, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30, 0.50, 1.0):
        g = up.p_marginalised(dev, u, TAU, mid_sigma_bps=S)
        r = ref(dev, u, TAU, S)
        print(f"{dev:7.3f} {dev/S:6.2f} {g:10.6f} {r:10.6f} {g-r:+9.6f} "
              f"{2*g-1:+9.4f} {2*r-1:+9.4f}")

print("\nstaircase: p as a function of dev, u=5, tau=0.5, s=0.2")
prev = None
for i in range(0, 61):
    dev = i * 0.005
    g = up.p_marginalised(dev, 5.0, 0.5, mid_sigma_bps=0.2)
    if prev is None or abs(g - prev) > 1e-9:
        print(f"   dev={dev:6.3f}  p={g:.6f}   <- value changes here")
    prev = g
