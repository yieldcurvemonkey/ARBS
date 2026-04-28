"""SFR Convex Linear Structure Screener.

Ranks 3M SOFR futures calendar spreads and butterflies by the asymmetry of
their option-implied payoff distributions. See
``docs/plans/2026-04-28-sfr-convex-screener-design.md`` for the design
rationale and ``docs/plans/2026-04-28-sfr-convex-screener.md`` for the
implementation plan.
"""

from RVUtils.SFRConvexScreener._types import (
    JointMethod,
    Leg,
    SFRConvexScreenerConfig,
    StructureDef,
    StructureType,
)
from RVUtils.SFRConvexScreener._universe import (
    enumerate_butterflies,
    enumerate_calendars,
    enumerate_structures,
)
from RVUtils.SFRConvexScreener._market_data import (
    SFRMarketData,
    load_market_data,
    resolve_universe_symbols,
)

__all__ = [
    "JointMethod",
    "Leg",
    "SFRConvexScreenerConfig",
    "SFRMarketData",
    "StructureDef",
    "StructureType",
    "enumerate_butterflies",
    "enumerate_calendars",
    "enumerate_structures",
    "load_market_data",
    "resolve_universe_symbols",
]
