"""Which spot tenors are actually WARM in the computed-timeseries store?

A warm tenor-day returns in ~1-3 s off disk; a cold one reprices at ~13 ms/minute
(~19 s for one day). Probe one ordinary day and time it. Known-answer anchor: 10y and
1m were both measured warm earlier (7.6 s and 1.9 s for a full day including import).
"""
import os, sys, time
os.environ["ARBS_SUPABASE_ENABLED"] = "0"
os.environ.setdefault("ARBS_RL_OMIT_UNUSED_FIXINGS", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapValue
from TB.IRSwapsTB import IRSwapsTB
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

TENORS = ["1m", "2m", "3m", "4m", "5m", "6m", "9m", "1y", "15m", "18m", "21m",
          "2y", "3y", "4y", "5y", "6y", "7y", "8y", "9y", "10y", "11y", "12y",
          "15y", "20y", "25y", "30y", "40y", "50y"]

tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False,
               use_ts_cache=True, use_duckdb=False,
               ts_base_dir=os.path.join(os.path.dirname(os.path.dirname(
                   os.path.abspath(__file__))), "data", "ts"))
s = pd.Timestamp("2026-07-15 12:00", tz="UTC").to_pydatetime()
e = pd.Timestamp("2026-07-15 13:00", tz="UTC").to_pydatetime()
print(f"{'tenor':6s} {'secs':>7s} {'rows':>6s}  verdict")
warm = []
for tn in TENORS:
    t = time.time()
    try:
        ts = tb.get_timeseries(start=s, end=e,
                               queries=[IRSwapQuery(curve="USD-SOFR-1D", tenor=tn,
                                                    value=IRSwapValue.RATE)], freq="1min")
        dt = time.time() - t
        n = 0 if ts is None else int(ts.iloc[:, 0].notna().sum())
    except Exception as exc:
        dt = time.time() - t
        n = -1
        print(f"{tn:6s} {dt:7.2f} {n:6d}  ERROR {type(exc).__name__}")
        continue
    ok = dt < 3.0 and n > 50
    if ok:
        warm.append(tn)
    print(f"{tn:6s} {dt:7.2f} {n:6d}  {'WARM' if ok else 'cold/absent'}")
print()
print("WARM =", warm)
