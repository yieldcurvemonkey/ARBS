# tests/test_tape_levered_tag.py
"""A LEVERED tape-tag marks forward-levered swaps (fwd-start > tenor)."""
import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape


def _tags(rows):
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_context(df.copy())
    out = tape._build_enriched_label(out)
    return out["tape_tags"].tolist()


def _leg(**over):
    row = {
        "trade_id": "T1", "execution_timestamp": pd.Timestamp("2026-07-06 14:30:00", tz="UTC"),
        "product_type": "OIS_SWAP", "upi_underlier_name": "USD-SOFR-COMPOUND 1D",
        "upi_reset_freq": "1D", "upi_notional_schedule": "Constant", "upi_delivery_type": "PHYS",
        "trade_type": "OUTRIGHT", "package_type": "OUTRIGHT", "forward_label": "10Y",
        "forward_start_years": 10.0, "tenor_label": "1Y", "tenor_display": "1Y", "tenor_years": 1.0,
        "package_tenors": "1Y", "cleared": "Y", "special_tenor_type": "STANDARD",
        "effective_date": pd.Timestamp("2036-07-08"), "expiration_date": pd.Timestamp("2037-07-08"),
        "is_unwind": False, "is_mac": False, "is_ufro": False, "is_block": False,
    }
    row.update(over)
    return row


def test_10y1y_outright_is_levered():
    assert "LEVERED" in _tags([_leg()])[0]


def test_5y5y_is_not_levered():
    tags = _tags([_leg(forward_label="5Y", forward_start_years=5.0,
                       tenor_label="5Y", tenor_years=5.0)])[0]
    assert "LEVERED" not in tags


def test_spot_10y_is_not_levered():
    tags = _tags([_leg(forward_label="spot", forward_start_years=0.0,
                       tenor_label="10Y", tenor_years=10.0)])[0]
    assert "LEVERED" not in tags


def test_missing_forward_does_not_error():
    tags = _tags([_leg(forward_start_years=None)])[0]
    assert "LEVERED" not in tags
