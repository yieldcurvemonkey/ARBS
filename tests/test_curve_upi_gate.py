"""Hard UPI gate on curve detection.

Two trades that are otherwise a valid curve pair but carry distinct
``Unique Product Identifier`` strings MUST NOT be grouped.
"""
import pandas as pd
import pytest

from SDRUtils.packages.curve import detect_curve_trades_df


def _mk_pair(upi_a: str, upi_b: str) -> pd.DataFrame:
    base = pd.Timestamp("2026-04-15 14:30:00", tz="UTC")
    return pd.DataFrame([
        {
            "trade_id": "A",
            "execution_timestamp": base,
            "product_type": "OIS_SWAP",
            "package_type": "OUTRIGHT",
            "estimated_pv01": 45_000.0,
            "tenor_label": "5Y",
            "notional_currency": "USD",
            "effective_date": pd.Timestamp("2026-04-17"),
            "forward_label": "spot",
            "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
            "Platform identifier": "TW",
            "Cleared": "Y",
            "Unique Product Identifier": upi_a,
        },
        {
            "trade_id": "B",
            "execution_timestamp": base + pd.Timedelta(seconds=15),
            "product_type": "OIS_SWAP",
            "package_type": "OUTRIGHT",
            # Within both curve DV01 gates (10% relative, $500 absolute)
            "estimated_pv01": 45_300.0,
            "tenor_label": "10Y",
            "notional_currency": "USD",
            "effective_date": pd.Timestamp("2026-04-17"),
            "forward_label": "spot",
            "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
            "Platform identifier": "TW",
            "Cleared": "Y",
            "Unique Product Identifier": upi_b,
        },
    ])


def test_same_upi_bundles_into_curve():
    df = _mk_pair("QZF08M5TR8H3", "QZF08M5TR8H3")
    out = detect_curve_trades_df(df, require_same_upi=True)
    assert (out["package_type"] == "CURVE").all()
    assert out["package_id"].nunique(dropna=True) == 1


def test_distinct_upi_stays_outright():
    df = _mk_pair("QZF08M5TR8H3", "DIFFERENTUPIABC")
    out = detect_curve_trades_df(df, require_same_upi=True)
    assert (out["package_type"] == "OUTRIGHT").all()


def test_upi_gate_off_allows_distinct_upi():
    """Back-compat: setting require_same_upi=False restores prior behavior."""
    df = _mk_pair("QZF08M5TR8H3", "DIFFERENTUPIABC")
    out = detect_curve_trades_df(df, require_same_upi=False)
    assert (out["package_type"] == "CURVE").any()
