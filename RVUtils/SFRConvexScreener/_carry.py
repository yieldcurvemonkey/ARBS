"""Structure P&L helpers."""

from __future__ import annotations

from typing import Mapping, Sequence

from RVUtils.SFRConvexScreener._types import Leg


def structure_pnl_from_rates_bp(
    legs: Sequence[Leg],
    *,
    rates_now: Mapping[str, float],
    rates_then: Mapping[str, float],
) -> float:
    """P&L (bp) of a long-rate structure given two rate snapshots (% units).

    Convention: structure rate = sum(weight * rate). A "long-rate"
    structure profits when the weighted rate sum *increases*. So if
    ``rates_then`` is the realised state and ``rates_now`` is the entry
    state, P&L is ``(rate_then - rate_now) * 100`` in bp.

    Example: receive 1:-2:1 fly. If the belly rate drops 5 bp (curve
    bellied), the structure rate increases by 10 bp → P&L = +10 bp.
    """
    rate_now = sum(leg.weight * rates_now[leg.contract] for leg in legs)
    rate_then = sum(leg.weight * rates_then[leg.contract] for leg in legs)
    return (rate_then - rate_now) * 100.0
