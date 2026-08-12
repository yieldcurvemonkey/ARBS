import sys, datetime, math
import pandas as pd
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd\tests")
from SDRUtils.dealer_direction import midprice
import test_dealer_direction_midprice as T

nan = float("nan")
print("== NaN mid, good pv01 ==")
rep = midprice.UnitRepricer(T._FakePricer(mids=[nan], pv01s=[4000.0]))
out = rep.price_unit(T._unit())
print("failure:", out.failure, "| mids:", out.pricing.leg_mid_pct,
      "| dv01:", out.pricing.structure_dv01, "| gross:", out.gross_pv01,
      "| flags:", out.flags)

print("== NaN pv01 ==")
rep = midprice.UnitRepricer(T._FakePricer(mids=[0.04], pv01s=[nan]))
out = rep.price_unit(T._unit())
print("failure:", out.failure, "| mids:", out.pricing.leg_mid_pct,
      "| pv01:", out.pricing.leg_pv01, "| dv01:", out.pricing.structure_dv01,
      "| gross:", out.gross_pv01, "| flags:", out.flags)

print("== NaN mid with upfront (npv path) ==")
rep = midprice.UnitRepricer(T._FakePricer(mids=[nan], pv01s=[4000.0]))
out = rep.price_unit(T._unit(upfront=125_000.0))
print("failure:", out.failure, "| npv:", out.pricing.npv_pay)

print("== zero-leg unit ==")
rep = midprice.UnitRepricer(T._FakePricer())
try:
    u = T._unit(legs=pd.DataFrame(columns=["trade_id","effective_date","expiration_date","notional","fixed_rate"]))
    out = rep.price_unit(u)
    print("failure:", out.failure, "| dv01:", out.pricing.structure_dv01)
except Exception as e:
    print("RAISES", type(e).__name__, e)

print("== served_from_future unknown (None) but lag negative ==")
rep = midprice.UnitRepricer(T._FakePricer(lag=-900.0, from_future=None))
out = rep.price_unit(T._unit())
print("failure:", out.failure, "| lag:", out.pricing.snapshot_lag_seconds, "| flags:", out.flags)
