"""Enumerate calendar / butterfly structure universes from a contract list."""

from __future__ import annotations

from typing import List, Sequence

from RVUtils.SFRConvexScreener._types import (
    Leg,
    SFRConvexScreenerConfig,
    StructureDef,
    StructureType,
)


def _make_leg(contract: str, weight: float) -> Leg:
    # price/dv01 placeholders — filled in by the market-data step
    return Leg(contract=contract, weight=float(weight), price=float("nan"), dv01=25.0)


def enumerate_outrights(symbols: Sequence[str]) -> List[StructureDef]:
    """One ``OUTRIGHT`` structure per contract — single leg with weight=+1.

    The asymmetry of the BL marginal directly tells us whether paying or
    receiving the contract has the better-asymmetric directional payoff.
    Convention: weight=+1 → P&L distribution is the realised rate change in
    bp, so ``asymmetry > 1`` means *paying* has positive asymmetric edge
    (equivalently, *receiving* has negative asymmetric edge).
    """
    out: List[StructureDef] = []
    for sym in symbols:
        out.append(
            StructureDef(
                structure_id=f"{sym}_OUTRIGHT",
                structure_type=StructureType.OUTRIGHT,
                legs=(_make_leg(sym, 1.0),),
            )
        )
    return out


def enumerate_calendars(symbols: Sequence[str], gap: int) -> List[StructureDef]:
    out: List[StructureDef] = []
    n = len(symbols)
    for i in range(n - gap):
        front, back = symbols[i], symbols[i + gap]
        out.append(
            StructureDef(
                structure_id=f"{front}_{back}_CAL_{gap}",
                structure_type=StructureType.CALENDAR,
                legs=(_make_leg(front, 1.0), _make_leg(back, -1.0)),
            )
        )
    return out


def enumerate_butterflies(symbols: Sequence[str], gap: int) -> List[StructureDef]:
    out: List[StructureDef] = []
    n = len(symbols)
    for i in range(n - 2 * gap):
        a, b, c = symbols[i], symbols[i + gap], symbols[i + 2 * gap]
        out.append(
            StructureDef(
                structure_id=f"{a}_{b}_{c}_FLY_1_-2_1",
                structure_type=StructureType.BUTTERFLY,
                legs=(_make_leg(a, 1.0), _make_leg(b, -2.0), _make_leg(c, 1.0)),
            )
        )
    return out


def enumerate_structures(
    symbols: Sequence[str], config: SFRConvexScreenerConfig
) -> List[StructureDef]:
    out: List[StructureDef] = []
    if getattr(config, "include_outrights", True):
        out.extend(enumerate_outrights(symbols))
    for g in config.calendar_gaps:
        out.extend(enumerate_calendars(symbols, g))
    for g in config.fly_gaps:
        out.extend(enumerate_butterflies(symbols, g))
    return out
