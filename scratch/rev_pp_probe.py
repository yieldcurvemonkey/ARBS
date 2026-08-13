"""Adversarial probes for package_price gate-vs-classify divergence. Read-only."""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import package_price as pp


def legs(pkg, opas, ptp, dv01s):
    return pd.DataFrame([
        {"_unit_group": pkg, "other_payment_amount": o,
         "package_transaction_price": ptp, "_dv01_proxy": d}
        for o, d in zip(opas, dv01s)])


print("=== P1: net == 0 -- gate says recoverable, classify refuses ===")
opas = [10_000.0, 10_000.0]
ptp = 600.0
dv01s = [10_000.0, 10_000.0]          # gate dv01 = 10,000
g = pp.tape_gate(legs("A", opas, ptp, dv01s))
print("gate  :", g.to_dict("records"))
c = pp.classify(opas=opas, package_price=ptp,
                npv_pays=[-10_000.0, -15_000.0], pv01s=dv01s,
                structure_dv01=10_000.0)
print("classify exclusion:", c.exclusion, " tieout:", c.tieout_bps)

print()
print("=== P1b: 4 equal fees, a real PKG-4 shape ===")
opas = [250_000.0] * 4
g = pp.tape_gate(legs("B", opas, 20_000.0, [50_000.0] * 4))
print("gate  :", g.to_dict("records"))
c = pp.classify(opas=opas, package_price=20_000.0,
                npv_pays=[1.0, -2.0, 3.0, -4.0], pv01s=[50_000.0] * 4,
                structure_dv01=100_000.0)
print("classify exclusion:", c.exclusion)

print()
print("=== P2: an infinite OPA -- NaN tieout reads as recoverable ===")
g = pp.tape_gate(legs("C", [10_000.0, float("inf")], -4_000.0,
                      [10_000.0, 10_000.0]))
print("gate  :", g.to_dict("records"))
c = pp.classify(opas=[10_000.0, float("inf")], package_price=-4_000.0,
                npv_pays=[-10_000.0, -15_000.0], pv01s=[10_000.0, 10_000.0],
                structure_dv01=10_000.0)
print("classify exclusion:", c.exclusion)

print()
print("=== P2b: an infinite dv01 proxy ===")
g = pp.tape_gate(legs("D", [10_000.0, 15_000.0], -4_000.0,
                      [10_000.0, float("inf")]))
print("gate  :", g.to_dict("records"))

print()
print("=== P3: stratum order -- no PTP and no dv01 ===")
g = pp.tape_gate(legs("E", [10_000.0, 15_000.0], 100.0, [0.0, 0.0]))
print("gate  :", g.to_dict("records"))
c = pp.classify(opas=[10_000.0, 15_000.0], package_price=100.0,
                npv_pays=[-10_000.0, -15_000.0], pv01s=[10_000.0, 10_000.0],
                structure_dv01=0.0)
print("classify exclusion:", c.exclusion)

print()
print("=== P4: PTP differs between legs of one package (gate takes first) ===")
df = pd.DataFrame([
    {"_unit_group": "F", "other_payment_amount": 10_000.0,
     "package_transaction_price": np.nan, "_dv01_proxy": 10_000.0},
    {"_unit_group": "F", "other_payment_amount": 15_000.0,
     "package_transaction_price": -4_000.0, "_dv01_proxy": 10_000.0},
])
print("gate  :", pp.tape_gate(df).to_dict("records"))

print()
print("=== P5: empty-frame dtypes ===")
e = pp.tape_gate(legs("X", [1.0], None, [1.0]).iloc[:0])
print(e.dtypes.to_dict())

print()
print("=== P6: solver greedy above 24 legs -- flag and exactness ===")
n = 26
opas = [float(1000 * (i + 1)) for i in range(n)]
cs = pp.solve_cash_signs(opas, 5_000.0)
print("exact flag:", cs.exact, "residual:", cs.residual)
c = pp.classify(opas=opas, package_price=5_000.0,
                npv_pays=[float(-100 * (i + 1)) for i in range(n)],
                pv01s=[10_000.0] * n, structure_dv01=130_000.0)
print("flags:", c.flags, "exclusion:", c.exclusion)
g = pp.tape_gate(legs("G", opas, 5_000.0, [10_000.0] * n))
print("gate  :", g.to_dict("records"), " (no greedy flag column at all)")

print()
print("=== P7: near-zero net -- polarity from $1 of fee imbalance ===")
c = pp.classify(opas=[10_000.0, 10_001.0], package_price=600.0,
                npv_pays=[-10_000.0, -15_000.0], pv01s=[10_000.0, 10_000.0],
                structure_dv01=10_000.0)
print("net-driven reported:", c.reported_price, "dev$:", c.deviation_dollars,
      "recv:", c.received_signs, "tieout_bps:", c.tieout_bps)
c2 = pp.classify(opas=[10_001.0, 10_000.0], package_price=600.0,
                 npv_pays=[-15_000.0, -10_000.0], pv01s=[10_000.0, 10_000.0],
                 structure_dv01=10_000.0)
print("swap the two legs   :", c2.reported_price, c2.deviation_dollars,
      c2.received_signs)
