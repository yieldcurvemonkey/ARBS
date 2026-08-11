"""Is the 40-node Gauss-Hermite in p_marginalised actually integrating?

Reference: the same integral on a 200k-point trapezoid grid over +-12 sigma
(validated below against a case with a closed form: u = 0, where the integrand
is a smooth logistic and both methods must agree).
"""
import math
import numpy as np
from SDRUtils.dealer_direction import upfront as up

TAU = 0.5


def ref(dev, u, tau, s, is_lifecycle=False, b=0.0):
    x = np.linspace(dev - 12 * s, dev + 12 * s, 400001)
    w = np.exp(-0.5 * ((x - dev) / s) ** 2) / (s * math.sqrt(2 * math.pi))
    e = np.where(x >= 0, x - (u + b), x + (u + b))
    if is_lifecycle:
        e = -e
    p = 1.0 / (1.0 + np.exp(-np.clip(e / tau, -500, 500)))
    return float(np.trapezoid(w * p, x))


print("validation, u = 0 (smooth integrand -- both methods must agree):")
for dev in (0.0, 0.3, 1.0, -2.0):
    print(f"   dev={dev:+5.2f}  GH={up.p_marginalised(dev, 0.0, TAU, mid_sigma_bps=0.2):.6f}"
          f"  ref={ref(dev, 0.0, TAU, 0.2):.6f}")

print()
print("the real case: u = 5 bp, s = 0.2 bp, tau = 0.5 bp")
print(f"{'dev/s':>7} {'dev':>7} {'GH(40)':>10} {'reference':>10} {'error':>9}")
for k in (0.0, 0.05, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0):
    dev = k * 0.2
    g = up.p_marginalised(dev, 5.0, TAU, mid_sigma_bps=0.2)
    r = ref(dev, 5.0, TAU, 0.2)
    print(f"{k:7.2f} {dev:7.3f} {g:10.6f} {r:10.6f} {g - r:+9.6f}")

print()
print("node coverage: 40-node Hermite abscissae span +-%.2f sigma" %
      (math.sqrt(2) * up._GH_NODES.max()))
print("smallest |node| in sigma units: %.4f" %
      (math.sqrt(2) * np.abs(up._GH_NODES).min()))

print()
print("does more resolution fix it?  (same integral, n-node Gauss-Hermite)")
for n in (40, 200, 1000, 5000):
    x, w = np.polynomial.hermite.hermgauss(n)
    d = 0.01 + math.sqrt(2) * 0.2 * x
    e = np.where(d >= 0, d - 5.0, d + 5.0)
    p = 1.0 / (1.0 + np.exp(-np.clip(e / TAU, -500, 500)))
    print(f"   n={n:5d}  p={float(np.dot(w, p) / math.sqrt(math.pi)):.6f}")
print(f"   reference    p={ref(0.01, 5.0, TAU, 0.2):.6f}")
