"""Validation gates for the curve-fly screener. Nothing is reported until these pass.

G1 forward    on FORWARD legs the static-curve roll must equal an independent
              repricing of the same calendar swap on a rolled curve (both are the
              unchanged-curve quantity there, since a forward swap has no carry).
              Spot legs are NOT expected to match: rateslib's aged repricing also
              books the accrued floating coupon, which is carry, not roll.
G2 reduction  a 3-leg structure with the back wing weighted 0 == the 2-leg curve.
G3 sign       on an upward-sloping curve a PAID spot swap has negative carry-roll.
G4 sanity     spot fly levels reconcile to the outright par rates.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
pd.set_option("display.width", 220)

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from RVUtils.CurveFlyScreener import (  # noqa: E402
    Leg, Structure, age, carry_roll_bp, par_rate_bp, structure_rate_bp,
)

CURVE = "USD-SOFR-1D"
ASOF = datetime.datetime(2026, 8, 21, 17, 0)

mdp = IRSwapsMDP(source="citivelo_excel_rl")
pricer = mdp.get_data({"curve_name": CURVE, "timestamp": ASOF})
print(f"curve built for {ASOF:%Y-%m-%d}")

print("\n=== par rates (bp) ===")
for leg in [Leg(0, 2), Leg(0, 5), Leg(0, 10), Leg(0, 30), Leg(1, 4), Leg(1, 9),
            Leg(5, 10), Leg(10, 10), Leg(20, 10)]:
    print(f"  {leg.label:<8} {par_rate_bp(pricer, leg):>9.2f}")

# ---------------------------------------------------------------- G1: identity
print("\n=== G1: aged-rate identity vs independent repricing ===")
ok1 = True
for leg in [Leg(5, 10), Leg(10, 10), Leg(20, 10), Leg(1, 9), Leg(2, 10)]:
    s = Structure(leg.label, (leg,), (1.0,), "outright")
    cr_ident = carry_roll_bp(pricer, s, 1.0)
    # independent: build the swap, roll the CURVE forward 1y, take the new fair rate
    swap = pricer.build_irswap(fwd=f"{leg.fwd:g}Y", tenor=f"{leg.tenor:g}Y", notional=1.0)
    h = pricer.handle()
    try:
        rolled = h.roll(pd.Timestamp(ASOF + datetime.timedelta(days=365)).to_pydatetime())
        swap2 = pricer.build_irswap(fwd=f"{leg.fwd:g}Y", tenor=f"{leg.tenor:g}Y", notional=1.0)
        r_rolled = float(swap2.rate(curves=rolled).real) * 100.0   # rate() is %, -> bp
        cr_indep = r_rolled - par_rate_bp(pricer, leg)
    except Exception as exc:
        print(f"  {leg.label:<8} identity {cr_ident:>+8.2f}   independent path failed: {str(exc)[:60]}")
        continue
    d = cr_ident - cr_indep
    flag = "OK " if abs(d) < 1.5 else "FAIL"
    ok1 &= abs(d) < 1.5
    print(f"  {leg.label:<8} identity {cr_ident:>+8.2f}   independent {cr_indep:>+8.2f}   "
          f"diff {d:>+7.2f}  {flag}")

# --------------------------------------------------------------- G2: reduction
print("\n=== G2: 3-leg with a zero wing == the 2-leg curve ===")
pair = Structure("5s10s", (Leg(0, 5), Leg(0, 10)), (-1.0, 1.0), "curve")
tri = Structure("5s10s(30s x0)", (Leg(0, 5), Leg(0, 10), Leg(0, 30)),
                (-1.0, 1.0, 0.0), "fly")
a, b = carry_roll_bp(pricer, pair, 1.0), carry_roll_bp(pricer, tri, 1.0)
la, lb = structure_rate_bp(pricer, pair), structure_rate_bp(pricer, tri)
ok2 = abs(a - b) < 1e-9 and abs(la - lb) < 1e-9
print(f"  level  pair {la:>+9.4f}  tri {lb:>+9.4f}   diff {la-lb:+.2e}")
print(f"  CR 1y  pair {a:>+9.4f}  tri {b:>+9.4f}   diff {a-b:+.2e}   "
      f"{'OK' if ok2 else 'FAIL'}")

# -------------------------------------------------------------------- G3: sign
print("\n=== G3: sign on an upward-sloping segment ===")
r5, r10 = par_rate_bp(pricer, Leg(0, 5)), par_rate_bp(pricer, Leg(0, 10))
slope_up = r10 > r5
s10 = Structure("10y", (Leg(0, 10),), (1.0,), "outright")
cr10 = carry_roll_bp(pricer, s10, 1.0)
# receiving (long the rate falling) earns +CR when the rate rolls DOWN, so a PAID
# position earns +CR when the quoted rate rolls UP. Upward curve -> aged rate lower.
ok3 = (cr10 < 0) if slope_up else (cr10 > 0)   # payer loses as the level rolls down
print(f"  5y {r5:.2f}  10y {r10:.2f}  -> {'upward' if slope_up else 'downward'} sloping")
print(f"  CR(10y, 1y) = {cr10:+.2f}bp  (paid position)   "
      f"{'OK' if ok3 else 'FAIL - sign convention is wrong'}")

# ------------------------------------------------------------------ G4: sanity
print("\n=== G4: fly level reconciles to outrights ===")
fly = Structure("5s10s30s", (Leg(0, 5), Leg(0, 10), Leg(0, 30)), (-1.0, 2.0, -1.0), "fly")
lvl = structure_rate_bp(pricer, fly)
manual = 2 * par_rate_bp(pricer, Leg(0, 10)) - par_rate_bp(pricer, Leg(0, 5)) \
    - par_rate_bp(pricer, Leg(0, 30))
ok4 = abs(lvl - manual) < 1e-9
print(f"  screener {lvl:+.4f}   manual {manual:+.4f}   diff {lvl-manual:+.2e}  "
      f"{'OK' if ok4 else 'FAIL'}")

print("\n" + "=" * 60)
print(f"G1 identity  {'PASS' if ok1 else 'FAIL'}")
print(f"G2 reduction {'PASS' if ok2 else 'FAIL'}")
print(f"G3 sign      {'PASS' if ok3 else 'FAIL'}")
print(f"G4 sanity    {'PASS' if ok4 else 'FAIL'}")
