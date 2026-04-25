"""Post-pass that upgrades CURVE/FLY packages to composite types when
all legs individually satisfy MMS or SPREADOVER criteria.

Rationale: the primary ``detect_curve`` / ``detect_fly`` passes run
BEFORE ``detect_mms`` / ``detect_spreadovers``. A 2-leg curve trade
whose maturities BOTH match UST coupons (i.e. "matched maturity curve")
will be paired as a plain CURVE at step 1, and subsequent MMS tagging
(``only_tag_outrights=True``) skips it — the MMS-ness is lost from the
final PKG label.

This post-pass scans existing CURVE/FLY packages and upgrades their
``package_type`` to ``MATCHED_MATURITY_CURVE`` / ``SPREADOVER_FLY`` /
etc. when ALL legs individually qualify, so spread-curves and spread-
flies surface in their own PKG bucket.
"""
from __future__ import annotations

import pandas as pd

from SDRUtils.products.usd.usd_swaps import detect_sub_package_curve_fly


def _curve_pair(
    *,
    matched_ust_maturity: bool = False,
    package_indicator: bool = False,
    package_transaction_spread: float | None = None,
) -> pd.DataFrame:
    """Two legs already paired as a CURVE by a prior detector run."""
    return pd.DataFrame([
        {
            "trade_id": "T10Y",
            "tenor_years": 10.0,
            "package_type": "CURVE",
            "package_id": "CURVE_1_T10Y",
            "package_legs": ["T10Y", "T20Y"],
            "matched_ust_maturity": matched_ust_maturity,
            "package_indicator": package_indicator,
            "package_transaction_spread": package_transaction_spread,
            "forward_label": "spot",
        },
        {
            "trade_id": "T20Y",
            "tenor_years": 20.0,
            "package_type": "CURVE",
            "package_id": "CURVE_1_T10Y",
            "package_legs": ["T10Y", "T20Y"],
            "matched_ust_maturity": matched_ust_maturity,
            "package_indicator": package_indicator,
            "package_transaction_spread": package_transaction_spread,
            "forward_label": "spot",
        },
    ])


def _fly_triple(
    *,
    matched_ust_maturity: bool = False,
    package_indicator: bool = False,
    package_transaction_spread: float | None = None,
) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "trade_id": f"T{t}Y",
            "tenor_years": float(t),
            "package_type": "FLY",
            "package_id": "FLY_1_T5Y",
            "package_legs": ["T5Y", "T10Y", "T20Y"],
            "matched_ust_maturity": matched_ust_maturity,
            "package_indicator": package_indicator,
            "package_transaction_spread": package_transaction_spread,
            "forward_label": "spot",
        }
        for t in (5, 10, 20)
    ])


def test_curve_all_mms_legs_upgrades_to_MATCHED_MATURITY_CURVE():
    df = _curve_pair(matched_ust_maturity=True)
    out = detect_sub_package_curve_fly(df)
    assert set(out["package_type"].tolist()) == {"MATCHED_MATURITY_CURVE"}


def test_fly_all_mms_legs_upgrades_to_MATCHED_MATURITY_FLY():
    df = _fly_triple(matched_ust_maturity=True)
    out = detect_sub_package_curve_fly(df)
    assert set(out["package_type"].tolist()) == {"MATCHED_MATURITY_FLY"}


def test_curve_all_spreadover_legs_upgrades_to_SPREADOVER_CURVE():
    df = _curve_pair(package_indicator=True, package_transaction_spread=-0.004)
    out = detect_sub_package_curve_fly(df)
    assert set(out["package_type"].tolist()) == {"SPREADOVER_CURVE"}


def test_spreadover_takes_precedence_over_mms_when_both_apply():
    # A spread-curve where each leg also matches a UST coupon — the
    # SPREADOVER tag is more specific, so prefer SPREADOVER_CURVE.
    df = _curve_pair(
        matched_ust_maturity=True,
        package_indicator=True,
        package_transaction_spread=-0.004,
    )
    out = detect_sub_package_curve_fly(df)
    assert set(out["package_type"].tolist()) == {"SPREADOVER_CURVE"}


def test_plain_curve_without_mms_or_spreadover_stays_CURVE():
    df = _curve_pair(matched_ust_maturity=False, package_indicator=False)
    out = detect_sub_package_curve_fly(df)
    assert set(out["package_type"].tolist()) == {"CURVE"}


def test_partial_mms_does_not_upgrade_curve():
    # If only ONE of the two legs matches a UST, the package is NOT a
    # MATCHED_MATURITY_CURVE — it's a mixed-nature curve.
    df = _curve_pair(matched_ust_maturity=False)
    df.loc[0, "matched_ust_maturity"] = True
    out = detect_sub_package_curve_fly(df)
    assert set(out["package_type"].tolist()) == {"CURVE"}


def test_outright_rows_untouched():
    df = pd.DataFrame([
        {
            "trade_id": "T1",
            "tenor_years": 10.0,
            "package_type": "OUTRIGHT",
            "package_id": "OUTRIGHT-T1",
            "matched_ust_maturity": True,
        },
    ])
    out = detect_sub_package_curve_fly(df)
    assert out.loc[0, "package_type"] == "OUTRIGHT"


def test_out_of_band_spread_does_not_count_as_spreadover():
    # |spread| > 100 bps (0.01) is a reporting error — don't upgrade.
    df = _curve_pair(package_indicator=True, package_transaction_spread=-50.0)
    out = detect_sub_package_curve_fly(df)
    assert set(out["package_type"].tolist()) == {"CURVE"}


def test_zero_spread_does_not_count_as_spreadover():
    df = _curve_pair(package_indicator=True, package_transaction_spread=0.0)
    out = detect_sub_package_curve_fly(df)
    assert set(out["package_type"].tolist()) == {"CURVE"}
