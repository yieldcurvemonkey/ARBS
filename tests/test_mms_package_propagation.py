from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from SDRUtils.packages.mms import detect_mms_trades_df

# Real mined UST coupons (design spec §10 / Global Constraints).
_UST = pd.DataFrame([
    {"cusip": "91282CQQ7", "maturity_date": pd.Timestamp("2036-05-15").date(),
     "issue_date": pd.Timestamp("2026-05-15").date(), "oi": "10-Year",
     "security_type": "Treasury Note", "coupon": 4.0, "original_security_term": "10-Year"},
    {"cusip": "912810UV8", "maturity_date": pd.Timestamp("2046-05-15").date(),
     "issue_date": pd.Timestamp("2026-05-15").date(), "oi": "20-Year",
     "security_type": "Treasury Bond", "coupon": 4.25, "original_security_term": "20-Year"},
    {"cusip": "91282CQV6", "maturity_date": pd.Timestamp("2029-06-15").date(),
     "issue_date": pd.Timestamp("2026-06-15").date(), "oi": "3-Year",
     "security_type": "Treasury Note", "coupon": 3.75, "original_security_term": "3-Year"},
])


@pytest.fixture
def fake_ust():
    with patch("SDRUtils.packages.mms._load_ust_reference_data", return_value=_UST.copy()):
        yield


def _leg(trade_id, tenor_years, expiration_date, package_type):
    # exec 2026-07-06; spot effective T+2 = 2026-07-08 (not needed exact for these gates).
    return {
        "trade_id": trade_id,
        "execution_timestamp": pd.Timestamp("2026-07-06 16:00:00", tz="UTC"),
        "effective_date": pd.Timestamp("2026-07-08"),
        "expiration_date": expiration_date,
        "product_type": "OIS_SWAP",
        "notional_currency": "USD",
        "package_type": package_type,
        "forward_label": "spot",
        "is_forward": False,
        "forward_start_years": 0.0,
        "tenor_years": tenor_years,
    }


def test_broken_tenor_packaged_leg_keeps_matched_flag(fake_ust):
    # 10Y leg @ 9.86y broken tenor tying the 2036-05-15 note, already in a CURVE.
    df = pd.DataFrame([_leg("A", 9.86, pd.Timestamp("2036-05-15"), "CURVE")])
    out = detect_mms_trades_df(df)
    assert bool(out.loc[0, "matched_ust_maturity"]) is True
    # outright_mask gates only the package rewrite, so a packaged leg is NOT retagged.
    assert out.loc[0, "package_type"] == "CURVE"


def test_clean_tenor_packaged_leg_is_still_wiped(fake_ust):
    # A GENUINELY clean 3Y (maturity on the exact anniversary of the
    # effective date) that coincidentally ties a UST coupon -> the
    # coincidence guard wipes it. The guard is date-based now: only a
    # maturity within a business-day roll of the standard anniversary
    # counts as clean.
    row = _leg("B", 3.0, pd.Timestamp("2029-06-15"), "CURVE")
    row["effective_date"] = pd.Timestamp("2026-06-15")
    df = pd.DataFrame([row])
    out = detect_mms_trades_df(df)
    assert bool(out.loc[0, "matched_ust_maturity"]) is False


def test_broken_date_near_standard_tenor_stays_matched(fake_ust):
    # 2.94y with maturity 23 days off the 3Y anniversary of 2026-07-08 —
    # a real matched-maturity swap (bug 7), not a clean 3Y; the old
    # ±0.1y year-fraction guard wrongly wiped these.
    df = pd.DataFrame([_leg("B2", 2.94, pd.Timestamp("2029-06-15"), "CURVE")])
    out = detect_mms_trades_df(df)
    assert bool(out.loc[0, "matched_ust_maturity"]) is True


def test_outright_broken_tenor_still_tagged(fake_ust):
    df = pd.DataFrame([_leg("C", 9.86, pd.Timestamp("2036-05-15"), "OUTRIGHT")])
    out = detect_mms_trades_df(df)
    assert bool(out.loc[0, "matched_ust_maturity"]) is True
    assert out.loc[0, "package_type"] == "MATCHED_MATURITY"
