"""Tests for the Hayashi-Yoshida lead-lag estimator (BT/dealer_ladder/hy.py).

Test order and coverage follow the task brief precisely (10 prescribed
tests, two of them MANDATORY convention-pinning tests), plus one small
addition (test_hy_corr_zero_variance_returns_zero) for a spec'd branch
that the 10 prescribed tests don't otherwise exercise.
"""

import numpy as np
import pytest

from BT.dealer_ladder import hy


def test_hy_corr_synchronized():
    """Two identical series at the same times: HY correlation == 1.0."""
    rng = np.random.default_rng(0)
    times = np.arange(50, dtype="float64")
    vals = np.cumsum(rng.normal(size=50))

    corr = hy.hy_corr(times, vals, times, vals)

    assert corr == pytest.approx(1.0, abs=1e-9)


def test_hy_corr_anti_correlated():
    """Y = -X at the same times: HY correlation == -1.0."""
    rng = np.random.default_rng(0)
    times = np.arange(50, dtype="float64")
    vals = np.cumsum(rng.normal(size=50))

    corr = hy.hy_corr(times, vals, times, -vals)

    assert corr == pytest.approx(-1.0, abs=1e-9)


def test_hy_corr_independent():
    """Truly independent series on a shared dense grid: correlation near 0."""
    rng = np.random.default_rng(1)
    n = 1000
    times = np.arange(n, dtype="float64")
    x_vals = np.cumsum(rng.normal(size=n))
    y_vals = np.cumsum(rng.normal(size=n))

    corr = hy.hy_corr(times, x_vals, times, y_vals)

    assert abs(corr) < 0.15


def test_hy_corr_no_overlap():
    """Non-overlapping time intervals: HY correlation is exactly 0.0."""
    x_times = np.array([0.0, 1.0, 2.0, 3.0])
    x_vals = np.array([0.0, 1.0, 2.0, 3.0])
    y_times = np.array([10.0, 11.0, 12.0, 13.0])
    y_vals = np.array([0.0, 1.0, 2.0, 3.0])

    assert hy.hy_corr(x_times, x_vals, y_times, y_vals) == 0.0


def test_hy_corr_partial_overlap():
    """Hand-calculated example with a genuine mix of overlapping / non-overlapping pairs.

    X: times [0, 4, 8], values [0, 2, 5] -> dX = [2, 3] over intervals [0,4], [4,8]
    Y: times [2, 6, 10], values [0, -1, 4] -> dY = [-1, 5] over intervals [2,6], [6,10]

    Overlap check (t_i^X < t_{j+1}^Y AND t_j^Y < t_{i+1}^X):
      [0,4] x [2,6]: 0<6 T, 2<4 T  -> overlap: dX0*dY0 = 2*-1  = -2
      [0,4] x [6,10]: 0<10 T, 6<4 F -> NO overlap
      [4,8] x [2,6]: 4<6 T, 2<8 T  -> overlap: dX1*dY0 = 3*-1  = -3
      [4,8] x [6,10]: 4<10 T, 6<8 T -> overlap: dX1*dY1 = 3*5   = 15

    HY_cov = -2 + -3 + 15 = 10
    sum(dX^2) = 4 + 9 = 13
    sum(dY^2) = 1 + 25 = 26
    HY_corr = 10 / sqrt(13*26) = 10 / sqrt(338)
    """
    x_times = [0.0, 4.0, 8.0]
    x_vals = [0.0, 2.0, 5.0]
    y_times = [2.0, 6.0, 10.0]
    y_vals = [0.0, -1.0, 4.0]

    expected = 10.0 / np.sqrt(338.0)

    assert hy.hy_corr(x_times, x_vals, y_times, y_vals) == pytest.approx(expected, abs=1e-9)


def test_hy_corr_zero_variance_returns_zero():
    """A flat (zero-variance) series makes HY correlation return 0.0, not NaN/inf."""
    times = np.array([0.0, 1.0, 2.0, 3.0])
    flat_vals = np.array([5.0, 5.0, 5.0, 5.0])
    moving_vals = np.array([0.0, 1.0, 2.0, 3.0])

    assert hy.hy_corr(times, flat_vals, times, moving_vals) == 0.0
    assert hy.hy_corr(times, moving_vals, times, flat_vals) == 0.0
    assert hy.hy_corr(times, flat_vals, times, flat_vals) == 0.0


def test_hy_convention_pinning_x_leads_y():
    """MANDATORY: X leads Y by 17s -> HY curve peaks at positive lag ~17s, LLS > 0.

    Dense X (1000 obs, 1-second spacing, seeded random walk). Sparse Y
    echoes X's OLDER value (from `theta` seconds earlier) at each of its
    own observation times, i.e. Y(t) = X(t - theta): Y is a stale/delayed
    copy of X, so X's information reaches Y only after a 17-second delay
    -- X leads Y by 17 seconds.
    """
    rng = np.random.default_rng(1)
    n = 1000
    theta = 17
    x_times = np.arange(n, dtype="float64")
    x_vals = np.cumsum(rng.normal(size=n))
    k_max = (n - 1) // theta
    y_vals = x_vals[0 : k_max * theta : theta]
    y_times = x_times[0 : k_max * theta : theta] + theta

    lags = list(range(-40, 41))  # seconds, fine enough to resolve a 17s peak
    curve = hy.hy_curve(x_times, x_vals, y_times, y_vals, lags=lags)

    positive_lags = {l: rho for l, rho in curve.items() if l > 0}
    peak_lag = max(positive_lags, key=lambda l: positive_lags[l])
    assert 10 <= peak_lag <= 25, f"expected peak near +17s, got {peak_lag}"

    lls_value = hy.lls(curve)
    assert lls_value > 0, f"expected positive LLS (X leads Y), got {lls_value}"


def test_hy_convention_pinning_y_leads_x():
    """MANDATORY: mirror of the above. Y leads X by 17s -> LLS < 0 (X does not lead)."""
    rng = np.random.default_rng(1)
    n = 1000
    theta = 17
    y_times = np.arange(n, dtype="float64")
    y_vals = np.cumsum(rng.normal(size=n))
    k_max = (n - 1) // theta
    x_vals = y_vals[0 : k_max * theta : theta]
    x_times = y_times[0 : k_max * theta : theta] + theta

    lags = list(range(-40, 41))
    curve = hy.hy_curve(x_times, x_vals, y_times, y_vals, lags=lags)

    negative_lags = {l: rho for l, rho in curve.items() if l < 0}
    peak_lag = max(negative_lags, key=lambda l: negative_lags[l])
    assert -25 <= peak_lag <= -10, f"expected peak near -17s, got {peak_lag}"

    lls_value = hy.lls(curve)
    assert lls_value < 0, f"expected negative LLS (Y leads X), got {lls_value}"


def test_hy_placebo_independent():
    """Independent X and Y (no true lead-lag relationship): |LLS| stays small."""
    rng = np.random.default_rng(1)
    n = 1000
    times = np.arange(n, dtype="float64")
    x_vals = np.cumsum(rng.normal(size=n))
    y_vals = np.cumsum(rng.normal(size=n))

    lags = list(range(-40, 41))
    curve = hy.hy_curve(times, x_vals, times, y_vals, lags=lags)

    lls_value = hy.lls(curve)
    assert abs(lls_value) < 5.0, f"expected |LLS| near 0 for independent series, got {lls_value}"


def test_lls_symmetric_curve():
    """A perfectly symmetric curve (same rho at +l and -l) has LLS == 0."""
    curve = {-10: 0.5, -5: 0.3, 0.0: 0.9, 5: 0.3, 10: 0.5}

    assert hy.lls(curve) == pytest.approx(0.0, abs=1e-12)


def test_hy_corr_golden_fixture():
    """Hand-computed golden fixture, hard-coded expected result.

    X: times [0, 2, 5, 8, 10], values [0, 1, 3, 2, 4]
       increments: dX = [1, 2, -1, 2] over [0,2], [2,5], [5,8], [8,10]
    Y: times [1, 4, 7, 11], values [0, 2, 1, 3]
       increments: dY = [2, -1, 2] over [1,4], [4,7], [7,11]

    Overlapping pairs (strict: t_i^X < t_{j+1}^Y AND t_j^Y < t_{i+1}^X):
      [0,2] x [1,4]: 0<4 T, 1<2 T  -> dX=1  * dY=2  = 2
      [2,5] x [1,4]: 2<4 T, 1<5 T  -> dX=2  * dY=2  = 4
      [2,5] x [4,7]: 2<7 T, 4<5 T  -> dX=2  * dY=-1 = -2
      [5,8] x [4,7]: 5<7 T, 4<8 T  -> dX=-1 * dY=-1 = 1
      [5,8] x [7,11]: 5<11 T, 7<8 T -> dX=-1 * dY=2  = -2
      [8,10] x [7,11]: 8<11 T, 7<10 T -> dX=2  * dY=2  = 4

    HY_cov = 2 + 4 - 2 + 1 - 2 + 4 = 7
    sum(dX^2) = 1 + 4 + 1 + 4 = 10
    sum(dY^2) = 4 + 1 + 4 = 9
    HY_corr = 7 / sqrt(90) ~= 0.7379
    """
    x_times = [0, 2, 5, 8, 10]
    x_vals = [0, 1, 3, 2, 4]
    y_times = [1, 4, 7, 11]
    y_vals = [0, 2, 1, 3]

    expected = 7.0 / np.sqrt(90.0)

    result = hy.hy_corr(x_times, x_vals, y_times, y_vals)
    assert result == pytest.approx(expected, abs=1e-9)
    assert result == pytest.approx(0.7379, abs=1e-4)
