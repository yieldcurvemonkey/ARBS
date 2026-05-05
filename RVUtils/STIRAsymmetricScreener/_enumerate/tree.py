"""Trees / broken flies enumerator (spec §1.7).

Three strikes with weights ``(+1, -2, +1)`` standard fly, then broken at
one wing by replacing the far wing with a different (further) strike.
The fly can be a "tree" (broken at the long wing) — we generate both
sides.
"""

from __future__ import annotations

from typing import List, Optional

from RVUtils.STIRAsymmetricScreener._types import (
    ArchetypeType,
    CandidateDef,
    OptionLeg,
    ScreenerConfig,
)
from RVUtils.STIRAsymmetricScreener._universe import UniverseEntry


def enumerate_trees(
    entry: UniverseEntry,
    *,
    rnd=None,
    fomc_path=None,
    config: Optional[ScreenerConfig] = None,
) -> List[CandidateDef]:
    """Enumerate broken-fly / tree candidates.

    For each (right, center_strike) where center is within ±25bp of
    forward, look for a triple (low, center, high) where ``high - center``
    differs from ``center - low`` (broken).
    """
    if config is None:
        config = ScreenerConfig()

    candidates: List[CandidateDef] = []
    strikes = sorted(entry.strikes)
    fwd = entry.forward_price

    for right in ("C", "P"):
        for j, center in enumerate(strikes):
            if abs(center - fwd) > 0.25:
                continue
            for i in range(j):
                low = strikes[i]
                low_width = center - low
                if low_width <= 0 or low_width > 0.50:
                    continue
                for k in range(j + 1, len(strikes)):
                    high = strikes[k]
                    high_width = high - center
                    if high_width <= 0 or high_width > 0.50:
                        continue
                    # Tree = broken fly: widths must differ by at least one tick
                    if abs(low_width - high_width) < entry.fine_step * 0.5:
                        continue
                    legs = (
                        OptionLeg(
                            contract=entry.contract, expiry=entry.expiry,
                            right=right, strike=float(low), quantity=1,
                        ),
                        OptionLeg(
                            contract=entry.contract, expiry=entry.expiry,
                            right=right, strike=float(center), quantity=-2,
                        ),
                        OptionLeg(
                            contract=entry.contract, expiry=entry.expiry,
                            right=right, strike=float(high), quantity=1,
                        ),
                    )
                    cdef = CandidateDef.from_components(
                        archetype=ArchetypeType.TREE,
                        underlying=entry.contract,
                        expiry=entry.expiry,
                        legs=legs,
                    )
                    candidates.append(cdef)
    return candidates
