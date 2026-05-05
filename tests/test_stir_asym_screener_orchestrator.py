"""Tests for the orchestrator (Phase 14)."""

from __future__ import annotations

import datetime
from typing import Tuple
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


def _stub_smile(*, contract: str = "SFRU26", forward_price: float = 96.30, time_to_expiry: float = 0.40):
    from MDP.STIRFutures.STIRFutureOptionMDP import (
        STIRFutureOptionSABRParams,
        STIRFutureOptionSABRSmile,
    )

    params = STIRFutureOptionSABRParams(
        alpha=0.005, beta=0.0, rho=-0.05, nu=0.6,
        forward_price=forward_price,
        forward_rate=100.0 - forward_price,
        time_to_expiry=time_to_expiry,
        expiry_date=datetime.date(2026, 9, 11),
        as_of=datetime.date(2026, 4, 28),
    )
    return STIRFutureOptionSABRSmile(
        source="STUB",
        symbol=contract,
        underlying_contract=contract,
        quote_timestamp=datetime.datetime(2026, 4, 28, 16, 0),
        params=params,
        points=tuple(),
    )


def test_orchestrator_returns_empty_snapshot_when_universe_empty():
    from RVUtils.STIRAsymmetricScreener._market_data import STIRMarketData
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig
    from RVUtils.STIRAsymmetricScreener.screener import build_snapshot

    md = STIRMarketData(
        as_of=datetime.date(2026, 4, 28),
        universe=tuple(),
        smiles={},
        curve_handle=None,
        curve_asof=None,
        fomc_schedule=pd.DataFrame(),
        leg_market={},
    )
    snap = build_snapshot(
        ScreenerConfig(), as_of=datetime.date(2026, 4, 28), md=md
    )
    assert snap.results == ()


def test_orchestrator_emits_records_for_full_pipeline_with_stubs():
    from RVUtils.STIRAsymmetricScreener._market_data import STIRMarketData
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        ScreenerConfig,
    )
    from RVUtils.STIRAsymmetricScreener._universe import UniverseEntry
    from RVUtils.STIRAsymmetricScreener.screener import build_snapshot

    smile = _stub_smile()
    entry = UniverseEntry(
        underlying="SFRU26",
        contract="SFRU26",
        option_root="SFR",
        expiry=datetime.date(2026, 9, 11),
        forward_price=96.30,
        atm_strike=96.30,
        strikes=tuple(96.30 + (i - 8) * 0.0625 for i in range(17)),
        fine_step=0.0625,
        coarse_step=0.25,
        dte_calendar=120,
    )
    md = STIRMarketData(
        as_of=datetime.date(2026, 4, 28),
        universe=(entry,),
        smiles={(entry.contract, entry.expiry): smile},
        curve_handle=MagicMock(spot_target=0.0445),
        curve_asof=datetime.date(2026, 4, 28),
        fomc_schedule=pd.DataFrame(),
        leg_market={},
    )
    cfg = ScreenerConfig(
        underlyings=("SR3",),
        include_midcurves=False,
        include_serials=False,
        archetypes=(
            ArchetypeType.WING,
            ArchetypeType.WIDE_VERTICAL,
        ),
        dte_floor=30,
        dte_ceiling=200,
    )
    snap = build_snapshot(cfg, as_of=datetime.date(2026, 4, 28), md=md)
    # With wing + wide_vertical archetypes and a 17-strike grid, expect many candidates
    assert len(snap.results) > 0
    # Every result has a rank
    ranks = sorted(r.rank for r in snap.results)
    assert ranks == list(range(1, len(snap.results) + 1))
    # Composite scores monotonically non-increasing
    scores = [r.composite_score for r in snap.results]
    assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))


def test_orchestrator_records_run_warnings_from_market_data():
    from RVUtils.STIRAsymmetricScreener._market_data import STIRMarketData
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig
    from RVUtils.STIRAsymmetricScreener.screener import build_snapshot

    md = STIRMarketData(
        as_of=datetime.date(2026, 4, 28),
        universe=tuple(),
        smiles={},
        curve_handle=None,
        curve_asof=None,
        fomc_schedule=pd.DataFrame(),
        leg_market={},
        warnings=("upstream_warn_1",),
    )
    snap = build_snapshot(
        ScreenerConfig(), as_of=datetime.date(2026, 4, 28), md=md
    )
    assert "upstream_warn_1" in snap.run_warnings


def test_orchestrator_to_dataframe_has_spec_columns_when_results_present():
    from RVUtils.STIRAsymmetricScreener._market_data import STIRMarketData
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        ScreenerConfig,
    )
    from RVUtils.STIRAsymmetricScreener._universe import UniverseEntry
    from RVUtils.STIRAsymmetricScreener.screener import build_snapshot

    smile = _stub_smile()
    entry = UniverseEntry(
        underlying="SFRU26",
        contract="SFRU26",
        option_root="SFR",
        expiry=datetime.date(2026, 9, 11),
        forward_price=96.30,
        atm_strike=96.30,
        strikes=tuple(96.30 + (i - 5) * 0.0625 for i in range(11)),
        fine_step=0.0625,
        coarse_step=0.25,
        dte_calendar=120,
    )
    md = STIRMarketData(
        as_of=datetime.date(2026, 4, 28),
        universe=(entry,),
        smiles={(entry.contract, entry.expiry): smile},
        curve_handle=MagicMock(spot_target=0.0445),
        curve_asof=datetime.date(2026, 4, 28),
        fomc_schedule=pd.DataFrame(),
        leg_market={},
    )
    cfg = ScreenerConfig(
        underlyings=("SR3",),
        include_midcurves=False,
        include_serials=False,
        archetypes=(ArchetypeType.WING,),
        dte_floor=30,
        dte_ceiling=200,
    )
    snap = build_snapshot(cfg, as_of=datetime.date(2026, 4, 28), md=md)
    df = snap.to_dataframe()
    expected = {
        "structure_type", "underlying", "expiry_date", "dte", "ref_underlying_price",
        "net_premium", "max_payoff", "max_loss", "asymmetry_ratio",
        "composite_score", "candidate_id",
    }
    if not df.empty:
        missing = expected - set(df.columns)
        assert not missing, f"Missing columns: {missing}"
