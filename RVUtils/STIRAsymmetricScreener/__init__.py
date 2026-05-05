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
from RVUtils.STIRAsymmetricScreener._universe import (
    ContractEntry,
    UniverseEntry,
    attach_strike_grid,
    enumerate_contracts,
    resolve_universe,
)
from RVUtils.STIRAsymmetricScreener._market_data import (
    LegMarket,
    STIRMarketData,
    load_market_data,
)

__all__ = [
    "ArchetypeType",
    "CandidateDef",
    "CandidateResult",
    "ContractEntry",
    "LegMarket",
    "OptionLeg",
    "STIRMarketData",
    "ScreenerConfig",
    "ScreenerSnapshot",
    "UniverseEntry",
    "attach_strike_grid",
    "enumerate_contracts",
    "load_market_data",
    "resolve_universe",
]
