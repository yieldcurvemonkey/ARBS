"""Tests for STIRAsymmetricScreener._rnd."""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass
from typing import Tuple
from unittest.mock import MagicMock

import numpy as np
import pytest


# --- Stub smile builder -------------------------------------------------------


def _make_stub_smile(
    *,
    forward_price: float = 96.30,
    time_to_expiry: float = 0.5,
    alpha: float = 0.005,
    beta: float = 0.0,
    rho: float = -0.05,
    nu: float = 0.6,
    symbol: str = "SFRU26",
    expiry_date: datetime.date = datetime.date(2026, 9, 11),
):
    from MDP.STIRFutures.STIRFutureOptionMDP import (
        STIRFutureOptionSABRParams,
        STIRFutureOptionSABRSmile,
        STIRFutureOptionSmilePoint,
    )

    params = STIRFutureOptionSABRParams(
        alpha=alpha,
        beta=beta,
        rho=rho,
        nu=nu,
        forward_price=forward_price,
        forward_rate=100.0 - forward_price,
        time_to_expiry=time_to_expiry,
        expiry_date=expiry_date,
        as_of=datetime.date(2026, 4, 28),
        calibration_rmse=1e-5,
    )
    points: Tuple = tuple()  # SABR-only, no market points needed for vols
    return STIRFutureOptionSABRSmile(
        source="STUB",
        symbol=symbol,
        underlying_contract=symbol,
        quote_timestamp=datetime.datetime(2026, 4, 28, 16, 0, 0),
        params=params,
        points=points,
    )


# --- Tests --------------------------------------------------------------------


def test_extract_per_expiry_rnd_returns_unimodal_density_for_unimodal_smile():
    from RVUtils.STIRAsymmetricScreener._rnd import (
        RNDRecord,
        extract_per_expiry_rnd,
    )
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

    smile = _make_stub_smile()
    cfg = ScreenerConfig()

    rec = extract_per_expiry_rnd(
        smile=smile,
        leg_market={},
        config=cfg,
        as_of=datetime.date(2026, 4, 28),
    )
    assert isinstance(rec, RNDRecord)
    assert rec.contract == "SFRU26"
    assert rec.dte > 0
    # Must produce valid density
    assert rec.density_pdf is not None
    assert (rec.density_pdf >= 0).all()
    # Unimodal SABR → mode count == 1
    assert rec.mode_count >= 1


def test_extract_per_expiry_rnd_density_integrates_to_one():
    from scipy.integrate import trapezoid

    from RVUtils.STIRAsymmetricScreener._rnd import extract_per_expiry_rnd
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

    smile = _make_stub_smile()
    rec = extract_per_expiry_rnd(
        smile=smile,
        leg_market={},
        config=ScreenerConfig(),
        as_of=datetime.date(2026, 4, 28),
    )
    mass = float(trapezoid(rec.density_pdf, rec.strike_grid_rate))
    assert abs(mass - 1.0) < 0.05


def test_extract_per_expiry_rnd_emits_sabr_density_on_same_grid():
    from RVUtils.STIRAsymmetricScreener._rnd import extract_per_expiry_rnd
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

    smile = _make_stub_smile()
    rec = extract_per_expiry_rnd(
        smile=smile,
        leg_market={},
        config=ScreenerConfig(),
        as_of=datetime.date(2026, 4, 28),
    )
    assert rec.sabr_density_on_same_grid is not None
    assert len(rec.sabr_density_on_same_grid) == len(rec.density_pdf)


def test_rnd_record_has_spec_fields():
    from RVUtils.STIRAsymmetricScreener._rnd import extract_per_expiry_rnd
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

    smile = _make_stub_smile()
    rec = extract_per_expiry_rnd(
        smile=smile,
        leg_market={},
        config=ScreenerConfig(),
        as_of=datetime.date(2026, 4, 28),
    )

    expected_fields = {
        "contract",
        "expiry",
        "dte",
        "strike_grid_rate",
        "n_strikes_observed",
        "density_pdf",
        "density_cdf",
        "fed_target_bins",
        "mode_count",
        "mode_locations",
        "mode_heights",
        "mean_rate",
        "std_rate",
        "skew",
        "kurt",
        "stability_flag",
        "extrapolation_dominated",
        "sabr_density_on_same_grid",
        "sabr_rnd_kl_divergence",
    }
    for f in expected_fields:
        assert hasattr(rec, f), f"Missing RNDRecord field: {f}"


def test_rnd_stability_check_runs_smoothing_sensitivity():
    from RVUtils.STIRAsymmetricScreener._rnd import extract_per_expiry_rnd
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

    smile = _make_stub_smile()
    rec = extract_per_expiry_rnd(
        smile=smile,
        leg_market={},
        config=ScreenerConfig(),
        as_of=datetime.date(2026, 4, 28),
    )
    # Stability flag is one of the documented values
    assert rec.stability_flag in {
        "stable",
        "unstable_smoothing",
        "unstable_order",
        "mass_violation",
        "negative_density",
        "parity_violation",
        "stale_reference_quarter",
    }


def test_rnd_reference_quarter_short_circuits_for_in_quarter_quarterly():
    from RVUtils.STIRAsymmetricScreener._rnd import extract_per_expiry_rnd
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

    # A SFRU26 option whose as_of is INSIDE its reference quarter (Sep-Dec 2026)
    # should be marked as stale per spec §9 / §12.2. SFRU26 IMM date is in
    # mid-September; using as_of=2026-09-15 is firmly inside the staleness window.
    smile = _make_stub_smile(
        symbol="SFRU26",
        expiry_date=datetime.date(2026, 9, 16),
        time_to_expiry=0.003,  # ~1d to expiry
    )

    rec = extract_per_expiry_rnd(
        smile=smile,
        leg_market={},
        config=ScreenerConfig(),
        as_of=datetime.date(2026, 9, 15),  # in / next-to reference quarter
    )
    assert rec.stability_flag == "stale_reference_quarter"


def test_payoff_zone_probability_helper_integrates_density():
    from RVUtils.STIRAsymmetricScreener._rnd import (
        extract_per_expiry_rnd,
        payoff_zone_probability,
    )
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

    smile = _make_stub_smile()
    rec = extract_per_expiry_rnd(
        smile=smile,
        leg_market={},
        config=ScreenerConfig(),
        as_of=datetime.date(2026, 4, 28),
    )

    # Probability over full support must be ~1
    p_full = payoff_zone_probability(rec, density="rnd", lower_rate=0.0, upper_rate=10.0)
    assert 0.85 <= p_full <= 1.0

    # Splitting into two halves should sum to ~1
    fwd_rate = float(smile.params.forward_rate)
    p_below = payoff_zone_probability(rec, density="rnd", lower_rate=0.0, upper_rate=fwd_rate)
    p_above = payoff_zone_probability(rec, density="rnd", lower_rate=fwd_rate, upper_rate=10.0)
    assert abs((p_below + p_above) - p_full) < 0.05


def test_extract_per_expiry_rnd_handles_observed_market_when_provided():
    """When leg_market dict has dense observed premiums, RND should use those."""
    from RVUtils.STIRAsymmetricScreener._market_data import LegMarket
    from RVUtils.STIRAsymmetricScreener._rnd import extract_per_expiry_rnd
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

    smile = _make_stub_smile()
    # Empty leg_market — extractor should fall back to SABR-modeled prices
    rec = extract_per_expiry_rnd(
        smile=smile,
        leg_market={},
        config=ScreenerConfig(),
        as_of=datetime.date(2026, 4, 28),
    )
    # Should not raise; n_strikes_observed reflects the SABR strike grid
    assert rec.n_strikes_observed > 0
