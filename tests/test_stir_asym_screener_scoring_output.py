"""Tests for the scoring + output modules."""

from __future__ import annotations

import datetime
import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest


def test_composite_score_in_zero_one():
    from RVUtils.STIRAsymmetricScreener._scoring import (
        composite_asymmetry_score,
    )

    sb = composite_asymmetry_score(
        payoff_multiple=0.8,
        probability_edge=0.5,
        carry_quality=0.3,
        liquidity=0.7,
        weights={"payoff_multiple": 0.30, "probability_edge": 0.30, "carry_quality": 0.20, "liquidity": 0.20},
    )
    assert 0.0 <= sb.composite <= 1.0
    # Composite = .30*.8 + .30*.5 + .20*.3 + .20*.7 = .24+.15+.06+.14 = .59
    assert abs(sb.composite - 0.59) < 1e-9


def test_normalize_payoff_multiple_saturates_at_one():
    from RVUtils.STIRAsymmetricScreener._scoring import (
        normalize_payoff_multiple,
    )

    assert normalize_payoff_multiple(20.0) == 1.0  # saturated
    assert normalize_payoff_multiple(0.0) == 0.0
    assert 0 < normalize_payoff_multiple(5.0) < 1


def test_normalize_probability_edge_zero_when_negative():
    from RVUtils.STIRAsymmetricScreener._scoring import (
        normalize_probability_edge,
    )

    assert normalize_probability_edge(-0.05) == 0.0
    assert normalize_probability_edge(0.30) == 1.0


def test_write_snapshot_round_trip_parquet(tmp_path):
    from RVUtils.STIRAsymmetricScreener._output import write_snapshot
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        CandidateDef,
        CandidateResult,
        OptionLeg,
        ScreenerSnapshot,
    )

    leg = OptionLeg(
        contract="SFRU26",
        expiry=datetime.date(2026, 9, 11),
        right="P",
        strike=96.50,
        quantity=1,
        premium_ticks=3.0,
    )
    cdef = CandidateDef.from_components(
        archetype=ArchetypeType.WING,
        underlying="SFRU26",
        expiry=datetime.date(2026, 9, 11),
        legs=(leg,),
    )
    res = CandidateResult(
        candidate_def=cdef,
        ref_underlying_price=96.30,
        net_premium=3.0,
        max_payoff=24.5,
        max_loss=3.0,
        breakevens=(96.47,),
        payoff_zone=(95.50, 96.4925),
        delta=0.18,
        gamma=0.012,
        vega=0.45,
        theta=-0.08,
        vega_aged_1m=0.32,
        theta_to_expiry=-0.50,
        carry_3m=-0.20,
        carry_to_expiry=-0.40,
        asymmetry_ratio=8.17,
        implied_prob_full_payoff_rnd=0.10,
        implied_prob_full_payoff_sabr=0.07,
        prob_density_divergence=0.04,
        conditional_prob_full_payoff=0.18,
        prob_edge=0.08,
        prob_source="rnd",
        path_scenario="0_cuts_through_Sep26",
        path_delta_required_bp=-50.0,
        triggers=("path_bias",),
        catalyst_count=2,
        liquidity_score=0.85,
        sdr_confirmation=False,
        composite_score=0.62,
    )
    snap = ScreenerSnapshot(
        as_of=datetime.date(2026, 4, 28),
        results=(res,),
        config_summary={"foo": 1},
        run_warnings=("test",),
    )

    path = write_snapshot(snap, root=str(tmp_path), fmt="parquet")
    assert path.exists()
    df = pd.read_parquet(path)
    assert len(df) == 1
    assert df["structure_type"].iloc[0] == "wing"
    # Sidecar exists
    sidecar = path.parent / "snapshot.meta.json"
    assert sidecar.exists()
    meta = json.loads(sidecar.read_text())
    assert meta["n_results"] == 1
