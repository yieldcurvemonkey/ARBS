"""Approach 1: Breeden-Litzenberger RND extraction via smoothing spline.

The risk-neutral density Q(K) = e^(rT) * d²C/dK² where C(K) is the call
price as a function of strike. We fit C(K) with a 4th-order smoothing spline
and take the analytical 2nd derivative.

Reference: Breeden & Litzenberger 1978, Journal of Business, Vol. 51, No. 4.
Implementation follows JPM Technical Appendix A (2026 Outlook).
"""

import math
from typing import List, Optional

import numpy as np
from scipy.integrate import trapezoid
from scipy.interpolate import UnivariateSpline

from RVUtils.ImpliedDistribution._data_prep import add_ghost_points
from RVUtils.ImpliedDistribution._types import BreedenLitzenbergerResult, RNDInput


def extract_rnd_breeden_litzenberger(
    rnd_input: RNDInput,
    *,
    smoothing_param: float = 1e-4,
    spline_order: int = 4,
    n_ghost_points: int = 10,
    ghost_extension_bps: float = 5.0,
    bin_width_bps: float = 25.0,
    grid_points: int = 2000,
    rate_floor: Optional[float] = 0.0,
) -> BreedenLitzenbergerResult:
    """Extract risk-neutral density via Breeden-Litzenberger with smoothing spline.

    Parameters
    ----------
    rnd_input : RNDInput
        Market data (strikes in price space, call premiums).
    smoothing_param : float
        Spline smoothing factor (scaled by N internally). JPM uses 10^-4.
    spline_order : int
        Spline polynomial degree (max 5). JPM uses 4.
    n_ghost_points : int
        Number of ghost points per side for tail extrapolation.
    ghost_extension_bps : float
        Spacing of ghost points in price-space bps.
    bin_width_bps : float
        Width of rate bins for scenario probabilities.
    grid_points : int
        Number of points in fine evaluation grid.
    rate_floor : float or None
        If set, zero out density below this rate and renormalize.
        Default 0.0 (SOFR cannot go negative). Set to None to disable.
    """
    strikes = rnd_input.strikes_price
    premiums = rnd_input.call_premiums
    df = rnd_input.discount_factor

    # 1. Add ghost points
    ext_strikes, ext_premiums = add_ghost_points(
        strikes,
        premiums,
        n_ghost=n_ghost_points,
        extension_bps=ghost_extension_bps,
    )

    # 2. Fit smoothing spline C(K)
    # s parameter: UnivariateSpline interprets s as the total sum-of-squares
    # residual budget. Scaling by N gives behavior similar to a per-point lambda.
    k = min(spline_order, 5)
    n = len(ext_strikes)
    spline = UnivariateSpline(ext_strikes, ext_premiums, k=k, s=smoothing_param * n)

    # 3. Fine grid for evaluation
    grid_min = float(ext_strikes[0])
    grid_max = float(ext_strikes[-1])
    strike_grid = np.linspace(grid_min, grid_max, grid_points)

    # 4. 2nd derivative → RND in price space
    d2c_dk2 = spline(strike_grid, nu=2)
    rnd_price = d2c_dk2 / df

    # Floor at zero (numerical artifacts at tails)
    rnd_price = np.maximum(rnd_price, 0.0)

    # 5. Normalize
    total_mass = trapezoid(rnd_price, strike_grid)
    if total_mass > 1e-10:
        rnd_price = rnd_price / total_mass

    # 6. Convert to rate space (rate = 100 - price)
    # strike_grid is ascending in price → descending in rate, so flip
    rate_grid = (100.0 - strike_grid)[::-1]
    rnd_rate = rnd_price[::-1]

    # 6b. Truncate at rate floor (e.g. 0% for SOFR — negative rates impossible)
    if rate_floor is not None:
        floor_mask = rate_grid >= rate_floor
        rate_grid = rate_grid[floor_mask]
        rnd_rate = rnd_rate[floor_mask]
        # Renormalize so density integrates to 1.0
        total_mass = trapezoid(rnd_rate, rate_grid)
        if total_mass > 1e-10:
            rnd_rate = rnd_rate / total_mass

    # 7. CDF via trapezoidal integration
    dx = np.diff(rate_grid)
    cdf = np.zeros_like(rate_grid)
    cdf[1:] = np.cumsum(0.5 * (rnd_rate[:-1] + rnd_rate[1:]) * dx)
    if cdf[-1] > 1e-10:
        cdf = cdf / cdf[-1]

    # 8. Bin into scenario probabilities
    bin_width = bin_width_bps / 100.0
    fwd_rate = rnd_input.forward_rate
    center_bin = round(fwd_rate / bin_width) * bin_width

    # Build bin edges spanning the grid
    edge = center_bin
    while edge - bin_width >= rate_grid[0]:
        edge -= bin_width
    bin_edges_list: List[float] = []
    while edge <= rate_grid[-1] + bin_width:
        bin_edges_list.append(edge)
        edge += bin_width
    bin_edges = np.array(bin_edges_list)

    bin_probs: List[float] = []
    bin_labels: List[str] = []
    for i in range(len(bin_edges) - 1):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (rate_grid >= lo) & (rate_grid < hi)
        prob = float(trapezoid(rnd_rate[mask], rate_grid[mask])) if mask.any() else 0.0
        bin_probs.append(prob)
        mid = (lo + hi) / 2.0
        bin_labels.append(f"{mid:.3f}")
    bin_probabilities = np.array(bin_probs)

    # 9. Summary statistics
    mean_rate = float(trapezoid(rate_grid * rnd_rate, rate_grid))
    var_rate = float(trapezoid((rate_grid - mean_rate) ** 2 * rnd_rate, rate_grid))
    std_rate = math.sqrt(max(var_rate, 0.0))
    if std_rate > 1e-10:
        skewness = float(trapezoid((rate_grid - mean_rate) ** 3 * rnd_rate, rate_grid)) / (std_rate**3)
        kurtosis = float(trapezoid((rate_grid - mean_rate) ** 4 * rnd_rate, rate_grid)) / (std_rate**4)
    else:
        skewness = 0.0
        kurtosis = 0.0

    # Spline residual (on original data, not ghost points)
    spline_fitted = spline(strikes)
    spline_residual = float(np.sqrt(np.mean((spline_fitted - premiums) ** 2)))

    return BreedenLitzenbergerResult(
        input=rnd_input,
        strike_grid_rate=rate_grid,
        rnd_density=rnd_rate,
        rnd_cumulative=cdf,
        bin_edges_rate=bin_edges,
        bin_probabilities=bin_probabilities,
        bin_labels=bin_labels,
        mean_rate=mean_rate,
        std_rate=std_rate,
        skewness=skewness,
        kurtosis=kurtosis,
        smoothing_param=smoothing_param,
        n_ghost_points=n_ghost_points,
        spline_residual=spline_residual,
    )
