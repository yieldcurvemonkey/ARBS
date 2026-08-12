"""Hand-traced sign example, run through the real functions, plus the
UnitPricing getattr-drift repro."""
import datetime

import pandas as pd

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import health, ladder, provenance
from SDRUtils.dealer_direction import types as T
from SDRUtils.stir_flow import ladder_conventions as legacy

print("=" * 72)
print("OUTRIGHT: printed 4.00%, mid 3.98%  (customer pays fixed above mid)")
print("=" * 72)
P = conv.structure_price([4.00], conv.OUTRIGHT, 1, conv.RULE_RATE)
M = conv.structure_price([3.98], conv.OUTRIGHT, 1, conv.RULE_RATE)
dev = P - M
side = conv.dealer_side(dev)
print(f"  structure_price traded={P} bp  mid={M} bp  deviation={dev:+.1f} bp")
print(f"  dealer_side -> {side}  (DEALER_RECEIVED={conv.DEALER_RECEIVED})")
print(f"  dealer_received_signs = "
      f"{conv.dealer_received_signs(conv.OUTRIGHT, 1, conv.RULE_RATE, side)}")
print(f"  legacy dealer_leg_signs = "
      f"{legacy.dealer_leg_signs('OUTRIGHT', 'RATE_VS_MID', 'RECEIVED', 1)}")
p = 0.90                                   # p(customer paid fixed)
w = conv.signed_weight(p)
dv01_if_received = +4500.0                 # long duration if the dealer received
print(f"  p={p} -> signed_weight={w:+.2f};  delta_dv01 = {w:+.2f} * "
      f"{dv01_if_received:+.1f} = {w * dv01_if_received:+.1f}")
print("  PINNED CONVENTION: customer pays fixed -> dealer RECEIVED -> "
      "delta_dv01 > 0  ->", "OK" if w * dv01_if_received > 0 else "VIOLATED")

print()
print("=" * 72)
print("CURVE 2s5s: base orientation o = pay the BACK leg, receive the FRONT")
print("=" * 72)
o = conv.base_orientation(conv.CURVE, 2, conv.RULE_RATE)
q = conv.quote_weights(conv.CURVE, 2, conv.RULE_RATE)
print(f"  o={o}  q={q}")
Pc = conv.structure_price([3.50, 4.00], conv.CURVE, 2, conv.RULE_RATE)
Mc = conv.structure_price([3.50, 3.98], conv.CURVE, 2, conv.RULE_RATE)
print(f"  traded 2s=3.50 5s=4.00 -> P={Pc:+.1f} bp ; mid 5s=3.98 -> P_mid={Mc:+.1f} bp")
sidec = conv.dealer_side(Pc - Mc)
print(f"  deviation {Pc - Mc:+.1f} -> dealer_side={sidec}")
rs = conv.dealer_received_signs(conv.CURVE, 2, conv.RULE_RATE, sidec)
print(f"  dealer_received_signs={rs}   legacy="
      f"{legacy.dealer_leg_signs('CURVE', 'RATE_VS_MID', 'RECEIVED', 2)}")
print("  reading: base party (= the customer, it overpaid) received the 2s and "
      "paid the 5s;\n           so the dealer PAID the 2s and RECEIVED the 5s "
      f"-> received_signs {rs} ... ")
print("  NOTE the two negations cancel: dealer_received_signs == dealer_sign * o "
      f"= {tuple(sidec * s for s in o)}")

print()
print("=" * 72)
print("orient_to_received round trip")
print("=" * 72)
frame = pd.DataFrame([{"unit_key": "U", "bucket_space": "IRS_KRD",
                       "bucket_key": "5Y", "delta_dv01": -4500.0,
                       "dealer_sign": -1}])
print(ladder.orient_to_received(frame).to_string(index=False))
print("  dealer PAID (-1) and holds -4500 -> if it had RECEIVED it would hold "
      "+4500  ->  correct")

print()
print("=" * 72)
print("R11: provenance.build getattr defaults hide a UnitPricing rename")
print("=" * 72)


class RenamedPricing:
    """A fully-priced unit whose field was renamed snapshot_policy -> policy."""
    curve_name = "USD-SOFR-1D"
    curve_timestamp = pd.Timestamp("2026-06-10T13:59Z")
    lag_seconds = 41.0                 # was snapshot_lag_seconds
    policy = "method=asof max_lag=60s allow_future=False on_miss=raise"


unit = T.Unit(unit_key="U", kind=conv.OUTRIGHT, legs=pd.DataFrame({"trade_id": ["t"]}),
              package_id=None, rate_index="SOFR",
              as_of_date=datetime.date(2026, 6, 10), venue_class=T.VENUE_D2C,
              clocks=T.Clocks(pricing=pd.Timestamp("2026-06-10T14:00Z"),
                              execution=pd.Timestamp("2026-06-10T14:00Z"),
                              event=pd.Timestamp("2026-06-10T14:00Z"),
                              visibility=pd.Timestamp("2026-06-10T15:00Z"),
                              visibility_source="APPENDIX_C_ESTIMATE"))
call = T.DirectionCall(unit_key="U", rule=conv.RULE_RATE, deviation_bps=2.0, p=0.9,
                       signed_weight=conv.signed_weight(0.9), dealer_sign=1)
rec = provenance.build(unit, RenamedPricing(), call,
                       pricing_clock_field="execution_timestamp")
print("  snapshot_policy:", repr(rec.snapshot_policy),
      " snapshot_lag_seconds:", rec.snapshot_lag_seconds,
      " failure_reason:", rec.failure_reason)
f = provenance.to_frame([rec])
print("  health.served_mask ->", list(health.served_mask(f)))
m = health.overnight_hole_fraction(f)
print("  overnight_hole_fraction ->", m.status, m.value, m.detail)
print("  a fully-priced row is reported UNSERVED, the monitor reports NO_DATA, "
      "and nothing raised")
