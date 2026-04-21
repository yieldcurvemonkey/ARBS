"""Safety-net UPI validator in TradeTape._enrich_packages.

An SDR-native package (package_indicator=True, package_type set upstream,
package_legs populated) whose legs have heterogeneous UPIs must be
un-packaged back to OUTRIGHT.
"""
import pandas as pd

from SDRUtils.analytics.trade_tape import TradeTape


def _mk_spurious_curve(upi_a: str, upi_b: str) -> pd.DataFrame:
    base = pd.Timestamp("2026-04-15 14:30:00", tz="UTC")
    rows = [
        {"trade_id": "A", "execution_timestamp": base,
         "product_type": "OIS_SWAP", "package_type": "CURVE",
         "package_id": "SPURIOUS_1", "package_legs": ["A", "B"],
         "package_indicator": True,
         "tenor_label": "5Y", "tenor_years": 5.0, "tenor_display": "5Y",
         "notional_currency": "USD",
         "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "trade_type": "CURVE",
         "Unique Product Identifier": upi_a,
         "unique_product_identifier": upi_a},
        {"trade_id": "B", "execution_timestamp": base + pd.Timedelta(seconds=10),
         "product_type": "OIS_SWAP", "package_type": "CURVE",
         "package_id": "SPURIOUS_1", "package_legs": ["A", "B"],
         "package_indicator": True,
         "tenor_label": "10Y", "tenor_years": 10.0, "tenor_display": "10Y",
         "notional_currency": "USD",
         "effective_date": pd.Timestamp("2026-04-17"),
         "forward_label": "spot", "trade_type": "CURVE",
         "Unique Product Identifier": upi_b,
         "unique_product_identifier": upi_b},
    ]
    return pd.DataFrame(rows)


def test_heterogeneous_upi_gets_unpackaged():
    df = _mk_spurious_curve("QZF08M5TR8H3", "DIFFERENTUPIABC")
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_packages(df.copy())
    assert (out["package_type"].str.upper() == "OUTRIGHT").all()
    assert out["is_package"].eq(False).all()


def test_homogeneous_upi_survives():
    df = _mk_spurious_curve("QZF08M5TR8H3", "QZF08M5TR8H3")
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_packages(df.copy())
    assert (out["package_type"].str.upper() == "CURVE").all()
