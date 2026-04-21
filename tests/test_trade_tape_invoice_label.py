"""tape_label rendering for invoice-swap / MMS trades."""
import pandas as pd
import pytest

from SDRUtils.analytics.trade_tape import TradeTape


@pytest.fixture
def base_row():
    return {
        "trade_id": "T1",
        "execution_timestamp": pd.Timestamp("2026-04-15 14:30:00", tz="UTC"),
        "product_type": "OIS_SWAP",
        "upi_underlier_name": "USD-SOFR-COMPOUND 1D",
        "upi_reset_freq": "1D",
        "upi_notional_schedule": "Constant",
        "upi_delivery_type": "PHYS",
        "trade_type": "OUTRIGHT",
        "package_type": "OUTRIGHT",
        "forward_label": "IMM_M2026",
        "forward_start_years": 0.2,
        "tenor_label": "2Y",
        "tenor_display": "2Y",
        "package_tenors": "2Y",
        "cleared": "Y",
        "special_tenor_type": "INVOICE_SWAP",
        "effective_date": pd.Timestamp("2026-07-06"),
        "expiration_date": pd.Timestamp("2028-03-15"),
        "invoice_swap_ticker": "TVA",
        "matched_ust_maturity": True,
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


def test_invoice_swap_ticker_surfaces_in_tape_label(base_row):
    out = _compute([base_row])
    label = out.loc[0, "tape_label"]
    assert "TVA" in label
    assert "PHYS" in label
    # Expect ticker to appear BEFORE settlement
    ticker_idx = label.index("TVA")
    phys_idx = label.index("PHYS")
    assert ticker_idx < phys_idx


def test_mms_tag_surfaces_when_no_invoice_ticker(base_row):
    row = dict(base_row)
    row["invoice_swap_ticker"] = None
    row["special_tenor_type"] = "MATCHED_MATURITY"
    out = _compute([row])
    label = out.loc[0, "tape_label"]
    assert "MMS" in label
    assert "TVA" not in label


def test_standard_trade_has_neither_tag(base_row):
    row = dict(base_row)
    row["invoice_swap_ticker"] = None
    row["special_tenor_type"] = "STANDARD"
    row["matched_ust_maturity"] = False
    out = _compute([row])
    label = out.loc[0, "tape_label"]
    assert "TVA" not in label
    assert "MMS" not in label


def test_invoice_ticker_wins_over_mms_tag(base_row):
    """If both invoice_swap_ticker and MATCHED_MATURITY are set, show only
    the ticker — MMS is just generic matched-maturity, and the ticker is
    the more specific tag."""
    row = dict(base_row)
    row["invoice_swap_ticker"] = "TYA"
    row["special_tenor_type"] = "MATCHED_MATURITY"
    out = _compute([row])
    label = out.loc[0, "tape_label"]
    assert "TYA" in label
    assert "MMS" not in label
