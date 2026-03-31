"""Test: CashSpline integration with Query/Value/Structure pattern."""
import datetime
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np


def test_imports():
    from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue, FixedRateBondValueFunctionMap
    from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
    from Query.FixedRateBonds.spline_values import MATURITY_BUCKETS, parse_bucket
    from MDP.FixedRateBonds.cash_spline import CashSpline, CashSplineBuilder, CashSplineConfig

    print("SPLINE_SPREAD:", FixedRateBondValue.SPLINE_SPREAD)
    print("SPLINE_Z_SCORE:", FixedRateBondValue.SPLINE_Z_SCORE)
    print("SPLINE_RMSE:", FixedRateBondValue.SPLINE_RMSE)
    print("SPLINE_RMSE_BUCKET:", FixedRateBondValue.SPLINE_RMSE_BUCKET)
    print("[PASS] Imports")


def test_query_universe_detection():
    from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
    from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

    q_spline = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.SPLINE_SPREAD)
    assert q_spline._uses_spline_universe(), "SPLINE_SPREAD should use spline universe"
    assert not q_spline._uses_carry_roll_universe()

    q_rmse = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.SPLINE_RMSE_BUCKET,
                                 value_kwargs={"bucket": "7-10Y"})
    assert q_rmse._uses_spline_universe()

    q_ytm = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)
    assert not q_ytm._uses_spline_universe()
    print("[PASS] Query universe detection")


def test_bucket_parsing():
    from Query.FixedRateBonds.spline_values import MATURITY_BUCKETS, parse_bucket

    assert parse_bucket("7-10Y") == (7.0, 10.0)
    assert parse_bucket("ALL") == (0.0, 100.0)
    assert parse_bucket("2-3Y") == (2.0, 3.0)
    assert len(MATURITY_BUCKETS) == 8
    print("[PASS] Bucket parsing")


def test_cash_spline_helpers():
    from MDP.FixedRateBonds.cash_spline import CashSplineBuilder, CashSplineConfig

    cfg = CashSplineConfig(
        method="b_spline_with_knots", knots=(5.0, 15.0), degree=3,
        exclude_ranks=(), min_ttm=0.0, min_points=3,
    )
    builder = CashSplineBuilder(cfg)
    ttm = np.array([1.5, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 25.0, 30.0])
    ytm = np.array([4.30, 4.25, 4.18, 4.10, 4.06, 4.08, 4.22, 4.38, 4.50, 4.55])
    cusips = np.array(["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10"])

    spline = builder.fit(ttm=ttm, y=ytm, cusips=cusips)

    # spread_for_cusip
    spread = spline.spread_for_cusip("C5")
    assert np.isfinite(spread), f"Expected finite spread, got {spread}"
    print(f"  C5 spread: {spread:.2f} bp")

    # Missing CUSIP returns NaN
    assert np.isnan(spline.spread_for_cusip("MISSING"))

    # z_score_for_cusip
    z = spline.z_score_for_cusip("C5")
    assert np.isfinite(z), f"Expected finite z-score, got {z}"
    print(f"  C5 z-score: {z:.2f}")

    # rmse_bucket
    rmse_57 = spline.rmse_bucket(5.0, 10.0)
    assert np.isfinite(rmse_57), f"Expected finite bucket RMSE, got {rmse_57}"
    print(f"  5-10Y bucket RMSE: {rmse_57:.2f} bp")

    # rmse_bucket for empty range
    assert np.isnan(spline.rmse_bucket(50.0, 60.0))

    # Full RMSE matches
    full_rmse = spline.rmse_bucket(0.0, 100.0)
    assert abs(full_rmse - spline.rmse) < 0.01, f"Full bucket RMSE {full_rmse} != rmse {spline.rmse}"

    print("[PASS] CashSpline helper methods")


def test_col_name():
    from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
    from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

    q = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.SPLINE_SPREAD)
    col = q.col_name()
    assert "SPLINE_SPREAD" in col, f"Expected SPLINE_SPREAD in col_name, got {col!r}"
    print(f"  col_name: {col}")

    q2 = FixedRateBondQuery(cusip="CT5/CT30", value=FixedRateBondValue.SPLINE_SPREAD)
    col2 = q2.col_name()
    assert "CURVE" in col2, f"Expected CURVE in col_name, got {col2!r}"
    print(f"  curve col_name: {col2}")
    print("[PASS] Column names")


if __name__ == "__main__":
    test_imports()
    test_query_universe_detection()
    test_bucket_parsing()
    test_cash_spline_helpers()
    test_col_name()
    print("\n=== ALL TESTS PASS ===")
