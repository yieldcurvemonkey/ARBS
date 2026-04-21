"""Hard UPI gate on basis-package detection."""
import pandas as pd

from SDRUtils.packages.basis import detect_basis_packages_df


def _mk_basis_pair(upi_a: str, upi_b: str):
    base = pd.Timestamp("2026-04-15 14:30:00", tz="UTC")
    return pd.DataFrame([
        {"trade_id": "A", "execution_timestamp": base,
         "package_type": "OUTRIGHT", "basis_type": "SOFR_FF",
         "tenor_label": "2Y", "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "Platform identifier": "TW", "Cleared": "Y",
         "Unique Product Identifier": upi_a},
        {"trade_id": "B", "execution_timestamp": base + pd.Timedelta(seconds=20),
         "package_type": "OUTRIGHT", "basis_type": "SOFR_FF",
         "tenor_label": "10Y", "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "Platform identifier": "TW", "Cleared": "Y",
         "Unique Product Identifier": upi_b},
    ])


def test_same_upi_bundles_basis_curve():
    df = _mk_basis_pair("BSISSAME001", "BSISSAME001")
    out = detect_basis_packages_df(df, require_same_upi=True)
    assert (out["package_type"] == "BASIS_CURVE").sum() == 2


def test_distinct_upi_leaves_outrights():
    df = _mk_basis_pair("BSISSAME001", "DIFFERENTBASI")
    out = detect_basis_packages_df(df, require_same_upi=True)
    assert (out["package_type"] == "OUTRIGHT").all()
