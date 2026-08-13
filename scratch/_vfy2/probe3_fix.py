"""Re-runs of D5/D7/D8 after two probe bugs of my own.

* D5/D7 passed a `tau`, so HEAD died later in `p_from_edge` on a NaN rather
  than returning the silent tie the fixer's comment describes. The claim is
  explicitly "with no tau", so `tau=None` is the condition to test.
* D8 compared two dataclass instances from two different module objects.
  `UpfrontCall.__eq__` is dataclass-generated and returns NotImplemented for a
  foreign class, so every comparison was unequal for a reason that has nothing
  to do with the mutation. Compare field values instead.
"""
from __future__ import annotations

import dataclasses
import importlib.util
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
m29 = load(os.path.join(HERE, "_m29_upfront.py"), "up_m29")


def fields(c):
    return {f.name: getattr(c, f.name) for f in dataclasses.fields(c)}


def same(a, b):
    fa, fb = fields(a), fields(b)
    if set(fa) != set(fb):
        return False, f"different field sets: {set(fa) ^ set(fb)}"
    for k in fa:
        x, y = fa[k], fb[k]
        if isinstance(x, float) and isinstance(y, float):
            if x != y and not (x != x and y != y):
                return False, f"{k}: {x!r} vs {y!r}"
        elif x != y:
            return False, f"{k}: {x!r} vs {y!r}"
    return True, ""


print("=== D5 (redone). npv_pay = NaN, tau=None -- the 'silent tie' claim ===")
for label, mod in (("HEAD", head), ("CURRENT", cur)):
    try:
        c = mod.classify(npv_pay=float("nan"), upfront=25000.0,
                         structure_dv01=1000.0, mid_sigma_bps=0.25, tau=None)
        print(f"  {label:8s} dealer_sign={c.dealer_sign} "
              f"exclusion={c.exclusion!r} dev_bps={c.dev_bps} p={c.p} "
              f"edge={c.edge_bps}")
    except Exception as exc:                                   # noqa: BLE001
        print(f"  {label:8s} raised {type(exc).__name__}: {str(exc)[:80]}")

print()
print("=== D7 (redone). non-finite mid calibration, tau=None ===")
for arg in ("mid_bias_bps", "mid_sigma_bps"):
    for label, mod in (("HEAD", head), ("CURRENT", cur)):
        kw = {"npv_pay": -3000.0, "upfront": 2500.0, "structure_dv01": 1000.0,
              "mid_sigma_bps": 0.25, "tau": None}
        kw[arg] = float("nan")
        try:
            c = mod.classify(**kw)
            print(f"  {arg:14s} {label:8s} dealer_sign={c.dealer_sign} "
                  f"exclusion={c.exclusion!r} dev={c.dev_bps} "
                  f"fragile={mod.FLAG_SIGN_FRAGILE in c.flags}")
        except Exception as exc:                               # noqa: BLE001
            print(f"  {arg:14s} {label:8s} raised {type(exc).__name__}: "
                  f"{str(exc)[:60]}")

print()
print("=== D8 (redone). is M29 an equivalent mutant on the current code? ===")
rng = np.random.default_rng(99)
diffs = []
for _ in range(20000):
    dv01 = float(rng.uniform(1.0, 1e5))
    kw = dict(npv_pay=float(rng.normal(0, 5e4)),
              upfront=abs(float(rng.normal(0, 5e4))),
              structure_dv01=dv01,
              mid_sigma_bps=float(rng.uniform(0.05, 1.0)),
              mid_bias_bps=float(rng.normal(0, 0.5)))
    t_cur = cur.TauUpfront(tau_bps=float(rng.uniform(0.5, 5.0)), bias_bps=0.0,
                           half_spread_bps=0.1, sigma_bps=0.25, n=500,
                           population=cur.POPULATION_FLOW)
    t_m29 = m29.TauUpfront(**dataclasses.asdict(t_cur))
    a = cur.classify(tau=t_cur, **kw)
    b = m29.classify(tau=t_m29, **kw)
    ok, why = same(a, b)
    if not ok:
        diffs.append((kw, why))
print(f"  field-wise differences over 20,000 random calls: {len(diffs)}")
if diffs:
    print(f"  first: {diffs[0][1]}")

print()
print("  can u_bps be negative on the current code? "
      "(u_bps = upfront / dv01)")
for name, kw in (
        ("negative fee", dict(npv_pay=-1.0, upfront=-1.0, structure_dv01=1e3)),
        ("negative DV01", dict(npv_pay=-1.0, upfront=1.0, structure_dv01=-1e3)),
        ("zero DV01", dict(npv_pay=-1.0, upfront=1.0, structure_dv01=0.0)),
        ("NaN fee", dict(npv_pay=-1.0, upfront=float("nan"),
                         structure_dv01=1e3)),
):
    for label, mod in (("HEAD", head), ("CURRENT", cur)):
        try:
            c = mod.classify(**kw)
            print(f"  {name:14s} {label:8s} -> u_bps={c.upfront_bps!r} "
                  f"exclusion={c.exclusion!r}")
        except Exception as exc:                               # noqa: BLE001
            print(f"  {name:14s} {label:8s} -> {type(exc).__name__}: "
                  f"{str(exc)[:55]}")
