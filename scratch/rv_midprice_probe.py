import datetime, sys
import pandas as pd
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd\tests")

from SDRUtils.dealer_direction import midprice, snapshot
from SDRUtils.dealer_direction.types import Clocks, Unit

import test_dealer_direction_midprice as T

print("== pd.NaT.date() ==")
try:
    print(repr(pd.NaT.date()))
except Exception as e:
    print("raises", type(e).__name__, e)

print("== start_class(None, ts) ==")
try:
    print(midprice.start_class(None, T.IN_SESSION))
except Exception as e:
    print("raises", type(e).__name__, e)

print("== _price_one with missing effective_date on the PRICING path ==")
legs = T._legs([{"trade_id": "A", "effective_date": None,
                 "expiration_date": datetime.date(2031, 4, 3), "notional": 1e7,
                 "fixed_rate": 0.041}])
rep = midprice.UnitRepricer(T._FakePricer())
try:
    out = rep.price_unit(T._unit(legs=legs))   # rate_index SOFR -> reaches _price_one
    print("returned:", out.failure, out.legs[0].start_class)
except Exception as e:
    print("RAISES OUT OF price_unit:", type(e).__name__, e)
