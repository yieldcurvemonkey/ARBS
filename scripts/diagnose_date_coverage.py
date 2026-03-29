"""Check if RL and QL sources have different date coverage."""

import datetime
import pandas as pd

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

CURVE = "USD-SOFR-1D"
SOURCE_RL = "ERIS_EOD_LIVE-RL_BASIC"
SOURCE_QL = "ERIS_EOD_LIVE-QL_BASIC"

print("Loading MDP instances...")
mdp_rl = IRSwapsMDP(source=SOURCE_RL)
mdp_ql = IRSwapsMDP(source=SOURCE_QL)

START = datetime.date(2024, 1, 2)
END = datetime.date(2024, 12, 31)

# Get available dates for each source
print(f"\nChecking date coverage for {CURVE} ({START} to {END})...")
print("Loading RL dates...")
try:
    rl_dates_raw = mdp_rl.get_bdates({"curve_name": CURVE, "start_date": START, "end_date": END})
    rl_dates = set(rl_dates_raw) if rl_dates_raw is not None else set()
    print(f"  RL: {len(rl_dates)} dates")
except Exception as e:
    print(f"  RL get_bdates failed: {e}")
    # Try loading curves individually
    rl_dates = set()
    bdates = pd.bdate_range(START, END).date
    for d in bdates:
        try:
            c = mdp_rl.get_data({"curve_name": CURVE, "timestamp": d})
            if c is not None:
                rl_dates.add(d)
        except:
            pass
    print(f"  RL (manual scan): {len(rl_dates)} dates")

print("Loading QL dates...")
try:
    ql_dates_raw = mdp_ql.get_bdates({"curve_name": CURVE, "start_date": START, "end_date": END})
    ql_dates = set(ql_dates_raw) if ql_dates_raw is not None else set()
    print(f"  QL: {len(ql_dates)} dates")
except Exception as e:
    print(f"  QL get_bdates failed: {e}")
    ql_dates = set()
    bdates = pd.bdate_range(START, END).date
    for d in bdates:
        try:
            c = mdp_ql.get_data({"curve_name": CURVE, "timestamp": d})
            if c is not None:
                ql_dates.add(d)
        except:
            pass
    print(f"  QL (manual scan): {len(ql_dates)} dates")

if rl_dates and ql_dates:
    common = rl_dates & ql_dates
    rl_only = rl_dates - ql_dates
    ql_only = ql_dates - rl_dates
    print(f"\n  Common dates: {len(common)}")
    print(f"  RL-only dates: {len(rl_only)}")
    print(f"  QL-only dates: {len(ql_only)}")
    if rl_only:
        print(f"    RL-only sample: {sorted(rl_only)[:10]}")
    if ql_only:
        print(f"    QL-only sample: {sorted(ql_only)[:10]}")

# Also check: how does the backtest engine get curves?
print("\n" + "=" * 70)
print("Checking how backtest engine loads curves...")
print("=" * 70)

# Check if get_data returns None or raises for missing dates
test_dates = [datetime.date(2024, 1, 15), datetime.date(2024, 7, 4), datetime.date(2024, 12, 25)]
for d in test_dates:
    for label, mdp in [("RL", mdp_rl), ("QL", mdp_ql)]:
        try:
            c = mdp.get_data({"curve_name": CURVE, "timestamp": d})
            if c is None:
                print(f"  {label} {d}: returned None")
            else:
                print(f"  {label} {d}: OK (ref_date={c.reference_date()})")
        except Exception as e:
            print(f"  {label} {d}: Error: {type(e).__name__}: {e}")
