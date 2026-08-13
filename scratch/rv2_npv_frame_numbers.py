"""The numbers behind the new real-path payer-frame test, printed."""
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)
sys.path.insert(0, os.path.join(root, "tests"))

import pandas as pd  # noqa: E402

from SDRUtils.dealer_direction import midprice, snapshot  # noqa: E402
from test_dealer_direction_midprice import IN_SESSION, _legs, _unit  # noqa: E402
import datetime  # noqa: E402

rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
for over in (0.0413, 0.0363, 0.0313):
    legs = _legs([{"trade_id": "R", "effective_date": datetime.date(2026, 4, 3),
                   "expiration_date": datetime.date(2031, 4, 3),
                   "notional": 1e7, "fixed_rate": over}])
    out = rep.price_unit(_unit(legs=legs, upfront=1.0,
                               pricing_ts=IN_SESSION + pd.Timedelta(minutes=1)))
    mid, pv01 = out.pricing.leg_mid_pct[0] / 100.0, out.pricing.leg_pv01[0]
    pred = (mid - over) * 1e4 * pv01
    print(f"fixed={over:.4%}  mid={mid:.6%}  pv01={pv01:.2f}  "
          f"npv_pay={out.pricing.npv_pay:>12,.1f}  (mid-fixed)*1e4*pv01={pred:>12,.1f}  "
          f"rel={abs(out.pricing.npv_pay - pred) / max(abs(pred), 1):.2e}")
