"""Adversarial-review repros for SDRUtils.dealer_direction.universe. Read-only."""
import datetime
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd\tests")

from test_dealer_direction_universe import _frame, _leg  # noqa: E402

from SDRUtils.dealer_direction import universe  # noqa: E402

print("=" * 78)
print("R1  EOD fallback: date-only event stamp -> visibility BEFORE the trade")
print("=" * 78)
legs = _frame(_leg(
    lifecycle_type="TERMINATION",
    execution_timestamp=pd.Timestamp("2024-04-01 14:15:36", tz="UTC"),
    original_execution_timestamp=pd.Timestamp("2024-04-01 14:15:36", tz="UTC"),
    event_timestamp=pd.Timestamp("2026-06-16 00:00:00", tz="UTC"),
    event_timestamp_granularity="DATE",
))
units, excl = universe.build_universe(legs)
u = units[0]
print("  pricing            :", repr(u.clocks.pricing), type(u.clocks.pricing).__name__)
print("  visibility         :", repr(u.clocks.visibility))
print("  visibility_source  :", u.clocks.visibility_source)
print("  execution          :", repr(u.clocks.execution))
print("  visibility tz-aware:", u.clocks.visibility.tzinfo is not None)
print("  vis < exec (2024)? :", u.clocks.visibility < pd.Timestamp("2024-04-01 14:15:36"))
try:
    _ = u.clocks.visibility > u.clocks.execution
    print("  compare vis>exec   : ok")
except TypeError as e:
    print("  compare vis>exec   : TypeError ->", e)

print()
print("=" * 78)
print("R2  builder vs report: lifecycle leg with no event_timestamp")
print("=" * 78)
legs = _frame(_leg(lifecycle_type="TERMINATION", event_timestamp=None))
uf = universe.unit_frame(legs)
print("  unit_frame rows    :", len(uf), " exclusion:", uf["exclusion"].tolist())
rep = universe.summarise(legs)
print("  summarise kept     :", rep["kept_units"], " excluded:", rep["excluded_units"])
try:
    units, excl = universe.build_universe(legs)
    print("  build_universe     :", len(units), "kept /", len(excl), "excluded")
except Exception as e:
    print(f"  build_universe     : RAISED {type(e).__name__}: {e}")

print()
print("=" * 78)
print("R3  mixed rate_index package (both indices supported)")
print("=" * 78)
legs = _frame(
    _leg(trade_id="A", package_id="PX", rate_index_clean="SOFR",
         expiration_date=datetime.date(2028, 6, 18)),
    _leg(trade_id="B", package_id="PX", rate_index_clean="FED_FUNDS",
         expiration_date=datetime.date(2031, 6, 18)),
)
uf = universe.unit_frame(legs)
print("  exclusion:", uf["exclusion"].tolist(), " rate_index:", uf["rate_index"].tolist())

print()
print("=" * 78)
print("R4  on_facility for off-facility / unknown codes and the delay it buys")
print("=" * 78)
for pid in ("TWSF", "BILT", "XXXX", "XOFF", "TREU", "RTXF", "ZZZZ", None):
    legs = _frame(_leg(platform_identifier=pid, cleared="N"))
    units, _e = universe.build_universe(legs)
    v = units[0].clocks
    print(f"  {str(pid):<6} on_facility={str(universe.on_facility(pid)):<5} "
          f"venue={universe.classify_venue(pid):<12} {v.visibility_source:<40} "
          f"delay={(v.visibility - v.pricing)}")

print()
print("=" * 78)
print("R5  exclusion_detail for the term-SOFR / PKG-4+ / mixed-index paths")
print("=" * 78)
cases = {
    "term sofr": [_leg(leg_tape_label="USD CME Term SOFR 3M 5Y")],
    "term sofr lowercase": [_leg(leg_tape_label="usd cme term sofr 3m 5y")],
    "TERM SOFR upper": [_leg(leg_tape_label="USD CME TERM SOFR 3M 5Y")],
    "mixed index": [
        _leg(trade_id="A", package_id="PX", rate_index_clean="SOFR",
             expiration_date=datetime.date(2028, 6, 18)),
        _leg(trade_id="B", package_id="PX", rate_index_clean="FED_FUNDS",
             expiration_date=datetime.date(2031, 6, 18))],
    "pkg-4": [_leg(trade_id=f"T{i}", package_id="PX",
                   expiration_date=datetime.date(2028 + i, 6, 18)) for i in range(4)],
}
for name, lg in cases.items():
    uf = universe.unit_frame(_frame(*lg))
    print(f"  {name:<22} -> {uf['exclusion'].tolist()} / {uf['exclusion_detail'].tolist()}")

print()
print("=" * 78)
print("R6  NULL lifecycle_type -> is_lifecycle True?")
print("=" * 78)
legs = _frame(_leg(lifecycle_type=None))
units, _e = universe.build_universe(legs)
print("  is_lifecycle:", units[0].is_lifecycle, " pricing:", units[0].clocks.pricing)

print()
print("=" * 78)
print("R7  NEW_TRADE with original_execution_timestamp != execution_timestamp")
print("=" * 78)
legs = _frame(_leg(
    lifecycle_type="NEW_TRADE",
    original_execution_timestamp=pd.Timestamp("2024-01-05 09:00:00", tz="UTC"),
    execution_timestamp=pd.Timestamp("2026-06-16 14:15:36", tz="UTC"),
    event_timestamp=pd.Timestamp("2026-06-16 14:15:36", tz="UTC"),
))
units, _e = universe.build_universe(legs)
c = units[0].clocks
print("  pricing   :", c.pricing)
print("  execution :", c.execution)
print("  visibility:", c.visibility)

print()
print("=" * 78)
print("R8  empty frame / all-excluded frame behaviour")
print("=" * 78)
empty = pd.DataFrame(columns=list(_leg().keys()))
try:
    units, excl = universe.build_universe(empty)
    print("  empty -> ", len(units), len(excl))
    print("  summarise ->", {k: v for k, v in universe.summarise(empty).items()
                             if not isinstance(v, pd.DataFrame)})
except Exception as e:
    print(f"  empty RAISED {type(e).__name__}: {e}")

print()
print("=" * 78)
print("R9  upfront sign is dropped (abs) - offsetting fees")
print("=" * 78)
legs = _frame(
    _leg(trade_id="A", package_id="PZ", expiration_date=datetime.date(2028, 6, 18),
         other_payment_ufro=100_000.0),
    _leg(trade_id="B", package_id="PZ", expiration_date=datetime.date(2031, 6, 18),
         other_payment_ufro=-100_000.0),
)
units, excl = universe.build_universe(legs)
print("  upfront:", units[0].upfront if units else excl["upfront"].tolist(),
      " source:", units[0].upfront_source if units else None)
legs2 = _frame(_leg(other_payment_ufro=-250_000.0))
units2, _e = universe.build_universe(legs2)
print("  single negative UFRO -> upfront:", units2[0].upfront,
      "source:", units2[0].upfront_source)

print()
print("=" * 78)
print("R10 duplicate trade_id across packages / unit_key collision")
print("=" * 78)
legs = _frame(
    _leg(trade_id="T1", package_id=None),
    _leg(trade_id="T1", package_id=None, leg_order=1,
         expiration_date=datetime.date(2031, 6, 18)),
)
uf = universe.unit_frame(legs)
print("  units:", len(uf), uf["unit_key"].tolist(), uf["kind"].tolist())
