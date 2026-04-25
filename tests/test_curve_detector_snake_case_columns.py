"""Column-naming bug: detector silently skipped the platform/UPI/cleared
gate when running inside the production pipeline because the classifier
renames all upstream raw-SDR columns to snake_case before calling the
detectors, while the detector defaults expect raw-SDR casing.

Observed: a 20Y trade on platform ``TWSF`` paired with a 30Y trade on
``BBSF`` because the platform guard silently short-circuited. At the
same time a 10Y/20Y true pair on the same platform + same millisecond
execution block was left as an orphan outright.

These tests exercise the snake_case path to show the guards fire.
"""
from __future__ import annotations

import pandas as pd
import pytest

from SDRUtils.packages.curve import detect_curve_trades_df


def _leg(**overrides):
    base = {
        "trade_id": "",
        "execution_timestamp": pd.Timestamp("2026-04-23 20:47:38", tz="UTC"),
        "product_type": "OIS_SWAP",
        "package_type": "OUTRIGHT",
        "estimated_pv01": 30_000.0,
        "tenor_label": "10Y",
        "notional_currency": "USD",
        "effective_date": pd.Timestamp("2026-04-27"),
        "forward_label": "spot",
        # snake_case columns as the classifier emits them:
        "upi_underlier_name": "USD-SOFR-OIS Compound",
        "platform_identifier": "TWSF",
        "cleared": "Y",
        "unique_product_identifier": "QZXQ4R16245X",
    }
    base.update(overrides)
    return base


def test_different_platforms_block_curve_pair_on_snake_case_columns():
    df = pd.DataFrame([
        _leg(trade_id="T10Y", tenor_label="10Y", estimated_pv01=30_000.0,
             platform_identifier="TWSF"),
        _leg(trade_id="T30Y", tenor_label="30Y", estimated_pv01=32_000.0,
             platform_identifier="BBSF",
             execution_timestamp=pd.Timestamp("2026-04-23 20:46:42", tz="UTC")),
    ])
    out = detect_curve_trades_df(
        df,
        platform_col="platform_identifier",
        underlier_col="upi_underlier_name",
        cleared_col="cleared",
        upi_col="unique_product_identifier",
    )
    assert (out["package_type"] == "CURVE").sum() == 0


def test_same_platform_snake_case_bundles_into_curve():
    df = pd.DataFrame([
        _leg(trade_id="T10Y", tenor_label="10Y", estimated_pv01=29_900.0,
             platform_identifier="TWSF"),
        _leg(trade_id="T20Y", tenor_label="20Y", estimated_pv01=30_100.0,
             platform_identifier="TWSF"),
    ])
    out = detect_curve_trades_df(
        df,
        platform_col="platform_identifier",
        underlier_col="upi_underlier_name",
        cleared_col="cleared",
        upi_col="unique_product_identifier",
    )
    assert (out["package_type"] == "CURVE").sum() == 2


def test_user_screenshot_10y_20y_pair_detected():
    """The exact 2026-04-23 trade_ids from the user report.

    10Y (trade_id ...101) and 20Y (trade_id ...201) executed at the same
    timestamp on the same platform/UPI — must pair as a 10s20s CURVE."""
    df = pd.DataFrame([
        _leg(
            trade_id="2844466371000000101",
            tenor_label="10Y",
            estimated_pv01=29_888.898,
        ),
        _leg(
            trade_id="2844466372000000201",
            tenor_label="20Y",
            estimated_pv01=30_111.067,
            # 20Y fixed_rate differs but detector doesn't gate on that.
        ),
    ])
    out = detect_curve_trades_df(
        df,
        platform_col="platform_identifier",
        underlier_col="upi_underlier_name",
        cleared_col="cleared",
        upi_col="unique_product_identifier",
    )
    assert (out["package_type"] == "CURVE").sum() == 2
    pkg_ids = out.loc[out["package_type"] == "CURVE", "package_id"].unique()
    assert len(pkg_ids) == 1
