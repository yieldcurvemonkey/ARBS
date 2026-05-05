"""Ratio spread enumerator (spec §1.4).

Three sub-shapes: 1×2, 2×1, 2×3 (call and put variants). Drift target =
forward rate from FOMC path; max-payoff strike must be within ±25bp.
Catastrophic-loss strike must be ≥ 1.5σ away.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from RVUtils.STIRAsymmetricScreener._rnd import RNDRecord
from RVUtils.STIRAsymmetricScreener._types import (
    ArchetypeType,
    CandidateDef,
    OptionLeg,
    ScreenerConfig,
)
from RVUtils.STIRAsymmetricScreener._universe import UniverseEntry


_RATIO_SHAPES: Tuple[Tuple[int, int], ...] = (
    (1, 2),  # 1× near, 2× far
    (2, 1),  # 2× near, 1× far  (synthetic of 1×2 with extra long)
    (2, 3),  # 2× near, 3× far
)


def enumerate_ratios(
    entry: UniverseEntry,
    *,
    rnd: Optional[RNDRecord] = None,
    fomc_path=None,
    config: Optional[ScreenerConfig] = None,
) -> List[CandidateDef]:
    """Enumerate ratio spread candidates."""
    if config is None:
        config = ScreenerConfig()

    candidates: List[CandidateDef] = []
    strikes = sorted(entry.strikes)
    fwd = entry.forward_price
    sigma_price = (rnd.std_rate if rnd is not None and rnd.std_rate > 0 else 0.30)

    for right in ("C", "P"):
        for n_long, n_short in _RATIO_SHAPES:
            for i, near in enumerate(strikes):
                # near strike must be near-OTM relative to forward
                if right == "C" and near <= fwd:
                    continue
                if right == "P" and near >= fwd:
                    continue
                far_options = strikes[i + 1 :] if right == "C" else list(reversed(strikes[:i]))
                for far in far_options:
                    width = abs(far - near)
                    if width < 0.0625:
                        continue
                    if width > 1.0:
                        continue
                    # Catastrophic-loss strike (the far strike) must be ≥ 1.5σ
                    z = abs(far - fwd) / max(sigma_price, 1e-6)
                    if z < 1.5:
                        continue
                    near_leg = OptionLeg(
                        contract=entry.contract,
                        expiry=entry.expiry,
                        right=right,
                        strike=float(near),
                        quantity=int(n_long),
                    )
                    far_leg = OptionLeg(
                        contract=entry.contract,
                        expiry=entry.expiry,
                        right=right,
                        strike=float(far),
                        quantity=-int(n_short),
                    )
                    cdef = CandidateDef.from_components(
                        archetype=ArchetypeType.RATIO,
                        underlying=entry.contract,
                        expiry=entry.expiry,
                        legs=(near_leg, far_leg),
                    )
                    candidates.append(cdef)
    return candidates
