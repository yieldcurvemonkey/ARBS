"""Approach 2: Gaussian mixture decomposition into scenario-specific weights.

The implied distribution is modeled as a weighted sum of N Normal distributions,
each corresponding to a Fed policy scenario (e.g., "5 cuts", "unchanged", "1 hike").
Weights are solved by fitting to observed option prices across strikes.

Reference: JPM Interest Rate Derivatives, various reports (2023-2026).
"""

import math
from typing import List, Sequence

import numpy as np
from scipy.integrate import cumulative_trapezoid
from scipy.optimize import minimize
from scipy.stats import norm

from RVUtils.ImpliedDistribution._bachelier import bachelier_call_prices_vectorized
from RVUtils.ImpliedDistribution._types import (
    GaussianMixtureResult,
    RNDInput,
    ScenarioDefinition,
)


def _mixture_call_prices(
    strikes: np.ndarray,
    tte: float,
    discount: float,
    means_rate: np.ndarray,
    stds_rate: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    """Compute call prices from a weighted mixture of Bachelier models.

    Each scenario j has mean rate mu_j → forward price F_j = 100 - mu_j.
    The normal vol in price space equals the vol in rate space (since
    price = 100 - rate, the transformation is a sign flip with unit Jacobian).
    """
    prices = np.zeros(len(strikes))
    sqrt_t = math.sqrt(max(tte, 1e-12))
    for j in range(len(weights)):
        fwd_j = 100.0 - means_rate[j]
        vol_j = stds_rate[j]
        d = (fwd_j - strikes) / (vol_j * sqrt_t)
        component = discount * (vol_j * sqrt_t * norm.pdf(d) + (fwd_j - strikes) * norm.cdf(d))
        prices += weights[j] * component
    return prices


def extract_gaussian_mixture(
    rnd_input: RNDInput,
    scenarios: Sequence[ScenarioDefinition],
    *,
    optimize_stds: bool = True,
    initial_std_bps: float = 30.0,
    grid_points: int = 2000,
    rmse_warn_threshold: float = 1e-3,
) -> GaussianMixtureResult:
    """Extract scenario weights via Gaussian mixture decomposition.

    Parameters
    ----------
    rnd_input : RNDInput
        Market data (strikes and call premiums).
    scenarios : sequence of ScenarioDefinition
        Each defines a label, mean_rate, and optional fixed std_rate.
    optimize_stds : bool
        If True, optimize standard deviations for scenarios where std_rate is None.
    initial_std_bps : float
        Starting guess for free std deviations (in basis points of rate).
    grid_points : int
        Number of points for the output density grid.
    """
    n_scenarios = len(scenarios)
    means_rate = np.array([s.mean_rate for s in scenarios], dtype=float)
    fwd_rate = rnd_input.forward_rate
    tte = rnd_input.time_to_expiry
    df = rnd_input.discount_factor

    market_strikes = rnd_input.strikes_price
    market_calls = rnd_input.call_premiums

    # Determine which stds are free vs fixed
    fixed_stds = np.array(
        [s.std_rate if s.std_rate is not None else initial_std_bps / 100.0 for s in scenarios],
        dtype=float,
    )
    std_free_mask = np.array([s.std_rate is None for s in scenarios])
    n_free_stds = int(std_free_mask.sum()) if optimize_stds else 0

    # Parameter vector: [w_0, ..., w_{N-2}, sigma_free_0, ...]
    # Last weight = 1 - sum(others)

    def _unpack(x: np.ndarray):
        w_free = x[: n_scenarios - 1]
        w_last = 1.0 - np.sum(w_free)
        weights = np.append(w_free, w_last)
        stds = fixed_stds.copy()
        if n_free_stds > 0:
            stds[std_free_mask] = x[n_scenarios - 1 :]
        return weights, stds

    def _objective(x: np.ndarray) -> float:
        weights, stds = _unpack(x)
        if np.any(weights < -1e-10) or np.any(stds <= 0):
            return 1e12
        model = _mixture_call_prices(market_strikes, tte, df, means_rate, stds, weights)
        return float(np.sum((model - market_calls) ** 2))

    # Initial guess: equal weights
    x0_w = np.full(n_scenarios - 1, 1.0 / n_scenarios)
    x0_std = fixed_stds[std_free_mask] if n_free_stds > 0 else np.array([])
    x0 = np.concatenate([x0_w, x0_std])

    # Bounds
    bounds_w = [(0.0, 1.0)] * (n_scenarios - 1)
    bounds_std = [(0.001, 2.0)] * n_free_stds
    bounds = bounds_w + bounds_std

    # Constraints
    constraints = [
        # Last weight >= 0
        {"type": "ineq", "fun": lambda x: 1.0 - np.sum(x[: n_scenarios - 1])},
        # Forward recovery: sum(w_j * mu_j) = forward_rate
        {
            "type": "eq",
            "fun": lambda x: float(np.dot(_unpack(x)[0], means_rate) - fwd_rate),
        },
    ]

    result = minimize(
        _objective,
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 5000, "ftol": 1e-14},
    )

    warnings: List[str] = []
    if not result.success:
        warnings.append(
            f"GM optimizer failed to converge: {result.message}"
        )

    opt_weights, opt_stds = _unpack(result.x)
    # Clean up: floor small negatives, renormalize
    opt_weights = np.maximum(opt_weights, 0.0)
    total_w = opt_weights.sum()
    if total_w > 1e-10:
        opt_weights = opt_weights / total_w

    # Fit quality
    model_calls = _mixture_call_prices(market_strikes, tte, df, means_rate, opt_stds, opt_weights)
    rmse = float(np.sqrt(np.mean((model_calls - market_calls) ** 2)))
    max_err = float(np.max(np.abs(model_calls - market_calls)))

    if rmse > rmse_warn_threshold:
        warnings.append(
            f"GM fit quality poor: RMSE={rmse:.4e} > {rmse_warn_threshold:.0e}"
        )

    # Build composite density on fine grid (rate space)
    rate_min = float(means_rate.min() - 4.0 * opt_stds.max())
    rate_max = float(means_rate.max() + 4.0 * opt_stds.max())
    rate_grid = np.linspace(rate_min, rate_max, grid_points)

    component_densities = np.zeros((n_scenarios, grid_points))
    composite_density = np.zeros(grid_points)
    for j in range(n_scenarios):
        component_densities[j] = norm.pdf(rate_grid, loc=means_rate[j], scale=opt_stds[j])
        composite_density += opt_weights[j] * component_densities[j]

    # CDF
    composite_cdf = np.zeros(grid_points)
    composite_cdf[1:] = cumulative_trapezoid(composite_density, rate_grid)
    if composite_cdf[-1] > 0:
        composite_cdf /= composite_cdf[-1]

    return GaussianMixtureResult(
        input=rnd_input,
        scenarios=tuple(scenarios),
        weights=opt_weights,
        fitted_std_rates=opt_stds,
        strike_grid_rate=rate_grid,
        composite_density=composite_density,
        composite_cdf=composite_cdf,
        rmse_price=rmse,
        max_abs_error_price=max_err,
        optimization_success=result.success,
        component_densities=component_densities,
        warnings=tuple(warnings),
    )
