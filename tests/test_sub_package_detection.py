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
    package_transaction_spread: float | tuple[float, float] | None = None,
) -> pd.DataFrame:
    """Two legs already paired as a CURVE by a prior detector run.

    ``package_transaction_spread`` may be a single scalar (broadcast to both
    legs, i.e. a uniform/broadcast package spread) or a (front, back) tuple
    for DISTINCT per-leg spreads -- the genuine Phase-1 spreadover-curve case.
    """
    if isinstance(package_transaction_spread, tuple):
        spread_front, spread_back = package_transaction_spread
    else:
        spread_front = spread_back = package_transaction_spread
    return pd.DataFrame([
        {
            "trade_id": "T10Y",
            "tenor_years": 10.0,
            "package_type": "CURVE",
            "package_id": "CURVE_1_T10Y",
            "package_legs": ["T10Y", "T20Y"],
            "matched_ust_maturity": matched_ust_maturity,
            "package_indicator": package_indicator,
            "package_transaction_spread": spread_front,
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
            "package_transaction_spread": spread_back,
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
    # DISTINCT per-leg spreads -- the genuine Phase-1 case. A uniform/shared
    # spread across legs is a broadcast package spread, not distinct
    # standalone spreadover levels, and is left to detect_spreadover_curves_df
    # (the differential detector) instead -- see
    # test_uniform_leg_spread_does_not_upgrade_in_phase1 below.
    df = _curve_pair(
        package_indicator=True,
        package_transaction_spread=(-0.004239, -0.007475),
    )
    out = detect_sub_package_curve_fly(df)
    assert set(out["package_type"].tolist()) == {"SPREADOVER_CURVE"}


def test_spreadover_takes_precedence_over_mms_when_both_apply():
    # A spread-curve where each leg also matches a UST coupon — the
    # SPREADOVER tag is more specific, so prefer SPREADOVER_CURVE.
    # DISTINCT per-leg spreads -- the genuine Phase-1 case (see above).
    df = _curve_pair(
        matched_ust_maturity=True,
        package_indicator=True,
        package_transaction_spread=(-0.004239, -0.007475),
    )
    out = detect_sub_package_curve_fly(df)
    assert set(out["package_type"].tolist()) == {"SPREADOVER_CURVE"}


def test_uniform_leg_spread_does_not_upgrade_in_phase1():
    # A UNIFORM (shared) per-leg spread is a broadcast package spread, not
    # distinct individual spreadover levels -- Phase-1 leaves it as a plain
    # CURVE. Confirming it as SPREADOVER_CURVE is the differential
    # detector's job (detect_spreadover_curves_df), which requires standalone
    # SPREADOVER prints to tie the package PTS out to a differential.
    df = _curve_pair(package_indicator=True, package_transaction_spread=-0.004)
    out = detect_sub_package_curve_fly(df)
    assert set(out["package_type"].tolist()) == {"CURVE"}


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


from SDRUtils.products.usd.usd_swaps import _rollup_matched_maturity_packages


def _ptp_curve(*, matched_ust_maturity: bool, package_type: str = "CURVE",
               package_id: str = "PTP_1") -> pd.DataFrame:
    """A PTP-grouped CURVE (bypasses detect_sub_package_curve_fly today)."""
    return pd.DataFrame([
        {"trade_id": "L1", "tenor_years": 9.86, "package_type": package_type,
         "package_id": package_id, "matched_ust_maturity": matched_ust_maturity},
        {"trade_id": "L2", "tenor_years": 19.87, "package_type": package_type,
         "package_id": package_id, "matched_ust_maturity": matched_ust_maturity},
    ])


def test_rollup_promotes_ptp_all_mms_curve():
    out = _rollup_matched_maturity_packages(_ptp_curve(matched_ust_maturity=True))
    assert set(out["package_type"].tolist()) == {"MATCHED_MATURITY_CURVE"}


def test_rollup_leaves_pkg_n_type_unchanged():
    df = _ptp_curve(matched_ust_maturity=True, package_type="PKG-3", package_id="PTP_2")
    out = _rollup_matched_maturity_packages(df)
    assert set(out["package_type"].tolist()) == {"PKG-3"}


def test_rollup_partial_stays_base():
    df = _ptp_curve(matched_ust_maturity=False)
    df.loc[0, "matched_ust_maturity"] = True
    out = _rollup_matched_maturity_packages(df)
    assert set(out["package_type"].tolist()) == {"CURVE"}


def test_rollup_skips_spreadover_and_invoice():
    for ptype in ("SPREADOVER_CURVE", "INVOICE_SWITCH", "MATCHED_MATURITY_CURVE"):
        df = _ptp_curve(matched_ust_maturity=True, package_type=ptype, package_id=f"P_{ptype}")
        out = _rollup_matched_maturity_packages(df)
        assert set(out["package_type"].tolist()) == {ptype}
