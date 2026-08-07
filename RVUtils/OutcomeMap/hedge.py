"""The linear leg: what a cell package owes to each meeting, and what it costs.

A cell butterfly is multilinear in the per-meeting probabilities *in the
frame-frozen representation* (atom locations held at absolute rates
``base + n*25bp``, only probabilities moving) — the representation the
meeting-prob study proved is the one real dynamics live in. So the package's
exposure to meeting ``m`` is a single number ``h_m`` = bp of package premium per
bp of that meeting's priced jump, and the hedge is a fixed-weight basket in
whichever linear market you choose to mark that jump from (ZQ months, or the
FOMC-dated swap strip).

Dollar bookkeeping, stated once so the cost dials are auditable:

* one package unit moves ``$25`` per bp of SR3 price (``$2500`` per price point);
* one ZQ contract moves ``$41.67`` per bp of ITS rate;
* the FedWatch basket spends ``ZQ_LEGS_PER_MEETING`` contracts to express one
  unit of exposure to a single meeting's jump (the bracketing-months convention
  inherited from :mod:`RVUtils.MeetingProb.backtest`).

Hence ``contracts_m = h_m * (SR3_DV01 / ZQ_DV01) * ZQ_LEGS_PER_MEETING`` and a
half-tick on that basket costs ``contracts * half_tick * (ZQ_DV01 / SR3_DV01)``
bp of package premium. The DV01 ratios cancel in the product — deliberately kept
explicit so a change of instrument (swap package instead of ZQ) only has to
touch the two constants.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from RVUtils.MeetingProb.atoms import AtomEngine, ContractMeetings
from RVUtils.MeetingProb.pricer import price_option

__all__ = ["SR3_DV01", "ZQ_DV01", "OPT_HALF_TICK_BP", "FUT_HALF_TICK_BP",
           "ZQ_LEGS_PER_MEETING", "package_tree_value", "package_hedge_ratios",
           "zq_basket_contracts", "linear_leg_cost_bp", "option_leg_cost_bp"]

SR3_DV01 = 25.0
ZQ_DV01 = 41.67
OPT_HALF_TICK_BP = 0.125
FUT_HALF_TICK_BP = 0.25
ZQ_LEGS_PER_MEETING = 3


def package_tree_value(
    engine: AtomEngine,
    forward_rate: float,
    legs: Sequence[Tuple[str, float, float]],
    smear_bp: float,
    *,
    q: Optional[Sequence[float]] = None,
    q_ref: Optional[Sequence[float]] = None,
) -> float:
    """Lattice-fair premium (bp) of a listed package under (atoms, smear)."""
    rates, probs = engine.rates_probs(forward_rate, q=q, q_ref=q_ref)
    return float(sum(
        w * price_option(rates, probs, right, 100.0 - k, smear_bp=smear_bp)
        for right, k, w in legs))


def package_hedge_ratios(
    cm: ContractMeetings,
    forward_rate: float,
    legs: Sequence[Tuple[str, float, float]],
    smear_bp: float,
    *,
    q: Optional[Sequence[float]] = None,
    outcomes: Optional[Dict[int, int]] = None,
    bump_bp: float = 1.0,
) -> np.ndarray:
    """``d(package premium bp) / d(jump_m bp)``, frame-frozen, per meeting.

    Meetings already resolved (``outcomes``: index -> realised move count) are
    pinned at their outcome and carry a zero ratio. The bump runs through the
    mantissa slope ``1 / (25 * |support span|)``, matching
    :func:`RVUtils.MeetingProb.backtest.hedge_ratios` so the two studies' hedges
    are the same object measured on different packages.
    """
    q_ref = np.array([r.q_zq for r in cm.resolved], dtype=float)
    q0 = q_ref.copy() if q is None else np.asarray(q, dtype=float).copy()
    fixed = outcomes or {}
    for i, n in fixed.items():
        a, b = cm.resolved[i].support
        q0[i] = 0.0 if n == a else 1.0

    engine = AtomEngine(cm)

    def value(qv: np.ndarray) -> float:
        return package_tree_value(engine, forward_rate, legs, smear_bp,
                                  q=qv, q_ref=q_ref)

    out = np.zeros(len(q0))
    for i, r in enumerate(cm.resolved):
        if i in fixed:
            continue
        span = abs(r.support[1] - r.support[0]) * 25.0
        if span <= 0:
            continue
        dq = min(bump_bp / span, 0.49)
        hi, lo = q0.copy(), q0.copy()
        hi[i] = min(q0[i] + dq, 1.0)
        lo[i] = max(q0[i] - dq, 0.0)
        if hi[i] <= lo[i]:
            continue
        out[i] = (value(hi) - value(lo)) / ((hi[i] - lo[i]) * span)
    return out


def zq_basket_contracts(h: Sequence[float]) -> float:
    """Contracts of the linear basket that carry the package's meeting risk."""
    return float(np.abs(np.asarray(h, dtype=float)).sum()
                 * (SR3_DV01 / ZQ_DV01) * ZQ_LEGS_PER_MEETING)


def linear_leg_cost_bp(contracts: float, n_sides: int = 2, *,
                       half_tick_bp: float = FUT_HALF_TICK_BP,
                       mult: float = 1.0) -> float:
    """Cost of the linear leg in bp of package premium.

    ``n_sides`` counts every crossing: 2 for a plain round trip, plus one more
    per rebalance (a meeting resolving re-ratios the basket).
    """
    return float(mult * contracts * half_tick_bp * n_sides
                 * (ZQ_DV01 / SR3_DV01))


def option_leg_cost_bp(contracts: float, n_sides: int = 2, *,
                       half_tick_bp: float = OPT_HALF_TICK_BP,
                       mult: float = 1.0) -> float:
    """Cost of the option package in bp of premium: lots x half-tick x sides."""
    return float(mult * contracts * half_tick_bp * n_sides)
