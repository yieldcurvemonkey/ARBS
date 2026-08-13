"""Worked sign trace: legs -> universe order -> conventions -> dealer signs."""
import datetime
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd\tests")

from test_dealer_direction_universe import _frame, _leg  # noqa: E402

from SDRUtils.dealer_direction import conventions as cv, universe  # noqa: E402
from SDRUtils.stir_flow import ladder_conventions as lc  # noqa: E402

# a 2s5s10s fly, fed to the builder in DELIBERATELY WRONG row order
legs = _frame(
    _leg(trade_id="BACK", package_id="PF", fixed_rate=0.0420,
         expiration_date=datetime.date(2036, 6, 18)),
    _leg(trade_id="BELLY", package_id="PF", fixed_rate=0.0406,
         expiration_date=datetime.date(2031, 6, 18)),
    _leg(trade_id="FRONT", package_id="PF", fixed_rate=0.0390,
         expiration_date=datetime.date(2028, 6, 18)),
)
unit = universe.build_units(legs)[0]
print("order after annotate_legs :", list(unit.legs["trade_id"]))
print("iloc[1] (must be BELLY)   :", unit.legs.iloc[1]["trade_id"])

traded_pct = [3.90, 4.06, 4.20]   # front, belly, back -- percent
mid_pct = [3.90, 4.05, 4.20]

p_tr = cv.structure_price(traded_pct, unit.kind, unit.n_legs, cv.RULE_RATE)
p_md = cv.structure_price(mid_pct, unit.kind, unit.n_legs, cv.RULE_RATE)
dev = p_tr - p_md
side = cv.dealer_side(dev)
o = cv.base_orientation(unit.kind, unit.n_legs, cv.RULE_RATE)
q = cv.quote_weights(unit.kind, unit.n_legs, cv.RULE_RATE)
recv = cv.dealer_received_signs(unit.kind, unit.n_legs, cv.RULE_RATE, side)
frozen = lc.dealer_leg_signs("FLY", "SPREAD_VS_MID", "RECEIVED" if side == 1 else "PAID", 3)

print(f"o (pay_signs)             : {o}   (+1 = base party PAYS fixed)")
print(f"q (quote weights)         : {q}   sign(q)==o: {all((qq > 0) == (oo > 0) for qq, oo in zip(q, o))}")
print(f"P_traded / P_mid (bp)     : {p_tr:.4f} / {p_md:.4f}")
print(f"deviation (bp)            : {dev:+.4f}")
print(f"dealer_side               : {side:+d}  ({'RECEIVED' if side == 1 else 'PAID'})")
print(f"dealer_received_signs     : {recv}   (+1 = dealer RECEIVED fixed on that leg)")
print(f"frozen dealer_leg_signs   : {frozen}   match={list(recv) == list(frozen)}")
for p in (0.5, 0.8, 0.2):
    print(f"  p(customer paid fixed)={p:.1f} -> signed_weight {cv.signed_weight(p):+.2f}")

print()
print("interpretation: customer PAID the belly 1bp above mid -> dealer RECEIVED")
print("the belly (recv[1]=+1) -> dealer long belly duration -> delta_dv01>0 at the")
print("belly bucket, which is the pinned convention.")

print()
print("--- CURVE cross-check ---")
legs2 = _frame(
    _leg(trade_id="BACK", package_id="PC", fixed_rate=0.0420,
         expiration_date=datetime.date(2036, 6, 18)),
    _leg(trade_id="FRONT", package_id="PC", fixed_rate=0.0390,
         expiration_date=datetime.date(2028, 6, 18)),
)
c = universe.build_units(legs2)[0]
print("order      :", list(c.legs["trade_id"]))
p_tr = cv.structure_price([3.90, 4.21], c.kind, 2, cv.RULE_RATE)
p_md = cv.structure_price([3.90, 4.20], c.kind, 2, cv.RULE_RATE)
s = cv.dealer_side(p_tr - p_md)
print(f"spread traded/mid (bp): {p_tr:.2f}/{p_md:.2f}  dev {p_tr - p_md:+.2f}  side {s:+d}")
print("recv signs :", cv.dealer_received_signs(c.kind, 2, cv.RULE_RATE, s),
      " frozen:", lc.dealer_leg_signs("CURVE", "X", "RECEIVED" if s == 1 else "PAID", 2))

print()
print("--- UPFRONT rule frame ---")
for n in (1, 2, 3, 5):
    print(f"  n={n} o={cv.base_orientation('PKG', n, cv.RULE_UPFRONT)} "
          f"recv(+1)={cv.dealer_received_signs('PKG', n, cv.RULE_UPFRONT, 1)} "
          f"frozen={lc.dealer_leg_signs('PKG', 'NPV_VS_UPFRONT', 'RECEIVED', n)}")
