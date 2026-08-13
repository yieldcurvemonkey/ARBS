import sys, datetime, warnings
import pandas as pd
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
from SDRUtils.dealer_direction import midprice, snapshot
from SDRUtils.dealer_direction.types import Clocks, Unit

NY="America/New_York"
ts = pd.Timestamp("2026-04-01 14:31:00", tz=NY)

def unit(eff, exp, key):
    legs = pd.DataFrame([{"trade_id":"X","effective_date":eff,"expiration_date":exp,
                          "notional":1e7,"fixed_rate":0.0363}])
    return Unit(unit_key=key, kind="OUTRIGHT", legs=legs, package_id=None,
                rate_index="SOFR", as_of_date=ts.date(), venue_class="D2C",
                clocks=Clocks(pricing=ts, execution=ts, event=ts, visibility=ts,
                              visibility_source="T"), upfront=1.0)

rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
cases = [
    ("deep past start 2015", datetime.date(2015,1,5), datetime.date(2031,1,5)),
    ("past start 2020",      datetime.date(2020,1,6), datetime.date(2030,1,6)),
    ("matured leg",          datetime.date(2020,1,6), datetime.date(2024,1,6)),
    ("1-day stub",           datetime.date(2026,4,3), datetime.date(2026,4,6)),
]
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    for name, eff, exp in cases:
        try:
            out = rep.price_unit(unit(eff, exp, name))
            print(f"{name:22s} failure={out.failure} mid={out.pricing.leg_mid_pct} "
                  f"pv01={out.pricing.leg_pv01} dv01={out.pricing.structure_dv01} "
                  f"npv={out.pricing.npv_pay} gross={out.gross_pv01}")
        except Exception as e:
            print(f"{name:22s} RAISES {type(e).__name__}: {str(e)[:120]}")

print("--- details ---")
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    for name, eff, exp in cases[2:]:
        out = rep.price_unit(unit(eff, exp, name))
        print(name, "->", out.failure_detail)
