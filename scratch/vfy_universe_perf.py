"""3.6 re-check: is build_universe still the slow path, and does it still
annotate twice? Synthetic legs only -- no DB."""
import datetime
import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd\tests")

from test_dealer_direction_universe import _frame, _leg  # noqa: E402

from SDRUtils.dealer_direction import universe  # noqa: E402

N = 10_000
legs = _frame(*[
    _leg(trade_id=f"T{i}", package_id=None,
         expiration_date=datetime.date(2028, 6, 18)) for i in range(N)])

t0 = time.perf_counter()
uf = universe.unit_frame(legs)
t1 = time.perf_counter()
units, excl = universe.build_universe(legs)
t2 = time.perf_counter()
print(f"unit_frame     {N:,} legs -> {len(uf):,} units : {t1-t0:6.2f}s")
print(f"build_universe {N:,} legs -> {len(units):,} units : {t2-t1:6.2f}s")
print(f"linear extrapolation to 1,437,838 units: "
      f"{(t2-t1) * 1_437_838 / max(len(units),1) / 60:.1f} min")

# does build_universe annotate twice?
calls = {"n": 0}
real = universe.annotate_legs


def counting(df):
    calls["n"] += 1
    return real(df)


universe.annotate_legs = counting
try:
    universe.build_universe(_frame(_leg()))
finally:
    universe.annotate_legs = real
print(f"annotate_legs calls inside one build_universe: {calls['n']}")
