"""Types and configuration for the STIR Options Asymmetric Screener.

Mirrors RVUtils/SFRConvexScreener/_types.py in spirit but extends to the
STIR options taxonomy (8 archetypes) defined in spec §1.
"""

from __future__ import annotations

from enum import Enum


class ArchetypeType(Enum):
    """Eight structural archetypes from spec §1 (STIR Options Asymmetric Screener)."""

    WING = "wing"                         # §1.1 single OTM put/call
    WIDE_VERTICAL = "wide_vertical"       # §1.2 wide-width vertical
    RISK_REVERSAL = "risk_reversal"       # §1.3 25d risk reversal
    RATIO = "ratio"                       # §1.4 1×2 / 2×1 / 2×3
    LADDER = "ladder"                     # §1.5 1×1×1 ladder
    CONDITIONAL_CURVE = "conditional_curve"  # §1.6 calendar option spread
    TREE = "tree"                         # §1.7 broken fly / tree
    CONDOR = "condor"                     # §1.8 4-strike condor
