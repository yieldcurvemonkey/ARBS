"""Tests for the inverted confidence gate in _apply_invoice_swap_lookup.

A CBOT Treasury Invoice Swap spec match is by itself definitive:
- The ticker must resolve regardless of prior matched_ust_maturity_trade_confidence.
- The match must upgrade matched_ust_maturity_trade_confidence to "high".
- The match must set matched_ust_maturity to True if it wasn't already.

This reverses the previous gating (where a LOW MMS confidence blocked the
ticker from ever populating), because the gating logic was inverted — an
unambiguous CME spec match should *promote* the MMS confidence rather than
be gated by it.
"""
import pandas as pd
import pytest

from SDRUtils.products.usd.usd_swaps import _apply_invoice_swap_lookup


@pytest.fixture
def lookup():
    return pd.DataFrame([
        {
            "invoice_swap_delivery_date": pd.Timestamp("2026-07-06"),
            "invoice_swap_ctd_maturity": pd.Timestamp("2028-03-15"),
            "invoice_swap_ticker": "TVA",
        },
    ])


@pytest.fixture
def base_row():
    return {
        "trade_id": "T1",
        "execution_timestamp": pd.Timestamp("2026-04-15 14:30:00", tz="UTC"),
        "effective_date": pd.Timestamp("2026-07-06"),
        "expiration_date": pd.Timestamp("2028-03-15"),
        "matched_ust_maturity": True,
        "matched_ust_maturity_trade_confidence": "low",
        "forward_label": "spot",
    }


def test_low_mms_confidence_still_resolves_invoice_ticker(lookup, base_row):
    df = pd.DataFrame([base_row])
    out = _apply_invoice_swap_lookup(
        df,
        lookup,
        effective_col="effective_date",
        maturity_col="expiration_date",
        confidence_col="matched_ust_maturity_trade_confidence",
        require_high_confidence=True,
        output_col="invoice_swap_ticker",
    )
    assert out.loc[0, "invoice_swap_ticker"] == "TVA"


def test_invoice_match_upgrades_mms_confidence_to_high(lookup, base_row):
    df = pd.DataFrame([base_row])
    out = _apply_invoice_swap_lookup(
        df,
        lookup,
        effective_col="effective_date",
        maturity_col="expiration_date",
        confidence_col="matched_ust_maturity_trade_confidence",
        require_high_confidence=True,
        output_col="invoice_swap_ticker",
    )
    assert out.loc[0, "matched_ust_maturity_trade_confidence"] == "high"


def test_invoice_match_sets_matched_ust_maturity_true(lookup, base_row):
    row = dict(base_row)
    row["matched_ust_maturity"] = False
    df = pd.DataFrame([row])
    out = _apply_invoice_swap_lookup(
        df,
        lookup,
        effective_col="effective_date",
        maturity_col="expiration_date",
        confidence_col="matched_ust_maturity_trade_confidence",
        require_high_confidence=True,
        output_col="invoice_swap_ticker",
    )
    assert out.loc[0, "matched_ust_maturity"] is True or out.loc[0, "matched_ust_maturity"] == True


def test_no_spec_match_does_not_touch_confidence(lookup, base_row):
    row = dict(base_row)
    row["effective_date"] = pd.Timestamp("2026-07-06")
    row["expiration_date"] = pd.Timestamp("2033-05-15")  # Not in lookup
    df = pd.DataFrame([row])
    out = _apply_invoice_swap_lookup(
        df,
        lookup,
        effective_col="effective_date",
        maturity_col="expiration_date",
        confidence_col="matched_ust_maturity_trade_confidence",
        require_high_confidence=True,
        output_col="invoice_swap_ticker",
    )
    # No ticker, confidence untouched.
    assert pd.isna(out.loc[0, "invoice_swap_ticker"])
    assert out.loc[0, "matched_ust_maturity_trade_confidence"] == "low"


def test_invoice_match_sets_package_type_invoice(lookup, base_row):
    """Ticker hit -> package_type = trade_type = "INVOICE" so the PKG
    column in the dashboard groups invoice swaps as a distinct bucket."""
    row = dict(base_row)
    row["package_type"] = "OUTRIGHT"
    row["trade_type"] = "OUTRIGHT"
    df = pd.DataFrame([row])
    out = _apply_invoice_swap_lookup(
        df,
        lookup,
        effective_col="effective_date",
        maturity_col="expiration_date",
        confidence_col="matched_ust_maturity_trade_confidence",
        require_high_confidence=True,
        output_col="invoice_swap_ticker",
    )
    assert out.loc[0, "package_type"] == "INVOICE"
    assert out.loc[0, "trade_type"] == "INVOICE"


def test_no_spec_match_does_not_touch_package_type(lookup, base_row):
    row = dict(base_row)
    row["effective_date"] = pd.Timestamp("2026-07-06")
    row["expiration_date"] = pd.Timestamp("2033-05-15")  # Not in lookup
    row["package_type"] = "OUTRIGHT"
    row["trade_type"] = "OUTRIGHT"
    df = pd.DataFrame([row])
    out = _apply_invoice_swap_lookup(
        df,
        lookup,
        effective_col="effective_date",
        maturity_col="expiration_date",
        confidence_col="matched_ust_maturity_trade_confidence",
        require_high_confidence=True,
        output_col="invoice_swap_ticker",
    )
    assert out.loc[0, "package_type"] == "OUTRIGHT"
    assert out.loc[0, "trade_type"] == "OUTRIGHT"


def test_empty_confidence_series_on_spec_match(lookup, base_row):
    row = dict(base_row)
    row["matched_ust_maturity"] = False
    row["matched_ust_maturity_trade_confidence"] = pd.NA
    df = pd.DataFrame([row])
    out = _apply_invoice_swap_lookup(
        df,
        lookup,
        effective_col="effective_date",
        maturity_col="expiration_date",
        confidence_col="matched_ust_maturity_trade_confidence",
        require_high_confidence=True,
        output_col="invoice_swap_ticker",
    )
    assert out.loc[0, "invoice_swap_ticker"] == "TVA"
    assert out.loc[0, "matched_ust_maturity_trade_confidence"] == "high"
    assert bool(out.loc[0, "matched_ust_maturity"]) is True
