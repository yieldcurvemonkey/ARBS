"""Regression: package_id must be globally unique across separate detector
invocations.

Previous detectors used a local ``pkg_counter`` starting at 0 per call, so
two independent daily runs both emitted ``CURVE_1``, ``CURVE_2``, ... .
When the daily frames were concatenated downstream, unrelated trades
landed in the same (package_type, package_id) group and
``merge_package_legs_to_one_row`` collapsed them into a single row with
N>2 legs.

The fix makes each package_id include a trade-id suffix so it is unique
across any set of SDR trades.
"""
import pandas as pd
import pytest

from SDRUtils.packages.curve import detect_curve_trades_df
from SDRUtils.packages.fly import detect_fly_trades_df
from SDRUtils.packages.basis import detect_basis_packages_df
from SDRUtils.packages.utils import merge_package_legs_to_one_row


# --- curve --------------------------------------------------------------

def _curve_pair(day: str, trade_id_prefix: str, upi: str = "QZF08M5TR8H3"):
    base = pd.Timestamp(f"{day} 14:30:00", tz="UTC")
    return pd.DataFrame([
        {
            "trade_id": f"{trade_id_prefix}A",
            "execution_timestamp": base,
            "product_type": "OIS_SWAP",
            "package_type": "OUTRIGHT",
            "estimated_pv01": 45_000.0,
            "tenor_label": "5Y",
            "notional_currency": "USD",
            "effective_date": pd.Timestamp(day) + pd.Timedelta(days=2),
            "forward_label": "spot",
            "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
            "Platform identifier": "TW",
            "Cleared": "Y",
            "Unique Product Identifier": upi,
        },
        {
            "trade_id": f"{trade_id_prefix}B",
            "execution_timestamp": base + pd.Timedelta(seconds=15),
            "product_type": "OIS_SWAP",
            "package_type": "OUTRIGHT",
            # Within both curve DV01 gates (10% relative, $500 absolute)
            "estimated_pv01": 45_300.0,
            "tenor_label": "10Y",
            "notional_currency": "USD",
            "effective_date": pd.Timestamp(day) + pd.Timedelta(days=2),
            "forward_label": "spot",
            "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
            "Platform identifier": "TW",
            "Cleared": "Y",
            "Unique Product Identifier": upi,
        },
    ])


def test_curve_package_ids_disjoint_across_invocations():
    """Two independent detector runs must produce disjoint package_ids."""
    day1 = detect_curve_trades_df(_curve_pair("2026-04-08", "T10000000000"))
    day2 = detect_curve_trades_df(_curve_pair("2026-04-13", "T20000000000"))

    ids_day1 = set(day1.loc[day1["package_id"].notna(), "package_id"].tolist())
    ids_day2 = set(day2.loc[day2["package_id"].notna(), "package_id"].tolist())

    assert ids_day1, "Day 1 should have produced a CURVE package"
    assert ids_day2, "Day 2 should have produced a CURVE package"
    assert ids_day1.isdisjoint(ids_day2), (
        f"package_id collision across runs: {ids_day1 & ids_day2}"
    )


def test_merge_does_not_collapse_unrelated_daily_curves():
    """After concat, merge_package_legs_to_one_row must keep the two
    independent curves as two separate merged rows, not one."""
    d1 = detect_curve_trades_df(_curve_pair("2026-04-08", "T10000000000"))
    d2 = detect_curve_trades_df(_curve_pair("2026-04-13", "T20000000000"))
    combined = pd.concat([d1, d2], ignore_index=True)

    merged = merge_package_legs_to_one_row(combined)
    curve_rows = merged[merged["package_type"] == "CURVE"]
    assert len(curve_rows) == 2, (
        f"Expected 2 merged CURVE rows, got {len(curve_rows)}:\n{curve_rows}"
    )


# --- fly ----------------------------------------------------------------

def _fly_triple(day: str, trade_id_prefix: str, upi: str = "QZF08M5TR8H3"):
    """5Y / 7Y belly / 9Y trio, belly arrives last."""
    base = pd.Timestamp(f"{day} 14:30:00", tz="UTC")
    common = {
        "product_type": "OIS_SWAP",
        "package_type": "OUTRIGHT",
        "notional_currency": "USD",
        "effective_date": pd.Timestamp(day) + pd.Timedelta(days=2),
        "forward_label": "spot",
        "UPI Underlier Name": "USD-SOFR-COMPOUND 1D",
        "Platform identifier": "TW",
        "Cleared": "Y",
        "Unique Product Identifier": upi,
    }
    rows = [
        {**common,
         "trade_id": f"{trade_id_prefix}A",
         "execution_timestamp": base,
         "estimated_pv01": 22_500.0,
         "tenor_label": "5Y", "tenor_years": 5.0},
        {**common,
         "trade_id": f"{trade_id_prefix}C",
         "execution_timestamp": base + pd.Timedelta(seconds=10),
         "estimated_pv01": 22_500.0,
         "tenor_label": "9Y", "tenor_years": 9.0},
        {**common,
         "trade_id": f"{trade_id_prefix}B",
         "execution_timestamp": base + pd.Timedelta(seconds=20),
         "estimated_pv01": 45_000.0,
         "tenor_label": "7Y", "tenor_years": 7.0},
    ]
    return pd.DataFrame(rows)


def test_fly_package_ids_disjoint_across_invocations():
    d1 = detect_fly_trades_df(_fly_triple("2026-04-08", "F10000000000"))
    d2 = detect_fly_trades_df(_fly_triple("2026-04-13", "F20000000000"))
    ids_d1 = set(d1.loc[d1["package_id"].notna(), "package_id"].tolist())
    ids_d2 = set(d2.loc[d2["package_id"].notna(), "package_id"].tolist())
    assert ids_d1 and ids_d2, "Both runs must produce FLY ids"
    assert ids_d1.isdisjoint(ids_d2), f"fly id collision: {ids_d1 & ids_d2}"


# --- basis --------------------------------------------------------------

def _basis_pair(day: str, trade_id_prefix: str, upi: str = "BSISSAME001"):
    base = pd.Timestamp(f"{day} 14:30:00", tz="UTC")
    return pd.DataFrame([
        {"trade_id": f"{trade_id_prefix}A", "execution_timestamp": base,
         "package_type": "OUTRIGHT", "basis_type": "SOFR_FF",
         "tenor_label": "2Y",
         "effective_date": pd.Timestamp(day) + pd.Timedelta(days=2),
         "forward_label": "spot", "Platform identifier": "TW", "Cleared": "Y",
         "Unique Product Identifier": upi},
        {"trade_id": f"{trade_id_prefix}B",
         "execution_timestamp": base + pd.Timedelta(seconds=20),
         "package_type": "OUTRIGHT", "basis_type": "SOFR_FF",
         "tenor_label": "10Y",
         "effective_date": pd.Timestamp(day) + pd.Timedelta(days=2),
         "forward_label": "spot", "Platform identifier": "TW", "Cleared": "Y",
         "Unique Product Identifier": upi},
    ])


def test_basis_package_ids_disjoint_across_invocations():
    d1 = detect_basis_packages_df(_basis_pair("2026-04-08", "B10000000000"))
    d2 = detect_basis_packages_df(_basis_pair("2026-04-13", "B20000000000"))
    ids_d1 = set(d1.loc[d1["package_id"].astype(str) != "", "package_id"].tolist())
    ids_d1.discard("")
    ids_d2 = set(d2.loc[d2["package_id"].astype(str) != "", "package_id"].tolist())
    ids_d2.discard("")
    assert ids_d1 and ids_d2, "Both runs must produce BPKG ids"
    assert ids_d1.isdisjoint(ids_d2), f"basis id collision: {ids_d1 & ids_d2}"
