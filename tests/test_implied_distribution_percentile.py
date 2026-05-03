import datetime
import numpy as np

from RVUtils.ImpliedDistribution import BreedenLitzenbergerResult, RNDInput


def _result_with_uniform_density() -> BreedenLitzenbergerResult:
    """Uniform [3.0, 4.0]: CDF(x) = (x - 3.0). 50th pct = 3.5 exactly."""
    grid = np.linspace(3.0, 4.0, 1001)
    density = np.ones_like(grid)
    cdf = (grid - 3.0)
    return BreedenLitzenbergerResult(
        input=RNDInput(
            symbol="X", as_of=datetime.date(2026, 4, 28),
            forward_price=96.5, forward_rate=3.5, time_to_expiry=0.5,
            expiry_date=datetime.date(2026, 12, 14), discount_factor=1.0,
            strikes_price=np.array([96.0]), call_premiums=np.array([0.5]),
            strike_source="test",
        ),
        strike_grid_rate=grid,
        rnd_density=density,
        rnd_cumulative=cdf,
        bin_edges_rate=np.array([3.0, 4.0]),
        bin_probabilities=np.array([1.0]),
        bin_labels=["3.5"],
        mean_rate=3.5, std_rate=1 / np.sqrt(12),
        skewness=0.0, kurtosis=1.8,
        smoothing_param=1e-4, n_ghost_points=10, spline_residual=0.0,
    )


def test_percentile_50_returns_exact_median():
    r = _result_with_uniform_density()
    assert abs(r.percentile(50.0) - 3.5) < 1e-6


def test_percentile_25_and_75_interpolate_correctly():
    r = _result_with_uniform_density()
    assert abs(r.percentile(25.0) - 3.25) < 1e-6
    assert abs(r.percentile(75.0) - 3.75) < 1e-6


def test_percentile_off_grid_p_value_interpolates():
    """A 1001-point grid (dx=1e-3) with uniform CDF: percentile 33.33 should give
    3.3333 — exact searchsorted cannot achieve this."""
    r = _result_with_uniform_density()
    # CDF is exactly the rate offset from 3.0; 33.33% → 3.3333
    assert abs(r.percentile(33.33) - 3.3333) < 1e-6
    assert abs(r.percentile(66.66) - 3.6666) < 1e-6


def test_percentile_extreme_values_clamped():
    r = _result_with_uniform_density()
    assert r.percentile(0.0) == r.strike_grid_rate[0]
    assert r.percentile(100.0) == r.strike_grid_rate[-1]
