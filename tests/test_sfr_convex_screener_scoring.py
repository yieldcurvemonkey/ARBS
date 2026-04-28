import numpy as np
import pandas as pd

from RVUtils.SFRConvexScreener._scoring import (
    apply_liquidity_filters,
    composite_score_series,
    zscore,
)


def test_zscore_zero_mean_unit_std():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = zscore(s)
    assert abs(z.mean()) < 1e-9
    assert abs(z.std(ddof=0) - 1.0) < 1e-9


def test_zscore_handles_zero_variance():
    s = pd.Series([3.0, 3.0, 3.0])
    z = zscore(s)
    assert (z == 0.0).all()


def test_composite_score_weighted_sum():
    df = pd.DataFrame(
        {
            "asymmetry": [1.0, 2.0, 3.0],
            "p_profit": [0.5, 0.6, 0.7],
            "ev_carry": [0.1, 0.2, 0.3],
            "tail_ratio": [1.0, 1.5, 2.0],
        }
    )
    weights = (0.4, 0.2, 0.3, 0.1)
    score = composite_score_series(
        df,
        weights=weights,
        columns=("asymmetry", "p_profit", "ev_carry", "tail_ratio"),
    )
    assert score.idxmax() == 2
    assert score.idxmin() == 0


def test_filter_excludes_below_oi_threshold():
    df = pd.DataFrame(
        {
            "structure_id": ["A_B_CAL_1", "C_D_CAL_1"],
            "min_leg_oi": [10_000, 1_000],
            "min_leg_volume": [5_000, 500],
            "max_leg_bid_ask_bp": [0.2, 0.6],
            "carry_adjusted_ev_bp": [1.0, -2.0],
        }
    )
    out = apply_liquidity_filters(
        df,
        min_open_interest_per_leg=5_000,
        min_avg_daily_volume_per_leg=1_000,
        max_bid_ask_bp=0.5,
        min_carry_adjusted_ev_bp=0.5,
    )
    assert list(out["structure_id"]) == ["A_B_CAL_1"]
