"""Risk reversal enumerator (spec §1.3).

Long OTM call + short OTM put (call-over) or inverse (put-over). Target
offsetting deltas (~25 delta each). 25d-RR Z-score gating happens in the
signals layer; this enumerator just emits candidates that match the
delta-pair structure.
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


def enumerate_risk_reversals(
    entry: UniverseEntry,
    *,
    rnd=None,
    fomc_path=None,
    smile=None,
    config: Optional[ScreenerConfig] = None,
) -> List[CandidateDef]:
    """Enumerate risk reversal candidates.

    Emits a 25-delta call-over (long call, short put) and a 25-delta
    put-over (long put, short call) candidate when a SABR smile is
    available. Without a smile, falls back to forward + offsets matching
    the 25d-RR convention (forward ± 25bp).
    """
    if config is None:
        config = ScreenerConfig()

    candidates: List[CandidateDef] = []
    fwd = entry.forward_price

    # Resolve 25d strikes from the smile when possible
    call_strike: Optional[float] = None
    put_strike: Optional[float] = None
    if smile is not None:
        try:
            call_strike = float(smile.delta_to_strike(0.25, "C"))
            put_strike = float(smile.delta_to_strike(0.25, "P"))
        except Exception:
            call_strike = put_strike = None
    if call_strike is None or put_strike is None:
        # Fallback: forward ± 25bp (in price space) snapped to the listed grid
        listed = list(entry.strikes)
        target_call = fwd + 0.25
        target_put = fwd - 0.25
        call_strike = min(listed, key=lambda k: abs(k - target_call))
        put_strike = min(listed, key=lambda k: abs(k - target_put))

    if call_strike <= fwd or put_strike >= fwd:
        return []

    long_call = OptionLeg(
        contract=entry.contract,
        expiry=entry.expiry,
        right="C",
        strike=float(call_strike),
        quantity=1,
    )
    short_put = OptionLeg(
        contract=entry.contract,
        expiry=entry.expiry,
        right="P",
        strike=float(put_strike),
        quantity=-1,
    )
    short_call = OptionLeg(
        contract=entry.contract,
        expiry=entry.expiry,
        right="C",
        strike=float(call_strike),
        quantity=-1,
    )
    long_put = OptionLeg(
        contract=entry.contract,
        expiry=entry.expiry,
        right="P",
        strike=float(put_strike),
        quantity=1,
    )
    candidates.append(
        CandidateDef.from_components(
            archetype=ArchetypeType.RISK_REVERSAL,
            underlying=entry.contract,
            expiry=entry.expiry,
            legs=(long_call, short_put),
        )
    )
    candidates.append(
        CandidateDef.from_components(
            archetype=ArchetypeType.RISK_REVERSAL,
            underlying=entry.contract,
            expiry=entry.expiry,
            legs=(long_put, short_call),
        )
    )
    return candidates
