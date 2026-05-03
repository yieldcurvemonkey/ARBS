import pandas as pd

from SDRUtils.analytics.trade_quality import (
    TradeQualityFlag,
    flag_capped_notional,
    flag_outliers,
)


def test_flag_outliers_ignores_nullable_na_boolean_flags():
    df = pd.DataFrame(
        {
            "fixed_rate": pd.Series([pd.NA], dtype="Float64"),
            "tenor_label": ["5Y"],
            "execution_date": [pd.Timestamp("2026-01-09")],
            "is_notional_capped": pd.Series([pd.NA], dtype="boolean"),
        }
    )

    out = flag_outliers(df)

    assert out.loc[0, "quality_flags"] == []


def test_flag_capped_notional_maps_nullable_booleans():
    df = pd.DataFrame(
        {
            "is_notional_capped": pd.Series([True, pd.NA, False], dtype="boolean"),
        }
    )

    out = flag_capped_notional(df)

    assert out["is_capped"].tolist() == [True, False, False]


def test_flag_outliers_collects_explicit_true_flags():
    df = pd.DataFrame(
        {
            "fixed_rate": [0.051, 0.05],
            "tenor_label": ["5Y", "5Y"],
            "execution_date": [pd.Timestamp("2026-01-09")] * 2,
            "is_notional_capped": [True, False],
        }
    )

    out = flag_outliers(df, threshold_bp=1.0)

    assert TradeQualityFlag.CAPPED_NOTIONAL.value in out.loc[0, "quality_flags"]
