"""Per-leg labels for undetected (PKG-N) packages must show individual tenors."""
from __future__ import annotations

import pandas as pd

from SDRUtils.analytics.trade_tape import TradeTape


def _pkg_n_legs(n_legs, package_id, legs):
    """legs: list of (trade_id, tenor_years, tenor_display, forward_label)."""
    tids = [t for t, _, _, _ in legs]
    rows = []
    for tid, ten, td, fwd in legs:
        rows.append({
            "trade_id": tid,
            "tenor_years": ten,
            "tenor_display": td,
            "tenor_label": td,
            "forward_label": fwd,
            "forward_start_years": 0.0 if fwd == "spot" else 0.25,
            "package_type": f"PKG-{n_legs}",
            "package_id": package_id,
            "package_legs": tids,
            "package_indicator": True,
            "is_package": True,
            "product_type": "OIS_SWAP",
            "trade_type": "OUTRIGHT",
            "upi_underlier_name": "USD-SOFR-COMPOUND",
            "upi_reset_freq": "1D",
            "upi_notional_schedule": "Constant",
            "upi_delivery_type": "PHYS",
            "cleared": "Y",
        })
    return rows


def _enrich_and_label(rows):
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_packages(df.copy())
    out = tape._build_enriched_label(out)
    return out


def test_pkg3_leg_tape_labels_show_individual_tenors():
    """PKG-3: each leg's leg_tape_label should show its own tenor + Outright."""
    rows = _pkg_n_legs(3, "P1", [
        ("L1", 1.75, "21M", "3M"),
        ("L2", 2.0, "2Y", "spot"),
        ("L3", 2.0, "2Y", "spot"),
    ])
    out = _enrich_and_label(rows)

    # Package-level label: compact PKG-N format (no individual tenors)
    for i in range(3):
        pkg_label = out.loc[i, "tape_label"]
        assert "PKG-3" in pkg_label
        assert "21M/2Y/2Y" not in pkg_label

    # Leg-level labels: individual tenor + "Outright"
    leg0 = out.loc[0, "leg_tape_label"]
    assert "21M" in leg0
    assert "Outright" in leg0
    assert "/" not in leg0.split("Outright")[0]

    leg1 = out.loc[1, "leg_tape_label"]
    assert "2Y" in leg1
    assert "Outright" in leg1

    leg2 = out.loc[2, "leg_tape_label"]
    assert "2Y" in leg2
    assert "Outright" in leg2


def test_pkg2_leg_tape_labels_show_individual_tenors():
    """PKG-2 (undetected): each leg should get its own outright label."""
    rows = _pkg_n_legs(2, "P2", [
        ("L1", 5.0, "5Y", "spot"),
        ("L2", 10.0, "10Y", "spot"),
    ])
    out = _enrich_and_label(rows)

    leg0 = out.loc[0, "leg_tape_label"]
    assert "5Y" in leg0
    assert "Outright" in leg0
    assert "10Y" not in leg0

    leg1 = out.loc[1, "leg_tape_label"]
    assert "10Y" in leg1
    assert "Outright" in leg1
    assert "5Y" not in leg1


def test_curve_legs_still_get_outright_labels():
    """CURVE legs already worked — make sure they still do after the change."""
    tids = ["L1", "L2"]
    rows = []
    for tid, ten, td in [("L1", 5.0, "5Y"), ("L2", 10.0, "10Y")]:
        rows.append({
            "trade_id": tid,
            "tenor_years": ten,
            "tenor_display": td,
            "tenor_label": td,
            "forward_label": "spot",
            "forward_start_years": 0.0,
            "package_type": "CURVE",
            "package_id": "C1",
            "package_legs": tids,
            "package_indicator": True,
            "is_package": True,
            "product_type": "OIS_SWAP",
            "trade_type": "CURVE",
            "upi_underlier_name": "USD-SOFR-COMPOUND",
            "upi_reset_freq": "1D",
            "upi_notional_schedule": "Constant",
            "upi_delivery_type": "PHYS",
            "cleared": "Y",
        })
    out = _enrich_and_label(rows)

    # Package label: combined
    assert "5Y/10Y" in out.loc[0, "tape_label"]
    assert "CURVE" in out.loc[0, "tape_label"]

    # Leg labels: individual
    assert "5Y" in out.loc[0, "leg_tape_label"]
    assert "Outright" in out.loc[0, "leg_tape_label"]
    assert "10Y" in out.loc[1, "leg_tape_label"]
    assert "Outright" in out.loc[1, "leg_tape_label"]


def test_fomc_curve_leg_labels_omit_redundant_tenor():
    """FOMC CURVE legs: meeting label is the tenor — don't append '1M'/'2M'."""
    tids = ["L1", "L2"]
    rows = []
    for tid, ten, td, fomc in [
        ("L1", 0.33, "1M", "OCT26"),
        ("L2", 0.17, "2M", "JUL26"),
    ]:
        rows.append({
            "trade_id": tid,
            "tenor_years": ten,
            "tenor_display": td,
            "tenor_label": td,
            "forward_label": "spot",
            "forward_start_years": 0.0,
            "package_type": "CURVE",
            "package_id": "FC1",
            "package_legs": tids,
            "package_indicator": True,
            "is_package": True,
            "product_type": "OIS_SWAP",
            "trade_type": "CURVE",
            "upi_underlier_name": "USD-Federal Funds-OIS Compound",
            "upi_reset_freq": "1D",
            "upi_notional_schedule": "Constant",
            "upi_delivery_type": "PHYS",
            "cleared": "Y",
            "fomc_meeting_label": fomc,
            "special_tenor_type": "FOMC",
        })
    out = _enrich_and_label(rows)

    leg0 = out.loc[0, "leg_tape_label"]
    assert "FOMC OCT26" in leg0
    assert "Outright" in leg0
    assert "1M" not in leg0

    leg1 = out.loc[1, "leg_tape_label"]
    assert "FOMC JUL26" in leg1
    assert "Outright" in leg1
    assert "2M" not in leg1


def test_outright_non_package_label_unchanged():
    """Outright (non-package) trades: leg_tape_label == tape_label."""
    rows = [{
        "trade_id": "T1",
        "tenor_years": 5.0,
        "tenor_display": "5Y",
        "tenor_label": "5Y",
        "forward_label": "spot",
        "forward_start_years": 0.0,
        "package_type": "OUTRIGHT",
        "package_id": None,
        "package_legs": None,
        "package_indicator": False,
        "is_package": False,
        "product_type": "OIS_SWAP",
        "trade_type": "OUTRIGHT",
        "upi_underlier_name": "USD-SOFR-COMPOUND",
        "upi_reset_freq": "1D",
        "upi_notional_schedule": "Constant",
        "upi_delivery_type": "PHYS",
        "cleared": "Y",
    }]
    out = _enrich_and_label(rows)

    assert out.loc[0, "tape_label"] == out.loc[0, "leg_tape_label"]
    assert "5Y" in out.loc[0, "leg_tape_label"]
    assert "Outright" in out.loc[0, "leg_tape_label"]
