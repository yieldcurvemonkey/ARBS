"""Profile UST Futures timeseries: cold vs warm cache.

Run from worktree: /c/Users/chris/anaconda3/envs/stir/python.exe scripts/profile_ustf.py
"""

import cProfile
import datetime
import io
import logging
import os
import pstats
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

logging.basicConfig(level=logging.WARNING)


def run_ustf_3m():
    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
    from TB.USTFuturesTB import USTFuturesTB
    from TB.TimeseriesBuilder import TimeseriesBuilder
    from Query.USTFutures.USTFutureQuery import USTFutureQuery
    from Query.USTFutures.USTFutureValue import USTFutureValue

    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    tb = TimeseriesBuilder(
        ustfutures_tb=USTFuturesTB(mdp, show_tqdm=True),
    )

    start = datetime.date(2026, 1, 1)
    end = datetime.date(2026, 3, 27)

    queries = [
        USTFutureQuery(symbol="TYM26", value=USTFutureValue.PRICE),
    ]

    df = tb.get_timeseries(start=start, end=end, queries=queries, n_jobs=1)
    return df


if __name__ == "__main__":
    # Run 1: cold cache (first run)
    print("=" * 72)
    print(" UST Futures TYM26 PRICE: 2026-01-01 to 2026-03-27 (Run 1 - cold)")
    print("=" * 72)

    t0 = time.perf_counter()
    pr = cProfile.Profile()
    pr.enable()
    df = run_ustf_3m()
    pr.disable()
    elapsed = time.perf_counter() - t0

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats(30)
    print(s.getvalue())
    print(f"Run 1 wall time: {elapsed:.2f}s")
    print(f"Shape: {df.shape}")
    if not df.empty:
        col = df.columns[0]
        vals = df[col].dropna()
        print(f"Values: [{vals.min():.4f}, {vals.max():.4f}], {len(vals)} rows")

    # Run 2: warm cache (second run, same data)
    print("\n" + "=" * 72)
    print(" UST Futures TYM26 PRICE: 2026-01-01 to 2026-03-27 (Run 2 - warm)")
    print("=" * 72)

    t0 = time.perf_counter()
    df2 = run_ustf_3m()
    elapsed2 = time.perf_counter() - t0

    print(f"Run 2 wall time: {elapsed2:.2f}s")
    print(f"Shape: {df2.shape}")
    print(f"Speedup: {elapsed / max(elapsed2, 0.001):.1f}x")
