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
