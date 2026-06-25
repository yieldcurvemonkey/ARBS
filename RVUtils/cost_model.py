"""Transaction cost model (data-agnostic).

Parameterized bid-ask cost model for rates structures. Default calibration
is indicative for USD SOFR swaps; override via custom functions if needed.
"""
from __future__ import annotations

from typing import Sequence


def transaction_cost_bps(tenor: float, fwd_start: float = 0.0) -> float:
    """Parameterized bid-ask half-spread in bp.

    Default: 0.25 + 0.05 * min(tenor, 30) + 0.04 * min(fwd_start, 10).
    """
    return 0.25 + 0.05 * min(float(tenor), 30.0) + 0.04 * min(float(fwd_start), 10.0)


def structure_cost_bps(
    legs: Sequence[float],
    weights: Sequence[float],
    fwd_start: float = 0.0,
) -> float:
    """Total cost of a multi-leg structure = sum |w_i| * leg_cost_i."""
    return sum(abs(float(w)) * transaction_cost_bps(float(t), fwd_start) for t, w in zip(legs, weights))
