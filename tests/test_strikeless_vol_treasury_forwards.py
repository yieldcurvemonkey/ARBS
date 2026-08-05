import numpy as np
import pytest

from RVUtils.StrikelessVol.treasury_forwards import (
    forward_par_rate,
    par_to_discount,
)


def _analytic_curve(rate, ttms, freq=2):
    """Discount factors and par yields of a flat continuously-quoted curve."""
    dfs = 1.0 / (1.0 + rate / freq) ** (ttms * freq)
    return dfs


def test_bootstrap_round_trips_a_flat_par_curve():
    ttms = np.arange(0.5, 40.5, 0.5)
    par = np.full_like(ttms, 0.04)
    dfs = par_to_discount(ttms, par, freq=2)
    expected = _analytic_curve(0.04, ttms)
    assert np.allclose(dfs, expected, atol=1e-10)


def test_forward_par_rate_of_a_flat_curve_is_the_flat_rate():
    ttms = np.arange(0.5, 40.5, 0.5)
    dfs = par_to_discount(ttms, np.full_like(ttms, 0.04), freq=2)
    fwd = forward_par_rate(ttms, dfs, fwd_years=10, tail_years=10)
    assert fwd == pytest.approx(0.04, abs=1e-8)


def test_forward_of_an_upward_sloping_curve_exceeds_the_spot_rate():
    ttms = np.arange(0.5, 40.5, 0.5)
    par = 0.03 + 0.0005 * ttms
    dfs = par_to_discount(ttms, par, freq=2)
    fwd = forward_par_rate(ttms, dfs, fwd_years=10, tail_years=10)
    spot20 = float(np.interp(20.0, ttms, par))
    assert fwd > spot20


def test_discount_factors_are_monotone_decreasing():
    ttms = np.arange(0.5, 40.5, 0.5)
    dfs = par_to_discount(ttms, 0.03 + 0.0005 * ttms, freq=2)
    assert np.all(np.diff(dfs) < 0)


def test_bootstrap_rejects_an_unsorted_grid():
    with pytest.raises(ValueError):
        par_to_discount(np.array([2.0, 1.0]), np.array([0.04, 0.04]))
