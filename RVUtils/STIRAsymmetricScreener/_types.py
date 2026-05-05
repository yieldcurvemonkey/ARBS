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


def _default_min_payoff_multiple_per_archetype() -> Dict[str, float]:
    return {
        ArchetypeType.WING.value: 10.0,
        ArchetypeType.WIDE_VERTICAL.value: 4.0,
        ArchetypeType.RATIO.value: 3.0,
        ArchetypeType.LADDER.value: 2.5,
        ArchetypeType.TREE.value: 4.0,
        ArchetypeType.CONDOR.value: 3.0,
        ArchetypeType.RISK_REVERSAL.value: 0.0,        # tracked by zero-cost achievability
        ArchetypeType.CONDITIONAL_CURVE.value: 0.0,    # tracked by carry/cost ratio
    }


def _default_composite_weights() -> Dict[str, float]:
    # Spec §4: payoff_multiple 0.30, probability_edge 0.30, carry_quality 0.20, liquidity 0.20
    return {
        "payoff_multiple": 0.30,
        "probability_edge": 0.30,
        "carry_quality": 0.20,
        "liquidity": 0.20,
    }


@dataclass
class ScreenerConfig:
    """User-tunable screener configuration. All knobs from spec §10."""

    # Universe (spec §0)
    underlyings: Tuple[str, ...] = ("SR3", "SR1", "ER")
    include_midcurves: bool = True
    include_serials: bool = True
    include_weeklies: bool = False
    dte_floor: int = 7
    dte_ceiling: int = 730

    # Archetypes to enumerate (any subset)
    archetypes: Tuple[ArchetypeType, ...] = field(default_factory=lambda: tuple(ArchetypeType))

    # Per-archetype payoff multiple gates (spec §3)
    min_payoff_multiple_per_archetype: Dict[str, float] = field(
        default_factory=_default_min_payoff_multiple_per_archetype
    )

    # Signal thresholds (spec §2 / §10)
    path_bias_threshold_bp: float = 50.0
    rr_zscore_threshold: float = 1.5
    vol_spread_percentile_extremes: Tuple[float, float] = (0.15, 0.85)
    wing_percentile_threshold: float = 0.30
    atm_percentile_threshold_low: float = 0.25
    atm_percentile_threshold_high: float = 0.75
    prob_edge_threshold: float = 0.10
    sabr_rnd_payoff_zone_diff_threshold_pp: float = 5.0  # §2.9b 5 percentage points

    # Per-archetype risk reversal gate
    rr_max_zero_cost_ticks: float = 5.0  # spec §3.3

    # Liquidity floors (spec §0)
    liquidity_min_oi_sofr: int = 500
    liquidity_min_oi_sofr_serial: int = 250
    liquidity_min_oi_euribor: int = 250
    liquidity_min_oi_far_dated: int = 100  # ≥ 1y DTE
    liquidity_min_adv: int = 100
    bid_ask_max_pct_of_mid: float = 0.25

    # Path enumeration (spec §5)
    path_scenarios_to_evaluate: Tuple[int, ...] = (-4, -3, -2, -1, 0, 1, 2)

    # Composite weights (spec §4)
    composite_weights: Dict[str, float] = field(default_factory=_default_composite_weights)

    # Data sources
    options_source: str = "BARCHART_STIRFO-QL"
    curve_source: str = "BARCHART_STIRF-RL"
    curve_name: str = "USD-SOFR-1D-Q12STIRT"
    eur_curve_name: str = "EUR-ESTR-1D"

    # RND extraction (spec §12)
    rnd_smoothing_param: float = 1e-4
    rnd_spline_order: int = 4
    rnd_n_ghost_points: int = 10
    rnd_ghost_extension_bps: float = 5.0
    rnd_bin_width_bps: float = 25.0
    rnd_grid_points: int = 2000
    rnd_smoothing_sensitivity_pp_threshold: float = 1.0  # §12.3

    # Output
    output_root: str = "data/screener_results/stir_asymmetric_screener"

    # Reproducibility
    random_seed: int = 17

    def archetype_names(self) -> Tuple[str, ...]:
        return tuple(a.value for a in self.archetypes)
