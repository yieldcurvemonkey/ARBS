"""Known-answer tests for the JPM relative-value framework pieces.

The planted answers here are analytic:

* A **flat** normal-vol smile has, by construction, a Gaussian risk-neutral
  density. So ``implied_shift_density`` fed a flat smile at sigma must return
  N(0, sigma*sqrt(T)) -- if the Breeden-Litzenberger differentiation or the bp
  unit handling is wrong, this is where it shows.
* A payoff that is exactly quadratic in the shift has an analytic expectation
  under a zero-mean normal, ``E[a*x^2 + c] = a*sigma^2 + c``, which pins both
  ``normal_pdf_weights`` and ``expected_payoff``.
* That same quadratic gives a closed-form breakeven vol, ``sigma = sqrt(-c/a)``,
  which pins the root solve.
"""

import numpy as np
import pytest
from scipy.stats import norm

from RVUtils.ConvexityRV.payoff import (
    breakeven_vol_bp_per_day,
    breakeven_vol_bp_per_year,
    expected_payoff,
    normal_pdf_weights,
)
from RVUtils.ConvexityRV.swaption_cube import implied_shift_density

# A grid fine and wide enough that truncation/discretisation are negligible.
GRID = np.arange(-1000.0, 1000.01, 2.0)


def test_normal_weights_match_scipy():
    sigma = 120.0
    w = normal_pdf_weights(GRID, sigma)
    ref = norm.pdf(GRID, scale=sigma)
    ref = ref / ref.sum()
    assert np.max(np.abs(w - ref)) < 1e-12
    assert w.sum() == pytest.approx(1.0)


def test_expected_payoff_of_quadratic_is_a_sigma_squared_plus_c():
    """E[a*x^2 + c] = a*sigma^2 + c under a zero-mean normal."""
    a, c, sigma = 0.002, -30.0, 90.0
    payoff = a * GRID**2 + c
    got = expected_payoff(GRID, payoff, normal_pdf_weights(GRID, sigma))
    assert got == pytest.approx(a * sigma**2 + c, rel=1e-6)


def test_breakeven_vol_of_quadratic_is_sqrt_minus_c_over_a():
    """Analytic root: a*sigma^2 + c = 0  =>  sigma = sqrt(-c/a)."""
    a, c = 0.002, -30.0
    payoff = a * GRID**2 + c
    expected = np.sqrt(-c / a)  # 122.47 bp/yr
    got = breakeven_vol_bp_per_year(GRID, payoff, horizon_years=1.0)
    assert got == pytest.approx(expected, rel=1e-4)


def test_breakeven_vol_scales_with_horizon():
    """Terminal sigma = annual sigma * sqrt(T), so a 4y horizon halves the
    annual vol needed to reach the same terminal width."""
    a, c = 0.002, -30.0
    payoff = a * GRID**2 + c
    one = breakeven_vol_bp_per_year(GRID, payoff, horizon_years=1.0)
    four = breakeven_vol_bp_per_year(GRID, payoff, horizon_years=4.0)
    assert four == pytest.approx(one / 2.0, rel=1e-3)


def test_breakeven_vol_daily_conversion():
    a, c = 0.002, -30.0
    payoff = a * GRID**2 + c
    annual = breakeven_vol_bp_per_year(GRID, payoff, horizon_years=1.0)
    daily = breakeven_vol_bp_per_day(GRID, payoff, horizon_years=1.0)
    assert daily == pytest.approx(annual / np.sqrt(252.0), rel=1e-9)


def test_positive_carry_convex_payoff_has_no_breakeven():
    """A convex payoff that is already positive everywhere never needs vol to
    break even. That must be NaN, not a spurious root at the bracket edge."""
    payoff = 0.002 * GRID**2 + 5.0
    assert np.isnan(breakeven_vol_bp_per_year(GRID, payoff, horizon_years=1.0))


# --------------------------------------------------------------- density


def _flat_smile(sigma_bp: float, offsets=(-200, -100, -75, -50, -25, -10, 0, 10, 25, 50, 75, 100, 200)):
    import pandas as pd

    return pd.DataFrame({"offset_bp": list(map(float, offsets)),
                         "vol_bp": [float(sigma_bp)] * len(offsets)})


def test_flat_smile_gives_gaussian_density():
    """The planted answer: flat normal vol => exactly N(0, sigma*sqrt(T))."""
    sigma, tte = 100.0, 1.0
    grid = np.arange(-300.0, 300.01, 5.0)
    w = implied_shift_density(_flat_smile(sigma), grid, tte_years=tte)
    ref = norm.pdf(grid, scale=sigma * np.sqrt(tte))
    ref = ref / ref.sum()
    assert np.isfinite(w).all()
    # Discretised BL on a truncated grid: a few tenths of a percent is expected.
    assert np.max(np.abs(w - ref)) < 5e-4


def test_flat_smile_density_scales_with_tte():
    """Doubling T widens the density by sqrt(2)."""
    grid = np.arange(-600.0, 600.01, 4.0)
    w1 = implied_shift_density(_flat_smile(100.0), grid, tte_years=1.0)
    w2 = implied_shift_density(_flat_smile(100.0), grid, tte_years=2.0)
    sd1 = np.sqrt(np.sum(w1 * grid**2))
    sd2 = np.sqrt(np.sum(w2 * grid**2))
    assert sd1 == pytest.approx(100.0, rel=2e-3)
    assert sd2 / sd1 == pytest.approx(np.sqrt(2.0), rel=5e-3)


def test_sparse_smile_returns_nan_not_a_guess():
    """ATM-only days (all of 2019) must be detectable, not silently filled."""
    import pandas as pd

    atm_only = pd.DataFrame({"offset_bp": [0.0], "vol_bp": [95.0]})
    w = implied_shift_density(atm_only, GRID)
    assert np.isnan(w).all()


def test_smiling_smile_is_fatter_tailed_than_flat():
    """A convex (smiling) vol curve must put more mass in the tails than the
    flat smile with the same ATM vol -- the direction the note relies on."""
    import pandas as pd

    offs = np.array([-200, -100, -75, -50, -25, -10, 0, 10, 25, 50, 75, 100, 200], float)
    smiled = pd.DataFrame({"offset_bp": offs, "vol_bp": 100.0 + 0.0004 * offs**2})
    grid = np.arange(-400.0, 400.01, 4.0)
    w_flat = implied_shift_density(_flat_smile(100.0), grid)
    w_smile = implied_shift_density(smiled, grid)
    tail = np.abs(grid) > 200
    assert w_smile[tail].sum() > w_flat[tail].sum()
