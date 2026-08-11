import sys, datetime, warnings
import pandas as pd
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
from SDRUtils.dealer_direction import midprice, snapshot
from SDRUtils.dealer_direction.types import Clocks, Unit
NY="America/New_York"

def unit(ts, idx, eff, exp, key, upfront=None):
    legs = pd.DataFrame([{"trade_id":"X","effective_date":eff,"expiration_date":exp,
                          "notional":1e7,"fixed_rate":0.0363}])
    return Unit(unit_key=key, kind="OUTRIGHT", legs=legs, package_id=None,
                rate_index=idx, as_of_date=ts.date(), venue_class="D2C",
                clocks=Clocks(pricing=ts, execution=ts, event=ts, visibility=ts,
                              visibility_source="T"), upfront=upfront)

rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
cases = [
    ("SOFR in-session",  pd.Timestamp("2026-04-01 14:31", tz=NY), "SOFR"),
    ("FF   in-session",  pd.Timestamp("2026-04-01 14:31", tz=NY), "FED_FUNDS"),
    ("SOFR 00:30 hole",  pd.Timestamp("2026-04-02 00:30", tz=NY), "SOFR"),
    ("FF   00:30 hole",  pd.Timestamp("2026-04-02 00:30", tz=NY), "FED_FUNDS"),
    ("SOFR Saturday",    pd.Timestamp("2026-04-04 12:00", tz=NY), "SOFR"),
]
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    for name, ts, idx in cases:
        try:
            out = rep.price_unit(unit(ts, idx, datetime.date(2026,4,3), datetime.date(2031,4,3), name))
            print(f"{name:18s} policy={out.pricing.snapshot_policy:28s} lag={out.pricing.snapshot_lag_seconds} "
                  f"failure={out.failure} mid={out.pricing.leg_mid_pct}")
        except Exception as e:
            print(f"{name:18s} RAISES {type(e).__name__}: {str(e)[:150]}")
