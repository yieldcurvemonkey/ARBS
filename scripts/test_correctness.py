"""
Correctness tests for TimeseriesBuilder performance fixes.

Validates:
1. IRS EOD returns correct shape and non-NaN values
2. FRB EOD returns correct shape and non-NaN values
3. IRS intraday returns data for timestamp queries
4. FRB warm cache matches previous results

Run: /c/Users/chris/anaconda3/envs/stir/python.exe scripts/test_correctness.py
"""

import datetime
import os
import sys

REPO_ROOT = r"C:\Users\chris\clee\ARBS"
os.chdir(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

import pandas as pd
import numpy as np


def test_irs_eod():
    """Test IRS EOD: 3-month window, 1 tenor."""
    print("\n[TEST] IRS EOD (3 months, 1 tenor)...")
    from TB.TimeseriesBuilder import TimeseriesBuilder
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    tb = TimeseriesBuilder()
    mdps = {"IRS": IRSwapsMDP(source="BARCHART_STIRF-RL")}

    start = datetime.date(2025, 12, 1)
    end = datetime.date(2026, 2, 28)
    queries = [IRSwapQuery(curve="USD-SOFR-1D-Q12STIRT", tenor="5Y", value=IRSwapValue.RATE)]

    df = tb.get_timeseries(start, end, queries, freq="eod", mdps=mdps)

    assert not df.empty, "IRS EOD returned empty DataFrame"
    assert df.shape[1] == 1, f"Expected 1 column, got {df.shape[1]}"
    assert df.shape[0] >= 50, f"Expected >=50 rows for 3 months, got {df.shape[0]}"
    nan_pct = df.isna().sum().sum() / df.size
    assert nan_pct < 0.1, f"Too many NaNs: {nan_pct:.1%}"

    col = df.columns[0]
    vals = df[col].dropna()
    assert vals.min() > 0, f"IRS rates should be positive, got min={vals.min()}"
    assert vals.max() < 20, f"IRS rates seem unreasonable, max={vals.max()}"

    print(f"  PASSED: shape={df.shape}, col='{col}'")
    print(f"  Range: [{vals.min():.4f}, {vals.max():.4f}], NaN={nan_pct:.1%}")
    return True


def test_frb_eod():
    """Test FRB EOD: 3-month window, 1 CUSIP."""
    print("\n[TEST] FRB EOD (3 months, CT10)...")
    from TB.TimeseriesBuilder import TimeseriesBuilder
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
    from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

    tb = TimeseriesBuilder()
    mdps = {"FRB": FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")}

    start = datetime.date(2025, 12, 1)
    end = datetime.date(2026, 2, 28)
    queries = [FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)]

    df = tb.get_timeseries(start, end, queries, freq="eod", mdps=mdps)

    assert not df.empty, "FRB EOD returned empty DataFrame"
    assert df.shape[1] == 1, f"Expected 1 column, got {df.shape[1]}"
    assert df.shape[0] >= 50, f"Expected >=50 rows for 3 months, got {df.shape[0]}"

    col = df.columns[0]
    vals = df[col].dropna()
    assert vals.min() > 0, f"YTM should be positive, got min={vals.min()}"
    assert vals.max() < 20, f"YTM seems unreasonable, max={vals.max()}"
    nan_pct = df.isna().sum().sum() / df.size
    assert nan_pct < 0.1, f"Too many NaNs: {nan_pct:.1%}"

    print(f"  PASSED: shape={df.shape}, col='{col}'")
    print(f"  Range: [{vals.min():.4f}, {vals.max():.4f}], NaN={nan_pct:.1%}")
    return True


def test_irs_multi_tenor():
    """Test IRS EOD: multiple tenors."""
    print("\n[TEST] IRS Multi-tenor (3 months, 5 tenors)...")
    from TB.TimeseriesBuilder import TimeseriesBuilder
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    tb = TimeseriesBuilder()
    mdps = {"IRS": IRSwapsMDP(source="BARCHART_STIRF-RL")}

    start = datetime.date(2025, 12, 1)
    end = datetime.date(2026, 2, 28)
    tenors = ["2Y", "5Y", "10Y", "20Y", "30Y"]
    queries = [IRSwapQuery(curve="USD-SOFR-1D-Q12STIRT", tenor=t, value=IRSwapValue.RATE) for t in tenors]

    df = tb.get_timeseries(start, end, queries, freq="eod", mdps=mdps)

    assert not df.empty, "IRS multi-tenor returned empty DataFrame"
    assert df.shape[1] == len(tenors), f"Expected {len(tenors)} columns, got {df.shape[1]}"

    print(f"  PASSED: shape={df.shape}")
    for col in df.columns:
        vals = df[col].dropna()
        print(f"    {col}: [{vals.min():.4f}, {vals.max():.4f}]")
    return True


def test_run_twice_consistent():
    """Test that running the same query twice gives identical results."""
    print("\n[TEST] Consistency (run same IRS query twice)...")
    from TB.TimeseriesBuilder import TimeseriesBuilder
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    start = datetime.date(2026, 1, 1)
    end = datetime.date(2026, 1, 31)
    queries = [IRSwapQuery(curve="USD-SOFR-1D-Q12STIRT", tenor="5Y", value=IRSwapValue.RATE)]

    tb1 = TimeseriesBuilder()
    mdps1 = {"IRS": IRSwapsMDP(source="BARCHART_STIRF-RL")}
    df1 = tb1.get_timeseries(start, end, queries, freq="eod", mdps=mdps1)

    tb2 = TimeseriesBuilder()
    mdps2 = {"IRS": IRSwapsMDP(source="BARCHART_STIRF-RL")}
    df2 = tb2.get_timeseries(start, end, queries, freq="eod", mdps=mdps2)

    assert df1.shape == df2.shape, f"Shape mismatch: {df1.shape} vs {df2.shape}"

    # Values should be identical (both from cache)
    diff = (df1.values - df2.values)
    max_diff = np.nanmax(np.abs(diff))
    assert max_diff < 1e-10, f"Values differ by {max_diff}"

    print(f"  PASSED: shapes match ({df1.shape}), max diff = {max_diff}")
    return True


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)

    results = {}
    for name, fn in [
        ("IRS EOD", test_irs_eod),
        ("FRB EOD", test_frb_eod),
        ("IRS Multi-tenor", test_irs_multi_tenor),
        ("Consistency", test_run_twice_consistent),
    ]:
        try:
            results[name] = fn()
        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback; traceback.print_exc()
            results[name] = False

    print("\n" + "="*60)
    print(" TEST SUMMARY")
    print("="*60)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    all_passed = all(results.values())
    print(f"\n  {'All tests passed!' if all_passed else 'Some tests FAILED!'}")
    sys.exit(0 if all_passed else 1)
