"""Reviewer harness: the pinned sign trace, worked with numbers.

Validated against a case whose answer is already known -- the frozen
predecessor `stir_flow.ladder_conventions.dealer_leg_signs` -- BEFORE it is
pointed at krd.py, which does not exist yet.

What krd.py must satisfy, derived from the downstream contract in
ladder.py:78-186 (`KRD_VALUE_COL = "dv01_if_received"`, and `_validated_krd`
raising DoubleSignedKRD when a frame carries `dealer_sign` instead):

    dv01_if_received[i] = base_orientation(kind, n, rule)[i] * pv01[i]

i.e. the profile the dealer would hold IF dealer_sign == DEALER_RECEIVED,
with pv01 > 0, and NO dealer_sign factor and NO 2p-1 factor applied.
"""
from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.stir_flow import ladder_conventions as frozen

FAILURES: list[str] = []


def check(name: str, got, want) -> None:
    if isinstance(got, float) and isinstance(want, float):
        ok = abs(got - want) < 1e-12
    else:
        ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got!r} want {want!r}")
    if not ok:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# 1. the harness against the known answer: the frozen predecessor
#
# `dealer_received_signs` claims (conventions.py:197) to reproduce
# `stir_flow.ladder_conventions.dealer_leg_signs` exactly. Check it here, on
# every case the frozen function supports, before trusting the harness on
# anything krd.py produces.
# ---------------------------------------------------------------------------
print("== harness validation vs the frozen stir_flow.ladder_conventions ==")
_CASES = [
    (conv.OUTRIGHT, 1, conv.RULE_RATE, "OUTRIGHT"),
    (conv.CURVE, 2, conv.RULE_RATE, "CURVE"),
    (conv.FLY, 3, conv.RULE_RATE, "FLY"),
    (conv.PKG, 4, conv.RULE_UPFRONT, "PKG"),
    (conv.OUTRIGHT, 1, conv.RULE_UPFRONT, "OUTRIGHT"),
]
for kind, n, rule, frozen_kind in _CASES:
    for ds_, direction in ((conv.DEALER_RECEIVED, "RECEIVED"),
                           (conv.DEALER_PAID, "PAID")):
        got = list(conv.dealer_received_signs(kind, n, rule, ds_))
        want = frozen.dealer_leg_signs(frozen_kind, rule, direction, n)
        check(f"frozen tie-out {kind}/{n}/{rule}/{direction}", got, want)

# ---------------------------------------------------------------------------
# 2. the pinned example, worked by hand, OUTRIGHT
#
#    customer pays fixed -> dealer RECEIVED fixed -> delta_dv01 > 0
# ---------------------------------------------------------------------------
print("\n== pinned example: OUTRIGHT 10Y, pv01 = 900 USD/bp ==")
PV01 = 900.0

o = conv.base_orientation(conv.OUTRIGHT, 1, conv.RULE_RATE)
check("base_orientation OUTRIGHT (pay_signs, +1 = base pays fixed)", o, (1,))

# the customer paid fixed, so the print came in ABOVE mid for the base party
# (the base party IS the payer here), so deviation > 0.
dev_bps = +0.25
ds = conv.dealer_side(dev_bps)
check("dealer_side(+0.25bp)", ds, conv.DEALER_RECEIVED)

rs = conv.dealer_received_signs(conv.OUTRIGHT, 1, conv.RULE_RATE, ds)
check("dealer_received_signs (+1 = dealer received)", rs, (1,))

# the hypothesis frame: what the dealer holds IF the dealer received.
dv01_if_received = tuple(s * PV01 for s in o)
check("dv01_if_received", dv01_if_received, (900.0,))

p = 0.80
w = conv.signed_weight(p)
check("signed_weight(0.80)", w, 0.6)
delta = tuple(w * v for v in dv01_if_received)
print(f"      delta_dv01 = {delta}  -> must be > 0 (dealer received, long duration)")
if delta[0] <= 0:
    FAILURES.append("delta_dv01 sign on the pinned example")

# and the mirror: customer received fixed -> dealer PAID -> delta_dv01 < 0
ds2 = conv.dealer_side(-0.25)
check("dealer_side(-0.25bp)", ds2, conv.DEALER_PAID)
p2 = 0.20
w2 = conv.signed_weight(p2)
check("signed_weight(0.20)", w2, -0.6)
delta2 = w2 * dv01_if_received[0]
print(f"      delta_dv01 = {delta2}  -> must be < 0")
if delta2 >= 0:
    FAILURES.append("delta_dv01 sign on the mirrored example")

# ---------------------------------------------------------------------------
# 3. CURVE: the two legs must come out OPPOSITE in dv01_if_received
# ---------------------------------------------------------------------------
print("\n== CURVE 2s10s: pv01 = (200, 900) ==")
oc = conv.base_orientation(conv.CURVE, 2, conv.RULE_RATE)
check("base_orientation CURVE", oc, (-1, 1))
pv01c = (200.0, 900.0)
krd_c = tuple(s * v for s, v in zip(oc, pv01c))
check("dv01_if_received CURVE", krd_c, (-200.0, 900.0))
if krd_c[0] * krd_c[1] >= 0:
    FAILURES.append("CURVE legs are not opposite in dv01_if_received")

# ---------------------------------------------------------------------------
# 4. FLY: belly opposite the wings, and quote weights are NOT hedge ratios
# ---------------------------------------------------------------------------
print("\n== FLY 5s10s30s ==")
of = conv.base_orientation(conv.FLY, 3, conv.RULE_RATE)
check("base_orientation FLY", of, (-1, 1, -1))
check("quote_weights FLY (2*belly - wings)", conv.quote_weights(conv.FLY, 3, conv.RULE_RATE),
      (-1.0, 2.0, -1.0))

# ---------------------------------------------------------------------------
# 5. the upfront rule uses the NET-FIXED frame: every leg the same sign
# ---------------------------------------------------------------------------
print("\n== upfront rule orientation ==")
check("base_orientation PKG-4 under RULE_UPFRONT",
      conv.base_orientation(conv.PKG, 4, conv.RULE_UPFRONT), (1, 1, 1, 1))
try:
    conv.base_orientation(conv.PKG, 4, conv.RULE_RATE)
    FAILURES.append("PKG-4 under RULE_RATE should raise UnorientableUnit")
    print("FAIL  PKG-4 RULE_RATE did not raise")
except conv.UnorientableUnit:
    print("PASS  PKG-4 RULE_RATE raises UnorientableUnit")

print("\n" + ("ALL CHECKS PASS" if not FAILURES else f"FAILURES: {FAILURES}"))
raise SystemExit(1 if FAILURES else 0)
