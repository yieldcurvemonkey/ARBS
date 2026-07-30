"""FedWatch-style meeting lattice for a single SR3 contract.

The null this builds is the *curve-only* distribution of a contract's settlement
rate: per-meeting two-point lattices whose means reproduce the futures strip,
coupled **independently**. It throws away exactly what options add — the shape
of each marginal and the coupling between meetings — so the gap between it and a
listed digital is the price of that information.

Two rules matter and are easy to get wrong:

* **Day weighting.** SR3 settles on the day-weighted average of the reference
  quarter, so a meeting late in the quarter moves the contract by only a
  fraction of its jump. A Dec-9 hike moves a Sep contract not at all and a Dec
  contract by roughly a sixth. Naive 25bp lattice mapping is wrong.
* **Jumps come from the curve, not from a guess.** The per-meeting jumps are
  least-squares solved from the observed strip given the day-weight matrix, so
  the null reproduces the futures market by construction.
"""
from __future__ import annotations

import datetime
from typing import Dict, List, Mapping, Sequence, Tuple

import numpy as np

from RVUtils.FlyVsVol.baselines import mantissa_probs

__all__ = [
    "day_weight_matrix", "solve_meeting_jumps", "meeting_null_distribution",
    "null_prob_ge",
]


def _window_weight(window: Tuple[datetime.date, datetime.date],
                   effective: datetime.date) -> float:
    """Fraction of a reference quarter's days spent at the post-meeting rate."""
    start, end = window
    total = (end - start).days
    if total <= 0:
        return 0.0
    covered = (end - max(start, effective)).days
    return min(max(covered, 0), total) / total


def day_weight_matrix(
    windows: Sequence[Tuple[datetime.date, datetime.date]],
    meetings: Sequence[datetime.date],
    *,
    effective_lag_days: int = 1,
) -> np.ndarray:
    """``W[i, m]`` — the share of contract ``i``'s quarter after meeting ``m``."""
    out = np.zeros((len(windows), len(meetings)), dtype=float)
    for m, decision in enumerate(meetings):
        eff = decision + datetime.timedelta(days=effective_lag_days)
        for i, w in enumerate(windows):
            out[i, m] = _window_weight(w, eff)
    return out


def solve_meeting_jumps(
    forwards_bp: Sequence[float],
    weights: np.ndarray,
    base_rate_bp: float,
    *,
    ridge: float = 1e-3,
) -> np.ndarray:
    """Least-squares per-meeting jumps (bp) reproducing the observed strip.

    Solves ``forward_i = base + sum_m W[i, m] * jump_m``. The system is usually
    close to square but can be ill-conditioned when two meetings sit inside the
    same quarter with nearly equal weights, so a small ridge keeps the solution
    stable rather than letting two adjacent meetings blow up with opposite signs.
    """
    y = np.asarray(forwards_bp, dtype=float) - float(base_rate_bp)
    W = np.asarray(weights, dtype=float)
    if W.size == 0:
        return np.zeros(0)
    A = W.T @ W + ridge * np.eye(W.shape[1])
    return np.linalg.solve(A, W.T @ y)


def meeting_null_distribution(
    jumps_bp: Sequence[float],
    contract_weights: Sequence[float],
    *,
    move_size_bp: float = 25.0,
    merge_bp: float = 0.25,
    max_states: int = 200_000,
) -> Tuple[np.ndarray, np.ndarray]:
    """Independent-meeting distribution of one contract's settlement offset.

    Each meeting contributes ``mantissa_probs(jump)`` over the 25bp lattice,
    scaled by that meeting's day weight for this contract. Outcomes are merged
    on a ``merge_bp`` grid so the convolution stays finite as the meeting count
    grows; the merge is the only approximation and it is far below the bid-ask.

    Returns ``(offsets_bp, probs)`` sorted by offset.
    """
    acc: Dict[int, float] = {0: 1.0}
    q = max(merge_bp, 1e-9)
    for jump, w in zip(jumps_bp, contract_weights):
        if w <= 0:
            continue
        outcomes = mantissa_probs(float(jump), move_size_bp)
        nxt: Dict[int, float] = {}
        for state, p in acc.items():
            for moves, prob in outcomes.items():
                if prob <= 0:
                    continue
                add = int(round(moves * move_size_bp * w / q))
                k = state + add
                nxt[k] = nxt.get(k, 0.0) + p * prob
        if len(nxt) > max_states:      # keep the dominant mass, renormalise
            keep = sorted(nxt.items(), key=lambda kv: -kv[1])[:max_states]
            tot = sum(v for _, v in keep)
            nxt = {k: v / tot for k, v in keep}
        acc = nxt
    keys = np.array(sorted(acc), dtype=float)
    probs = np.array([acc[int(k)] for k in keys], dtype=float)
    total = probs.sum()
    if total > 0:
        probs = probs / total
    return keys * q, probs


def null_prob_ge(
    offsets_bp: np.ndarray, probs: np.ndarray, base_rate_bp: float,
    strike_rate_bp: float,
) -> float:
    """``P(settlement rate >= strike)`` under the lattice null."""
    rates = np.asarray(offsets_bp, dtype=float) + float(base_rate_bp)
    return float(np.asarray(probs)[rates >= float(strike_rate_bp)].sum())
