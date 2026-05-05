"""Wing enumerator (spec §1.1).

A single OTM call or put on a midcurve / quarterly / serial underlying.
Generation rules:
- Implied probability of strike (RND CDF at strike) ≤ 0.30 — keep low-delta wings only.
- Smile ≤ 4σ from forward (spec §9 skew-explosion gate).
- Single-leg CandidateDef per (right, strike).
"""

from __future__ import annotations

import math
from typing import List, Optional

import numpy as np

from RVUtils.STIRAsymmetricScreener._rnd import RNDRecord
from RVUtils.STIRAsymmetricScreener._types import (
    ArchetypeType,
    CandidateDef,
    OptionLeg,
    ScreenerConfig,
)
from RVUtils.STIRAsymmetricScreener._universe import UniverseEntry


def _strike_implied_prob(
    *,
    rnd: Optional[RNDRecord],
    strike_price: float,
    right: str,
) -> float:
    """RND-implied probability that the underlying terminal is past ``strike``
    in the direction the wing benefits from.

    For a call wing struck at K (K > forward in price space), the wing pays
    off when terminal price ≥ K, i.e. terminal *rate* ≤ 100 - K. So we need
    P(rate ≤ 100 - K) which is the RND CDF at that rate.

    For a put wing struck at K (K < forward), payoff when terminal price ≤ K
    i.e. rate ≥ 100 - K → 1 - CDF.
    """
    if rnd is None or rnd.density_pdf is None or len(rnd.density_pdf) < 2:
        return float("nan")
    rate = 100.0 - strike_price
    if len(rnd.strike_grid_rate) < 2:
        return float("nan")
    cdf_at_rate = float(np.interp(rate, rnd.strike_grid_rate, rnd.density_cdf))
    if right == "C":
        # call pays off if rate ≤ rate(K)
        return cdf_at_rate
    else:
        return 1.0 - cdf_at_rate


def _within_4sigma(
    *,
    rnd: Optional[RNDRecord],
    strike_price: float,
    forward_price: float,
) -> bool:
    """Spec §9 skew-explosion gate: reject if strike > 4σ from spot.

    σ here is the RND standard deviation in rate space, converted to
    price space (1 rate-pp ≈ -1 price-pp).
    """
    if rnd is None or rnd.std_rate <= 0:
        return True  # Accept when σ unavailable; gate is best-effort
    fwd_rate = 100.0 - forward_price
    rate = 100.0 - strike_price
    z = abs(rate - fwd_rate) / max(rnd.std_rate, 1e-6)
    return z <= 4.0


def enumerate_wings(
    entry: UniverseEntry,
    *,
    rnd: Optional[RNDRecord] = None,
    fomc_path=None,
    config: Optional[ScreenerConfig] = None,
) -> List[CandidateDef]:
    """Enumerate wing candidates for one universe entry.

    Returns one ``CandidateDef`` per (right, strike) pair satisfying:
    - implied_prob_strike ≤ 0.30 (spec §3.1)
    - strike within 4σ of forward (spec §9)
    """
    if config is None:
        config = ScreenerConfig()

    candidates: List[CandidateDef] = []
    fwd = entry.forward_price

    for strike in entry.strikes:
        for right in ("C", "P"):
            # OTM only: call OTM means strike > forward, put OTM means strike < forward
            if right == "C" and strike <= fwd:
                continue
            if right == "P" and strike >= fwd:
                continue

            # Spec §9: reject far-out strikes
            if not _within_4sigma(rnd=rnd, strike_price=strike, forward_price=fwd):
                continue

            # Spec §3.1: implied_prob_strike ≤ 0.30
            ip = _strike_implied_prob(rnd=rnd, strike_price=strike, right=right)
            if math.isfinite(ip) and ip > 0.30:
                continue

            leg = OptionLeg(
                contract=entry.contract,
                expiry=entry.expiry,
                right=right,
                strike=float(strike),
                quantity=1,
            )
            cdef = CandidateDef.from_components(
                archetype=ArchetypeType.WING,
                underlying=entry.contract,
                expiry=entry.expiry,
                legs=(leg,),
            )
            candidates.append(cdef)
    return candidates
