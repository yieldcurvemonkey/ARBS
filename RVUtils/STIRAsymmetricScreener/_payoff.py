"""Terminal payoff helpers for the STIR Options Asymmetric Screener.

Provides:
- ``terminal_payoff_ticks(legs, terminal_price)`` — evaluate a multi-leg
  structure's payoff at a single terminal price.
- ``payoff_at_grid(legs, price_grid)`` — vectorized payoff over a grid.
- ``breakevens(legs, premium_ticks)`` — numerical roots in price space.
- ``max_payoff_loss(legs, grid)`` — bounds and zones in price space.

All payoffs are in **ticks** (0.25bp = 0.01 of price). Premium is in
ticks as well; the "net entry price" is the sum of leg quantities ×
per-leg premiums.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

import numpy as np

from RVUtils.STIRAsymmetricScreener._types import OptionLeg


def _leg_terminal_value_price(leg: OptionLeg, terminal_price: float) -> float:
    """Per-leg terminal payoff in price units (NOT ticks)."""
    if leg.right == "C":
        intrinsic = max(terminal_price - leg.strike, 0.0)
    else:
        intrinsic = max(leg.strike - terminal_price, 0.0)
    return float(leg.quantity) * intrinsic


def terminal_payoff_ticks(
    legs: Sequence[OptionLeg],
    terminal_price: float,
    *,
    net_premium_ticks: float = 0.0,
) -> float:
    """Net P&L of a structure at a single terminal underlying price, in ticks.

    Subtracts ``net_premium_ticks`` (the entry debit in ticks; positive ⇒
    net debit). Output is in ticks (1 tick = 0.01 of price = 0.25bp).
    """
    intrinsic_price = sum(_leg_terminal_value_price(leg, terminal_price) for leg in legs)
    intrinsic_ticks = intrinsic_price * 100.0
    return float(intrinsic_ticks - net_premium_ticks)


def payoff_at_grid(
    legs: Sequence[OptionLeg],
    price_grid: np.ndarray,
    *,
    net_premium_ticks: float = 0.0,
) -> np.ndarray:
    """Vectorized terminal payoff over a price grid, in ticks."""
    grid = np.asarray(price_grid, dtype=float)
    out = np.zeros_like(grid)
    for leg in legs:
        if leg.right == "C":
            intrinsic = np.maximum(grid - leg.strike, 0.0)
        else:
            intrinsic = np.maximum(leg.strike - grid, 0.0)
        out += float(leg.quantity) * intrinsic
    return out * 100.0 - float(net_premium_ticks)


def breakevens(
    legs: Sequence[OptionLeg],
    *,
    net_premium_ticks: float = 0.0,
    grid: np.ndarray | None = None,
) -> Tuple[float, ...]:
    """Find roots of the payoff curve in price space.

    Uses sign-change detection on a fine numerical grid. Default grid spans
    from 90 to 102 (covers any plausible STIR underlying).
    """
    if grid is None:
        grid = np.linspace(85.0, 105.0, 4000)
    payoff = payoff_at_grid(legs, grid, net_premium_ticks=net_premium_ticks)
    roots: list[float] = []
    for i in range(1, len(grid)):
        if payoff[i - 1] == 0.0:
            roots.append(float(grid[i - 1]))
            continue
        if payoff[i - 1] * payoff[i] < 0:
            x0, x1 = grid[i - 1], grid[i]
            y0, y1 = payoff[i - 1], payoff[i]
            roots.append(float(x0 - y0 * (x1 - x0) / (y1 - y0)))
    # Dedup
    out: list[float] = []
    for r in sorted(roots):
        if not out or abs(r - out[-1]) > 1e-4:
            out.append(r)
    return tuple(out)


@dataclass(frozen=True)
class PayoffSummary:
    max_payoff_ticks: float
    max_loss_ticks: float
    payoff_zone_price: Tuple[float, float]
    max_loss_zone_price: Tuple[float, float]


def max_payoff_loss(
    legs: Sequence[OptionLeg],
    *,
    net_premium_ticks: float = 0.0,
    grid: np.ndarray | None = None,
    payoff_zone_threshold_pct: float = 0.95,
) -> PayoffSummary:
    """Compute max payoff / max loss + their zones in price space.

    ``payoff_zone_threshold_pct`` (default 95%) defines what counts as
    "max payoff zone" — the contiguous slice of price grid where the
    payoff exceeds 95% of the maximum.
    """
    if grid is None:
        grid = np.linspace(85.0, 105.0, 4000)
    payoff = payoff_at_grid(legs, grid, net_premium_ticks=net_premium_ticks)
    if len(payoff) == 0:
        return PayoffSummary(0.0, 0.0, (math.nan, math.nan), (math.nan, math.nan))
    max_p = float(np.max(payoff))
    min_p = float(np.min(payoff))
    threshold = max_p - payoff_zone_threshold_pct * (max_p - min_p) if max_p > min_p else max_p
    payoff_mask = payoff >= threshold
    loss_mask = payoff <= min_p + (1.0 - payoff_zone_threshold_pct) * (max_p - min_p)

    def _zone(mask):
        idx = np.where(mask)[0]
        if len(idx) == 0:
            return (float("nan"), float("nan"))
        return (float(grid[idx[0]]), float(grid[idx[-1]]))

    return PayoffSummary(
        max_payoff_ticks=max_p,
        max_loss_ticks=min_p,
        payoff_zone_price=_zone(payoff_mask),
        max_loss_zone_price=_zone(loss_mask),
    )
