"""Would this resting order have filled?  An exact answer, because the data is L3.

Most fill simulators are probabilistic because most data is not order-resolved:
with only aggregated depth you cannot tell whether a size decrease happened ahead
of your order or behind it, so you model it.  That is what hftbacktest's queue
models do, and their author is explicit that choosing between them is a
calibration exercise against your own live fills.

Market-by-order removes the guess.  Every order at a level is individually
identified, so the set resting ahead of a hypothetical order at a given instant is
known exactly, and so is the moment each of them left.  Under FIFO that gives a
closed form:

    a hypothetical order fills at the first trade at its price
    after every order ahead of it has gone

-- gone by execution or by cancellation, which is precisely the distinction an L2
queue model has to assume away.

The remaining assumptions are stated in :mod:`RVUtils.MBO.sim.simulator` and are
the ones no replay-based simulator escapes: the hypothetical order does not change
anyone else's behaviour, and it does not consume the liquidity it is measured
against.
"""
from __future__ import annotations

from RVUtils.MBO.sim.simulator import (
    FillResult,
    fill_probability_curve,
    simulate_resting_order,
    simulate_many,
)

__all__ = [
    "FillResult",
    "fill_probability_curve",
    "simulate_many",
    "simulate_resting_order",
]
