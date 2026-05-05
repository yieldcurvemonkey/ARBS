"""Static-curve aged carry for the STIR Options Asymmetric Screener.

For each candidate, age the structure by N days (assume static curve and
SABR surface) and compute the change in net premium. Used by spec §2.7
(carry-to-risk gate) and §4 (composite scoring).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from RVUtils.ImpliedDistribution._bachelier import (
    bachelier_call_prices_vectorized,
)
from RVUtils.STIRAsymmetricScreener._types import OptionLeg


@dataclass(frozen=True)
class CarryRecord:
    carry_1w: float
    carry_1m: float
    carry_3m: float
    carry_to_expiry: float
    carry_to_premium_ratio: float


def _structure_premium_ticks(
    *,
    legs: Sequence[OptionLeg],
    smile,
    tte: float,
) -> float:
    """Price a multi-leg structure under the SABR smile at the supplied tte.

    Vols evaluated on per-leg strikes; premium in price units → multiply by
    100 → ticks. Sum across legs (signed by quantity).
    """
    if tte <= 0:
        # Intrinsic at expiry
        forward = float(smile.params.forward_price)
        total_price = 0.0
        for leg in legs:
            if leg.right == "C":
                total_price += float(leg.quantity) * max(forward - leg.strike, 0.0)
            else:
                total_price += float(leg.quantity) * max(leg.strike - forward, 0.0)
        return total_price * 100.0

    forward = float(smile.params.forward_price)
    strikes = np.array([leg.strike for leg in legs], dtype=float)
    vols = np.asarray(
        smile.normal_vol(strikes, strike_space="price", vol_units="price"),
        dtype=float,
    )
    vols = np.maximum(vols, 1e-8)
    call_prices = bachelier_call_prices_vectorized(strikes, forward, vols, tte, 1.0)

    total_price = 0.0
    for i, leg in enumerate(legs):
        if leg.right == "C":
            leg_price = float(call_prices[i])
        else:
            # put-call parity: P = C - (F - K)
            leg_price = float(call_prices[i] - (forward - leg.strike))
        total_price += float(leg.quantity) * leg_price
    return total_price * 100.0


def aged_premium_ticks(
    *,
    legs: Sequence[OptionLeg],
    smile,
    horizon_days: int,
    base_tte: float,
) -> float:
    """Re-price the structure with ``time_to_expiry → base_tte − horizon_days/365``."""
    aged_tte = max(base_tte - horizon_days / 365.0, 0.0)
    return _structure_premium_ticks(legs=legs, smile=smile, tte=aged_tte)


def compute_carry(
    *,
    legs: Sequence[OptionLeg],
    smile,
    base_tte: float,
    net_premium_ticks: float,
) -> CarryRecord:
    """Compute aged premium at 1w / 1m / 3m / to-expiry and the carry ratios.

    Carry := change in premium going forward in time (positive carry =
    premium growing for a long structure). For long structures with
    negative theta, carry is typically negative.
    """
    p_now = _structure_premium_ticks(legs=legs, smile=smile, tte=base_tte)
    p_1w = aged_premium_ticks(legs=legs, smile=smile, horizon_days=7, base_tte=base_tte)
    p_1m = aged_premium_ticks(legs=legs, smile=smile, horizon_days=30, base_tte=base_tte)
    p_3m = aged_premium_ticks(legs=legs, smile=smile, horizon_days=90, base_tte=base_tte)
    p_exp = _structure_premium_ticks(legs=legs, smile=smile, tte=0.0)

    carry_1w = p_1w - p_now
    carry_1m = p_1m - p_now
    carry_3m = p_3m - p_now
    carry_to_expiry = p_exp - p_now

    if abs(net_premium_ticks) < 1e-9:
        ratio = 0.0
    else:
        ratio = carry_3m / abs(net_premium_ticks)

    return CarryRecord(
        carry_1w=float(carry_1w),
        carry_1m=float(carry_1m),
        carry_3m=float(carry_3m),
        carry_to_expiry=float(carry_to_expiry),
        carry_to_premium_ratio=float(ratio),
    )
