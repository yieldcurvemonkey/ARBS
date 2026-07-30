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

from RVUtils.ImpliedDistribution._bachelier import (
    bachelier_call_prices_vectorized,
    bachelier_implied_vols_vectorized,
    bachelier_vega,
)
from RVUtils.ImpliedDistribution._data_prep import build_ghost_wings
from RVUtils.ImpliedDistribution._types import BreedenLitzenbergerResult, RNDInput


def extract_rnd_breeden_litzenberger(
    rnd_input: RNDInput,
    *,
    smoothing_param: float = 1e-4,
    scale_smoothing_by_n: bool = False,
    spline_order: int = 4,
    n_ghost_points: int = 10,
    ghost_extension_bps: float = 5.0,
    bin_width_bps: float = 25.0,
    grid_points: int = 2000,
    rate_floor: Optional[float] = 0.0,
    fit_space: str = "price",
    vol_smoothing_param: Optional[float] = None,
    anchor_wings: bool = False,
    ghost_anchor_weight: float = 100.0,
) -> BreedenLitzenbergerResult:
    """Extract risk-neutral density via Breeden-Litzenberger with smoothing spline.

    Parameters
    ----------
    rnd_input : RNDInput
        Market data (strikes in price space, call premiums).
    smoothing_param : float
        Spline smoothing factor. JPM uses 10^-4.
    scale_smoothing_by_n : bool
        If True, multiply ``smoothing_param`` by the number of fitted points
        before passing it to SciPy. Defaults to False to match Appendix A's
        literal smoothing parameter.
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
    strikes = np.asarray(rnd_input.strikes_price, dtype=float)
    premiums = np.asarray(rnd_input.call_premiums, dtype=float)
    df = rnd_input.discount_factor

    warnings: List[str] = list(getattr(rnd_input, "warnings", ()) or ())

    # Near expiry the premium grid collapses onto the 0.0025 settlement tick, the SABR
    # fit degenerates, and second-differencing tick noise across a shrinking strike
    # spacing dominates everything. The module docstring already warns callers off this
    # regime; say so in the result rather than only in prose.
    tte = float(getattr(rnd_input, "time_to_expiry", float("nan")))
    if math.isfinite(tte) and tte < 0.04:
        warnings.append(
            f"time to expiry {tte * 365.0:.1f} calendar days is inside the ~10 business day "
            f"floor for this method; the recovered density is dominated by tick noise"
        )

    k = int(max(2, min(spline_order, 5)))
    if k != spline_order:
        warnings.append(f"spline_order {spline_order} clamped to {k} (need 2 <= k <= 5 for d2/dK2)")

    finite = np.isfinite(strikes) & np.isfinite(premiums)
    if not finite.all():
        warnings.append(f"dropped {int((~finite).sum())} strike(s) with non-finite strike or premium")
        strikes, premiums = strikes[finite], premiums[finite]

    order = np.argsort(strikes, kind="stable")
    if not np.array_equal(order, np.arange(strikes.size)):
        strikes, premiums = strikes[order], premiums[order]
    dup = np.concatenate([[True], np.diff(strikes) > 0.0])
    if not dup.all():
        warnings.append(f"dropped {int((~dup).sum())} duplicate strike(s)")
        strikes, premiums = strikes[dup], premiums[dup]

    # A degree-k spline needs more than k points; with ghosts off, the raw set must carry it.
    min_points = 2 if n_ghost_points > 0 else k + 1
    if len(strikes) < min_points:
        source_hint = getattr(rnd_input, "strike_source", "unknown")
        raise ValueError(
            f"Breeden-Litzenberger requires at least {min_points} strike points for "
            f"spline_order={k} and n_ghost_points={n_ghost_points}, got {len(strikes)} "
            f"(source={source_hint!r}). If using raw market data with OI/OTM filtering, "
            f"try lowering raw_market_open_interest_min or using use_sabr_vols=True."
        )

    # 1. Add ghost points
    fit_space = str(fit_space).strip().lower()
    if fit_space not in {"price", "vol"}:
        raise ValueError(f"fit_space must be 'price' or 'vol', got {fit_space!r}")

    if fit_space == "vol":
        return _extract_rnd_via_vol_space(
            rnd_input=rnd_input,
            strikes=strikes,
            premiums=premiums,
            df=df,
            warnings=warnings,
            k=k,
            smoothing_param=(
                vol_smoothing_param if vol_smoothing_param is not None else 1.0
            ),
            n_ghost_points=n_ghost_points,
            ghost_extension_bps=ghost_extension_bps,
            bin_width_bps=bin_width_bps,
            grid_points=grid_points,
            rate_floor=rate_floor,
        )

    ext_strikes, ext_premiums, ghost_warnings = build_ghost_wings(
        strikes,
        premiums,
        n_ghost=n_ghost_points,
        extension_bps=ghost_extension_bps,
    )
    warnings.extend(ghost_warnings)

    # 2. Fit smoothing spline C(K)
    # s parameter: UnivariateSpline interprets s as the total sum-of-squares residual
    # budget in the units of the fitted values, so it is NOT scale-invariant. Premiums
    # here are IMM Index points and CME settles all SOFR options on a 0.0025 tick
    # (Rulebook 460A01.C), so the literal Appendix A value of 1e-4 is, on a ~70-point
    # ladder, about a half-tick RMS residual per point: n*(tick/2)^2 = 71*1.5625e-6
    # = 1.1e-4. That is why the literal number transplants sensibly here. It does not
    # scale with n, though - see ``scale_smoothing_by_n``.
    n = len(ext_strikes)
    if n <= k:
        raise ValueError(
            f"Breeden-Litzenberger needs more than spline_order={k} fitted points, got {n}"
        )
    spline_s = smoothing_param * n if scale_smoothing_by_n else smoothing_param

    # Appendix A is explicit that the ghost points exist so "the fitted RND will approach
    # zero outside of the strike range spanned by the data, avoiding unphysical behavior
    # in the wings" - a linear premium ramp has zero second derivative, so the density
    # over the ghost region should vanish. Fitting the ghosts with the same weight as the
    # quotes does not deliver that: scipy spends its residual budget wherever it likes,
    # and drifting even half a settlement tick off the ramp bends the wings enough to
    # manufacture real probability mass. Measured on a 19-strike SFRZ26 delta smile,
    # 4.08% of the total density ended up outside the observed strike range.
    #
    # The asymmetry that fixes it: observed premiums carry +/- half a tick of settlement
    # noise, but the ghost ramp is *constructed* and carries none. It is a constraint, not
    # an observation, and weighting it accordingly pins the wings flat - the same case
    # drops to 0.08%. scipy minimises sum((w*(f-y))^2) <= s, so leaving the observed
    # weights at 1 keeps `smoothing_param` meaning exactly what it meant before.
    spline_weights = None
    if anchor_wings and n_ghost_points > 0 and ghost_anchor_weight > 0:
        spline_weights = np.ones(n, dtype=float)
        spline_weights[:n_ghost_points] = float(ghost_anchor_weight)
        spline_weights[n - n_ghost_points:] = float(ghost_anchor_weight)

    spline = UnivariateSpline(
        ext_strikes, ext_premiums, k=k, s=spline_s, w=spline_weights
    )

    # 3. Fine grid for evaluation
    grid_min = float(ext_strikes[0])
    grid_max = float(ext_strikes[-1])
    strike_grid = np.linspace(grid_min, grid_max, grid_points)

    # 3b. No-arbitrage shape of the FITTED curve. A call curve must be non-increasing in
    # K with slope no steeper than -DF, and convex. Violations are what turn into
    # negative density below; reporting them names the cause rather than the symptom.
    d1 = spline(strike_grid, nu=1)
    max_slope = float(np.max(d1))
    min_slope = float(np.min(d1))
    if max_slope > 1e-6:
        warnings.append(f"fitted C(K) is non-monotone: max dC/dK = {max_slope:+.5f} > 0")
    if min_slope < -float(df) - 1e-6:
        warnings.append(
            f"fitted C(K) breaches the delta bound: min dC/dK = {min_slope:+.5f} < -DF = {-float(df):.5f}"
        )

    # 4. 2nd derivative → RND in price space
    d2c_dk2 = spline(strike_grid, nu=2)
    rnd_price = d2c_dk2 / df

    return _finalize_bl_result(
        rnd_input=rnd_input,
        strikes=strikes,
        strike_grid=strike_grid,
        rnd_price=rnd_price,
        warnings=warnings,
        spline_residual=float(np.sqrt(np.mean((spline(strikes) - premiums) ** 2))),
        smoothing_param=smoothing_param,
        n_ghost_points=n_ghost_points,
        bin_width_bps=bin_width_bps,
        rate_floor=rate_floor,
    )


def _finalize_bl_result(
    *,
    rnd_input: RNDInput,
    strikes: np.ndarray,
    strike_grid: np.ndarray,
    rnd_price: np.ndarray,
    warnings: List[str],
    spline_residual: float,
    smoothing_param: float,
    n_ghost_points: int,
    bin_width_bps: float,
    rate_floor: Optional[float],
) -> BreedenLitzenbergerResult:
    """Shared tail: clip, normalise, flip to rate space, bin, and summarise.

    Both the price-space and vol-space fits produce an unnormalised density on a
    price-strike grid; everything downstream of that is identical, so it lives here
    rather than being duplicated (and drifting) between the two.
    """
    # Detect negative density before clipping
    neg_mass_raw = float(trapezoid(np.abs(np.minimum(rnd_price, 0.0)), strike_grid))
    pos_mass_raw = float(trapezoid(np.maximum(rnd_price, 0.0), strike_grid))
    if neg_mass_raw > 0 and (pos_mass_raw + neg_mass_raw) > 0:
        frac = neg_mass_raw / (pos_mass_raw + neg_mass_raw)
        if frac > 1e-4:  # ignore numerical noise below 0.01%
            warnings.append(
                f"negative density mass clipped ({frac * 100:.2f}% of total)"
            )

    # Floor at zero (numerical artifacts at tails)
    rnd_price = np.maximum(rnd_price, 0.0)

    # 5. Normalize. Keep the pre-normalization mass: it is the only direct read on fit
    # quality that survives the rescale. Below 1 is legitimate for a truncated smile
    # (it is P(Kmin < S_T < Kmax)); above 1 can only come from butterfly arbitrage
    # surviving the clip.
    total_mass = float(trapezoid(rnd_price, strike_grid))
    pre_normalization_mass = total_mass
    if total_mass > 1e-10:
        rnd_price = rnd_price / total_mass
    else:
        warnings.append(
            f"degenerate fit: total density mass {total_mass:.3e} is ~0; the returned "
            f"density, moments and bin probabilities are meaningless"
        )
    if total_mass > 1.01:
        warnings.append(
            f"pre-normalization mass {total_mass:.4f} exceeds 1: butterfly arbitrage in the "
            f"fitted call curve"
        )

    # Fraction of mass carried by the synthetic ghost wings rather than by observed strikes.
    if total_mass > 1e-10:
        obs = (strike_grid >= strikes[0]) & (strike_grid <= strikes[-1])
        observed_mass = float(trapezoid(rnd_price[obs], strike_grid[obs])) if obs.sum() > 1 else 0.0
        ghost_mass_fraction = max(0.0, 1.0 - observed_mass)
    else:
        ghost_mass_fraction = float("nan")
    # 2%, not 5%: the SFRZ26 delta-mode case put 4.08% of the density outside the
    # observed strikes and stayed silent, which is exactly the case a user needs told.
    if math.isfinite(ghost_mass_fraction) and ghost_mass_fraction > 0.02:
        warnings.append(
            f"{ghost_mass_fraction * 100:.1f}% of density mass lies outside the observed "
            f"strike range; std_rate/skewness/kurtosis and the extreme percentiles are "
            f"extrapolation artefacts"
        )

    # 6. Convert to rate space (rate = 100 - price)
    # strike_grid is ascending in price → descending in rate, so flip
    rate_grid = (100.0 - strike_grid)[::-1]
    rnd_rate = rnd_price[::-1]

    # 6b. Truncate at rate floor (e.g. 0% for SOFR — negative rates impossible)
    if rate_floor is not None:
        pre_mass = float(trapezoid(rnd_rate, rate_grid))
        floor_mask = rate_grid >= rate_floor
        rate_grid = rate_grid[floor_mask]
        rnd_rate = rnd_rate[floor_mask]
        # Renormalize so density integrates to 1.0
        post_mass = float(trapezoid(rnd_rate, rate_grid)) if len(rate_grid) > 1 else 0.0
        if pre_mass > 1e-10:
            truncated_frac = max(0.0, (pre_mass - post_mass) / pre_mass)
            if truncated_frac > 1e-4:
                # rate_floor is already a percentage (0.0 == 0%), so :.2% would
                # multiply by 100 again and print a 2% floor as "200.00%".
                warnings.append(
                    f"rate floor at {rate_floor:.2f}% truncated {truncated_frac * 100:.2f}% of mass"
                )
        if post_mass > 1e-10:
            rnd_rate = rnd_rate / post_mass
        elif pre_mass > 1e-10:
            warnings.append(
                f"rate floor at {rate_floor:.2f}% truncated the entire density; the returned "
                f"distribution is degenerate"
            )

    # 7. CDF via trapezoidal integration
    dx = np.diff(rate_grid)
    cdf = np.zeros_like(rate_grid)
    cdf[1:] = np.cumsum(0.5 * (rnd_rate[:-1] + rnd_rate[1:]) * dx)
    if cdf[-1] > 1e-10:
        cdf = cdf / cdf[-1]
    else:
        warnings.append(
            "degenerate CDF: total probability is ~0, so percentiles and bin probabilities "
            "are meaningless"
        )

    # 8. Bin into scenario probabilities.
    #
    # Bin mass is read off the CDF rather than re-integrated over the grid nodes that
    # happen to fall inside each bin. Integrating `rnd_rate[mask]` over `rate_grid[mask]`
    # silently discards the two partial intervals at each bin's edges, so every bin came
    # out low by exactly one grid spacing's worth of mass and the vector summed to
    # 1 - dx/bin_width (0.988 at 25bp bins on a 2000-point grid) instead of 1. It also
    # returned exactly 0.0 for any bin narrow enough to contain a single node, because
    # `trapezoid` of a one-element array is 0.
    if bin_width_bps <= 0.0:
        raise ValueError(f"bin_width_bps must be positive, got {bin_width_bps!r}")
    bin_width = bin_width_bps / 100.0
    fwd_rate = rnd_input.forward_rate

    # Edges land on exact multiples of the bin width either side of the forward, so at
    # 25bp the boundaries sit on the FOMC target-range boundaries and the midpoints on
    # the target midpoints.
    center_bin = round(fwd_rate / bin_width) * bin_width
    first_edge = center_bin - math.ceil(max(0.0, center_bin - rate_grid[0]) / bin_width) * bin_width
    n_bins = int(math.ceil((rate_grid[-1] - first_edge) / bin_width))
    n_bins = max(n_bins, 1)
    bin_edges = first_edge + bin_width * np.arange(n_bins + 1)

    # np.interp clamps outside the grid, which is exactly right: there is no mass there.
    edge_cdf = np.interp(bin_edges, rate_grid, cdf)
    bin_probabilities = np.diff(edge_cdf)
    bin_labels: List[str] = [
        f"{(bin_edges[i] + bin_edges[i + 1]) / 2.0:.3f}" for i in range(len(bin_edges) - 1)
    ]

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

    # Forward tie-out. Under Q the SR3 future is a martingale, so E[100 - P_T] must equal
    # 100 - F. Any material residual means the fit or the wings are wrong, and it is the
    # single cheapest check on the whole pipeline.
    forward_residual_bp = (mean_rate - float(rnd_input.forward_rate)) * 100.0
    if math.isfinite(forward_residual_bp) and abs(forward_residual_bp) > 2.0:
        warnings.append(
            f"RND mean {mean_rate:.4f}% misses the forward {float(rnd_input.forward_rate):.4f}% "
            f"by {forward_residual_bp:+.2f}bp (martingale tie-out)"
        )


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
        warnings=tuple(warnings),
        pre_normalization_mass=pre_normalization_mass,
        forward_residual_bp=forward_residual_bp,
        ghost_mass_fraction=ghost_mass_fraction,
    )



def _extract_rnd_via_vol_space(
    *,
    rnd_input: RNDInput,
    strikes: np.ndarray,
    premiums: np.ndarray,
    df: float,
    warnings: List[str],
    k: int,
    smoothing_param: float,
    n_ghost_points: int,
    ghost_extension_bps: float,
    bin_width_bps: float,
    grid_points: int,
    rate_floor: Optional[float],
) -> BreedenLitzenbergerResult:
    """Breeden-Litzenberger with the smoothing done in implied-vol space.

    Same estimator, better-conditioned coordinates. Fitting ``C(K)`` directly and
    differentiating twice is what the JPM appendix specifies, but the call curve spans
    orders of magnitude between the money and the wings while its curvature - the thing we
    actually want - is a small residual on top of a near-linear ramp. A spline through
    that has almost no leverage in the wings, so wherever the observed strikes thin out it
    is free to invent curvature, and the second derivative turns that into probability
    mass in bins where no option ever traded.

    Implied vol is the natural coordinate: it is O(1), smooth, and close to linear in the
    wings, so extrapolating it is stable and repricing turns it back into a call curve
    that is convex by construction. This is the Shimko / Bliss-Panigirtzoglou approach.

    Steps: invert each observed premium to a Bachelier normal vol, extend the smile
    linearly in vol space, fit a smoothing spline to vol(K), reprice on the fine grid, and
    take a second difference of the repriced curve. The repriced curve is analytically
    smooth, so a plain central difference is accurate and introduces no further spline.
    """
    fwd = float(rnd_input.forward_price)
    tte = float(rnd_input.time_to_expiry)

    vols = bachelier_implied_vols_vectorized(premiums, strikes, fwd, tte, df)
    usable = np.isfinite(vols) & (vols > 0.0)
    n_dropped = int((~usable).sum())
    if n_dropped:
        warnings.append(
            f"vol-space fit: {n_dropped} of {len(strikes)} quotes could not be inverted to "
            f"an implied vol (premium at or below intrinsic - typically a wing pinned at "
            f"the settlement tick) and were dropped"
        )
    k_obs, v_obs = strikes[usable], vols[usable]
    if len(k_obs) < max(4, k + 1):
        raise ValueError(
            f"vol-space fit needs at least {max(4, k + 1)} invertible quotes, got {len(k_obs)}. "
            f"Use fit_space='price' or widen the strike set."
        )

    # Extend the smile linearly in vol space. Unlike a price ramp this cannot cross zero
    # or manufacture a kink: vol stays positive and the wings inherit the observed slope.
    step = ghost_extension_bps / 100.0
    if n_ghost_points > 0:
        left_slope = (v_obs[1] - v_obs[0]) / (k_obs[1] - k_obs[0])
        right_slope = (v_obs[-1] - v_obs[-2]) / (k_obs[-1] - k_obs[-2])
        left_k = np.array([k_obs[0] - (n_ghost_points - i) * step for i in range(n_ghost_points)])
        right_k = np.array([k_obs[-1] + (i + 1) * step for i in range(n_ghost_points)])
        floor_vol = 1e-4
        left_v = np.maximum(v_obs[0] + left_slope * (left_k - k_obs[0]), floor_vol)
        right_v = np.maximum(v_obs[-1] + right_slope * (right_k - k_obs[-1]), floor_vol)
        fit_k = np.concatenate([left_k, k_obs, right_k])
        fit_v = np.concatenate([left_v, v_obs, right_v])
    else:
        fit_k, fit_v = k_obs, v_obs

    # Weight each point by how precisely its vol is actually determined. CME settles on a
    # 0.0025 tick (Rulebook 460A01.C), so a quote pins its vol only to within
    # (tick/2)/vega - and vega collapses in the wings, where a single tick can move the
    # implied vol by tens of bp. Fitting those as if they were precise is what makes a
    # near-interpolating vol spline reprice into a violently non-convex call curve.
    #
    # scipy minimises sum(w_i * (y_i - f(x_i))^2) <= s, so with w_i = 1/tol_i and s = n
    # this becomes "about one tolerance of error per point" - a chi-square criterion that
    # automatically trusts the money and distrusts the wings. `smoothing_param` scales it.
    tick = 0.0025
    vega = bachelier_vega(fit_k, fwd, np.maximum(fit_v, 1e-8), tte, df)
    tol = np.maximum((tick / 2.0) / np.maximum(vega, 1e-12), 1e-6)
    weights = 1.0 / tol
    n_fit = len(fit_k)
    spline_s = float(smoothing_param) * n_fit

    vol_spline = UnivariateSpline(
        fit_k, fit_v, k=min(k, n_fit - 1), s=spline_s, w=weights
    )

    strike_grid = np.linspace(float(fit_k[0]), float(fit_k[-1]), grid_points)
    grid_vols = np.maximum(vol_spline(strike_grid), 1e-8)
    call_grid = bachelier_call_prices_vectorized(strike_grid, fwd, grid_vols, tte, df)

    # Second derivative by central difference on a uniform grid. The repriced curve is
    # analytically smooth, so this is stable - no second spline, no extra smoothing.
    h = float(strike_grid[1] - strike_grid[0])
    d2c = np.empty_like(call_grid)
    d2c[1:-1] = (call_grid[2:] - 2.0 * call_grid[1:-1] + call_grid[:-2]) / (h * h)
    d2c[0], d2c[-1] = d2c[1], d2c[-2]
    rnd_price = d2c / df

    d1 = np.gradient(call_grid, h)
    if float(np.max(d1)) > 1e-6:
        warnings.append(f"fitted C(K) is non-monotone: max dC/dK = {float(np.max(d1)):+.5f} > 0")
    if float(np.min(d1)) < -float(df) - 1e-6:
        warnings.append(
            f"fitted C(K) breaches the delta bound: min dC/dK = {float(np.min(d1)):+.5f} "
            f"< -DF = {-float(df):.5f}"
        )

    repriced_obs = bachelier_call_prices_vectorized(
        k_obs, fwd, np.maximum(vol_spline(k_obs), 1e-8), tte, df
    )
    spline_residual = float(np.sqrt(np.mean((repriced_obs - premiums[usable]) ** 2)))

    return _finalize_bl_result(
        rnd_input=rnd_input,
        strikes=k_obs,
        strike_grid=strike_grid,
        rnd_price=rnd_price,
        warnings=warnings,
        spline_residual=spline_residual,
        smoothing_param=smoothing_param,
        n_ghost_points=n_ghost_points,
        bin_width_bps=bin_width_bps,
        rate_floor=rate_floor,
    )
