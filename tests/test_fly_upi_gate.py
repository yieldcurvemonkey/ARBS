"""Hard UPI gate on fly detection."""
import pandas as pd

from SDRUtils.packages.fly import detect_fly_trades_df


def _mk_fly(upi_mid: str):
    """Build a fly: 5Y wing, 9Y wing, 7Y belly (belly arrives last so the
    detector's streaming "belly-sees-both-wings" constraint is satisfied)."""
    base = pd.Timestamp("2026-04-15 14:30:00", tz="UTC")
    return pd.DataFrame([
        # 5Y wing
        {"trade_id": "A", "execution_timestamp": base, "product_type": "OIS_SWAP",
         "package_type": "OUTRIGHT", "estimated_pv01": 22_500.0,
         "tenor_label": "5Y", "tenor_years": 5.0,
         "notional_currency": "USD", "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
         "Platform identifier": "TW", "Cleared": "Y",
         "Unique Product Identifier": "QZF08M5TR8H3"},
        # 9Y wing (within detector's +-8 tenor-bucket window for 7Y belly)
        {"trade_id": "C", "execution_timestamp": base + pd.Timedelta(seconds=10),
         "product_type": "OIS_SWAP", "package_type": "OUTRIGHT",
         "estimated_pv01": 22_500.0,
         "tenor_label": "9Y", "tenor_years": 9.0,
         "notional_currency": "USD", "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
         "Platform identifier": "TW", "Cleared": "Y",
         "Unique Product Identifier": "QZF08M5TR8H3"},
        # 7Y belly (arrives last -> both wings already in the store)
        {"trade_id": "B", "execution_timestamp": base + pd.Timedelta(seconds=20),
         "product_type": "OIS_SWAP", "package_type": "OUTRIGHT",
         "estimated_pv01": 45_000.0,
         "tenor_label": "7Y", "tenor_years": 7.0,
         "notional_currency": "USD", "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
         "Platform identifier": "TW", "Cleared": "Y",
         "Unique Product Identifier": upi_mid},
    ])


def test_same_upi_fly_is_detected():
    df = _mk_fly("QZF08M5TR8H3")
    out = detect_fly_trades_df(df, require_same_upi=True)
    assert (out["package_type"] == "FLY").sum() == 3


def test_belly_different_upi_not_a_fly():
    df = _mk_fly("DIFFERENTUPIABC")
    out = detect_fly_trades_df(df, require_same_upi=True)
    assert (out["package_type"] == "FLY").sum() == 0
