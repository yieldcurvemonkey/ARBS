"""Tests for STIRAsymmetricScreener._types."""

from __future__ import annotations

import datetime

import pytest


def test_archetype_type_has_eight_members():
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    assert {m.value for m in ArchetypeType} == {
        "wing",
        "wide_vertical",
        "risk_reversal",
        "ratio",
        "ladder",
        "conditional_curve",
        "tree",
        "condor",
    }


def test_option_leg_instantiation_and_dict_round_trip():
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    leg = OptionLeg(
        contract="SFRU6",
        expiry=datetime.date(2026, 9, 11),
        right="P",
        strike=96.50,
        quantity=1,
        premium_ticks=3.0,
        open_interest=1500.0,
        volume=120.0,
        bid=2.75,
        ask=3.25,
    )
    d = leg.to_dict()
    assert d["contract"] == "SFRU6"
    assert d["right"] == "P"
    assert d["strike"] == 96.50
    assert d["quantity"] == 1
    assert d["premium_ticks"] == 3.0
    assert d["expiry"] == "2026-09-11"


def test_option_leg_is_long_short_semantics():
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    long_leg = OptionLeg(
        contract="SFRU6",
        expiry=datetime.date(2026, 9, 11),
        right="C",
        strike=97.00,
        quantity=2,
    )
    short_leg = OptionLeg(
        contract="SFRU6",
        expiry=datetime.date(2026, 9, 11),
        right="C",
        strike=97.00,
        quantity=-1,
    )
    assert long_leg.is_long is True
    assert short_leg.is_long is False
    assert long_leg.abs_quantity == 2
    assert short_leg.abs_quantity == 1


def test_option_leg_is_frozen():
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    leg = OptionLeg(
        contract="ERV5",
        expiry=datetime.date(2025, 10, 31),
        right="P",
        strike=98.0625,
        quantity=1,
    )
    with pytest.raises(Exception):
        leg.strike = 99.0  # type: ignore[misc]


def test_candidate_def_id_uniqueness_and_legs_are_tuple():
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        CandidateDef,
        OptionLeg,
    )

    leg1 = OptionLeg(
        contract="SFRU6",
        expiry=datetime.date(2026, 9, 11),
        right="P",
        strike=96.50,
        quantity=1,
    )
    leg2 = OptionLeg(
        contract="SFRU6",
        expiry=datetime.date(2026, 9, 11),
        right="P",
        strike=96.25,
        quantity=-1,
    )
    cdef_a = CandidateDef.from_components(
        archetype=ArchetypeType.WIDE_VERTICAL,
        underlying="SFRU6",
        expiry=datetime.date(2026, 9, 11),
        legs=(leg1, leg2),
    )
    cdef_b = CandidateDef.from_components(
        archetype=ArchetypeType.WIDE_VERTICAL,
        underlying="SFRU6",
        expiry=datetime.date(2026, 9, 11),
        legs=(leg1,),
    )
    assert cdef_a.candidate_id != cdef_b.candidate_id
    assert isinstance(cdef_a.legs, tuple)
    # candidate_id is deterministic
    cdef_c = CandidateDef.from_components(
        archetype=ArchetypeType.WIDE_VERTICAL,
        underlying="SFRU6",
        expiry=datetime.date(2026, 9, 11),
        legs=(leg1, leg2),
    )
    assert cdef_a.candidate_id == cdef_c.candidate_id


def test_screener_config_defaults_match_spec():
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        ScreenerConfig,
    )

    cfg = ScreenerConfig()
    # Universe (spec §0)
    assert cfg.underlyings == ("SR3", "SR1", "ER")
    assert cfg.dte_floor == 7
    assert cfg.dte_ceiling == 730
    assert cfg.include_midcurves is True
    assert cfg.include_serials is True
    assert cfg.include_weeklies is False

    # Archetype set covers all 8
    assert set(cfg.archetypes) == set(ArchetypeType)

    # Per-archetype payoff multiples — every archetype key present (spec §3)
    expected_keys = {a.value for a in ArchetypeType}
    assert set(cfg.min_payoff_multiple_per_archetype) == expected_keys
    assert cfg.min_payoff_multiple_per_archetype["wing"] == 10.0
    assert cfg.min_payoff_multiple_per_archetype["wide_vertical"] == 4.0

    # Signal thresholds (spec §2 / §10)
    assert cfg.path_bias_threshold_bp == 50.0
    assert cfg.rr_zscore_threshold == 1.5
    assert cfg.vol_spread_percentile_extremes == (0.15, 0.85)
    assert cfg.wing_percentile_threshold == 0.30
    assert cfg.prob_edge_threshold == 0.10

    # Liquidity floors (spec §0)
    assert cfg.liquidity_min_oi_sofr == 500
    assert cfg.liquidity_min_oi_euribor == 250
    assert cfg.bid_ask_max_pct_of_mid == 0.25

    # Path scenarios (spec §5)
    assert cfg.path_scenarios_to_evaluate == (-4, -3, -2, -1, 0, 1, 2)

    # Composite weights sum to 1 (spec §4)
    assert sum(cfg.composite_weights.values()) == pytest.approx(1.0)

    # RND (spec §12)
    assert cfg.rnd_smoothing_param == 1e-4
    assert cfg.rnd_spline_order == 4


def test_screener_config_is_mutable():
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

    cfg = ScreenerConfig()
    cfg.dte_floor = 30  # Config is mutable per plan §1.4
    assert cfg.dte_floor == 30


def test_candidate_def_wing_id_format():
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        CandidateDef,
        OptionLeg,
    )

    leg = OptionLeg(
        contract="SFRU6",
        expiry=datetime.date(2026, 9, 11),
        right="P",
        strike=96.50,
        quantity=1,
    )
    cdef = CandidateDef.from_components(
        archetype=ArchetypeType.WING,
        underlying="SFRU6",
        expiry=datetime.date(2026, 9, 11),
        legs=(leg,),
    )
    # underlying, expiry ISO, archetype, leg description should all be encoded
    assert "SFRU6" in cdef.candidate_id
    assert "2026-09-11" in cdef.candidate_id
    assert "WING" in cdef.candidate_id
