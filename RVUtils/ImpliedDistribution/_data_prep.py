"""Bridge between STIRFutureOptionSABRSmile and RND extraction inputs."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional, Tuple

import numpy as np

from RVUtils.ImpliedDistribution._bachelier import bachelier_call_prices_vectorized
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
) -> RNDInput:
    """Convert a STIRFutureOptionSABRSmile to RNDInput for density extraction.

    Parameters
    ----------
    smile : STIRFutureOptionSABRSmile
        Calibrated SABR smile from fetch_sabr_smile().
    discount_factor : float, optional
        Defaults to 1.0 (futures options are daily-margined).
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
    """
    params = smile.params
    fwd = float(params.forward_price)
    tte = float(params.time_to_expiry)
    df = discount_factor if discount_factor is not None else 1.0

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
        # Use raw market vols, keeping OTM side per strike
        strike_vol_map: dict[float, float] = {}
        for pt in smile.points:
            k = float(pt.strike_price)
            v = float(pt.iv_normal_price)
            if math.isnan(v) or v <= 0:
                continue
            is_otm = (pt.right == "C" and k >= fwd) or (pt.right == "P" and k <= fwd)
            if k not in strike_vol_map or is_otm:
                strike_vol_map[k] = v
        sorted_items = sorted(strike_vol_map.items())
        strikes = np.array([x[0] for x in sorted_items], dtype=float)
        vols = np.array([x[1] for x in sorted_items], dtype=float)

    # Convert all to call premiums via Bachelier
    call_premiums = bachelier_call_prices_vectorized(strikes, fwd, vols, tte, df)

    if use_sabr_vols and sabr_extrapolation:
        source = "sabr_extrapolated"
    elif use_sabr_vols:
        source = "sabr_smile"
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
    )


def add_ghost_points(
    strikes: np.ndarray,
    premiums: np.ndarray,
    n_ghost: int = 10,
    extension_bps: float = 5.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Add ghost points on each side via linear extrapolation.

    JPM approach: 10 points per side, linearly extrapolated. This ensures
    the fitted RND approaches zero outside the observed strike range.

    Parameters
    ----------
    extension_bps : float
        Spacing between ghost points in price units (bps of price, i.e. 0.01).
        For SFR options 1 strike tick = 0.125 (12.5bp in price).
    """
    step = extension_bps / 100.0

    # Left ghost points (lower strikes → deep ITM calls, higher premiums)
    left_slope = (premiums[1] - premiums[0]) / (strikes[1] - strikes[0])
    left_strikes = np.array([strikes[0] - (n_ghost - i) * step for i in range(n_ghost)])
    left_premiums = premiums[0] + left_slope * (left_strikes - strikes[0])
    left_premiums = np.maximum(left_premiums, 0.0)

    # Right ghost points (higher strikes → deep OTM calls, approaching 0)
    right_slope = (premiums[-1] - premiums[-2]) / (strikes[-1] - strikes[-2])
    right_strikes = np.array([strikes[-1] + (i + 1) * step for i in range(n_ghost)])
    right_premiums = premiums[-1] + right_slope * (right_strikes - strikes[-1])
    right_premiums = np.maximum(right_premiums, 0.0)

    all_strikes = np.concatenate([left_strikes, strikes, right_strikes])
    all_premiums = np.concatenate([left_premiums, premiums, right_premiums])

    return all_strikes, all_premiums
