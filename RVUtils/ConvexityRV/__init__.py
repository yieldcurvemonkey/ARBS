"""Convexity relative-value strategies.

Three strategies, each from a specific research note, sharing one measurement
kernel (``curve_ops``: reprice a package on a shifted / aged curve):

``strat1`` -- **Curve-as-gamma vs swaptions.** JPM, "An option by any other
    name: Sourcing cheap convexity in the long end of the curve" (Younger,
    Sarkar, Salem; 03-Feb-2017). Long-end forward flatteners are an options-like
    payoff; the relative-value question is whether the curve or the swaption is
    the cheaper source of that gamma.

``strat2`` -- **STIR futures convexity vs butterfly.** Citi's STIR convexity
    screen, ported from ED (3M Eurodollar) to SFR (3M SOFR). The pack's
    convexity adjustment against a matched-maturity forward swap, inverted
    through Ho-Lee to an implied vol and compared to realised.

``strat3`` -- **Long convexity that pays theta.** Forward-curve structures
    selected so the position is long gamma *and* carries positively -- the
    "flattener = long vol, steepener = short vol" relationship from the US Rates
    Vol Lab notes, filtered for positive carry-and-roll.

The measurement convention that governs everything here, established
empirically against the engine rather than read off the risk-weight code::

    bpv < 0  =>  FLATTENER  (receive the back leg)  =>  LONG convexity
    bpv > 0  =>  STEEPENER  (pay the back leg)      =>  SHORT convexity
"""

from __future__ import annotations

from RVUtils.ConvexityRV.curve_ops import (
    horizon_handle,
    npv_on_handle,
    package_npv,
    payoff_profile,
    shifted_handle,
)
from RVUtils.ConvexityRV.holee import (
    ho_lee_ca,
    ho_lee_ca_bp,
    implied_vol_from_ca,
    implied_vol_from_ca_bp,
    pack_ca,
    pack_ca_bp,
    pack_time_weight,
)
from RVUtils.ConvexityRV.payoff import (
    breakeven_vol_bp_per_day,
    breakeven_vol_bp_per_year,
    expected_payoff,
    normal_pdf_weights,
)

__all__ = [
    "breakeven_vol_bp_per_day",
    "breakeven_vol_bp_per_year",
    "expected_payoff",
    "ho_lee_ca",
    "ho_lee_ca_bp",
    "horizon_handle",
    "implied_vol_from_ca",
    "implied_vol_from_ca_bp",
    "normal_pdf_weights",
    "npv_on_handle",
    "pack_ca",
    "pack_ca_bp",
    "pack_time_weight",
    "package_npv",
    "payoff_profile",
    "shifted_handle",
]
