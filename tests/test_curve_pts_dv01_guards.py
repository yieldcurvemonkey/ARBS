# tests/test_curve_pts_dv01_guards.py
"""Curve DV01-neutrality + PTS tie-out guards (07/07/2026 tape bugs).

Bug 1: two ISWV "5Y/30Y CURVE" rows were really four separate spreadover
prints. Evidence encoded here: legs carried DISTINCT package transaction
spreads (each leg's own swap spread vs UST, both negative) and the leg
DV01s did not tie out (45K vs 42K = 3K gap). A genuine curve package is
DV01-neutral within ~$500 and, when PTS is stamped, carries ONE spread
across its legs.

Bug 2: a TSEF 10Y/12Y/15Y triplet sharing one identical PTS at the same
second was split into CURVE(10Y/12Y) + OUTRIGHT(15Y) because the PTP
grouper only keyed on package transaction PRICE. Identical spread across
distinct tenors at the same instant is the same package fingerprint the
PTP path already trusts -> PKG-3.
"""
import numpy as np
import pandas as pd

from SDRUtils.core.parsing import SPREAD_DECIMAL_SENTINEL
from SDRUtils.packages.curve import detect_curve_trades_df
from SDRUtils.packages.ptp_grouper import classify_ptp_groups, group_by_ptp

_SNAKE = dict(underlier_col="upi_underlier_name", platform_col="platform_identifier",
              cleared_col="cleared", upi_col="unique_product_identifier")


def _curve_leg(tid, ts, tenor_lbl, tenor_yrs, pv01, pts=None, segment="MEDIUM",
               special_tenor="STANDARD"):
    return dict(
        trade_id=tid, execution_timestamp=ts,
        product_type="OIS_SWAP", package_type="OUTRIGHT",
        estimated_pv01=pv01, tenor_label=tenor_lbl, tenor_years=tenor_yrs,
        effective_date="2026-07-08", forward_label="spot", forward_start_years=0.0,
        notional_currency="USD", upi_underlier_name="USD-SOFR-COMPOUND",
        unique_product_identifier="UPI-OIS", platform_identifier="ISWV",
        cleared="I", rate_index="SOFR_COMPOUND", tenor_segment=segment,
        special_tenor_type=special_tenor, package_transaction_spread=pts,
        package_indicator=True,
    )


# ── Bug 1 unit: curve detector guards ────────────────────────────────


class TestCurvePtsTieOut:
    def test_mismatched_pts_blocks_curve_pairing(self):
        """Screenshot-1 pair: 5Y PTS -29.25bp vs 30Y PTS -74.625bp.
        Distinct per-leg spreads = two separate spreadover packages."""
        df = pd.DataFrame([
            _curve_leg("A", "2026-07-06 15:04:36Z", "5Y", 5.0, 45000.0, pts=-0.002925),
            _curve_leg("B", "2026-07-06 15:05:11Z", "30Y", 30.0, 45000.0, pts=-0.0074625),
        ])
        out = detect_curve_trades_df(df, **_SNAKE)
        assert not out["package_type"].astype(str).str.contains("CURVE").any()

    def test_equal_pts_does_not_block(self):
        """One spread stamped on both legs = one package; the PTS gate
        must not reject it (DV01s tie exactly here)."""
        df = pd.DataFrame([
            _curve_leg("A", "2026-07-06 15:04:36Z", "5Y", 5.0, 45000.0, pts=-0.0002),
            _curve_leg("B", "2026-07-06 15:04:40Z", "30Y", 30.0, 45000.0, pts=-0.0002),
        ])
        out = detect_curve_trades_df(df, **_SNAKE)
        assert out["package_type"].astype(str).str.contains("CURVE").all()

    def test_one_sided_pts_still_pairs(self):
        """Soft gate (mirrors fly.py): NaN on either side passes."""
        df = pd.DataFrame([
            _curve_leg("A", "2026-07-06 15:04:36Z", "5Y", 5.0, 45000.0, pts=None),
            _curve_leg("B", "2026-07-06 15:04:40Z", "30Y", 30.0, 45000.0, pts=-0.0002),
        ])
        out = detect_curve_trades_df(df, **_SNAKE)
        assert out["package_type"].astype(str).str.contains("CURVE").all()

    def test_sentinel_pts_never_vetoes_pairing(self):
        """9.9999999999 means 'unknown' (Tech Spec Appendix G) — it must
        behave as NaN in the gate, not as a real spread that mismatches."""
        df = pd.DataFrame([
            _curve_leg("A", "2026-07-06 15:04:36Z", "5Y", 5.0, 45000.0,
                       pts=SPREAD_DECIMAL_SENTINEL),
            _curve_leg("B", "2026-07-06 15:04:40Z", "30Y", 30.0, 45000.0,
                       pts=-0.0002),
        ])
        out = detect_curve_trades_df(df, **_SNAKE)
        assert out["package_type"].astype(str).str.contains("CURVE").all()

    def test_sentinel_pts_on_both_legs_passes_as_unknown(self):
        """sentinel == sentinel is NaN-vs-NaN, not affirmative evidence —
        the pair still pairs, on the DV01/econ guards alone."""
        df = pd.DataFrame([
            _curve_leg("A", "2026-07-06 15:04:36Z", "5Y", 5.0, 45000.0,
                       pts=SPREAD_DECIMAL_SENTINEL),
            _curve_leg("B", "2026-07-06 15:04:40Z", "30Y", 30.0, 45000.0,
                       pts=SPREAD_DECIMAL_SENTINEL),
        ])
        out = detect_curve_trades_df(df, **_SNAKE)
        assert out["package_type"].astype(str).str.contains("CURVE").all()


class TestCurveAbsDv01Tolerance:
    def test_3k_dv01_gap_blocks_curve(self):
        """Screenshot-1 DV01s: 45K vs 42K = 6.9% relative (old 10% gate
        passed) but $3K absolute -> not DV01-neutral, no curve."""
        df = pd.DataFrame([
            _curve_leg("A", "2026-07-06 15:04:36Z", "5Y", 5.0, 45000.0),
            _curve_leg("B", "2026-07-06 15:05:11Z", "30Y", 30.0, 42000.0),
        ])
        out = detect_curve_trades_df(df, **_SNAKE)
        assert not out["package_type"].astype(str).str.contains("CURVE").any()

    def test_sub_500_gap_still_pairs(self):
        df = pd.DataFrame([
            _curve_leg("A", "2026-07-06 15:04:36Z", "5Y", 5.0, 45000.0),
            _curve_leg("B", "2026-07-06 15:05:11Z", "30Y", 30.0, 44700.0),
        ])
        out = detect_curve_trades_df(df, **_SNAKE)
        assert out["package_type"].astype(str).str.contains("CURVE").all()

    def test_fomc_pairs_exempt_from_abs_gate(self):
        """FOMC switches trade risk-weighted, not DV01-flat; the wide
        0.50 relative tolerance stays authoritative for them."""
        df = pd.DataFrame([
            _curve_leg("A", "2026-07-06 15:04:36Z", "1M", 0.09, 20000.0,
                       segment="SHORT", special_tenor="FOMC"),
            _curve_leg("B", "2026-07-06 15:04:40Z", "2M", 0.17, 26000.0,
                       segment="SHORT", special_tenor="FOMC"),
        ])
        out = detect_curve_trades_df(df, **_SNAKE)
        assert out["package_type"].astype(str).str.contains("CURVE").all()

    def test_abs_gate_can_be_disabled(self):
        df = pd.DataFrame([
            _curve_leg("A", "2026-07-06 15:04:36Z", "5Y", 5.0, 45000.0),
            _curve_leg("B", "2026-07-06 15:05:11Z", "30Y", 30.0, 42000.0),
        ])
        out = detect_curve_trades_df(df, pv01_abs_tolerance=None, **_SNAKE)
        assert out["package_type"].astype(str).str.contains("CURVE").all()


# ── Bug 2 unit: PTS-keyed package grouping ───────────────────────────


def _pts_leg(tid, ts, tenor_yrs, pv01, pts, ptp=None, platform="TSEF",
             fwd_yrs=0.0, pkg_ind=True):
    return dict(
        trade_id=tid, execution_timestamp=ts,
        package_transaction_price=ptp, package_transaction_spread=pts,
        package_indicator=pkg_ind, unique_product_identifier="UPI-OIS",
        platform_identifier=platform, estimated_pv01=pv01,
        tenor_years=tenor_yrs, forward_start_years=fwd_yrs,
        fixed_rate=0.04, product_type="OIS_SWAP",
    )


class TestPtsGrouping:
    def test_identical_pts_across_tenors_forms_pkg3(self):
        """Screenshot-2 triplet: 10Y/12Y/15Y, one PTS (-2.0625bp), same
        second, same platform -> one PKG-3, not CURVE + orphan."""
        ts = pd.Timestamp("2026-07-06 14:06:19", tz="UTC")
        df = pd.DataFrame([
            _pts_leg("T10", ts, 10.0, 250000.0, -0.00020625),
            _pts_leg("T12", ts, 12.0, 237000.0, -0.00020625),
            _pts_leg("T15", ts, 15.0, 234000.0, -0.00020625),
        ])
        grouped, remainder = group_by_ptp(df, time_tolerance_seconds=5)
        assert len(grouped) == 3 and len(remainder) == 0
        assert grouped["ptp_group_id"].nunique() == 1
        classified = classify_ptp_groups(grouped)
        assert (classified["package_type"] == "PKG-3").all()
        assert classified["package_legs"].iloc[0] == ["T10", "T12", "T15"]

    def test_same_tenor_same_pts_spreadover_not_grouped(self):
        """Screenshot-1's two 5Y prints share the prevailing swap-vs-UST
        spreadover level (a benchmark tenor, spot, NEGATIVE spread) at the
        same second. That is two separate asset-swap prints, never one
        package (mirrors the SOCRV same-tenor guard)."""
        ts = pd.Timestamp("2026-07-06 15:04:36", tz="UTC")
        df = pd.DataFrame([
            _pts_leg("A", ts, 5.0, 45000.0, -0.002925, platform="ISWV"),
            _pts_leg("B", ts, 5.0, 45000.0, -0.002925, platform="ISWV"),
        ])
        grouped, remainder = group_by_ptp(df, time_tolerance_seconds=5)
        assert len(grouped) == 0
        assert len(remainder) == 2

    def test_same_tenor_nonspreadover_pair_forms_pkg2(self):
        """A same-tenor pair that is NOT a spreadover — a non-benchmark
        tenor (15Y) with a small POSITIVE package spread, same second, same
        platform — is a genuine switch/roll and groups as PKG-2 (imgs #5/#6:
        two 15Y prints at +1.4bp PTS were shown as separate outrights)."""
        ts = pd.Timestamp("2026-07-06 15:04:36", tz="UTC")
        df = pd.DataFrame([
            _pts_leg("A", ts, 15.0, 250000.0, 0.00014),
            _pts_leg("B", ts, 15.0, 250000.0, 0.00014),
        ])
        grouped, remainder = group_by_ptp(df, time_tolerance_seconds=5)
        assert len(grouped) == 2 and len(remainder) == 0
        assert grouped["ptp_group_id"].nunique() == 1
        classified = classify_ptp_groups(grouped)
        # Same tenor => no second economic axis => PKG-2, never CURVE.
        assert (classified["package_type"] == "PKG-2").all()

    def test_same_tenor_benchmark_positive_pts_forms_pkg2(self):
        """Even at a benchmark tenor (10Y), a POSITIVE package spread is not a
        spreadover (spreadovers are quoted negative), so a same-second pair is
        a genuine PKG-2, not two separate prints."""
        ts = pd.Timestamp("2026-07-06 15:04:36", tz="UTC")
        df = pd.DataFrame([
            _pts_leg("A", ts, 10.0, 250000.0, 0.00013),
            _pts_leg("B", ts, 10.0, 250000.0, 0.00013),
        ])
        grouped, remainder = group_by_ptp(df, time_tolerance_seconds=5)
        assert len(grouped) == 2 and len(remainder) == 0
        classified = classify_ptp_groups(grouped)
        assert (classified["package_type"] == "PKG-2").all()

    def test_three_same_tenor_spreadover_still_block_split(self):
        """Three same-tenor spreadover prints (benchmark 5Y, negative PTS) stay
        separate — the same-tenor PKG-2 relaxation is restricted to PAIRS so a
        larger benchmark cluster is not coalesced into one package."""
        ts = pd.Timestamp("2026-07-06 15:04:36", tz="UTC")
        df = pd.DataFrame([
            _pts_leg("A", ts, 5.0, 45000.0, -0.002925, platform="ISWV"),
            _pts_leg("B", ts, 5.0, 45000.0, -0.002925, platform="ISWV"),
            _pts_leg("C", ts, 5.0, 45000.0, -0.002925, platform="ISWV"),
        ])
        grouped, remainder = group_by_ptp(df, time_tolerance_seconds=5)
        assert len(grouped) == 0
        assert len(remainder) == 3

    def test_same_tail_distinct_forwards_grouped(self):
        """Forward-axis packages (gap curves, FOMC switches) share the
        tail tenor but differ on forward start — still one package."""
        ts = pd.Timestamp("2026-07-06 15:04:36", tz="UTC")
        df = pd.DataFrame([
            _pts_leg("A", ts, 1.0, 20000.0, -0.0004, fwd_yrs=1.0),
            _pts_leg("B", ts, 1.0, 20000.0, -0.0004, fwd_yrs=2.0),
        ])
        grouped, remainder = group_by_ptp(df, time_tolerance_seconds=5)
        assert len(grouped) == 2 and len(remainder) == 0

    def test_ptp_key_takes_precedence_over_pts(self):
        """Legs carrying a usable package PRICE keep grouping exactly as
        before, even when a spread is also stamped."""
        ts = pd.Timestamp("2026-07-06 15:04:36", tz="UTC")
        df = pd.DataFrame([
            _pts_leg("A", ts, 2.0, 5000.0, -0.0004, ptp=88100.0),
            _pts_leg("B", ts, 10.0, 5000.0, -0.0009, ptp=88100.0),
        ])
        grouped, _ = group_by_ptp(df, time_tolerance_seconds=5)
        assert len(grouped) == 2
        assert grouped["ptp_group_id"].nunique() == 1

    def test_sentinel_spread_never_groups(self):
        """The 9.9999999999 'unknown' sentinel is not a package
        fingerprint — two unrelated legs stamped with it must not merge."""
        ts = pd.Timestamp("2026-07-06 15:04:36", tz="UTC")
        df = pd.DataFrame([
            _pts_leg("A", ts, 2.0, 5000.0, SPREAD_DECIMAL_SENTINEL),
            _pts_leg("B", ts, 10.0, 5000.0, SPREAD_DECIMAL_SENTINEL),
        ])
        grouped, remainder = group_by_ptp(df, time_tolerance_seconds=5)
        assert len(grouped) == 0
        assert len(remainder) == 2

    def test_distinct_pts_distinct_tenors_do_not_merge(self):
        """The spread VALUE is the fingerprint. Two packages with
        different spreads must not merge even across tenors in the same
        window — only the tenor-axis guard rescuing this would mean the
        key itself stopped discriminating."""
        ts = pd.Timestamp("2026-07-06 15:04:36", tz="UTC")
        df = pd.DataFrame([
            _pts_leg("A", ts, 5.0, 45000.0, -0.002925, platform="ISWV"),
            _pts_leg("B", ts, 30.0, 42000.0, -0.0074625, platform="ISWV"),
        ])
        grouped, remainder = group_by_ptp(df, time_tolerance_seconds=5)
        assert len(grouped) == 0
        assert len(remainder) == 2

    def test_distinct_pts_values_do_not_merge(self):
        """Screenshot-1's 30Y prints: -74.625bp vs -74.5bp are different
        packages even in the same 2-second window."""
        ts = pd.Timestamp("2026-07-06 15:05:11", tz="UTC")
        df = pd.DataFrame([
            _pts_leg("A", ts, 30.0, 42000.0, -0.0074625, platform="ISWV"),
            _pts_leg("B", ts + pd.Timedelta(seconds=2), 30.0, 42000.0, -0.00745,
                     platform="ISWV"),
        ])
        grouped, remainder = group_by_ptp(df, time_tolerance_seconds=5)
        assert len(grouped) == 0
        assert len(remainder) == 2


class TestPtpPairCurveNeutrality:
    def test_two_leg_ptp_group_with_wide_dv01_gap_is_curve(self):
        """10Y/12Y with 250K/237K DV01 (5.3% gap). Under the scaled
        abs-DV01 gate (10% of avg), this passes as CURVE — the relative
        imbalance is well within tolerance for large-notional trades."""
        ts = pd.Timestamp("2026-07-06 14:06:19", tz="UTC")
        df = pd.DataFrame([
            _pts_leg("A", ts, 10.0, 250000.0, None, ptp=88100.0),
            _pts_leg("B", ts, 12.0, 237000.0, None, ptp=88100.0),
        ])
        grouped, _ = group_by_ptp(df, time_tolerance_seconds=5)
        classified = classify_ptp_groups(grouped)
        assert (classified["package_type"] == "CURVE").all()

    def test_two_leg_ptp_group_neutral_is_curve(self):
        ts = pd.Timestamp("2026-07-06 14:06:19", tz="UTC")
        df = pd.DataFrame([
            _pts_leg("A", ts, 5.0, 45000.0, None, ptp=88100.0),
            _pts_leg("B", ts, 10.0, 44800.0, None, ptp=88100.0),
        ])
        grouped, _ = group_by_ptp(df, time_tolerance_seconds=5)
        classified = classify_ptp_groups(grouped)
        assert (classified["package_type"] == "CURVE").all()


# ── Integration: full screenshot scenarios through the detector chain ─


def _bug1_frame():
    """The four ISWV prints from screenshot 1 (07/06 15:04-15:05Z)."""
    rows = [
        ("A5", "2026-07-06 15:04:36Z", "5Y", 5.0, 45000.0, -0.002925),
        ("B30", "2026-07-06 15:05:11Z", "30Y", 30.0, 42000.0, -0.0074625),
        ("C5", "2026-07-06 15:04:36Z", "5Y", 5.0, 45000.0, -0.002925),
        ("D30", "2026-07-06 15:05:35Z", "30Y", 30.0, 42000.0, -0.00745),
    ]
    df = pd.DataFrame([
        _curve_leg(t, ts, lbl, ty, pv, pts=pts,
                   segment="MEDIUM" if ty == 5.0 else "LONG")
        for t, ts, lbl, ty, pv, pts in rows
    ])
    df["forward_start_years"] = 0.0
    df["package_legs"] = None
    df["invoice_swap_ticker"] = None
    return df


def test_bug1_four_separate_spreadovers_end_to_end():
    from SDRUtils.products.usd.usd_swaps import (
        detect_spreadovers,
        detect_sub_package_curve_fly,
    )

    df = _bug1_frame()

    grouped, remainder = group_by_ptp(df, time_tolerance_seconds=5)
    # The 5Y twins share a market spread level but the same tenor:
    # separate prints, nothing groups.
    assert len(grouped) == 0

    out = detect_curve_trades_df(remainder, **_SNAKE)
    assert not out["package_type"].astype(str).str.contains("CURVE").any()

    out = detect_spreadovers(out)
    assert (out["package_type"] == "SPREADOVER").all()

    out = detect_sub_package_curve_fly(out)
    # SOCRV phase must not re-merge them: 5Y twins same tenor, 30Y
    # prints carry distinct spreads.
    assert (out["package_type"] == "SPREADOVER").all()
    assert out["package_id"].isna().all()


def test_pts_grouped_spreadover_pair_keeps_composite_label():
    """Two spreadover legs stamped with ONE shared PTS are one package —
    the PTS grouper claims them before the curve detector runs. The
    grouped frame must still receive the Phase-1 composite upgrade
    (CURVE -> SPREADOVER_CURVE), matching the detector-paired path."""
    from SDRUtils.products.usd.usd_swaps import detect_sub_package_curve_fly

    ts = pd.Timestamp("2026-07-06 15:04:36", tz="UTC")
    df = pd.DataFrame([
        {**_pts_leg("A", ts, 5.0, 45000.0, -0.0025, platform="ISWV"),
         "forward_label": "spot"},
        {**_pts_leg("B", ts, 10.0, 44800.0, -0.0025, platform="ISWV"),
         "forward_label": "spot"},
    ])
    grouped, remainder = group_by_ptp(df, time_tolerance_seconds=5)
    assert len(grouped) == 2 and len(remainder) == 0
    classified = classify_ptp_groups(grouped)
    assert (classified["package_type"] == "CURVE").all()
    upgraded = detect_sub_package_curve_fly(classified)
    assert (upgraded["package_type"] == "SPREADOVER_CURVE").all()


def test_bug2_pkg3_end_to_end():
    ts = pd.Timestamp("2026-07-06 14:06:19", tz="UTC")
    df = pd.DataFrame([
        _pts_leg("T10", ts, 10.0, 250000.0, -0.00020625),
        _pts_leg("T12", ts, 12.0, 237000.0, -0.00020625),
        _pts_leg("T15", ts, 15.0, 234000.0, -0.00020625),
    ])
    grouped, remainder = group_by_ptp(df, time_tolerance_seconds=5)
    assert len(remainder) == 0, "curve detector must never see these legs"
    classified = classify_ptp_groups(grouped)
    assert (classified["package_type"] == "PKG-3").all()
    assert classified["package_id"].nunique() == 1


# ── Hood expansion mirrors the widened grouping key ──────────────────


def test_hood_expansion_pulls_in_pts_keyed_mates():
    from SDRUtils.products.usd.usd_swaps import _expand_hood_for_ptp_keys

    t0 = pd.Timestamp("2026-07-06 14:06:19", tz="UTC")
    df = pd.DataFrame([
        {"trade_id": "P1", "execution_timestamp": t0,
         "package_transaction_price": None,
         "package_transaction_spread": "-0.00020625",
         "package_indicator": True,
         "unique_product_identifier": "UPI_A", "platform_identifier": "TSEF"},
        {"trade_id": "P2", "execution_timestamp": t0 + pd.Timedelta(seconds=2),
         "package_transaction_price": None,
         "package_transaction_spread": "-0.00020625",
         "package_indicator": True,
         "unique_product_identifier": "UPI_B", "platform_identifier": "TSEF"},
        {"trade_id": "O1", "execution_timestamp": t0 + pd.Timedelta(seconds=2),
         "package_transaction_price": None,
         "package_transaction_spread": None,
         "package_indicator": False,
         "unique_product_identifier": "UPI_A", "platform_identifier": "TSEF"},
    ])
    hood = pd.Series([True, False, False], index=df.index)
    out = _expand_hood_for_ptp_keys(df, hood, tolerance_seconds=5)
    assert bool(out.iloc[0]) and bool(out.iloc[1])
    assert not bool(out.iloc[2])


def test_hood_expansion_negative_ptp_not_dropped():
    """The old hood filter used ptp > 0; the grouper uses ptp != 0.
    Negative package prices must expand the hood too."""
    from SDRUtils.products.usd.usd_swaps import _expand_hood_for_ptp_keys

    t0 = pd.Timestamp("2026-07-06 14:06:19", tz="UTC")
    df = pd.DataFrame([
        {"trade_id": "P1", "execution_timestamp": t0,
         "package_transaction_price": "-88,100",
         "package_transaction_spread": None,
         "package_indicator": True,
         "unique_product_identifier": "UPI_A", "platform_identifier": "TSEF"},
        {"trade_id": "P2", "execution_timestamp": t0 + pd.Timedelta(seconds=2),
         "package_transaction_price": "-88,100",
         "package_transaction_spread": None,
         "package_indicator": True,
         "unique_product_identifier": "UPI_A", "platform_identifier": "TSEF"},
    ])
    hood = pd.Series([True, False], index=df.index)
    out = _expand_hood_for_ptp_keys(df, hood, tolerance_seconds=5)
    assert bool(out.iloc[1])
