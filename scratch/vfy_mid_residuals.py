"""Verification pass: residual behaviours the midprice fixes did NOT change.

Each block is a claim I make in the verification report, measured rather than
read off the source.
"""
import dataclasses
import datetime
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
_ROOT = r"C:\Users\chris\clee\ARBS-dd"
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import pandas as pd  # noqa: E402

from SDRUtils.dealer_direction import midprice  # noqa: E402
import test_dealer_direction_midprice as T  # noqa: E402

print("== LegQuote fields (is _MARKS a field?) ==")
print([f.name for f in dataclasses.fields(midprice.LegQuote)])

print("\n== a governed refusal still records an EMPTY snapshot_policy ==")
rep = midprice.UnitRepricer(T._FakePricer(governed=True))
out = rep.price_unit(T._unit(rate_index="BASIS"))
print("failure:", out.failure, "| policy:", repr(out.pricing.snapshot_policy),
      "| flags:", out.flags)

print("\n== the legacy refusal, for contrast ==")
rep = midprice.UnitRepricer(T._FakePricer(governed=False))
out = rep.price_unit(T._unit(rate_index="BASIS"))
print("failure:", out.failure, "| policy:", repr(out.pricing.snapshot_policy))

print("\n== ORDERING: a dateless leg that ALSO has no fixed rate, on the upfront route ==")
legs = T._legs([{"trade_id": "A", "effective_date": None,
                 "expiration_date": datetime.date(2031, 4, 3), "notional": 1e7,
                 "fixed_rate": None}])
out = midprice.UnitRepricer(T._FakePricer()).price_unit(
    T._unit(legs=legs, upfront=125_000.0))
print("failure:", out.failure, "| detail:", out.failure_detail)
print("  (was EXCL_NO_FIXED_RATE before the fix: START_UNKNOWN now preempts it)")

print("\n== public start_class(None, ...) still raises -- guarded at the caller only ==")
try:
    midprice.start_class(None, T.IN_SESSION)
    print("no raise")
except Exception as e:
    print("raises", type(e).__name__, e)

print("\n== a zero-leg unit still raises out of price_unit (pre-existing, not a review defect) ==")
empty = pd.DataFrame(columns=["trade_id", "effective_date", "expiration_date",
                              "notional", "fixed_rate"])
try:
    midprice.UnitRepricer(T._FakePricer()).price_unit(T._unit(legs=empty))
    print("no raise")
except Exception as e:
    print("raises", type(e).__name__, e)

print("\n== None marks are still 'ok' under the new contract (unreachable via _price_one) ==")
q = midprice.LegQuote(trade_id="T", start_class=midprice.START_SPOT,
                      is_capped=False, mid_pct=None, pv01=None)
print("ok:", q.ok, "| failure:", q.failure)

print("\n== inf marks ARE caught ==")
q = midprice.LegQuote(trade_id="T", start_class=midprice.START_SPOT,
                      is_capped=False, mid_pct=float("inf"), pv01=4000.0)
print("ok:", q.ok, "| failure:", q.failure, "| detail:", q.failure_detail)

print("\n== a NaN pv01 out of the real seam -> named failure, no gross_pv01 ==")
rep = midprice.UnitRepricer(T._FakePricer(pv01s=[float("inf")]))
out = rep.price_unit(T._unit())
print("failure:", out.failure, "| detail:", out.failure_detail,
      "| gross:", out.gross_pv01, "| dv01:", out.pricing.structure_dv01)
