"""Adversarial probes for upfront.py. Each prints a claim and the observed value."""
import math
import numpy as np
from SDRUtils.dealer_direction import upfront as up
from SDRUtils.dealer_direction import conventions as conv

PV01 = 10_000.0
TAU = up.TauUpfront(tau_bps=0.5, bias_bps=0.0, half_spread_bps=1.0, sigma_bps=1.0,
                    n=100, bucket="T", population=up.POPULATION_FLOW)

print("== P1: mid_bias_bps flips dev but not the orientation ==")
# raw dev = +0.20 bp (printed above mid). A +0.5 bp bucket mid-bias means the
# TRUE deviation is -0.30 bp, i.e. printed BELOW mid.
npv = -0.20 * PV01
c = up.classify(npv_pay=npv, upfront=0.0, structure_dv01=PV01, mid_bias_bps=0.5)
print("   dev_bps      =", c.dev_bps, "(true deviation, bias removed)")
print("   edge_bps     =", c.edge_bps)
print("   dealer_sign  =", c.dealer_sign, " conventions.dealer_side(dev) =",
      conv.dealer_side(c.dev_bps))
c2 = up.classify(npv_pay=npv, upfront=0.0, structure_dv01=PV01, mid_bias_bps=0.5,
                 tau=TAU, mid_sigma_bps=0.05)
print("   with tau+sigma: p =", round(c2.p, 6), " dealer_sign =", c2.dealer_sign,
      " signed_weight =", round(c2.signed_weight, 6))
print("   -> p and dealer_sign disagree:", (c2.p - 0.5) * c2.dealer_sign < 0)

print()
print("== P2: NaN npv_pay is a silent success ==")
c = up.classify(npv_pay=float("nan"), upfront=40_000.0, structure_dv01=PV01)
print("   dev", c.dev_bps, "edge", c.edge_bps, "sign", c.dealer_sign,
      "exclusion", c.exclusion, "flags", c.flags)
try:
    c = up.classify(npv_pay=float("nan"), upfront=40_000.0, structure_dv01=PV01,
                    tau=TAU)
    print("   with tau: p =", c.p)
except Exception as e:
    print("   with tau raises:", type(e).__name__, e)

print()
print("== P3: negative fee makes the call MORE confident ==")
for u in (40_000.0, -40_000.0):
    c = up.classify(npv_pay=-100_000.0, upfront=u, structure_dv01=PV01, tau=TAU)
    print(f"   upfront={u:>10.0f}  z={c.residual_bps:6.2f}  p={c.p:.6f}  flags={c.flags}")

print()
print("== P4: p_marginalised at s->0 vs the point estimate at dev=0 ==")
print("   classify(dev=0) edge:", up.classify(npv_pay=0.0, upfront=5e4,
                                              structure_dv01=PV01).edge_bps)
print("   _edge_from_dev(0):", up._edge_from_dev(0.0, 5.0, 0.0, False))
print("   p_marginalised(dev=0, s=0):", up.p_marginalised(0.0, 5.0, 0.5,
                                                          mid_sigma_bps=0.0))
print("   p_marginalised(dev=0, s=1e-9):", up.p_marginalised(0.0, 5.0, 0.5,
                                                             mid_sigma_bps=1e-9))

print()
print("== P5: FIT_OK is not written into fallback? ==")
from SDRUtils.dealer_direction import probability as prob
rng = np.random.default_rng(0)
z = 0.8 * rng.choice([-1.0, 1.0], 4000) + 0.4 * rng.standard_normal(4000)
t = up.fit_tau_upfront(z, population=up.POPULATION_FLOW, bucket="T")
print("   fallback =", t.fallback, " tau =", t.tau_bps, " h =", t.half_spread_bps)

print()
print("== P6: a tiny/degenerate sample still yields a tau ==")
t = up.fit_tau_upfront([0.1, -0.1], population=up.POPULATION_FLOW, bucket="T")
print("   n=2 ->", t)

print()
print("== P7: NaN inside the fee list ==")
print("   uwin=[5000, nan] lifecycle ->",
      up.resolve_upfront(None, ufros=[7000.0], uwins=[5000.0, float("nan")],
                         is_lifecycle=True))
print("   ufro=[25000, nan] flow     ->",
      up.resolve_upfront(None, ufros=[25_000.0, float("nan")]))

print()
print("== P8: is the module-docstring formula the code's formula? ==")
# docstring line ~105: edge = sign(mid - R) * (|f| - U - b0); npv_pay = (mid-R)*A
npv = +50_000.0            # mid > R  ->  sign(mid - R) = +1
c = up.classify(npv_pay=npv, upfront=10_000.0, structure_dv01=PV01)
doc_edge = math.copysign(1.0, npv) * (abs(npv) - 10_000.0) / PV01
print("   docstring edge =", doc_edge, " code edge =", c.edge_bps)

print()
print("== P9: capped exclusion loses the fee-source and every flag context ==")
c = up.classify(npv_pay=-1e5, upfront=1.0, structure_dv01=PV01, is_capped=True,
                exclude_capped=True, upfront_source=up.SRC_PTP)
print("  ", c)
