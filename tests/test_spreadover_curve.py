import pandas as pd
from SDRUtils.packages.spreadover_curve import (
    build_spreadover_level_index, detect_spreadover_curves_df,
)


def _so(tid, tenor, pts, ts="2026-07-10 20:00:00"):
    return dict(trade_id=tid, package_type="SPREADOVER", is_spreadover=True,
               tenor_years=tenor, package_transaction_spread=pts, forward_label="spot",
               execution_timestamp=pd.Timestamp(ts, tz="UTC"))


def _curve_leg(tid, pkg_id, tenor, pkg_pts, ptype="CURVE", ts="2026-07-10 21:00:32"):
    return dict(trade_id=tid, package_id=pkg_id, package_type=ptype,
                package_legs=[f"{pkg_id}_1", f"{pkg_id}_2"], tenor_years=tenor,
                package_transaction_spread=pkg_pts, forward_label="spot",
                execution_timestamp=pd.Timestamp(ts, tz="UTC"), is_spreadover=False)


def test_index_keeps_latest_per_tenor():
    df = pd.DataFrame([
        _so("A", 10.0, -0.004239, ts="2026-07-10 19:00:00"),
        _so("B", 30.0, -0.007475, ts="2026-07-10 19:30:00"),
        _so("C", 10.0, -0.004000, ts="2026-07-10 20:00:00"),  # newer 10Y
    ])
    idx = build_spreadover_level_index(df)
    assert abs(idx[10.0] - (-40.0)) < 0.01   # latest 10Y, -0.004 -> -40bp
    assert abs(idx[30.0] - (-74.75)) < 0.01


def test_curve_upgrades_when_differential_ties_out():
    # standalone 10Y=-42.39bp, 30Y=-74.75bp -> differential -32.36bp;
    # package PTS -0.00325 (decimal) ties -32.5bp at 10000x, within 5bp.
    df = pd.DataFrame([
        _so("SA", 10.0, -0.004239),
        _so("SB", 30.0, -0.007475),
        _curve_leg("C1", "P1", 10.0, -0.00325),
        _curve_leg("C2", "P1", 30.0, -0.00325),
    ])
    out = detect_spreadover_curves_df(df)
    got = out.loc[out["package_id"] == "P1", "package_type"].unique().tolist()
    assert got == ["SPREADOVER_CURVE"]


def test_curve_stays_plain_when_differential_off():
    df = pd.DataFrame([
        _so("SA", 10.0, -0.004239),
        _so("SB", 30.0, -0.007475),
        _curve_leg("C1", "P1", 10.0, -0.05),   # 500bp, nowhere near -32bp
        _curve_leg("C2", "P1", 30.0, -0.05),
    ])
    out = detect_spreadover_curves_df(df)
    assert (out.loc[out["package_id"] == "P1", "package_type"] == "CURVE").all()


def test_curve_stays_plain_when_level_missing():
    df = pd.DataFrame([
        _so("SA", 10.0, -0.004239),            # only 10Y level, no 30Y
        _curve_leg("C1", "P1", 10.0, -0.00325),
        _curve_leg("C2", "P1", 30.0, -0.00325),
    ])
    out = detect_spreadover_curves_df(df)
    assert (out.loc[out["package_id"] == "P1", "package_type"] == "CURVE").all()
