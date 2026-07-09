from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from SDRUtils.packages.mms import detect_mms_trades_df
from SDRUtils.products.usd.usd_swaps import _rollup_matched_maturity_packages

_UST = pd.DataFrame([
    {"cusip": "91282CQQ7", "maturity_date": pd.Timestamp("2036-05-15").date(),
     "issue_date": pd.Timestamp("2026-05-15").date(), "oi": "10-Year",
     "security_type": "Treasury Note", "coupon": 4.0, "original_security_term": "10-Year"},
    {"cusip": "912810UV8", "maturity_date": pd.Timestamp("2046-05-15").date(),
     "issue_date": pd.Timestamp("2026-05-15").date(), "oi": "20-Year",
     "security_type": "Treasury Bond", "coupon": 4.25, "original_security_term": "20-Year"},
    {"cusip": "91282CPZ8", "maturity_date": pd.Timestamp("2036-02-15").date(),
     "issue_date": pd.Timestamp("2026-02-15").date(), "oi": "10-Year",
     "security_type": "Treasury Note", "coupon": 4.0, "original_security_term": "10-Year"},
])


def _leg(tid, ten, exp, ptype, pid):
    return {
        "trade_id": tid, "execution_timestamp": pd.Timestamp("2026-07-06 16:00:00", tz="UTC"),
        "effective_date": pd.Timestamp("2026-07-08"), "expiration_date": pd.Timestamp(exp),
        "product_type": "OIS_SWAP", "notional_currency": "USD", "package_type": ptype,
        "package_id": pid, "forward_label": "spot", "is_forward": False,
        "forward_start_years": 0.0, "tenor_years": ten,
    }


def test_ptp_curve_promotes_and_pkg3_stays():
    df = pd.DataFrame([
        # PTP all-MMS CURVE (diff bonds) -> MATCHED_MATURITY_CURVE
        _leg("C1", 9.86, "2036-05-15", "CURVE", "PTP_C"),
        _leg("C2", 19.87, "2046-05-15", "CURVE", "PTP_C"),
        # all-MMS same-bond PKG-3 -> stays PKG-3, every leg matched
        _leg("P1", 9.86, "2036-02-15", "PKG-3", "PTP_P"),
        _leg("P2", 9.86, "2036-02-15", "PKG-3", "PTP_P"),
        _leg("P3", 9.86, "2036-02-15", "PKG-3", "PTP_P"),
    ])
    with patch("SDRUtils.packages.mms._load_ust_reference_data", return_value=_UST.copy()):
        tagged = detect_mms_trades_df(df)
    out = _rollup_matched_maturity_packages(tagged)
    curve = out[out["package_id"] == "PTP_C"]
    pkg3 = out[out["package_id"] == "PTP_P"]
    assert set(curve["package_type"]) == {"MATCHED_MATURITY_CURVE"}
    assert set(pkg3["package_type"]) == {"PKG-3"}
    assert bool(pkg3["matched_ust_maturity"].astype(str).str.lower().isin({"true", "t", "1"}).all())
