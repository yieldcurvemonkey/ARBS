"""STIR Options Asymmetric Screener.

Daily screener that ranks asymmetric STIR options trades driven by
policy-rate-path mispricing, classifying every candidate into one of
eight structural archetypes from the design spec
``docs/plans/2026-05-04-stir-asymmetric-screener-design.md`` (§1).

Implementation plan: ``docs/plans/2026-05-04-stir-asymmetric-screener.md``.
"""

from RVUtils.STIRAsymmetricScreener._types import (
    ArchetypeType,
    CandidateDef,
    CandidateResult,
    OptionLeg,
    ScreenerConfig,
    ScreenerSnapshot,
)

__all__ = [
    "ArchetypeType",
    "CandidateDef",
    "CandidateResult",
    "OptionLeg",
    "ScreenerConfig",
    "ScreenerSnapshot",
]
