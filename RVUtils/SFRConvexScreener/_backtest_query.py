"""Map BacktestSignal -> IRSwapQuery for the backtest engine."""

from __future__ import annotations

import logging

from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure

from RVUtils.SFRConvexScreener._backtest_signals import BacktestSignal
from RVUtils.SFRConvexScreener._carry_roll import sfr_to_imm_tenor
from RVUtils.SFRConvexScreener._types import StructureType

logger = logging.getLogger(__name__)


def structure_position_tag(sig: BacktestSignal) -> str:
    """Deterministic position tag — used by the exit trigger to find positions."""
    return f"sfr_screener_{sig.structure_def.structure_id}"


def structure_to_query(
    sig: BacktestSignal,
    *,
    curve: str,
    bpv: float,
) -> IRSwapQuery:
    """Build an ``IRSwapQuery`` for a single ``BacktestSignal``.

    bpv carries the long-rate convention; ``flip=True`` (i.e. asymmetry < 1)
    inverts the bpv to express the receiver / long-price direction.

    Calendars use ``IRSwapStructure.CURVE`` (matches ``BT.signals.sfr_fly_triggers``);
    the ``SPREAD`` enum value internally routes to the outright builder and
    cannot consume two-leg kwargs.
    """
    sd = sig.structure_def
    legs = sd.legs
    sign = -1.0 if sig.flip else 1.0
    tags = (structure_position_tag(sig),)

    if sd.structure_type is StructureType.OUTRIGHT:
        leg = legs[0]
        tenor_str = sfr_to_imm_tenor(leg.contract)
        return IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            curve=curve,
            tenor=tenor_str,
            structure_kwargs={
                "tenor": tenor_str,
                "bpv": sign * float(leg.weight) * float(bpv),
            },
            tags=tags,
        )

    if sd.structure_type is StructureType.CALENDAR:
        front = next(l for l in legs if l.weight > 0)
        back = next(l for l in legs if l.weight < 0)
        return IRSwapQuery(
            structure=IRSwapStructure.CURVE,
            curve=curve,
            structure_kwargs={
                "front_tenor": sfr_to_imm_tenor(front.contract),
                "back_tenor": sfr_to_imm_tenor(back.contract),
                "bpv": sign * float(bpv),
            },
            tags=tags,
        )

    if sd.structure_type is StructureType.BUTTERFLY:
        wings = [l for l in legs if l.weight > 0]
        belly = next(l for l in legs if l.weight < 0)
        if len(wings) != 2:
            raise ValueError(f"Butterfly needs exactly two +1 wings: {sd.structure_id}")
        front, back = sorted(wings, key=lambda l: l.contract)
        return IRSwapQuery(
            structure=IRSwapStructure.FLY,
            curve=curve,
            structure_kwargs={
                "front_tenor": sfr_to_imm_tenor(front.contract),
                "belly_tenor": sfr_to_imm_tenor(belly.contract),
                "back_tenor": sfr_to_imm_tenor(back.contract),
                "bpv": sign * float(bpv),
            },
            tags=tags,
        )

    raise ValueError(f"unsupported structure_type: {sd.structure_type}")
