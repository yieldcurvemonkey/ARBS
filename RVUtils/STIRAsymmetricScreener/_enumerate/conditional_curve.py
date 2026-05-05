"""Conditional curve enumerator (spec §1.6).

Calendar option spread: same option type, different expiries, often
different strikes. Sells front, buys back. Front-vs-back vol-spread
percentile gates this archetype upstream in the signals layer.

Universe-aware: this enumerator needs all universe entries (not just one)
because legs come from different expiries. The orchestrator dispatches a
modified signature that accepts ``all_entries`` instead of a single entry.
"""

from __future__ import annotations

import datetime
from typing import List, Optional, Sequence

from RVUtils.STIRAsymmetricScreener._types import (
    ArchetypeType,
    CandidateDef,
    OptionLeg,
    ScreenerConfig,
)
from RVUtils.STIRAsymmetricScreener._universe import UniverseEntry


def _pick_strike_near(
    *,
    target: float,
    strikes: Sequence[float],
    tolerance_price: float = 0.25,
) -> Optional[float]:
    if not strikes:
        return None
    best = min(strikes, key=lambda k: abs(k - target))
    if abs(best - target) > tolerance_price:
        return None
    return float(best)


def enumerate_conditional_curve(
    entry: UniverseEntry,
    *,
    rnd=None,
    fomc_path=None,
    config: Optional[ScreenerConfig] = None,
    all_entries: Optional[Sequence[UniverseEntry]] = None,
) -> List[CandidateDef]:
    """Enumerate conditional curve candidates.

    For the given ``entry`` (treated as the front leg), pair it with a
    back-month entry from ``all_entries`` and emit a 2-leg
    different-expiry spread per side. Without ``all_entries`` (e.g. when
    called per-entry), returns an empty list — caller is expected to
    dispatch this archetype at the orchestrator level.
    """
    if config is None:
        config = ScreenerConfig()
    if not all_entries:
        return []

    candidates: List[CandidateDef] = []
    front = entry
    fwd_front = front.forward_price

    for back in all_entries:
        if back.contract == front.contract or back.expiry <= front.expiry:
            continue
        # Filter to "compatible" pairs — same root family
        if back.option_root != front.option_root and not (
            front.option_root in {"SFR", "0Q", "2Q", "3Q", "4Q"}
            and back.option_root in {"SFR", "0Q", "2Q", "3Q", "4Q"}
        ):
            continue
        # Pair window: ≤ 365d apart (avoid white-vs-blue noise pairs in v1)
        if (back.expiry - front.expiry).days > 365:
            continue

        # Target strike: forward of front leg (ATM straddle around the front)
        for right in ("C", "P"):
            front_strike = _pick_strike_near(target=fwd_front, strikes=front.strikes)
            if front_strike is None:
                continue
            # Same target strike on the back-leg grid (so a "calendar" — same K)
            back_strike = _pick_strike_near(target=front_strike, strikes=back.strikes)
            if back_strike is None:
                continue
            front_leg = OptionLeg(
                contract=front.contract,
                expiry=front.expiry,
                right=right,
                strike=float(front_strike),
                quantity=-1,
            )
            back_leg = OptionLeg(
                contract=back.contract,
                expiry=back.expiry,
                right=right,
                strike=float(back_strike),
                quantity=1,
            )
            cdef = CandidateDef.from_components(
                archetype=ArchetypeType.CONDITIONAL_CURVE,
                underlying=f"{front.contract}/{back.contract}",
                expiry=back.expiry,  # the long leg drives DTE
                legs=(front_leg, back_leg),
            )
            candidates.append(cdef)
    return candidates
