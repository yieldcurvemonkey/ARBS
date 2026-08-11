"""Fix probe 1: what a PARENT-bucket h does to a child whose own h is smaller.

Reproduces the review's measurement and then asks the question the review did
not: does raising the child above the 800 floor make the parent anchor safe?
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from SDRUtils.dealer_direction import probability as prob


def one(n_child, h_child=0.07, s=0.20, parent_h=0.20, seed=5):
    rng = np.random.default_rng(seed)
    x, _ = prob.simulate(b0=0.0, h=h_child, s=s, n=n_child, rng=rng)
    truth = s * s / (2.0 * h_child)
    out = {}
    for name, kw in (("no anchor", {}), ("parent anchor", {"parent_h": parent_h})):
        f = prob.fit_mixture(x, bucket="CHILD", **kw)
        out[name] = f
        print(f"  n={n_child:5d} {name:14s} min_n_req={f.min_n_required:4d} "
              f"h={f.h:.4f} s={f.s:.4f} tau={f.tau:8.4f} "
              f"(truth {truth:.4f}, ratio {f.tau / truth:6.3f})  "
              f"admitted={'YES' if f.n_trimmed >= f.min_n_required else 'no ':3s} "
              f"[{','.join(f.flags)}]")
    return out


print("child true h=0.07 s=0.20 (tau=0.2857); parent h=0.20")
for n in (450, 900, 2000, 6000):
    one(n)

print()
print("control: child whose true h really IS the parent's (h=0.20, s=0.20, tau=0.1)")
for n in (450, 2000):
    one(n, h_child=0.20)

print()
print("what POOLING to the parent would give that child instead:")
rng = np.random.default_rng(9)
xp, _ = prob.simulate(b0=0.0, h=0.20, s=0.20, n=12000, rng=rng)
fp = prob.fit_mixture(xp, bucket="PARENT")
print(f"  parent fit h={fp.h:.4f} s={fp.s:.4f} tau={fp.tau:.4f} [{','.join(fp.flags)}]")

print()
print("inadmissible anchor (parent h exceeds the child's own dispersion):")
one(2000, h_child=0.07, s=0.10, parent_h=0.30)
