"""Condor enumerator (spec §1.8).

Four strikes with weights ``(+1, -1, -1, +1)`` bracketing a range. Body
width ≥ 1σ terminal range; cost ≤ 40% of total width. Broken condor
(asymmetric wing widths) is allowed.
"""

from __future__ import annotations

from typing import List, Optional

from RVUtils.STIRAsymmetricScreener._rnd import RNDRecord
from RVUtils.STIRAsymmetricScreener._types import (
    ArchetypeType,
    CandidateDef,
    OptionLeg,
    ScreenerConfig,
)
from RVUtils.STIRAsymmetricScreener._universe import UniverseEntry


def enumerate_condors(
    entry: UniverseEntry,
    *,
    rnd: Optional[RNDRecord] = None,
    fomc_path=None,
    config: Optional[ScreenerConfig] = None,
) -> List[CandidateDef]:
    """Enumerate condor candidates."""
    if config is None:
        config = ScreenerConfig()

    candidates: List[CandidateDef] = []
    strikes = sorted(entry.strikes)
    fwd = entry.forward_price
    sigma_price = (rnd.std_rate if rnd is not None and rnd.std_rate > 0 else 0.30)

    # Anchor body around forward: enumerate (lo_wing, body_lo, body_hi, hi_wing)
    for right in ("C", "P"):
        for body_lo in strikes:
            if abs(body_lo - fwd) > 1.0:
                continue
            for body_hi in strikes:
                body_width = body_hi - body_lo
                if body_width <= 0:
                    continue
                # Body width ≥ 1σ
                if body_width < sigma_price:
                    continue
                if body_width > 1.5:
                    continue
                for lo_wing in strikes:
                    if lo_wing >= body_lo:
                        continue
                    if body_lo - lo_wing > 0.50:
                        continue
                    for hi_wing in strikes:
                        if hi_wing <= body_hi:
                            continue
                        if hi_wing - body_hi > 0.50:
                            continue
                        legs = (
                            OptionLeg(
                                contract=entry.contract, expiry=entry.expiry,
                                right=right, strike=float(lo_wing), quantity=1,
                            ),
                            OptionLeg(
                                contract=entry.contract, expiry=entry.expiry,
                                right=right, strike=float(body_lo), quantity=-1,
                            ),
                            OptionLeg(
                                contract=entry.contract, expiry=entry.expiry,
                                right=right, strike=float(body_hi), quantity=-1,
                            ),
                            OptionLeg(
                                contract=entry.contract, expiry=entry.expiry,
                                right=right, strike=float(hi_wing), quantity=1,
                            ),
                        )
                        cdef = CandidateDef.from_components(
                            archetype=ArchetypeType.CONDOR,
                            underlying=entry.contract,
                            expiry=entry.expiry,
                            legs=legs,
                        )
                        candidates.append(cdef)
    return candidates
