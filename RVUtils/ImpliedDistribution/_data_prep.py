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
    """
    params = smile.params
    fwd = float(params.forward_price)
    tte = float(params.time_to_expiry)
    df = discount_factor if discount_factor is not None else 1.0

    if use_sabr_vols:
        # Use smile.normal_vol() which evaluates the calibrated SABR model
        all_strikes = sorted(set(float(pt.strike_price) for pt in smile.points))
        strikes = np.array(all_strikes, dtype=float)
        vols = np.asarray(smile.normal_vol(strikes, strike_space="price", vol_units="price"), dtype=float)
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
        strike_source="sabr_smile" if use_sabr_vols else "market_listed",
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
