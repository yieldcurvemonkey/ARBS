import datetime, sys
import pandas as pd
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
from SDRUtils.dealer_direction import midprice, snapshot

NY = "America/New_York"
instant = pd.Timestamp("2026-04-01 14:31:00", tz=NY)
snap = snapshot.snap_instant(instant)
br = midprice.SessionBranchPricer(source=snapshot.CURVE_SOURCE)
cn = br.curve_for("SOFR")
mid = br.price_leg(cn, snap, datetime.date(2026,4,3), datetime.date(2031,4,3), 1e7)
print("mid_pct", mid.mid_pct, "pv01", mid.pv01, "npv", mid.npv_pay)
m = mid.mid_pct / 100.0
for r in (m - 0.0050, m, m + 0.0050):
    lp = br.price_leg(cn, snap, datetime.date(2026,4,3), datetime.date(2031,4,3), 1e7, fixed_rate=r)
    print(f"fixed={r:.6f}  mid={lp.mid_pct:.5f}%  pv01={lp.pv01:,.1f}  npv_pay={lp.npv_pay:,.1f}")
