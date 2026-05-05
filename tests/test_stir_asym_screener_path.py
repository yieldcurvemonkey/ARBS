"""Tests for STIRAsymmetricScreener._path."""

from __future__ import annotations

import datetime
from typing import Tuple
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


def _stub_fomc_schedule():
    return pd.DataFrame(
        [
            {
                "meeting_label": "Jun26",
                "effective_date": pd.Timestamp("2026-06-17"),
                "maturity_date": pd.Timestamp("2026-07-29"),
                "period_days": 42,
            },
            {
                "meeting_label": "Jul26",
                "effective_date": pd.Timestamp("2026-07-29"),
                "maturity_date": pd.Timestamp("2026-09-16"),
                "period_days": 49,
            },
            {
                "meeting_label": "Sep26",
                "effective_date": pd.Timestamp("2026-09-16"),
                "maturity_date": pd.Timestamp("2026-10-28"),
                "period_days": 42,
            },
        ]
    )


def _flat_curve_handle(rate: float = 0.04):
    """Mock pricer with all forward rates equal."""
    handle = MagicMock(name="curve_handle")
    handle.fair_rate = MagicMock(return_value=rate)
    return handle


def test_extract_fomc_path_returns_one_entry_per_meeting():
    from RVUtils.STIRAsymmetricScreener._path import extract_fomc_path, FOMCPath

    handle = _flat_curve_handle(rate=0.04)
    sched = _stub_fomc_schedule()

    path = extract_fomc_path(
        as_of=datetime.date(2026, 4, 28),
        curve_handle=handle,
        fomc_schedule=sched,
        spot_target=0.04,
        forward_rate_fn=lambda *, eff_date, mat_date, handle: 0.04,
    )
    assert isinstance(path, FOMCPath)
    assert len(path.meetings) == 3
    # Flat curve → cumulative change ~ 0
    for c in path.cumulative_change_bp:
        assert abs(c) < 1.0


def test_extract_fomc_path_cuts_show_negative_cumulative_change():
    from RVUtils.STIRAsymmetricScreener._path import extract_fomc_path

    sched = _stub_fomc_schedule()

    # Step-down curve: each meeting takes 25bp off
    rates = {0: 0.0375, 1: 0.0350, 2: 0.0325}

    def fr(*, eff_date, mat_date, handle):
        idx = list(sched["effective_date"]).index(pd.Timestamp(eff_date))
        return rates[idx]

    path = extract_fomc_path(
        as_of=datetime.date(2026, 4, 28),
        curve_handle=MagicMock(),
        fomc_schedule=sched,
        spot_target=0.04,
        forward_rate_fn=fr,
    )
    # Cumulative change relative to spot: -25bp, -50bp, -75bp (all negative)
    assert path.cumulative_change_bp[0] == pytest.approx(-25.0, abs=1.0)
    assert path.cumulative_change_bp[1] == pytest.approx(-50.0, abs=1.0)
    assert path.cumulative_change_bp[2] == pytest.approx(-75.0, abs=1.0)


def test_enumerate_path_scenarios_covers_full_grid():
    from RVUtils.STIRAsymmetricScreener._path import (
        FOMCPath,
        enumerate_path_scenarios,
    )

    path = FOMCPath(
        as_of=datetime.date(2026, 4, 28),
        meetings=(datetime.date(2026, 6, 17), datetime.date(2026, 9, 16)),
        meeting_labels=("Jun26", "Sep26"),
        spot_target=0.04,
        implied_meeting_rates=(0.0375, 0.0325),
        cumulative_change_bp=(-25.0, -75.0),
        marginal_change_bp=(-25.0, -50.0),
    )
    scenarios = enumerate_path_scenarios(
        fomc_path=path, n_cuts_grid=(-2, -1, 0, 1)
    )
    # 4 scenarios per horizon × 2 horizons
    assert len(scenarios) == 8
    # Each scenario has horizon, cumulative_change_bp, delta_from_implied_bp
    for s in scenarios:
        assert hasattr(s, "horizon")
        assert hasattr(s, "delta_from_implied_bp")


def test_path_scenario_probability_under_rnd_integrates_density():
    from RVUtils.STIRAsymmetricScreener._path import (
        PathScenario,
        path_scenario_probability_rnd,
    )

    # Stub RNDRecord — uniform-ish density over 3.0-5.0 rate range
    grid = np.linspace(3.0, 5.0, 200)
    density = np.ones_like(grid) / 2.0  # density over 2-rate-pt window
    cdf = np.cumsum(density) * (grid[1] - grid[0])

    @pytest.fixture(autouse=False)
    def _():
        ...

    from RVUtils.STIRAsymmetricScreener._rnd import RNDRecord

    rec = RNDRecord(
        contract="SFRU26",
        expiry=datetime.date(2026, 9, 11),
        dte=120,
        strike_grid_rate=grid,
        n_strikes_observed=20,
        density_pdf=density,
        density_cdf=cdf,
        fed_target_bins={},
        mode_count=1,
        mode_locations=(4.0,),
        mode_heights=(0.5,),
        mean_rate=4.0,
        std_rate=0.5,
        skew=0.0,
        kurt=3.0,
        stability_flag="stable",
        extrapolation_dominated=False,
        sabr_density_on_same_grid=None,
        sabr_rnd_kl_divergence=0.0,
    )

    scen = PathScenario(
        name="0_cuts_through_Sep26",
        horizon=datetime.date(2026, 9, 16),
        cumulative_change_bp=0.0,
        delta_from_implied_bp=75.0,
        bin_lower_rate=3.875,
        bin_upper_rate=4.125,
    )
    p = path_scenario_probability_rnd(rnd_record=rec, scenario=scen)
    # 0.25 width * 0.5 density = 0.125
    assert 0.10 <= p <= 0.15


def test_extract_fomc_path_filters_by_lookahead():
    from RVUtils.STIRAsymmetricScreener._path import extract_fomc_path

    sched = _stub_fomc_schedule()
    path = extract_fomc_path(
        as_of=datetime.date(2026, 7, 1),  # past Jun26 meeting
        curve_handle=MagicMock(),
        fomc_schedule=sched,
        spot_target=0.04,
        forward_rate_fn=lambda *, eff_date, mat_date, handle: 0.04,
    )
    # Should only include meetings after as_of
    for m in path.meetings:
        assert m > datetime.date(2026, 7, 1)
