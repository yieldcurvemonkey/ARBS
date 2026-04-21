"""Secondary tape label for MMS trades using the UST-maturity MMYY alias.

Matches the alias scheme in
:mod:`Query.FixedRateBonds.FixedRateBondQuery` (e.g. ``'0236'`` for a
US Treasury note maturing in February 2036).
"""
import pandas as pd
import pytest

from SDRUtils.analytics.trade_tape import TradeTape


@pytest.fixture
def mms_row():
    return {
        "trade_id": "T1",
        "execution_timestamp": pd.Timestamp("2026-04-15 14:30:00", tz="UTC"),
        "product_type": "OIS_SWAP",
        "upi_underlier_name": "USD-SOFR-OIS Compound",
        "upi_reset_freq": "1D",
        "upi_notional_schedule": "Constant",
        "upi_delivery_type": "PHYS",
        "trade_type": "OUTRIGHT",
        "package_type": "OUTRIGHT",
        "package_indicator": True,
        "forward_label": "spot",
        "forward_start_years": 0.0,
        "tenor_label": "9Y10M",
        "tenor_display": "9Y10M",
        "package_tenors": "9Y10M",
        "cleared": "Y",
        "special_tenor_type": "MATCHED_MATURITY",
        "effective_date": pd.Timestamp("2026-04-17"),
        "expiration_date": pd.Timestamp("2036-02-15"),
        "matched_ust_maturity": True,
        "matched_ust_maturity_trade_confidence": "high",
        "invoice_swap_ticker": None,
        "is_unwind": False,
        "is_mac": False,
        "is_ufro": False,
        "is_block": False,
    }


def _compute(rows):
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_context(df.copy())
    out = tape._build_enriched_label(out)
    return out


def test_primary_label_keeps_raw_tenor(mms_row):
    out = _compute([mms_row])
    primary = out.loc[0, "tape_label"]
    assert "9Y10M" in primary
    assert "MMS" in primary


def test_secondary_label_replaces_tenor_with_mmyy_alias(mms_row):
    out = _compute([mms_row])
    alt = out.loc[0, "tape_label_ust_alias"]
    # Feb 2036 -> MMYY -> "0236"
    assert "0236" in alt
    assert "9Y10M" not in alt
    # MMS flag + settlement preserved
    assert "MMS" in alt
    assert "PHYS" in alt
    # Forward preserved
    assert "Spot" in alt


def test_secondary_label_equals_primary_for_non_mms(mms_row):
    """Non-MMS rows render identical primary and secondary labels."""
    row = dict(mms_row)
    row["special_tenor_type"] = "STANDARD"
    row["matched_ust_maturity"] = False
    out = _compute([row])
    assert out.loc[0, "tape_label"] == out.loc[0, "tape_label_ust_alias"]


def test_secondary_label_invariant_when_expiration_missing(mms_row):
    """If expiration_date is missing on an MMS row, fall back to the
    primary tenor — never emit an empty slot."""
    row = dict(mms_row)
    row["expiration_date"] = pd.NaT
    out = _compute([row])
    alt = out.loc[0, "tape_label_ust_alias"]
    assert "9Y10M" in alt


@pytest.mark.parametrize("exp_date,expected", [
    (pd.Timestamp("2036-02-15"), "0236"),
    (pd.Timestamp("2028-03-15"), "0328"),
    (pd.Timestamp("2030-08-31"), "0830"),
    (pd.Timestamp("2033-01-31"), "0133"),
    (pd.Timestamp("2044-05-15"), "0544"),
])
def test_mmyy_alias_format(mms_row, exp_date, expected):
    row = dict(mms_row)
    row["expiration_date"] = exp_date
    out = _compute([row])
    alt = out.loc[0, "tape_label_ust_alias"]
    assert expected in alt
