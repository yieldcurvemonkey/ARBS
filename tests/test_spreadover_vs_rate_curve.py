# tests/test_spreadover_vs_rate_curve.py
"""Phase-1 must not over-tag a plain rate curve/fly as SPREADOVER_*.

A curve/fly whose UNIFORM per-leg package spread ties out to its OWN fixed-rate
spread is a plain rate curve (the reported PTS *is* the curve level, e.g. a 2s5s
whose PTS = r5-r2). Only when the PTS is a DIFFERENT quantity (a swap-vs-UST
spreadover differential, or distinct per-leg levels) is it a spreadover
structure. Regression for the 07/12 backfill finding: bugs 1/3/14/16 rendered
SPREADOVER_CURVE instead of CURVE.
"""
import pandas as pd

from SDRUtils.products.usd.usd_swaps import detect_sub_package_curve_fly


def _curve(pkg_id, legs):
    """legs: list of (trade_id, tenor_years, fixed_rate, pts)."""
    tids = [t for t, *_ in legs]
    return pd.DataFrame([
        {"trade_id": t, "package_id": pkg_id, "package_type": "CURVE",
         "package_legs": tids, "tenor_years": ty, "fixed_rate": r,
         "package_transaction_spread": pts, "package_indicator": True,
         "forward_label": "spot", "matched_ust_maturity": False}
        for (t, ty, r, pts) in legs
    ])


def _fly(pkg_id, legs):
    tids = [t for t, *_ in legs]
    return pd.DataFrame([
        {"trade_id": t, "package_id": pkg_id, "package_type": "FLY",
         "package_legs": tids, "tenor_years": ty, "fixed_rate": r,
         "package_transaction_spread": pts, "package_indicator": True,
         "forward_label": "spot", "matched_ust_maturity": False}
        for (t, ty, r, pts) in legs
    ])


def _type(df):
    out = detect_sub_package_curve_fly(df)
    return sorted(set(out["package_type"].astype(str).tolist()))


def test_plain_rate_curve_pts_equals_rate_spread_stays_CURVE():
    # bug 16: PTS -0.000481 == the -4.8bp rate spread (r5 - r2), broadcast.
    df = _curve("P", [("A", 2.0, 0.04064, -0.000481), ("B", 5.0, 0.04016, -0.000481)])
    assert _type(df) == ["CURVE"]


def test_plain_rate_curve_tiny_spread_stays_CURVE():
    # bug 1b: 4Y/5Y, PTS 0.00002 == the 0.2bp rate spread.
    df = _curve("P", [("A", 4.0, 0.040127, 0.00002), ("B", 5.0, 0.040147, 0.00002)])
    assert _type(df) == ["CURVE"]


def test_spreadover_curve_pts_not_rate_spread_upgrades():
    # enh2b: PTS -0.00325 (-32.5bp) != the +17.4bp rate spread -> SPREADOVER_CURVE.
    df = _curve("P", [("A", 10.0, 0.04139, -0.00325), ("B", 30.0, 0.04313, -0.00325)])
    assert _type(df) == ["SPREADOVER_CURVE"]


def test_distinct_per_leg_spreads_upgrade():
    # each leg its own swap-vs-UST level -> genuine spreadover curve.
    df = _curve("P", [("A", 10.0, 0.04139, -0.004239), ("B", 30.0, 0.04313, -0.007475)])
    assert _type(df) == ["SPREADOVER_CURVE"]


def test_equal_rate_legs_degenerate_stays_spreadover():
    # equal rates -> rate spread is 0; a non-trivial PTS can't be the (zero)
    # rate spread, so it's a genuine spreadover structure (mirrors the PR#345
    # test_pts_grouped_spreadover_pair fixture with fixed_rate=0.04 both legs).
    df = _curve("P", [("A", 5.0, 0.04, -0.0025), ("B", 10.0, 0.04, -0.0025)])
    assert _type(df) == ["SPREADOVER_CURVE"]


def test_plain_rate_fly_pts_equals_fly_spread_stays_FLY():
    # fly rate spread = 2*belly - wings; PTS ties it -> plain FLY.
    # rates 4.016/4.083/4.292 (%): 2*4.083-4.016-4.292 = -0.142% = -14.2bp.
    df = _fly("P", [("A", 5.0, 0.04016, -0.00142), ("B", 8.0, 0.04083, -0.00142),
                    ("C", 15.0, 0.04292, -0.00142)])
    assert _type(df) == ["FLY"]
