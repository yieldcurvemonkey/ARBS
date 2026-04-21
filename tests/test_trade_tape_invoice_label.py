"""tape_label rendering for invoice-swap / MMS trades.

Invoice-swap trades render "<PRODUCT_NAME> <TICKER>" in place of forward +
tenor, keep structure as "Outright", and surface the PKG flag "INVOICE"
via package_type / trade_type. Matched-maturity trades without a resolved
ticker get an "MMS" flag appended instead.
"""
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
        "trade_type": "INVOICE",
        "package_type": "INVOICE",
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


def test_invoice_swap_product_name_replaces_forward_and_tenor(base_row):
    """Product label '2Y TREASURY INVOICE TVA' replaces '82D 2Y' branch.
    Structure stays 'Outright'. Raw forward/tenor should not appear."""
    out = _compute([base_row])
    label = out.loc[0, "tape_label"]
    assert "2Y TREASURY INVOICE TVA" in label
    assert "Outright" in label
    assert "PHYS" in label
    # Raw forward/tenor must not appear.
    assert "IMM_M2026" not in label
    # Order: product-label BEFORE Outright BEFORE PHYS.
    pi = label.index("2Y TREASURY INVOICE TVA")
    oi = label.index("Outright")
    pi_phys = label.index("PHYS")
    assert pi < oi < pi_phys


def test_ultra_bond_invoice_swap_label(base_row):
    """UBA -> root WN -> 'ULTRA TREASURY INVOICE UBA'."""
    row = dict(base_row)
    row.update({
        "invoice_swap_ticker": "UBA",
        "tenor_label": "~26Y",
        "tenor_display": "~26Y",
        "forward_label": "82D",
        "effective_date": pd.Timestamp("2026-06-29"),
        "expiration_date": pd.Timestamp("2052-11-14"),
    })
    out = _compute([row])
    label = out.loc[0, "tape_label"]
    assert "ULTRA TREASURY INVOICE UBA" in label
    assert "Outright" in label
    assert "PHYS" in label
    assert "82D" not in label
    assert "~26Y" not in label


def test_mms_tag_surfaces_when_no_invoice_ticker(base_row):
    """MATCHED_MATURITY without invoice_swap_ticker keeps forward+tenor,
    appends 'MMS' to flags."""
    row = dict(base_row)
    row["invoice_swap_ticker"] = None
    row["special_tenor_type"] = "MATCHED_MATURITY"
    row["trade_type"] = "OUTRIGHT"
    row["package_type"] = "OUTRIGHT"
    out = _compute([row])
    label = out.loc[0, "tape_label"]
    assert "MMS" in label
    assert "2Y TREASURY INVOICE" not in label
    # Original forward+tenor comes through.
    assert "IMM_M2026" in label


def test_standard_trade_has_neither_tag(base_row):
    row = dict(base_row)
    row["invoice_swap_ticker"] = None
    row["special_tenor_type"] = "STANDARD"
    row["trade_type"] = "OUTRIGHT"
    row["package_type"] = "OUTRIGHT"
    row["matched_ust_maturity"] = False
    out = _compute([row])
    label = out.loc[0, "tape_label"]
    assert "TREASURY INVOICE" not in label
    assert "MMS" not in label


def test_invoice_label_beats_mms_tag_when_both_present(base_row):
    """If invoice_swap_ticker set AND special_tenor_type='MATCHED_MATURITY',
    product label wins and no MMS flag is appended."""
    row = dict(base_row)
    row["invoice_swap_ticker"] = "TYA"
    row["special_tenor_type"] = "MATCHED_MATURITY"
    out = _compute([row])
    label = out.loc[0, "tape_label"]
    assert "10Y TREASURY INVOICE TYA" in label
    assert "MMS" not in label


@pytest.mark.parametrize("ticker,expected_name", [
    ("TVA", "2Y TREASURY INVOICE TVA"),
    ("FYA", "5Y TREASURY INVOICE FYA"),
    ("TYA", "10Y TREASURY INVOICE TYA"),
    ("TNA", "ULTRA 10Y TREASURY INVOICE TNA"),
    ("UTA", "TREASURY BOND INVOICE UTA"),
    ("UBA", "ULTRA TREASURY INVOICE UBA"),
    ("TVF", "2Y TREASURY INVOICE TVF"),
    ("TAB", "10Y TREASURY INVOICE TAB"),
    ("UET", "TREASURY BOND INVOICE UET"),
    ("UBF", "ULTRA TREASURY INVOICE UBF"),
])
def test_product_label_per_root(base_row, ticker, expected_name):
    row = dict(base_row)
    row["invoice_swap_ticker"] = ticker
    out = _compute([row])
    label = out.loc[0, "tape_label"]
    assert expected_name in label
