"""Tight-gate tests for detect_spreadovers.

The CFTC ``Package indicator`` + ``Package transaction spread`` pair fires
for many non-spreadover broker flows (0-bp routing tags, invoice swaps,
package-price-only packages). Tight gate requires:

  - package_legs is NaN (not already paired as CURVE/FLY)
  - package_indicator == True
  - forward_label == "spot"
  - package_transaction_spread is a genuine number
  - spread is non-zero
  - |spread| <= 0.01 (100 bps; everything above is a reporting error)
  - invoice_swap_ticker is not set (mutual exclusion with invoice swaps)

The field is in decimal form (e.g. -0.004437 == -0.4437% == -44 bps).
"""
import pandas as pd
import pytest

from SDRUtils.products.usd.usd_swaps import detect_spreadovers


def _mk(**overrides):
    row = {
        "trade_id": "T1",
        "package_legs": None,
        "package_indicator": True,
        "package_transaction_spread": -0.004437,  # -44 bps 10Y spreadover
        "forward_label": "spot",
        "other_payment_type": None,
        "package_type": "OUTRIGHT",
        "invoice_swap_ticker": None,
        "tenor_years": 10.0,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_typical_spreadover_fires():
    out = detect_spreadovers(_mk())
    assert bool(out.loc[0, "is_spreadover"]) is True
    assert out.loc[0, "package_type"] == "SPREADOVER"


def test_zero_spread_does_not_fire():
    """Exact-zero spread is a broker routing tag, not a real spreadover."""
    out = detect_spreadovers(_mk(package_transaction_spread=0.0))
    assert bool(out.loc[0, "is_spreadover"]) is False
    assert out.loc[0, "package_type"] == "OUTRIGHT"


def test_huge_spread_does_not_fire():
    """|spread| > 100 bps (0.01) is a reporting error — reject."""
    for bad in (-44.0, 24.0, 900000.0, 0.015):
        out = detect_spreadovers(_mk(package_transaction_spread=bad))
        assert bool(out.loc[0, "is_spreadover"]) is False, f"bad spread {bad} leaked through"


def test_exactly_at_ceiling_fires():
    """Spread at the 100 bps boundary is still a plausible spreadover."""
    out = detect_spreadovers(_mk(package_transaction_spread=0.01))
    assert bool(out.loc[0, "is_spreadover"]) is True


def test_tiny_nonzero_spread_still_fires():
    """0.5 bps is small but can be a legit short-dated spreadover."""
    out = detect_spreadovers(_mk(package_transaction_spread=0.00005))
    assert bool(out.loc[0, "is_spreadover"]) is True


def test_invoice_swap_row_excluded_from_spreadover():
    """Invoice swaps resolve to their own bucket — must NOT also tag as spreadover."""
    out = detect_spreadovers(_mk(invoice_swap_ticker="TVA"))
    assert bool(out.loc[0, "is_spreadover"]) is False
    assert out.loc[0, "package_type"] != "SPREADOVER"


def test_forward_starting_does_not_fire():
    out = detect_spreadovers(_mk(forward_label="1Y"))
    assert bool(out.loc[0, "is_spreadover"]) is False


def test_null_spread_does_not_fire():
    out = detect_spreadovers(_mk(package_transaction_spread=None))
    assert bool(out.loc[0, "is_spreadover"]) is False


def test_string_spread_coerced_and_passes_if_valid():
    """CFTC sometimes emits the field as a string — coerce and still gate."""
    out = detect_spreadovers(_mk(package_transaction_spread="-0.0044"))
    assert bool(out.loc[0, "is_spreadover"]) is True


def test_string_spread_that_is_blank_does_not_fire():
    out = detect_spreadovers(_mk(package_transaction_spread=""))
    assert bool(out.loc[0, "is_spreadover"]) is False


def test_already_paired_package_not_overwritten():
    out = detect_spreadovers(_mk(package_legs=["T1", "T2"], package_type="CURVE"))
    assert bool(out.loc[0, "is_spreadover"]) is False
    assert out.loc[0, "package_type"] == "CURVE"


def test_missing_invoice_swap_column_is_tolerated():
    """detect_spreadovers must not break when invoice_swap_ticker column absent."""
    df = _mk()
    df = df.drop(columns=["invoice_swap_ticker"])
    out = detect_spreadovers(df)
    assert bool(out.loc[0, "is_spreadover"]) is True
