"""Bridge between STIRFutureOptionSABRSmile and RND extraction inputs."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, List, Optional, Tuple

import numpy as np

from RVUtils.ImpliedDistribution._bachelier import bachelier_call_prices_vectorized, put_to_call_parity
from RVUtils.ImpliedDistribution._types import RNDInput

if TYPE_CHECKING:
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionSABRSmile


def smile_to_rnd_input(
    smile: "STIRFutureOptionSABRSmile",
    *,
    discount_factor: Optional[float] = None,
    use_sabr_vols: bool = True,
    sabr_extrapolation: bool = False,
    sabr_rate_floor: float = 0.0,
    sabr_rate_ceiling_nstdev: float = 6.0,
    sabr_n_strikes: int = 200,
    raw_market_open_interest_min: Optional[float] = None,
    raw_market_otm_only: bool = False,
    min_strikes: int = 6,
    allow_sabr_fallback: bool = True,
) -> RNDInput:
    """Convert a STIRFutureOptionSABRSmile to RNDInput for density extraction.

    Parameters
    ----------
    smile : STIRFutureOptionSABRSmile
        Calibrated SABR smile from fetch_sabr_smile().
    discount_factor : float, optional
        Discount factor from valuation to option expiry. CME SR3/SOFR options
        are premium-paid-up-front (equity-style, NOT daily-margined), so quoted
        premiums are discounted expectations and every downstream extractor
        divides by this to recover undiscounted values.

        When None, the default depends on ``use_sabr_vols``: the SABR branch
        prices its own premiums via Bachelier and uses df=1.0 (undiscounted in,
        undiscounted out); the raw-market branch takes the median per-point
        discount factor off the smile, because those premiums are real quotes
        and are genuinely discounted. Either way the extracted moments are
        df-invariant, so this coupling does not change results.
    use_sabr_vols : bool
        If True (default), evaluate the calibrated SABR model at all listed
        strikes for a smooth vol surface. If False, use raw market vols from
        smile.points (noisier but unfiltered).
    sabr_extrapolation : bool
        If True (and use_sabr_vols is True), extend the strike grid beyond
        observed strikes using SABR extrapolation to capture the full tail of
        the distribution down to the zero lower bound and up to a generous
        upper rate bound.
    sabr_rate_floor : float
        Lower bound in rate space (%) for SABR extrapolation. Defaults to 0.0
        (zero lower bound).
    sabr_rate_ceiling_nstdev : float
        Number of ATM normal vol standard deviations above the forward rate
        for the upper bound. Defaults to 6.0.
    sabr_n_strikes : int
        Number of strikes in the SABR-extrapolated grid. Defaults to 200.
    raw_market_open_interest_min : float, optional
        When ``use_sabr_vols=False``, drop smile points with lower open
        interest. Points without open-interest metadata are also dropped.
    raw_market_otm_only : bool
        When ``use_sabr_vols=False``, keep only at- or out-of-the-money calls
        and puts before converting puts into equivalent call premiums.
    min_strikes : int
        Minimum surviving strikes on the raw-market path. Matches the ``>= 6 OTM legs``
        gate the MDP applies on its ``jpm_method=True`` branch, which a smile fetched
        with ``strike_offsets_bps="listed"`` never passes through.
    allow_sabr_fallback : bool
        When fewer than ``min_strikes`` survive, fall back to evaluating the calibrated
        SABR model at the listed strikes (recording a warning) instead of raising. The
        fallback silently changes the method from observed premiums to a model density,
        so callers that need the JPM method should pass ``False``.
    """
    prep_warnings: List[str] = []
    params = smile.params
    fwd = float(params.forward_price)
    tte = float(params.time_to_expiry)
    df = discount_factor if discount_factor is not None else 1.0
    # Applies on the SABR path too: leaving df=1.0 there made a flag documented as
    # controlling vol smoothing silently change the BKM moment scale as well.
    if discount_factor is None:
        point_dfs = []
        for pt in smile.points:
            pt_df = getattr(pt, "discount_factor", None)
            if pt_df is None:
                continue
            try:
                pt_df_f = float(pt_df)
            except (TypeError, ValueError):
                continue
            if math.isfinite(pt_df_f) and pt_df_f > 0.0:
                point_dfs.append(pt_df_f)
        if point_dfs:
            df = float(np.median(np.asarray(point_dfs, dtype=float)))

    if use_sabr_vols:
        if sabr_extrapolation:
            # Compute ATM normal vol to determine the rate range
            atm_vol_price = float(
                smile.normal_vol(fwd, strike_space="price", vol_units="price")
            )
            # Normal vol in price space ≡ vol in rate space (price = 100 - rate)
            stdev_rate = atm_vol_price * math.sqrt(max(tte, 1e-6))

            fwd_rate = float(params.forward_rate)
            rate_ceiling = fwd_rate + sabr_rate_ceiling_nstdev * stdev_rate
            rate_floor_eff = max(sabr_rate_floor, -0.5)

            # Convert to price space (rate = 100 - price)
            price_min = 100.0 - rate_ceiling
            price_max = 100.0 - rate_floor_eff

            strikes = np.linspace(price_min, price_max, sabr_n_strikes)
        else:
            # Use only observed/listed strikes
            all_strikes = sorted(
                set(float(pt.strike_price) for pt in smile.points)
            )
            strikes = np.array(all_strikes, dtype=float)

        vols = np.asarray(
            smile.normal_vol(strikes, strike_space="price", vol_units="price"),
            dtype=float,
        )
        # Floor vols to handle SABR edge cases at extreme strikes
        vols = np.maximum(vols, 1e-8)
    else:
        # Use observed premiums when the smile carries them; otherwise fall
        # back to raw market vols. OTM puts are converted into equivalent call
        # premiums via put-call parity, matching JPM Appendix A.
        strike_map: dict[float, tuple[Optional[float], Optional[float], bool, bool]] = {}
        for pt in smile.points:
            k = float(pt.strike_price)
            right = str(pt.right).upper()
            if right not in {"C", "P"}:
                continue
            is_otm = (right == "C" and k >= fwd) or (right == "P" and k <= fwd)
            if raw_market_otm_only and not is_otm:
                continue

            if raw_market_open_interest_min is not None:
                oi = getattr(pt, "open_interest", None)
                if oi is None:
                    continue
                try:
                    oi_f = float(oi)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(oi_f) or oi_f < float(raw_market_open_interest_min):
                    continue

            market_price: Optional[float] = None
            raw_price = getattr(pt, "market_price", None)
            if raw_price is not None:
                try:
                    price_f = float(raw_price)
                except (TypeError, ValueError):
                    price_f = float("nan")
                if math.isfinite(price_f) and price_f > 0.0:
                    pt_df = getattr(pt, "discount_factor", None)
                    try:
                        pt_df_f = float(pt_df) if pt_df is not None else float(df)
                    except (TypeError, ValueError):
                        pt_df_f = float(df)
                    if not math.isfinite(pt_df_f) or pt_df_f <= 0.0:
                        pt_df_f = float(df)
                    market_price = (
                        price_f
                        if right == "C"
                        else put_to_call_parity(price_f, k, fwd, pt_df_f)
                    )

            vol: Optional[float] = None
            try:
                v = float(pt.iv_normal_price)
            except (TypeError, ValueError):
                v = float("nan")
            if math.isfinite(v) and v > 0.0:
                vol = v

            if market_price is None and vol is None:
                continue

            existing = strike_map.get(k)
            candidate = (market_price, vol, is_otm, market_price is not None)
            if existing is None:
                strike_map[k] = candidate
                continue
            existing_rank = (existing[2], existing[3])
            candidate_rank = (candidate[2], candidate[3])
            if candidate_rank >= existing_rank:
                strike_map[k] = candidate

        sorted_items = sorted(strike_map.items())
        strikes = np.array([x[0] for x in sorted_items], dtype=float)
        call_values = []
        vols = []
        needs_vol_pricing = False
        for _, (call_price, vol, _, _) in sorted_items:
            call_values.append(float(call_price) if call_price is not None else float("nan"))
            vols.append(float(vol) if vol is not None else float("nan"))
            needs_vol_pricing = needs_vol_pricing or call_price is None
        call_premiums = np.array(call_values, dtype=float)
        if needs_vol_pricing:
            vols_arr = np.array(vols, dtype=float)
            vol_prices = bachelier_call_prices_vectorized(strikes, fwd, vols_arr, tte, df)
            call_premiums = np.where(np.isfinite(call_premiums), call_premiums, vol_prices)

        # Adequacy of what survived the OTM/OI filter. The upstream >= 6 OTM leg guard
        # only exists on the jpm_method=True branch of the MDP; a smile fetched with
        # strike_offsets_bps="listed" never touches it, so this is the only gate.
        n_below = int(np.sum(strikes < fwd))
        n_above = int(np.sum(strikes > fwd))
        if len(strikes) < min_strikes:
            msg = (
                f"raw market filtering left only {len(strikes)} strikes (need >= {min_strikes}"
                f"); "
            )
            if not allow_sabr_fallback:
                raise ValueError(
                    msg + "set allow_sabr_fallback=True to fall back to SABR vol evaluation, "
                    "or lower raw_market_open_interest_min."
                )
            prep_warnings.append(
                msg + "fell back to SABR vol evaluation at listed strikes, so this is a MODEL "
                "density, not an observed-premium one"
            )
            all_strikes = sorted(set(float(pt.strike_price) for pt in smile.points))
            strikes = np.array(all_strikes, dtype=float)
            vols = np.asarray(
                smile.normal_vol(strikes, strike_space="price", vol_units="price"),
                dtype=float,
            )
            vols = np.fmax(np.nan_to_num(vols, nan=1e-8, posinf=1e-8, neginf=1e-8), 1e-8)
            use_sabr_vols = True
        elif n_below < 2 or n_above < 2:
            prep_warnings.append(
                f"strike set does not bracket the forward evenly ({n_below} below F={fwd:g}, "
                f"{n_above} above); the thin wing is extrapolated and its tail statistics are "
                f"unreliable"
            )

    if use_sabr_vols:
        # Convert all to call premiums via Bachelier
        call_premiums = bachelier_call_prices_vectorized(strikes, fwd, vols, tte, df)

    if use_sabr_vols and sabr_extrapolation:
        source = "sabr_extrapolated"
    elif use_sabr_vols:
        source = "sabr_smile"
    elif raw_market_open_interest_min is not None or raw_market_otm_only:
        source = "market_jpm"
    else:
        source = "market_listed"

    return RNDInput(
        symbol=str(smile.symbol),
        as_of=params.as_of,
        forward_price=fwd,
        forward_rate=float(params.forward_rate),
        time_to_expiry=tte,
        expiry_date=params.expiry_date,
        discount_factor=df,
        strikes_price=strikes,
        call_premiums=call_premiums,
        strike_source=source,
        warnings=tuple(prep_warnings),
    )


def build_ghost_wings(
    strikes: np.ndarray,
    premiums: np.ndarray,
    n_ghost: int = 10,
    extension_bps: float = 5.0,
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Add ghost points on each side, returning any diagnostics raised while doing so.

    JPM approach: 10 points per side, linearly extrapolated, so the fitted RND approaches
    zero outside the observed strike range (a straight line has zero second derivative,
    hence zero density).

    The right wing needs care. Deep-OTM call premiums decay towards zero, so a straight
    line through the last two points eventually crosses zero. Clamping the crossing at
    zero welds a downward ramp onto a flat segment, and ``d2C/dK2`` of that corner is a
    near-delta: the extractor reads it as a spike of probability parked at the ghost
    boundary, i.e. fabricated mass in the lowest-rate bins. Where the ramp would cross,
    this uses the exponential that matches the last premium *and* its slope,
    ``C(K) = C_n * exp(m/C_n * (K - K_n))``, which stays positive, decays monotonically,
    is C1 at the join, and carries only a small decaying density instead of a spike.

    Real SFR wings are usually pinned at the 0.0025 settlement tick (CME Rulebook
    460A01.C), giving a terminal slope of ~0 that never crosses within the ghost reach;
    those inputs take the linear branch and are unchanged.

    Parameters
    ----------
    extension_bps : float
        Spacing between ghost points in price units (bps of price, i.e. 0.01).
        For SFR options 1 strike tick = 0.125 (12.5bp in price).
    """
    warnings: List[str] = []
    if len(strikes) < 2:
        raise ValueError(
            f"add_ghost_points requires at least 2 data points, got {len(strikes)}"
        )
    if n_ghost <= 0:
        return np.asarray(strikes, dtype=float), np.asarray(premiums, dtype=float), warnings

    step = extension_bps / 100.0

    # Left ghost points (lower strikes -> deep ITM calls, higher premiums). The slope here
    # is ~ -DF and premiums are large, so the clamp below is inert in practice.
    left_slope = (premiums[1] - premiums[0]) / (strikes[1] - strikes[0])
    left_strikes = np.array([strikes[0] - (n_ghost - i) * step for i in range(n_ghost)])
    left_premiums = premiums[0] + left_slope * (left_strikes - strikes[0])
    if np.any(left_premiums < 0.0):
        warnings.append(
            "left ghost wing extrapolates to negative premiums; clamped at zero"
        )
    left_premiums = np.maximum(left_premiums, 0.0)

    # Right ghost points (higher strikes -> deep OTM calls, approaching 0)
    right_slope = (premiums[-1] - premiums[-2]) / (strikes[-1] - strikes[-2])
    right_strikes = np.array([strikes[-1] + (i + 1) * step for i in range(n_ghost)])
    reach = float(right_strikes[-1] - strikes[-1])
    last_premium = float(premiums[-1])

    if right_slope > 0.0:
        # Call premiums must be non-increasing in K. A rising terminal slope is a crossed
        # or stale quote; extrapolating it upward would be strictly arbitrage-violating.
        warnings.append(
            f"terminal call slope is positive ({right_slope:+.5f}); right ghost wing held "
            f"flat at {last_premium:.5f} instead of extrapolated"
        )
        right_premiums = np.full(n_ghost, last_premium)
    elif right_slope == 0.0 or last_premium <= 1e-9:
        # Flat wing, or one already at zero: nothing to extrapolate and nothing fabricated.
        right_premiums = last_premium + right_slope * (right_strikes - strikes[-1])
        right_premiums = np.maximum(right_premiums, 0.0)
    else:
        zero_crossing = last_premium / abs(right_slope)
        if zero_crossing >= reach:
            # Linear ramp never reaches zero inside the ghost span: JPM behaviour, exactly.
            right_premiums = last_premium + right_slope * (right_strikes - strikes[-1])
        else:
            right_premiums = last_premium * np.exp(
                (right_slope / last_premium) * (right_strikes - strikes[-1])
            )
            warnings.append(
                f"right ghost wing would cross zero {zero_crossing:.3f} price points out "
                f"(inside the {reach:.3f} ghost reach); used C1 exponential decay instead "
                f"of a zero-clipped ramp"
            )

    all_strikes = np.concatenate([left_strikes, strikes, right_strikes])
    all_premiums = np.concatenate([left_premiums, premiums, right_premiums])

    return all_strikes, all_premiums, warnings


def add_ghost_points(
    strikes: np.ndarray,
    premiums: np.ndarray,
    n_ghost: int = 10,
    extension_bps: float = 5.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Backwards-compatible wrapper around :func:`build_ghost_wings`."""
    ext_strikes, ext_premiums, _ = build_ghost_wings(
        strikes, premiums, n_ghost=n_ghost, extension_bps=extension_bps
    )
    return ext_strikes, ext_premiums
