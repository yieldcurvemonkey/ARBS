"""Are the new survivors X03/X05/X09 real gaps or immaterial mutants?

Same standard applied to M46: a survivor only counts as a hole in the suite if
it moves an answer by more than the answer's own precision. Measured against
the independent scipy reference from probe1, not against the module itself.
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


def load_src(src_text, name):
    path = os.path.join(HERE, f"_{name}.py")
    open(path, "w", encoding="utf-8").write(src_text)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


src = open(os.path.join(HERE, "cur_upfront.py"), encoding="utf-8").read()
spec = importlib.util.spec_from_file_location("mx", os.path.join(HERE, "mutset_x.py"))
mx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mx)

cur = load_src(src, "x_cur")


def mutant(key):
    old, new = mx.MUTATIONS[key]
    assert src.count(old) == 1, key
    return load_src(src.replace(old, new), "x_" + key.split("_")[0].lower())


def reference(dev, u, tau, s, b0=0.0):
    c = u + b0

    def integrand(d):
        e = (d - c) if d >= 0 else (d + c)
        x = max(-500.0, min(500.0, e / tau))
        pdf = math.exp(-0.5 * ((d - dev) / s) ** 2) / (s * math.sqrt(2 * math.pi))
        return pdf / (1.0 + math.exp(-x))

    lo, hi = dev - 12 * s, dev + 12 * s
    tot = 0.0
    if lo < 0:
        tot += quad(integrand, lo, min(0.0, hi), limit=400, epsabs=1e-15,
                    epsrel=1e-13)[0]
    if hi > 0:
        tot += quad(integrand, max(0.0, lo), hi, limit=400, epsabs=1e-15,
                    epsrel=1e-13)[0]
    return tot


def sweep(mod, label, n=3000, tau_lo=0.5, tau_hi=11.0, seed=20260811):
    rng = np.random.default_rng(seed)
    worst = (0.0, None)
    errs = []
    for _ in range(n):
        dev = float(rng.uniform(-6.0, 6.0))
        u = float(rng.uniform(0.0, 8.0))
        tau = float(rng.uniform(tau_lo, tau_hi))
        s = float(rng.uniform(0.05, 1.0))
        b0 = float(rng.uniform(-0.3, 0.3))
        got = mod.p_marginalised(dev, u, tau, mid_sigma_bps=s, bias_bps=b0)
        ref = reference(dev, u, tau, s, b0)
        e = abs(got - ref)
        errs.append(e)
        if e > worst[0]:
            worst = (e, (dev, u, tau, s, b0, got, ref))
    errs = np.array(errs)
    print(f"  {label:34s} max|err|={errs.max():.3e}  "
          f"frac>1e-6={np.mean(errs > 1e-6):.4f}  frac>1e-3={np.mean(errs > 1e-3):.4f}")
    if worst[1] and worst[0] > 1e-9:
        print(f"       worst dev={worst[1][0]:+.4f} u={worst[1][1]:.4f} "
              f"tau={worst[1][2]:.4f} s={worst[1][3]:.4f} -> got {worst[1][5]:.8f} "
              f"ref {worst[1][6]:.8f}")
    return errs.max()


print("=== X09: `_normal_mass` middle branch (lo < 0 < hi) ===")
x09 = mutant("X09_normal_mass_middle_branch")
print("  is the branch reachable at all?")
hit = 0
rng = np.random.default_rng(5)
for _ in range(2000):
    lo, hi = float(rng.uniform(-9, 0)), float(rng.uniform(0, 9))
    if abs(cur._normal_mass(lo, hi) - x09._normal_mass(lo, hi)) > 1e-12:
        hit += 1
print(f"  direct _normal_mass(lo<0<hi) differs on {hit}/2000 draws; "
      f"e.g. lo=-1 hi=1: cur={cur._normal_mass(-1, 1):.10f} "
      f"x09={x09._normal_mass(-1, 1):.10f}")
print("  effect on p_marginalised:")
sweep(cur, "current (control)")
sweep(x09, "X09 mutant")
print("  wide-tau corner (tau 6-11, where the saturated wing is used):")
sweep(cur, "current (control)", n=1500, tau_lo=0.01, tau_hi=0.2, seed=7)
sweep(x09, "X09 mutant", n=1500, tau_lo=0.01, tau_hi=0.2, seed=7)

print()
print("=== X03: panel width stops adapting to beta = s/tau ===")
x03 = mutant("X03_panel_width_ignores_beta")
print("  ordinary range (tau 0.5-11):")
sweep(cur, "current (control)")
sweep(x03, "X03 mutant")
print("  sharp-logistic corner (tau 0.005-0.05, beta up to 200):")
sweep(cur, "current (control)", n=1500, tau_lo=0.005, tau_hi=0.05, seed=13)
sweep(x03, "X03 mutant", n=1500, tau_lo=0.005, tau_hi=0.05, seed=13)

print()
print("=== X05: negative-fee guard slackened from 0.0 to -1e-6 ===")
x05 = mutant("X05_negative_fee_guard_slack")
for U in (-1e-7, -1e-6, -1.0):
    try:
        c = x05.classify(npv_pay=-3000.0, upfront=U, structure_dv01=1000.0)
        print(f"  upfront={U!r:12s} accepted, u_bps={c.upfront_bps:.3e} "
              f"z={c.residual_bps:.10f}")
    except ValueError as exc:
        print(f"  upfront={U!r:12s} refused: {str(exc)[:40]}")
c0 = cur.classify(npv_pay=-3000.0, upfront=0.0, structure_dv01=1000.0)
cm = x05.classify(npv_pay=-3000.0, upfront=-1e-7, structure_dv01=1000.0)
print(f"  largest z the slack admits vs a zero fee: "
      f"{abs(cm.residual_bps - c0.residual_bps):.3e} bp")
