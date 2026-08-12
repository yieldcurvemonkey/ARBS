"""Probe: what does `package_price.classify` return for the seam-test fixture?

Written before the krd seam test so the expected orientation comes from the
real module rather than from arithmetic done in a docstring.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

from SDRUtils.dealer_direction import package_price as pp  # noqa: E402

# Powers of two so the signed subset-sum is unique, and scaled so the solver's
# MARGIN to the runner-up clears the ambiguity gate: the margin is
# 2 * min(opa) = 30,000 = 1.5 bp of the 20,000 USD/bp package DV01.
OPAS = [15_000.0, 30_000.0, 60_000.0, 120_000.0]
PTP = -45_000.0
NPVS = [-6_000.0, 7_000.0, -5_000.0, 12_000.0]
PV01S = [1e4] * 4
DV01 = 2e4

call = pp.classify(opas=OPAS, package_price=PTP, npv_pays=NPVS, pv01s=PV01S,
                   structure_dv01=DV01)
for f in ("exclusion", "base_orientation", "model_price", "reported_price",
          "deviation_dollars", "deviation_bps", "dealer_sign",
          "received_signs", "tieout_bps", "unresolved_pv01", "flags"):
    print(f"{f:>20}: {getattr(call, f)!r}")
print(f"{'hypothesis signs':>20}: {pp.received_hypothesis_signs(call)!r}")

lc = pp.classify(opas=OPAS, package_price=PTP, npv_pays=NPVS, pv01s=PV01S,
                 structure_dv01=DV01, is_lifecycle=True)
print("\nlifecycle variant -- the invariant `dealer_sign * base_orientation ==")
print("received_signs` must hold on BOTH branches, or a producer piping the")
print("accessor into `DirectionCall.base_orientation` inverts every tear-up:")
print(f"{'base_orientation':>20}: {lc.base_orientation!r}")
print(f"{'dealer_sign':>20}: {lc.dealer_sign!r}")
print(f"{'received_signs':>20}: {lc.received_signs!r}")
print(f"{'hypothesis signs':>20}: {pp.received_hypothesis_signs(lc)!r}")
for tag, c in (("flow", call), ("lifecycle", lc)):
    lhs = tuple(c.dealer_sign * o for o in c.base_orientation)
    print(f"{tag:>20}: dealer_sign*base = {lhs!r}  received_signs = "
          f"{c.received_signs!r}  -> "
          f"{'HOLDS' if lhs == tuple(c.received_signs) else 'VIOLATED'}")
