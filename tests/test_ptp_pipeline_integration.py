# tests/test_ptp_pipeline_integration.py
"""Integration test: PTP legs bypass global detectors, non-PTP legs unchanged."""
import pandas as pd
import pytest

from SDRUtils.packages.ptp_grouper import group_by_ptp, classify_ptp_groups
from SDRUtils.packages.opa_sign_solver import solve_all_opa_signs


def _pipeline_sim(df):
    """Simulate the new _run_all_detectors flow without importing usd_swaps."""
    ptp_df, non_ptp_df = group_by_ptp(df, time_tolerance_seconds=5)

    if not ptp_df.empty:
        ptp_df = classify_ptp_groups(ptp_df)

    if not non_ptp_df.empty:
        if "package_type" not in non_ptp_df.columns:
            non_ptp_df["package_type"] = "OUTRIGHT"
        if "package_id" not in non_ptp_df.columns:
            non_ptp_df["package_id"] = None
        if "package_legs" not in non_ptp_df.columns:
            non_ptp_df["package_legs"] = None

    merged = pd.concat([ptp_df, non_ptp_df], ignore_index=True)
    merged = solve_all_opa_signs(merged)
    return merged


def test_ptp_legs_get_classified_non_ptp_stay_outright():
    ts = pd.Timestamp("2026-06-25 14:30:59", tz="UTC")
    rows = [
        # PTP group: 3-leg fly
        {"trade_id": "P1", "execution_timestamp": ts,
         "package_transaction_price": 88100.0, "package_indicator": True,
         "unique_product_identifier": "UPI_A", "platform_identifier": "BBSF",
         "estimated_pv01": 5000.0, "tenor_years": 2.0, "fixed_rate": 0.04,
         "other_payment_amount": 1000.0, "product_type": "OIS_SWAP"},
        {"trade_id": "P2", "execution_timestamp": ts,
         "package_transaction_price": 88100.0, "package_indicator": True,
         "unique_product_identifier": "UPI_A", "platform_identifier": "BBSF",
         "estimated_pv01": 10000.0, "tenor_years": 5.0, "fixed_rate": 0.04,
         "other_payment_amount": 5000.0, "product_type": "OIS_SWAP"},
        {"trade_id": "P3", "execution_timestamp": ts,
         "package_transaction_price": 88100.0, "package_indicator": True,
         "unique_product_identifier": "UPI_A", "platform_identifier": "BBSF",
         "estimated_pv01": 5000.0, "tenor_years": 10.0, "fixed_rate": 0.04,
         "other_payment_amount": 2000.0, "product_type": "OIS_SWAP"},
        # Non-PTP outright
        {"trade_id": "O1", "execution_timestamp": ts,
         "package_transaction_price": None, "package_indicator": False,
         "unique_product_identifier": "UPI_A", "platform_identifier": "BBSF",
         "estimated_pv01": 8000.0, "tenor_years": 5.0, "fixed_rate": 0.04,
         "other_payment_amount": 0.0, "product_type": "OIS_SWAP"},
    ]
    df = pd.DataFrame(rows)
    result = _pipeline_sim(df)

    ptp_rows = result[result["ptp_group_id"].notna()]
    non_ptp_rows = result[result["ptp_group_id"].isna()]

    assert len(ptp_rows) == 3
    assert (ptp_rows["package_type"] == "FLY").all()
    assert ptp_rows["opa_sign"].notna().all()
    assert ptp_rows["opa_sign_confidence"].iloc[0] is not None

    assert len(non_ptp_rows) == 1
    assert non_ptp_rows["package_type"].iloc[0] == "OUTRIGHT"
    assert non_ptp_rows["opa_sign"].iloc[0] is None
