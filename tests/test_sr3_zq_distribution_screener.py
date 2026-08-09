"""Tests for SR3 vs ZQ Distribution Screener."""

from __future__ import annotations

import datetime
from typing import Dict

import pandas as pd
import pytest


# --- _types ----------------------------------------------------------------


def test_regime_bucket_enum_has_four_members():
    from RVUtils.SR3ZQDistributionScreener import RegimeBucket

    assert {m.value for m in RegimeBucket} == {"calm", "stress", "pivot", "hike"}


def test_trade_flag_kinds_are_the_four_spec_families_plus_the_two_copula_ones():
    """The spec's four, plus the copula pair. lambda_dependence is a VIEW on the coupling;
    lambda_arbitrage is the separate hard tier where the RND variance lies outside what any
    coupling of the ZQ marginals can produce. They are deliberately distinct kinds: one is
    tradeable only against a prior, the other is a static arbitrage."""
    from RVUtils.SR3ZQDistributionScreener import TradeFlagKind

    assert {m.value for m in TradeFlagKind} == {
        "vol_cone", "skew", "tail", "cross_quarter",
        "lambda_dependence", "lambda_arbitrage",
    }


def test_distribution_screener_config_defaults():
    from RVUtils.SR3ZQDistributionScreener import DistributionScreenerConfig

    cfg = DistributionScreenerConfig()
    assert cfg.dte_floor == 60
    assert cfg.dte_ceiling == 200
    assert cfg.ref_period_days == 91
    assert cfg.basis_bp == 0.0
    assert cfg.optimize_lambda is True
    assert cfg.lambda_grid == (1e-5, 5e-5, 1e-4, 5e-4, 1e-3)


# --- _fedwatch -------------------------------------------------------------


def _stub_fomc_schedule():
    return pd.DataFrame(
        [
            {"meeting_label": "jun26", "effective_date": datetime.date(2026, 6, 17)},
            {"meeting_label": "jul26", "effective_date": datetime.date(2026, 7, 29)},
            {"meeting_label": "sep26", "effective_date": datetime.date(2026, 9, 16)},
            {"meeting_label": "oct26", "effective_date": datetime.date(2026, 10, 28)},
            {"meeting_label": "dec26", "effective_date": datetime.date(2026, 12, 9)},
        ]
    )


def test_fedwatch_tree_anchored_on_aug26():
    """Aug 2026 has no FOMC → anchor month → start = end = avg there."""
    from RVUtils.SR3ZQDistributionScreener import build_fedwatch_tree

    zq_prices: Dict[str, float] = {
        "ZQM26": 96.365, "ZQN26": 96.375, "ZQQ26": 96.385,
        "ZQU26": 96.380, "ZQV26": 96.370, "ZQX26": 96.335, "ZQZ26": 96.300,
    }
    states = build_fedwatch_tree(
        zq_prices=zq_prices,
        fomc_schedule=_stub_fomc_schedule(),
        months_range=((2026, 5), (2026, 12)),
    )
    aug = states["aug26"]
    assert not aug.has_meeting
    assert aug.effr_start == aug.effr_end
    assert abs(aug.effr_start - aug.avg_effr) < 1e-9


def test_fedwatch_tree_solved_meeting_month_consistent():
    """Sep 2026 meeting (mid-month) → start solved from Aug avg, end from Oct avg."""
    from RVUtils.SR3ZQDistributionScreener import build_fedwatch_tree

    zq_prices: Dict[str, float] = {
        "ZQM26": 96.365, "ZQN26": 96.375, "ZQQ26": 96.385,
        "ZQU26": 96.380, "ZQV26": 96.370, "ZQX26": 96.335, "ZQZ26": 96.300,
    }
    states = build_fedwatch_tree(
        zq_prices=zq_prices,
        fomc_schedule=_stub_fomc_schedule(),
        months_range=((2026, 5), (2026, 12)),
    )
    sep = states["sep26"]
    assert sep.has_meeting
    # Sep avg should be days-weighted between Sep start and Sep end
    n = sep.days_before_meeting
    mm = sep.days_after_meeting
    expected_avg = (n / (n + mm)) * sep.effr_start + (mm / (n + mm)) * sep.effr_end
    assert abs(expected_avg - sep.avg_effr) < 1e-6


# --- _variance -------------------------------------------------------------


def test_meeting_nodes_compute_binomial_variance():
    from RVUtils.SR3ZQDistributionScreener import (
        MonthState,
        meeting_nodes_from_states,
    )

    # Synthetic sep26 meeting with +10bp expected change
    states = {
        "sep26": MonthState(
            label="sep26",
            contract="ZQU26",
            avg_effr=0.040,
            has_meeting=True,
            meeting_date=datetime.date(2026, 9, 16),
            days_in_month=30,
            days_before_meeting=15,
            days_after_meeting=15,
            effr_start=0.0395,
            effr_end=0.0405,  # +10bp
        ),
    }
    nodes = meeting_nodes_from_states(states, [datetime.date(2026, 9, 16)])
    assert len(nodes) == 1
    n = nodes[0]
    assert abs(n.expected_change_bp - 10.0) < 0.01
    assert n.char_25bp == 0  # 10bp = 0.4 × 25bp → char=0
    assert abs(n.mantissa - 0.4) < 0.01
    # Probabilities: 60% no change, 40% +25bp
    assert abs(n.p_lower - 0.6) < 0.01
    assert abs(n.p_upper - 0.4) < 0.01
    # Variance = 0.6 × (0 - mean)² + 0.4 × (25 - mean)² where mean = 10
    # = 0.6 × 100 + 0.4 × 225 = 60 + 90 = 150 bp²
    assert abs(n.variance_bp2 - 150.0) < 0.5


def test_day_weighted_variance_excludes_pre_period_meetings():
    from RVUtils.SR3ZQDistributionScreener import (
        MeetingNode,
        day_weighted_meeting_variance_bp2,
    )

    nodes = [
        MeetingNode(
            label="jun26", date=datetime.date(2026, 6, 17),
            prior_effr=0.04, next_effr=0.04,
            expected_change_bp=0.0, char_25bp=0, mantissa=0.0,
            p_lower=1.0, p_upper=0.0, variance_bp2=100.0,
        ),
        MeetingNode(
            label="sep26", date=datetime.date(2026, 9, 16),
            prior_effr=0.04, next_effr=0.04,
            expected_change_bp=0.0, char_25bp=0, mantissa=0.0,
            p_lower=1.0, p_upper=0.0, variance_bp2=200.0,
        ),
    ]
    # Period starts AFTER jun26 meeting, includes sep26
    total, breakdown = day_weighted_meeting_variance_bp2(
        nodes,
        ref_start=datetime.date(2026, 8, 1),
        ref_end=datetime.date(2026, 11, 1),
    )
    # jun26 excluded; sep26 is 46/92 days into period → weight ≈ 0.5 → contrib ≈ 0.25 × 200 = 50
    assert len(breakdown) == 1
    assert breakdown[0][0] == "sep26"
    assert 35.0 <= total <= 65.0


# --- _regime ---------------------------------------------------------------


def test_regime_classifier_stress():
    from RVUtils.SR3ZQDistributionScreener import (
        DistributionScreenerConfig,
        RegimeBucket,
        classify_regime,
    )

    # Stress: residual_ratio top decile
    bucket = classify_regime(
        residual_ratio=100.0, skew=-0.5, tail_upper_50bp=0.30,
        config=DistributionScreenerConfig(),
    )
    assert bucket == RegimeBucket.STRESS


def test_regime_classifier_pivot():
    from RVUtils.SR3ZQDistributionScreener import (
        DistributionScreenerConfig, RegimeBucket, classify_regime,
    )

    bucket = classify_regime(
        residual_ratio=15.0, skew=-1.5, tail_upper_50bp=0.05,
        config=DistributionScreenerConfig(),
    )
    assert bucket == RegimeBucket.PIVOT


def test_regime_classifier_calm():
    from RVUtils.SR3ZQDistributionScreener import (
        DistributionScreenerConfig, RegimeBucket, classify_regime,
    )

    bucket = classify_regime(
        residual_ratio=28.0, skew=+0.35, tail_upper_50bp=0.07,
        config=DistributionScreenerConfig(),
    )
    assert bucket == RegimeBucket.CALM


def test_regime_classifier_hike():
    from RVUtils.SR3ZQDistributionScreener import (
        DistributionScreenerConfig, RegimeBucket, classify_regime,
    )

    # Hike: moderate negative skew, residual ratio in [10, 60]
    bucket = classify_regime(
        residual_ratio=11.0, skew=-0.45, tail_upper_50bp=0.12,
        config=DistributionScreenerConfig(),
    )
    assert bucket == RegimeBucket.HIKE


def test_regime_classifier_high_vol_hike_routes_to_stress():
    """High-vol hike-cycle dates (Jul22 ratio=130) collapse into stress.
    That's correct: they're trade-flag-equivalent to acute stress."""
    from RVUtils.SR3ZQDistributionScreener import (
        DistributionScreenerConfig, RegimeBucket, classify_regime,
    )

    bucket = classify_regime(
        residual_ratio=130.0, skew=-0.03, tail_upper_50bp=0.245,
        config=DistributionScreenerConfig(),
    )
    assert bucket == RegimeBucket.STRESS


# --- _signals --------------------------------------------------------------


def test_vol_cone_signal_fires_in_stress_with_high_residual():
    from RVUtils.SR3ZQDistributionScreener import (
        DistributionScreenerConfig, RegimeBucket, TradeFlagKind,
        compute_signals,
    )

    flags = compute_signals(
        residual_ratio=150.0, skew=-0.3,
        tail_upper_50bp=0.25, tail_lower_50bp=0.20,
        tail_upper_100bp=0.10, tail_lower_100bp=0.08,
        regime=RegimeBucket.STRESS,
        config=DistributionScreenerConfig(),
    )
    kinds = {f.kind for f in flags}
    assert TradeFlagKind.VOL_CONE in kinds
    vol_cone_flag = next(f for f in flags if f.kind == TradeFlagKind.VOL_CONE)
    assert vol_cone_flag.direction == "sell_vol"


def test_vol_cone_signal_buy_vol_in_calm_with_low_residual():
    from RVUtils.SR3ZQDistributionScreener import (
        DistributionScreenerConfig, RegimeBucket, TradeFlagKind,
        compute_signals,
    )

    flags = compute_signals(
        residual_ratio=15.0,
        skew=+0.30,
        tail_upper_50bp=0.05, tail_lower_50bp=0.04,
        tail_upper_100bp=0.01, tail_lower_100bp=0.01,
        regime=RegimeBucket.CALM,
        config=DistributionScreenerConfig(),
    )
    vol_cone = next((f for f in flags if f.kind == TradeFlagKind.VOL_CONE), None)
    assert vol_cone is not None
    assert vol_cone.direction == "buy_vol"


def test_skew_signal_fires_when_heavily_negative():
    from RVUtils.SR3ZQDistributionScreener import (
        DistributionScreenerConfig, RegimeBucket, TradeFlagKind,
        compute_signals,
    )

    flags = compute_signals(
        residual_ratio=15.0, skew=-1.8,
        tail_upper_50bp=0.10, tail_lower_50bp=0.10,
        tail_upper_100bp=0.02, tail_lower_100bp=0.02,
        regime=RegimeBucket.PIVOT,
        config=DistributionScreenerConfig(),
    )
    skew_flag = next((f for f in flags if f.kind == TradeFlagKind.SKEW), None)
    assert skew_flag is not None
    assert "dovish" in skew_flag.rationale or "directional" in skew_flag.rationale


def test_tail_signal_fires_above_threshold():
    from RVUtils.SR3ZQDistributionScreener import (
        DistributionScreenerConfig, RegimeBucket, TradeFlagKind,
        compute_signals,
    )

    flags = compute_signals(
        residual_ratio=80.0, skew=-0.3,
        tail_upper_50bp=0.30, tail_lower_50bp=0.25,
        tail_upper_100bp=0.12, tail_lower_100bp=0.08,
        regime=RegimeBucket.STRESS,
        config=DistributionScreenerConfig(),
    )
    tail_flag = next((f for f in flags if f.kind == TradeFlagKind.TAIL), None)
    assert tail_flag is not None
    assert tail_flag.severity_value >= 0.30


def test_cross_quarter_signal_fires_on_inversion():
    from RVUtils.SR3ZQDistributionScreener._signals import signal_cross_quarter
    from RVUtils.SR3ZQDistributionScreener import (
        DistributionScreenerConfig, RegimeBucket, TradeFlagKind,
    )

    # Front (50) much higher than back (20) → 2.5× inversion
    flag = signal_cross_quarter(
        residual_ratios_by_contract=[50.0, 30.0, 20.0],
        regime=RegimeBucket.CALM,
        config=DistributionScreenerConfig(),
    )
    assert flag is not None
    assert flag.kind == TradeFlagKind.CROSS_QUARTER
    assert flag.direction == "sell_front_vol_buy_back_vol"


def test_cross_quarter_signal_skips_when_too_few_contracts():
    from RVUtils.SR3ZQDistributionScreener._signals import signal_cross_quarter
    from RVUtils.SR3ZQDistributionScreener import (
        DistributionScreenerConfig, RegimeBucket,
    )

    flag = signal_cross_quarter(
        residual_ratios_by_contract=[50.0, 20.0],
        regime=RegimeBucket.CALM,
        config=DistributionScreenerConfig(),
    )
    assert flag is None


# --- snapshot output -------------------------------------------------------


def test_snapshot_to_dataframe_empty_when_no_records():
    from RVUtils.SR3ZQDistributionScreener._output import ScreenerSnapshot

    snap = ScreenerSnapshot(
        as_of=datetime.date(2026, 5, 4),
        records=tuple(),
        config_summary={},
    )
    assert snap.to_dataframe().empty


def test_snapshot_to_dataframe_has_one_row_per_record():
    from RVUtils.SR3ZQDistributionScreener._output import ScreenerSnapshot
    from RVUtils.SR3ZQDistributionScreener import (
        RegimeBucket, SignalRecord,
    )

    rec = SignalRecord(
        as_of=datetime.date(2026, 5, 4),
        sr3_contract="SFRU26",
        sr3_dte=135,
        ref_start=datetime.date(2026, 9, 16),
        ref_end=datetime.date(2026, 12, 16),
        forward_price=96.30,
        forward_rate=3.70,
        n_meetings_in_period=3,
        fedwatch_meeting_labels=("sep26", "oct26", "dec26"),
        fedwatch_expected_changes_bp=(1.0, 4.0, 4.7),
        sr3_total_var_bp2=1620.0,
        zq_day_weighted_var_bp2=49.0,
        intermeeting_drift_var_bp2=8.2,
        basis_var_bp2=0.0,
        explained_var_bp2=57.2,
        residual_var_bp2=1563.0,
        residual_to_explained_ratio=27.3,
        sr3_skew=0.22,
        sr3_kurt=10.2,
        tail_lower_50=0.060,
        tail_lower_75=0.029,
        tail_lower_100=0.015,
        tail_upper_50=0.087,
        tail_upper_75=0.046,
        tail_upper_100=0.020,
        stability_flag="stable",
        smoothing_sensitivity_pp=9.6,
        negative_density_pct=0.17,
        chosen_lambda=1e-4,
        n_strikes_used=47,
        prices_source="market_listed_jpm",
        regime_bucket=RegimeBucket.CALM,
        flags=tuple(),
    )
    snap = ScreenerSnapshot(
        as_of=datetime.date(2026, 5, 4),
        records=(rec,),
        config_summary={},
    )
    df = snap.to_dataframe()
    assert len(df) == 1
    assert df["sr3_contract"].iloc[0] == "SFRU26"
    assert df["regime_bucket"].iloc[0] == "calm"
