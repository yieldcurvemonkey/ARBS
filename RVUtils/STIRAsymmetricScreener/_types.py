"""Types and configuration for the STIR Options Asymmetric Screener.

Mirrors RVUtils/SFRConvexScreener/_types.py in spirit but extends to the
STIR options taxonomy (8 archetypes) defined in spec §1.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple


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


def _isnan(x: float) -> bool:
    try:
        return math.isnan(float(x))
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class OptionLeg:
    """A single option leg in price space (100 - rate).

    ``quantity`` is signed: positive = long, negative = short. NaN-default
    market fields are filled in by the market-data step (Phase 3); enumerate
    steps construct legs without market data first.
    """

    contract: str          # underlying contract code, e.g. "SFRU6", "0QM6", "ERV5"
    expiry: datetime.date
    right: str             # "C" or "P"
    strike: float          # price space (100 - rate)
    quantity: int          # signed; +N long, -N short
    premium_ticks: float = float("nan")
    open_interest: float = float("nan")
    volume: float = float("nan")
    bid: float = float("nan")
    ask: float = float("nan")

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def abs_quantity(self) -> int:
        return abs(self.quantity)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract": self.contract,
            "expiry": self.expiry.isoformat(),
            "right": self.right,
            "strike": self.strike,
            "quantity": self.quantity,
            "premium_ticks": self.premium_ticks,
            "open_interest": self.open_interest,
            "volume": self.volume,
            "bid": self.bid,
            "ask": self.ask,
        }


def _strike_token(strike: float) -> str:
    """Convert a strike (price space) to a stable token usable in IDs."""
    # 4 decimal places handles 6.25bp grid (e.g. 96.4375); strip trailing zeros
    return f"{strike:.4f}".rstrip("0").rstrip(".")


def _legs_token(legs: Tuple["OptionLeg", ...]) -> str:
    parts = []
    # canonical ordering by (right, strike, quantity) so identical structures
    # collide on the same id even if enumerated in different orders
    sorted_legs = sorted(legs, key=lambda l: (l.right, l.strike, l.quantity))
    for leg in sorted_legs:
        sign = "+" if leg.quantity >= 0 else "-"
        parts.append(
            f"{sign}{abs(leg.quantity)}{leg.right}{_strike_token(leg.strike)}"
        )
    return "_".join(parts)


@dataclass(frozen=True)
class CandidateDef:
    """Immutable definition of a candidate trade, prior to any computation.

    ``candidate_id`` is a deterministic string built from
    (underlying, expiry, archetype, legs). Use ``from_components`` to
    construct — ID generation lives there so callers don't have to think.
    """

    archetype: ArchetypeType
    underlying: str
    expiry: datetime.date
    legs: Tuple[OptionLeg, ...]
    candidate_id: str

    @classmethod
    def from_components(
        cls,
        *,
        archetype: ArchetypeType,
        underlying: str,
        expiry: datetime.date,
        legs: Tuple[OptionLeg, ...],
    ) -> "CandidateDef":
        if not isinstance(legs, tuple):
            legs = tuple(legs)
        cid = "_".join(
            [
                underlying,
                expiry.isoformat(),
                archetype.name,
                _legs_token(legs),
            ]
        )
        return cls(
            archetype=archetype,
            underlying=underlying,
            expiry=expiry,
            legs=legs,
            candidate_id=cid,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "archetype": self.archetype.value,
            "underlying": self.underlying,
            "expiry": self.expiry.isoformat(),
            "candidate_id": self.candidate_id,
            "legs": [leg.to_dict() for leg in self.legs],
        }
