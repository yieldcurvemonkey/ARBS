"""Behavioural repros #2-#8: the sign, the flag, and the guards.

Each block runs the SAME input through the pre-fix (HEAD) module and the
current one. A block only counts as evidence of a fix if HEAD misbehaves --
otherwise the probe is not testing anything.
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


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cur = load(os.path.join(HERE, "cur_upfront.py"), "up_cur")
head = load(os.path.join(HERE, "head_upfront.py"), "up_head")


def tau_of(mod, tau_bps=1.0, bias=0.0, sigma=0.25, pop=None):
    return mod.TauUpfront(tau_bps=tau_bps, bias_bps=bias, half_spread_bps=0.1,
                          sigma_bps=sigma, n=500,
                          population=pop or mod.POPULATION_FLOW)


print("=== D2. dealer_sign taken from the RAW npv while p reads the "
      "bias-corrected deviation ===")
# DV01 = 1000 $/bp. npv_pay = -300 => raw dev = +0.30 bp. A mid bias of +0.60 bp
# puts the print on the OTHER side of mid: corrected dev = -0.30 bp.
dv01, npv, mid_bias, U = 1000.0, -300.0, 0.60, 2000.0
for label, mod in (("HEAD", head), ("CURRENT", cur)):
    t = tau_of(mod, tau_bps=1.0, bias=0.0, sigma=0.25)
    c = mod.classify(npv_pay=npv, upfront=U, structure_dv01=dv01,
                     mid_bias_bps=mid_bias, mid_sigma_bps=0.25, tau=t)
    disagree = (c.dealer_sign != 0 and c.signed_weight is not None
                and c.dealer_sign * c.signed_weight < 0)
    print(f"  {label:8s} dev={c.dev_bps:+.4f} edge={c.edge_bps:+.4f} "
          f"dealer_sign={c.dealer_sign:+d} p={c.p:.4f} "
          f"signed_weight={c.signed_weight:+.4f} "
          f"disagree={disagree} flags={c.flags}")

print()
print("  sweep: how often do dealer_sign and signed_weight point opposite "
      "ways, and is it flagged?")
rng = np.random.default_rng(11)
for label, mod in (("HEAD", head), ("CURRENT", cur)):
    n = dis = dis_unflagged = 0
    worst = 0.0
    for _ in range(6000):
        dv01 = 1000.0
        dev_raw = float(rng.normal(0.0, 2.0))
        npv = -dev_raw * dv01
        mid_bias = float(rng.normal(0.0, 1.0))
        u_bps = abs(dev_raw - mid_bias) * float(rng.uniform(0.5, 1.5))
        U = u_bps * dv01
        sig = float(rng.uniform(0.05, 0.6))
        t = tau_of(mod, tau_bps=float(rng.uniform(0.5, 4.0)), bias=0.0,
                   sigma=sig)
        c = mod.classify(npv_pay=npv, upfront=U, structure_dv01=dv01,
                         mid_bias_bps=mid_bias, mid_sigma_bps=sig, tau=t)
        if c.dealer_sign == 0 or c.signed_weight is None:
            continue
        n += 1
        if c.dealer_sign * c.signed_weight < 0:
            dis += 1
            worst = max(worst, abs(c.signed_weight))
            if mod.FLAG_SIGN_FRAGILE not in c.flags:
                dis_unflagged += 1
    print(f"  {label:8s} n={n} disagreements={dis} ({dis / n:.3%}) "
          f"UNFLAGGED disagreements={dis_unflagged} "
          f"max|signed_weight| on a disagreement={worst:.4f}")

print()
print("=== D3. FLAG_SIGN_FRAGILE: is the new condition a strict superset? ===")
K = cur.FRAGILE_SIGMA_MULT
rng = np.random.default_rng(3)
old_only = new_only = both = neither = 0
for _ in range(200000):
    dev = float(rng.normal(0, 3)); u = abs(float(rng.normal(0, 3)))
    s = float(rng.uniform(0.05, 1.0)); z = abs(dev) - u
    old = (abs(dev) <= K * s) and (u > abs(dev))
    new = min(abs(dev), abs(z)) <= K * s
    if old and new: both += 1
    elif old: old_only += 1
    elif new: new_only += 1
    else: neither += 1
print(f"  old-only (a row the OLD flag caught and the new one drops): "
      f"{old_only}   both {both}   new-only {new_only}   neither {neither}")
print(f"  => strict superset: {old_only == 0}; "
      f"flag rate old {(both + old_only) / 200000:.4f} -> "
      f"new {(both + new_only) / 200000:.4f}")

print()
print("=== D4. resolve_upfront: one NaN leg in the ufro list ===")
for label, mod in (("HEAD", head), ("CURRENT", cur)):
    got = mod.resolve_upfront(None, ufros=[float("nan"), 25000.0], uwins=[])
    print(f"  {label:8s} resolve_upfront(ptp=None, ufros=[nan, 25000]) -> {got}")

print()
print("=== D5. a failed repricing: npv_pay = NaN ===")
for label, mod in (("HEAD", head), ("CURRENT", cur)):
    try:
        c = mod.classify(npv_pay=float("nan"), upfront=25000.0,
                         structure_dv01=1000.0, mid_sigma_bps=0.25,
                         tau=tau_of(mod))
        print(f"  {label:8s} dealer_sign={c.dealer_sign} "
              f"exclusion={c.exclusion!r} p={c.p} flags={c.flags}")
    except Exception as exc:                                   # noqa: BLE001
        print(f"  {label:8s} raised {type(exc).__name__}: {str(exc)[:70]}")

print()
print("=== D6. a negative fee ===")
for label, mod in (("HEAD", head), ("CURRENT", cur)):
    try:
        c = mod.classify(npv_pay=-3000.0, upfront=-5000.0,
                         structure_dv01=1000.0, mid_sigma_bps=0.25,
                         tau=tau_of(mod))
        print(f"  {label:8s} z={c.residual_bps:+.4f} |edge|={abs(c.edge_bps):.4f} "
              f"p={c.p:.6f}  (a POSITIVE fee of 5000 gives "
              f"p={mod.classify(npv_pay=-3000.0, upfront=5000.0, structure_dv01=1000.0, mid_sigma_bps=0.25, tau=tau_of(mod)).p:.6f})")
    except Exception as exc:                                   # noqa: BLE001
        print(f"  {label:8s} raised {type(exc).__name__}: {str(exc)[:80]}")

print()
print("=== D7. non-finite mid calibration ===")
for arg in ("mid_bias_bps", "mid_sigma_bps"):
    for label, mod in (("HEAD", head), ("CURRENT", cur)):
        kw = {"npv_pay": -3000.0, "upfront": 2500.0, "structure_dv01": 1000.0,
              "mid_sigma_bps": 0.25, "tau": tau_of(mod)}
        kw[arg] = float("nan")
        try:
            c = mod.classify(**kw)
            print(f"  {arg:14s} {label:8s} dealer_sign={c.dealer_sign} "
                  f"exclusion={c.exclusion!r} p={c.p} "
                  f"fragile={mod.FLAG_SIGN_FRAGILE in c.flags}")
        except Exception as exc:                               # noqa: BLE001
            print(f"  {arg:14s} {label:8s} raised {type(exc).__name__}: "
                  f"{str(exc)[:60]}")

print()
print("=== D8. M29 (`u_bps` -> `abs(u_bps)`): equivalent mutant or live gap? ===")
src = open(os.path.join(HERE, "cur_upfront.py"), encoding="utf-8").read()
mutated = src.replace("    z = abs(dev) - u_bps - bias",
                      "    z = abs(dev) - abs(u_bps) - bias")
assert mutated != src
mpath = os.path.join(HERE, "_m29_upfront.py")
open(mpath, "w", encoding="utf-8").write(mutated)
m29 = load(mpath, "up_m29")
rng = np.random.default_rng(99)
diffs = 0
neg_u_possible = False
for _ in range(20000):
    dv01 = float(rng.uniform(1.0, 1e5))
    npv = float(rng.normal(0, 5e4))
    U = abs(float(rng.normal(0, 5e4)))
    sig = float(rng.uniform(0.05, 1.0))
    kw = dict(npv_pay=npv, upfront=U, structure_dv01=dv01, mid_sigma_bps=sig,
              tau=tau_of(cur, tau_bps=float(rng.uniform(0.5, 5.0))),
              mid_bias_bps=float(rng.normal(0, 0.5)))
    a, b = cur.classify(**kw), m29.classify(**kw)
    if a != b:
        diffs += 1
# can u_bps ever be negative on the current code?
try:
    cur.classify(npv_pay=-1.0, upfront=-1.0, structure_dv01=1000.0)
except ValueError:
    pass
else:
    neg_u_possible = True
try:
    cur.classify(npv_pay=-1.0, upfront=1.0, structure_dv01=-1000.0)
except ValueError:
    pass
else:
    neg_u_possible = True
print(f"  outputs differing over 20,000 random calls: {diffs}")
print(f"  a negative u_bps reachable through classify (negative fee or "
      f"negative DV01 accepted): {neg_u_possible}")
