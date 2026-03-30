"""
Profile GSQUANT-RL IRS 11Y swap: 2010-01-01 to 2026-03-27
Identifies whether the bottleneck is CurveStore Parquet reads,
rateslib pricing, GS Quant API calls, or something else.

Run: /c/Users/chris/anaconda3/envs/stir/python.exe scripts/profile_gsquant.py
"""

import cProfile
import datetime
import io
import logging
import os
import pstats
import sys
import time

REPO_ROOT = r"C:\Users\chris\clee\ARBS"
os.chdir(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

logging.basicConfig(level=logging.WARNING)


def run_gsquant_11y():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from TB.IRSwapsTB import IRSwapsTB
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.TimeseriesBuilder import TimeseriesBuilder

    curve_mdp = IRSwapsMDP(source="GSQUANT-RL")
    usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")

    ts_builder = TimeseriesBuilder()

    start = datetime.date(2010, 1, 1)
    end = datetime.date(2026, 3, 27)

    df = ts_builder.get_timeseries(
        start=start,
        end=end,
        queries=[
            UnifiedQuery(
                curve="USD-OIS",
                tenor="11Y",
                value=UnifiedValue.IRS_RATE,
            ),
        ],
        n_jobs=12,
        routers={
            "IRS": IRSwapsTB(curve_mdp, show_tqdm=True),
            "FRB": FixedRateBondsTB(usts_mdp, show_tqdm=True),
        },
        ignore_cache_miss=True,
    )
    return df


if __name__ == "__main__":
    print("="*72)
    print(" GSQUANT-RL USD-OIS 11Y Swap: 2010-01-01 to 2026-03-27")
    print("="*72)

    t0 = time.perf_counter()

    pr = cProfile.Profile()
    pr.enable()
    try:
        df = run_gsquant_11y()
    except Exception as e:
        pr.disable()
        print(f"ERROR: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    pr.disable()

    elapsed = time.perf_counter() - t0

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats(50)
    print(s.getvalue())

    print(f"Wall time: {elapsed:.2f}s")
    print(f"Result shape: {df.shape}")
    if not df.empty:
        print(f"Columns: {list(df.columns)}")
        print(f"Date range: {df.index[0]} to {df.index[-1]}")
        col = df.columns[0]
        vals = df[col].dropna()
        print(f"Values: [{vals.min():.4f}, {vals.max():.4f}], {len(vals)} non-NaN rows")
