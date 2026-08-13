"""Behavioural repro #1: does `p_marginalised` integrate the kinked integrand?

The reviewer's mutants M06/M07/M08 all sat inside `p_marginalised` and all
survived, so the function had no test that could see its value. The fixer's
docstring claims 40-node Gauss-Hermite made `p` a staircase in `dev` with error
up to 0.030 and 27 of 2,025 real prints coming back with the wrong
`signed_weight` sign, and that panelled Gauss-Legendre now ties out to 1.8e-14.

Both halves are checked here against an independent reference that shares no
code with either implementation: `scipy.integrate.quad` run separately on each
side of the kink. Running it on the HEAD implementation first is the control --
if the reference did not reproduce the staircase on the old code, the reference
would be the thing that is wrong.
"""
from __future__ import annotations

import importlib.util
import math
import os
import sys

import numpy as np
from scipy.integrate import quad

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ["ARBS_SUPABASE_ENABLED"] = "0"

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cur = load(os.path.join(HERE, "cur_upfront.py"), "up_cur")
head = load(os.path.join(HERE, "head_upfront.py"), "up_head")


def reference(dev, u, tau, s, b0=0.0, is_lifecycle=False):
    """E[sigmoid(edge(d)/tau)] with d ~ N(dev, s^2), split at the kink."""
    c = u + b0

    def pdf(d):
        return math.exp(-0.5 * ((d - dev) / s) ** 2) / (s * math.sqrt(2 * math.pi))

    def integrand(d):
        e = (d - c) if d >= 0 else (d + c)
        if is_lifecycle:
            e = -e
        x = e / tau
        x = max(-500.0, min(500.0, x))
        return pdf(d) / (1.0 + math.exp(-x))

    lo, hi = dev - 12 * s, dev + 12 * s
    tot = 0.0
    if lo < 0:
        tot += quad(integrand, lo, min(0.0, hi), limit=400, epsabs=1e-15,
                    epsrel=1e-13)[0]
    if hi > 0:
        tot += quad(integrand, max(0.0, lo), hi, limit=400, epsabs=1e-15,
                    epsrel=1e-13)[0]
    return tot


def sweep(mod, label):
    rng = np.random.default_rng(20260811)
    worst = (0.0, None)
    errs = []
    for _ in range(1200):
        dev = float(rng.uniform(-6.0, 6.0))
        u = float(rng.uniform(0.0, 8.0))
        tau = float(rng.uniform(0.5, 11.0))
        s = float(rng.uniform(0.05, 1.0))
        b0 = float(rng.uniform(-0.3, 0.3))
        lc = bool(rng.integers(0, 2))
        try:
            got = mod.p_marginalised(dev, u, tau, mid_sigma_bps=s, bias_bps=b0,
                                     is_lifecycle=lc)
        except Exception as exc:                       # noqa: BLE001
            print(f"  {label}: raised on {(dev, u, tau, s, b0, lc)}: {exc}")
            continue
        ref = reference(dev, u, tau, s, b0, lc)
        e = abs(got - ref)
        errs.append(e)
        if e > worst[0]:
            worst = (e, (dev, u, tau, s, b0, lc, got, ref))
    errs = np.array(errs)
    print(f"{label:8s} n={len(errs)}  max|err|={errs.max():.3e}  "
          f"median={np.median(errs):.3e}  frac>1e-3={np.mean(errs > 1e-3):.4f}  "
          f"frac>1e-2={np.mean(errs > 1e-2):.4f}")
    print(f"         worst at dev={worst[1][0]:+.4f} u={worst[1][1]:.4f} "
          f"tau={worst[1][2]:.4f} s={worst[1][3]:.4f} -> got {worst[1][6]:.6f} "
          f"ref {worst[1][7]:.6f}")
    return errs


print("=== A. accuracy against an independent scipy.quad reference ===")
eh = sweep(head, "HEAD")
ec = sweep(cur, "CURRENT")

print()
print("=== B. the staircase: p as a function of dev, everything else fixed ===")
# tau small, sigma small -- the corner the docstring says the calibration is
# heading into.
u, tau, s, b0 = 2.0, 0.8, 0.25, 0.0
prev_h = prev_c = None
jh = jc = 0.0
for dev in np.linspace(-1.0, 1.0, 401):
    ph = head.p_marginalised(float(dev), u, tau, mid_sigma_bps=s, bias_bps=b0)
    pc = cur.p_marginalised(float(dev), u, tau, mid_sigma_bps=s, bias_bps=b0)
    if prev_h is not None:
        jh = max(jh, abs(ph - prev_h))
        jc = max(jc, abs(pc - prev_c))
    prev_h, prev_c = ph, pc
print(f"largest step between adjacent dev (grid 0.005 bp): "
      f"HEAD {jh:.4f}   CURRENT {jc:.4f}")

print()
print("=== C. sign of signed_weight: how often does HEAD land on the wrong "
      "side of 0.5? ===")
rng = np.random.default_rng(7)
bad_h = bad_c = n = 0
for _ in range(4000):
    dev = float(rng.normal(0.0, 3.0))
    u = abs(dev) * float(rng.uniform(0.8, 1.2))
    tau = float(rng.uniform(0.5, 4.0))
    s = float(rng.uniform(0.05, 0.6))
    ref = reference(dev, u, tau, s)
    ph = head.p_marginalised(dev, u, tau, mid_sigma_bps=s)
    pc = cur.p_marginalised(dev, u, tau, mid_sigma_bps=s)
    n += 1
    if (ph - 0.5) * (ref - 0.5) < 0:
        bad_h += 1
    if (pc - 0.5) * (ref - 0.5) < 0:
        bad_c += 1
print(f"n={n}  HEAD wrong side of 0.5: {bad_h} ({bad_h / n:.4%})   "
      f"CURRENT: {bad_c} ({bad_c / n:.4%})")
