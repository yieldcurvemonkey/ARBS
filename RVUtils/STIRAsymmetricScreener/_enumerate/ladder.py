"""Ladder enumerator (spec §1.5).

Three consecutive uniform-spacing strikes (6.25bp or 12.5bp depending on
``entry.fine_step``). Center strike aligned to drift target.
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


def enumerate_ladders(
    entry: UniverseEntry,
    *,
    rnd: Optional[RNDRecord] = None,
    fomc_path=None,
    config: Optional[ScreenerConfig] = None,
) -> List[CandidateDef]:
    """Enumerate 1×1×1 ladder candidates.

    Three consecutive strikes with weights ``(+1, -1, -1)`` — long the
    near (highest in price for puts, lowest for calls), short the next
    two consecutive strikes.
    """
    if config is None:
        config = ScreenerConfig()

    candidates: List[CandidateDef] = []
    step = entry.fine_step
    strikes = sorted(entry.strikes)
    fwd = entry.forward_price
    tol = step * 0.1

    # Find consecutive triples (a, b, c) where b - a ≈ step and c - b ≈ step
    triples = []
    for i in range(len(strikes) - 2):
        a, b, c = strikes[i], strikes[i + 1], strikes[i + 2]
        if abs((b - a) - step) > tol:
            continue
        if abs((c - b) - step) > tol:
            continue
        triples.append((a, b, c))

    for right in ("C", "P"):
        for a, b, c in triples:
            # Anchor: center strike (b) within 50bp of forward
            if abs(b - fwd) > 0.50:
                continue
            # Put ladder: 1× long highest + 1× short middle + 1× short lowest
            # which in price space (ascending): a < b < c
            #   -1 a, -1 b, +1 c   for puts
            #   +1 a, -1 b, -1 c   for calls (long-near, short-mid+far)
            if right == "P":
                long_leg = OptionLeg(
                    contract=entry.contract, expiry=entry.expiry,
                    right=right, strike=float(c), quantity=1,
                )
                short_mid = OptionLeg(
                    contract=entry.contract, expiry=entry.expiry,
                    right=right, strike=float(b), quantity=-1,
                )
                short_far = OptionLeg(
                    contract=entry.contract, expiry=entry.expiry,
                    right=right, strike=float(a), quantity=-1,
                )
            else:
                long_leg = OptionLeg(
                    contract=entry.contract, expiry=entry.expiry,
                    right=right, strike=float(a), quantity=1,
                )
                short_mid = OptionLeg(
                    contract=entry.contract, expiry=entry.expiry,
                    right=right, strike=float(b), quantity=-1,
                )
                short_far = OptionLeg(
                    contract=entry.contract, expiry=entry.expiry,
                    right=right, strike=float(c), quantity=-1,
                )
            cdef = CandidateDef.from_components(
                archetype=ArchetypeType.LADDER,
                underlying=entry.contract,
                expiry=entry.expiry,
                legs=(long_leg, short_mid, short_far),
            )
            candidates.append(cdef)
    return candidates
