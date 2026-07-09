"""Phase 2 (labels): package-level + per-leg MMYY UST-alias tape labels."""
from __future__ import annotations

import pandas as pd

from SDRUtils.analytics.trade_tape import TradeTape


def _pkg_legs(package_type, package_id, legs):
    """legs: list of (trade_id, tenor_years, expiration_date-str)."""
    tids = [t for t, _, _ in legs]
    rows = []
    for tid, ten, exp in legs:
        rows.append({
            "trade_id": tid, "tenor_years": ten, "expiration_date": pd.Timestamp(exp),
            "package_type": package_type, "package_id": package_id, "package_legs": tids,
            "is_package": True,
            "special_tenor_type": "MATCHED_MATURITY", "matched_ust_maturity": True,
            "forward_label": "spot", "product_type": "OIS_SWAP",
            "upi_underlier_name": "USD-SOFR-OIS Compound", "upi_reset_freq": "1D",
            "upi_notional_schedule": "Constant", "upi_delivery_type": "PHYS",
            "trade_type": package_type, "tenor_label": f"{int(round(ten))}Y",
            "tenor_display": f"{int(round(ten))}Y", "cleared": "Y",
        })
    return rows


def test_package_ust_aliases_case_a_collapses_to_single():
    rows = _pkg_legs("PKG-2", "P1", [("L1", 9.86, "2036-02-15"), ("L2", 9.86, "2036-02-15")])
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_packages(df.copy())
    assert set(out["package_ust_aliases"].tolist()) == {"0236"}


def test_package_ust_aliases_case_b_joins_distinct():
    rows = _pkg_legs("CURVE", "C1", [("L1", 9.86, "2036-05-15"), ("L2", 19.87, "2046-05-15")])
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_packages(df.copy())
    assert set(out["package_ust_aliases"].tolist()) == {"0536/0546"}


def _enrich_and_label(rows):
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_packages(df.copy())
    out = tape._build_enriched_label(out)
    return out


def test_pkg_alias_label_shows_alias_and_mms():
    rows = _pkg_legs("PKG-2", "P2", [("L1", 9.86, "2036-02-15"), ("L2", 9.86, "2036-02-15")])
    out = _enrich_and_label(rows)
    alt = out.loc[0, "tape_label_ust_alias"]
    assert "0236" in alt
    assert "MMS" in alt
    assert "PHYS" in alt


def test_curve_alias_label_joins_maturities():
    rows = _pkg_legs("CURVE", "C1", [("L1", 9.86, "2036-05-15"), ("L2", 19.87, "2046-05-15")])
    out = _enrich_and_label(rows)
    alt = out.loc[0, "tape_label_ust_alias"]
    assert "0536/0546" in alt
    assert "CURVE" in alt and "MMS" in alt


def test_leg_tape_label_ust_alias_present_per_leg():
    rows = _pkg_legs("CURVE", "C1", [("L1", 9.86, "2036-05-15"), ("L2", 19.87, "2046-05-15")])
    out = _enrich_and_label(rows)
    assert "leg_tape_label_ust_alias" in out.columns
    assert "0536" in out.loc[0, "leg_tape_label_ust_alias"]
    assert "0546" in out.loc[1, "leg_tape_label_ust_alias"]
