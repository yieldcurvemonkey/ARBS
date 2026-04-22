"""PKG flag: detect_spreadovers sets package_type = "SPREADOVER".

Exposes spreadovers as a distinct bucket in the dashboard PKG column
alongside CURVE / FLY / BASIS / INVOICE / OUTRIGHT.
"""
import pandas as pd
import pytest

from SDRUtils.products.usd.usd_swaps import detect_spreadovers


@pytest.fixture
def row_template():
    return {
        "trade_id": "T1",
        "package_legs": None,
        "package_indicator": True,
        # Decimal fraction (CFTC reporting unit): -0.00125 == -12.5 bps,
        # a typical 5Y spreadover quote.
        "package_transaction_spread": -0.00125,
        "forward_label": "spot",
        "other_payment_type": None,
        "package_type": "OUTRIGHT",
        "invoice_swap_ticker": None,
    }


def test_spreadover_row_gets_package_type_spreadover(row_template):
    df = pd.DataFrame([row_template])
    out = detect_spreadovers(df)
    assert out.loc[0, "is_spreadover"] is True or out.loc[0, "is_spreadover"] == True
    assert out.loc[0, "package_type"] == "SPREADOVER"


def test_non_spreadover_row_keeps_original_package_type(row_template):
    """Missing package_indicator -> not a spreadover -> package_type stays."""
    row = dict(row_template)
    row["package_indicator"] = False
    df = pd.DataFrame([row])
    out = detect_spreadovers(df)
    assert bool(out.loc[0, "is_spreadover"]) is False
    assert out.loc[0, "package_type"] == "OUTRIGHT"


def test_spreadover_does_not_overwrite_curve_or_fly(row_template):
    """If a detector already classified the trade as CURVE or FLY (legs set),
    detect_spreadovers should not flip it to SPREADOVER — the broker-spreadover
    mask requires package_legs to be NaN."""
    row = dict(row_template)
    row["package_legs"] = ["T1", "T2"]  # already paired as a package leg
    row["package_type"] = "CURVE"
    df = pd.DataFrame([row])
    out = detect_spreadovers(df)
    assert bool(out.loc[0, "is_spreadover"]) is False
    assert out.loc[0, "package_type"] == "CURVE"


def test_package_type_column_created_if_missing(row_template):
    row = dict(row_template)
    df = pd.DataFrame([row]).drop(columns=["package_type"])
    out = detect_spreadovers(df)
    assert "package_type" in out.columns
    assert out.loc[0, "package_type"] == "SPREADOVER"
