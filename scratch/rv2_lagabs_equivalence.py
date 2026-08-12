"""Is the reviewer's `lag_abs` mutation still killable after the telemetry fix?

It abs()es `UnitPricing.snapshot_lag_seconds` on the row `price_unit` RETURNS.
After the fix, a negative lag raises CircularCurve inside `price_unit`, so the
mutated line is only ever reached with a non-negative value and abs() is the
identity there. Demonstrated rather than argued.
"""
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests"))

from SDRUtils.dealer_direction import midprice  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
from test_dealer_direction_midprice import _FakePricer, _unit  # noqa: E402

# the mutation, applied by hand
_orig = midprice.UnitRepricer.price_unit


def _mutated(self, unit, *, instant=None):
    out = _orig(self, unit, instant=instant)
    if out.pricing.snapshot_lag_seconds is not None:
        out.pricing.snapshot_lag_seconds = abs(out.pricing.snapshot_lag_seconds)
    return out


for lag in (-900.0, -1.0, 0.0, 60.0, 7200.0):
    for mutated in (False, True):
        midprice.UnitRepricer.price_unit = _mutated if mutated else _orig
        rep = midprice.UnitRepricer(_FakePricer(lag=lag, from_future=None))
        try:
            got = rep.price_unit(_unit()).pricing.snapshot_lag_seconds
        except midprice.CircularCurve:
            got = "CircularCurve"
        print(f"lag={lag:>8}  mutated={mutated!s:<5} -> {got}")
