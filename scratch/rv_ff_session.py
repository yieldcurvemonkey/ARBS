import sys, pandas as pd
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
from SDRUtils.dealer_direction import snapshot, midprice
NY="America/New_York"
for cn in ("USD-SOFR-1D","USD-FEDFUNDS-1D","USD-SOFR-1D-Q12xM12STIRT","NOT-A-CURVE"):
    for ts in (pd.Timestamp("2026-04-01 14:30",tz=NY), pd.Timestamp("2026-04-02 00:30",tz=NY),
               pd.Timestamp("2026-04-04 12:00",tz=NY)):  # Saturday
        try:
            r = snapshot.in_session(cn, ts)
        except Exception as e:
            r = f"RAISES {type(e).__name__}: {e}"
        print(f"{cn:28s} {ts} -> {r}")
