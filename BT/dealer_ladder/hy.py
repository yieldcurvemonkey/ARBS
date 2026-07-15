"""Hayashi-Yoshida lead-lag estimator.

Implements:
  - the classic Hayashi & Yoshida (2005) realized-covariance/correlation
    estimator for two irregularly-spaced ("non-synchronous") increment
    series, and
  - the Hoffmann, Rosenbaum & Yoshida (2013) lagged extension used to
    detect a lead-lag relationship between two series by scanning a grid
    of time shifts.

Pure numpy/pandas, no other dependencies.

SIGN CONVENTION (critical -- read before touching the shift direction)
------------------------------------------------------------------------
``hy_curve`` shifts Y's observation times *backward* by each candidate
lag ``l`` (``Y_times_shifted = Y_times - l``) before computing
``hy_corr(X, Y_shifted)``. This is the direction that makes POSITIVE l
mean "X leads Y": if Y is a delayed/stale echo of X (Y's value at time t
equals X's value from ``theta`` seconds earlier -- i.e. X's information
reaches Y only after a real delay, the standard meaning of "X leads Y"),
the correlation curve empirically peaks at l = +theta under this
"minus" convention. (Naively adding l instead -- Y_times + l -- peaks at
l = -theta for the same "X leads Y" scenario; verified numerically
against BOTH mandatory convention-pinning tests before picking this
formula.) ``lls`` then reads a positive-lag-dominant curve as positive
LLS. In this module's intended usage, X = ladder increments and
Y = futures prices, so POSITIVE LLS = ladder leads futures = alpha
direction.

Units: times are converted internally to a plain numeric axis. Datetime-
like inputs (``pd.DatetimeIndex``, datetime64 arrays/Series) are
converted to minutes-since-epoch, matching ``DEFAULT_LAGS_MINUTES``.
Plain numeric arrays are used as-is (the caller's unit); the ``lags``
passed to ``hy_curve`` must then be expressed in that same unit.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Sequence, Union

import numpy as np
import pandas as pd

ArrayLike = Union[Sequence[float], np.ndarray, pd.Series, pd.DatetimeIndex]

# Default lag grid for hy_curve, in minutes (see module docstring re: units).
DEFAULT_LAGS_MINUTES: tuple = (
    -1440.0, -240.0, -120.0, -60.0, -30.0, -15.0, -5.0, -1.0,
    0.0,
    1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 240.0, 1440.0,
)


def _to_numeric_time(times: ArrayLike) -> np.ndarray:
    """Coerce a time-like array to a plain float64 numeric axis.

    Datetime-like input (pd.DatetimeIndex, or arrays/Series with a
    datetime64 dtype) is converted to minutes-since-epoch. Anything else
    is treated as already-numeric and passed through as float64 in the
    caller's own unit.
    """
    if isinstance(times, pd.DatetimeIndex):
        return times.astype("int64").to_numpy() / 1e9 / 60.0
    if isinstance(times, pd.Series) and pd.api.types.is_datetime64_any_dtype(times):
        return times.astype("int64").to_numpy() / 1e9 / 60.0
    arr = np.asarray(times)
    if np.issubdtype(arr.dtype, np.datetime64):
        return pd.DatetimeIndex(arr).astype("int64").to_numpy() / 1e9 / 60.0
    return arr.astype("float64")


def _to_values(vals: ArrayLike) -> np.ndarray:
    return np.asarray(vals, dtype="float64")


def hy_corr(x_times: ArrayLike, x_vals: ArrayLike, y_times: ArrayLike, y_vals: ArrayLike) -> float:
    """Classic Hayashi-Yoshida correlation between two increment series.

    X observed at t_0^X < ... < t_n^X with values x_0..x_n, Y observed at
    t_0^Y < ... < t_m^Y with values y_0..y_m. Increments dX_i = x_{i+1}-x_i
    live on interval [t_i^X, t_{i+1}^X]; dY_j analogously for Y.

    HY covariance sums dX_i * dY_j over every (i, j) pair whose intervals
    overlap (strict): t_i^X < t_{j+1}^Y AND t_j^Y < t_{i+1}^X.

    HY correlation = HY_cov / sqrt(sum(dX_i^2) * sum(dY_j^2)).

    Returns 0.0 if either series has zero variance (or fewer than 2
    observations, i.e. no increments to compare).
    """
    xt = _to_numeric_time(x_times)
    xv = _to_values(x_vals)
    yt = _to_numeric_time(y_times)
    yv = _to_values(y_vals)

    if len(xt) < 2 or len(yt) < 2:
        return 0.0

    dx = np.diff(xv)
    dy = np.diff(yv)

    sum_dx2 = float(np.sum(dx * dx))
    sum_dy2 = float(np.sum(dy * dy))
    if sum_dx2 == 0.0 or sum_dy2 == 0.0:
        return 0.0

    x_start, x_end = xt[:-1], xt[1:]
    y_start, y_end = yt[:-1], yt[1:]

    overlap = (x_start[:, None] < y_end[None, :]) & (y_start[None, :] < x_end[:, None])
    hy_cov = float(np.sum(overlap * (dx[:, None] * dy[None, :])))

    return hy_cov / np.sqrt(sum_dx2 * sum_dy2)


def hy_curve(
    x_times: ArrayLike,
    x_vals: ArrayLike,
    y_times: ArrayLike,
    y_vals: ArrayLike,
    lags: Iterable[float] = DEFAULT_LAGS_MINUTES,
) -> Dict[float, float]:
    """Hoffmann et al. lagged HY curve: hy_corr(X, Y) at each candidate lag.

    For each lag l in ``lags``, Y's observation times are shifted
    *backward* by l (Y_times_shifted = Y_times - l) and hy_corr(X,
    Y_shifted) is computed. See the module docstring's SIGN CONVENTION
    section for why this is a subtraction, not the naive addition.

    Returns a dict mapping each lag value (as passed in, unmodified) to
    the resulting HY correlation.
    """
    xt = _to_numeric_time(x_times)
    xv = _to_values(x_vals)
    yt = _to_numeric_time(y_times)
    yv = _to_values(y_vals)

    curve: Dict[float, float] = {}
    for lag in lags:
        shifted_yt = yt - lag
        curve[lag] = hy_corr(xt, xv, shifted_yt, yv)
    return curve


def lls(curve: Mapping[float, float]) -> float:
    """Lead-lag strength (paper eq. 4) from a lag -> correlation curve.

    POSITIVE LLS means X leads Y (see module docstring SIGN CONVENTION).
    """
    if not curve:
        return 0.0

    positive_lags = {l: rho for l, rho in curve.items() if l > 0}
    negative_lags = {l: rho for l, rho in curve.items() if l < 0}

    sum_pos = sum(rho ** 2 for rho in positive_lags.values())
    sum_neg = sum(rho ** 2 for rho in negative_lags.values())
    mean_sq = sum(rho ** 2 for rho in curve.values()) / len(curve)

    if mean_sq == 0:
        return 0.0

    if sum_pos >= sum_neg:
        ratio = sum_pos / sum_neg if sum_neg > 0 else float("inf")
        return (ratio - 1) * 100 * mean_sq
    else:
        ratio = sum_neg / sum_pos if sum_pos > 0 else float("inf")
        return -(ratio - 1) * 100 * mean_sq
