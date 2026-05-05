"""Wide-width vertical enumerator (spec §1.2).

Two strikes, one long, one short, same expiry, ≥ 25bp width. Reject if
``cost / width > 0.30``. For the no-leg-market-data case we don't
compute cost here — the gate runs after pricing.
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


def enumerate_wide_verticals(
    entry: UniverseEntry,
    *,
    rnd=None,
    fomc_path=None,
    config: Optional[ScreenerConfig] = None,
) -> List[CandidateDef]:
    """Enumerate wide-width vertical candidates.

    For each (long, short) strike pair on the same side with width ≥ 25bp,
    emit a 2-leg CandidateDef. Cost/width gating happens after pricing.
    """
    if config is None:
        config = ScreenerConfig()

    candidates: List[CandidateDef] = []
    strikes = sorted(entry.strikes)
    fwd = entry.forward_price
    min_width_price = 0.25  # 25bp = 0.25 in price space

    for right in ("C", "P"):
        for i, long_k in enumerate(strikes):
            # Long leg should be near-OTM (i.e., not deep-ITM)
            if right == "C" and long_k < fwd - 0.50:
                continue
            if right == "P" and long_k > fwd + 0.50:
                continue
            for short_k in strikes[i + 1 :] if right == "C" else strikes[:i]:
                # Calls: short strike > long strike (debit call spread)
                # Puts:  short strike < long strike (debit put spread)
                width = abs(short_k - long_k)
                if width < min_width_price:
                    continue
                if width > 1.50:  # cap at 150bp; deeper than that is rare
                    continue
                # Both legs OTM-relative-to-forward sanity: require that the
                # short leg is on the far side (further OTM) than long.
                if right == "C" and short_k <= long_k:
                    continue
                if right == "P" and short_k >= long_k:
                    continue
                long_leg = OptionLeg(
                    contract=entry.contract,
                    expiry=entry.expiry,
                    right=right,
                    strike=float(long_k),
                    quantity=1,
                )
                short_leg = OptionLeg(
                    contract=entry.contract,
                    expiry=entry.expiry,
                    right=right,
                    strike=float(short_k),
                    quantity=-1,
                )
                cdef = CandidateDef.from_components(
                    archetype=ArchetypeType.WIDE_VERTICAL,
                    underlying=entry.contract,
                    expiry=entry.expiry,
                    legs=(long_leg, short_leg),
                )
                candidates.append(cdef)
    return candidates
