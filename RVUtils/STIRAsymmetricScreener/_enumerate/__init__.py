"""Archetype enumerators for the STIR Options Asymmetric Screener.

Each module exposes ``enumerate_*`` returning ``List[CandidateDef]`` for
its archetype. The dispatch table below maps ArchetypeType to the
appropriate enumerator.
"""

from __future__ import annotations

from typing import Callable, Dict, List

from RVUtils.STIRAsymmetricScreener._enumerate.condor import enumerate_condors
from RVUtils.STIRAsymmetricScreener._enumerate.conditional_curve import (
    enumerate_conditional_curve,
)
from RVUtils.STIRAsymmetricScreener._enumerate.ladder import enumerate_ladders
from RVUtils.STIRAsymmetricScreener._enumerate.ratio import enumerate_ratios
from RVUtils.STIRAsymmetricScreener._enumerate.risk_reversal import (
    enumerate_risk_reversals,
)
from RVUtils.STIRAsymmetricScreener._enumerate.tree import enumerate_trees
from RVUtils.STIRAsymmetricScreener._enumerate.wide_vertical import (
    enumerate_wide_verticals,
)
from RVUtils.STIRAsymmetricScreener._enumerate.wing import enumerate_wings
from RVUtils.STIRAsymmetricScreener._types import ArchetypeType


ENUMERATOR_BY_ARCHETYPE: Dict[ArchetypeType, Callable[..., List]] = {
    ArchetypeType.WING: enumerate_wings,
    ArchetypeType.WIDE_VERTICAL: enumerate_wide_verticals,
    ArchetypeType.RISK_REVERSAL: enumerate_risk_reversals,
    ArchetypeType.RATIO: enumerate_ratios,
    ArchetypeType.LADDER: enumerate_ladders,
    ArchetypeType.CONDITIONAL_CURVE: enumerate_conditional_curve,
    ArchetypeType.TREE: enumerate_trees,
    ArchetypeType.CONDOR: enumerate_condors,
}


__all__ = [
    "ENUMERATOR_BY_ARCHETYPE",
    "enumerate_condors",
    "enumerate_conditional_curve",
    "enumerate_ladders",
    "enumerate_ratios",
    "enumerate_risk_reversals",
    "enumerate_trees",
    "enumerate_wide_verticals",
    "enumerate_wings",
]
