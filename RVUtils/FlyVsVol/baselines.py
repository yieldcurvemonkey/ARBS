"""FedWatch-style independence null — the curve-only baseline for Tier 3.

The CME FedWatch construction is a first-moment machine: per meeting it builds
the minimum-variance distribution on the 25bp lattice consistent with the
curve-implied mean (two adjacent points, probability = the mantissa of
jump/25), then couples meetings *independently*. Neither the two-point support
nor the independence comes from market prices — which is exactly why it is the
right null for this framework: options add information in precisely those two
dimensions (marginal shape, coupling). Independence and comonotonicity bracket
the couplings; where the option-implied joint sits between them is priced.

``solve_meeting_month`` reproduces the ZQ monthly-average bootstrap (needed only
for EFFR/monthly data and the CME fixture); with a meeting-dated SOFR curve the
jumps come directly from consecutive meeting-window forwards — same lattice
machinery, no bootstrap, no EFFR basis. tail_rent is then interpretable as the
fly-level price of everything this null throws away (tails, >25bp surprises,
intermeeting risk, coupling).
"""
from __future__ import annotations

import datetime
import itertools
import math
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "solve_meeting_month",
    "mantissa_probs",
    "conditional_tree",
    "independent_move_table",
]

_EPS = 1e-12


def solve_meeting_month(
    avg: float,
    days_before: int,
    days_after: int,
    *,
    known_start: Optional[float] = None,
    known_end: Optional[float] = None,
) -> Tuple[float, float, float]:
    """FedWatch monthly bootstrap for one meeting month: returns (start, end, jump).

    ``avg`` is the month's futures-implied average rate; exactly one of
    ``known_start`` / ``known_end`` comes from the adjacent no-FOMC anchor month.
    """
    if (known_start is None) == (known_end is None):
        raise ValueError("provide exactly one of known_start / known_end")
    total = days_before + days_after
    if known_end is not None:
        end = float(known_end)
        start = (avg * total - days_after * end) / days_before
    else:
        start = float(known_start)
        end = (avg * total - days_before * start) / days_after
    return start, end, end - start


def mantissa_probs(jump_bp: float, move_size_bp: float = 25.0) -> Dict[int, float]:
    """Two-point lattice distribution: integer part vs one-further move.

    E.g. +72.5bp -> {2: 0.10, 3: 0.90}; -10bp -> {0: 0.6, -1: 0.4}.
    """
    n = jump_bp / move_size_bp
    k = math.trunc(n)
    frac = n - k
    if abs(frac) < _EPS:
        return {k: 1.0}
    step = 1 if frac > 0 else -1
    return {k: 1.0 - abs(frac), k + step: abs(frac)}


def conditional_tree(
    meeting_probs: Sequence[Mapping[int, float]]
) -> Dict[int, float]:
    """FedWatch conditional tree: convolution of independent per-meeting moves."""
    acc: Dict[int, float] = {0: 1.0}
    for probs in meeting_probs:
        nxt: Dict[int, float] = {}
        for total, p in acc.items():
            for moves, q in probs.items():
                nxt[total + moves] = nxt.get(total + moves, 0.0) + p * q
        acc = nxt
    return acc


def _window_weight(
    window: Tuple[datetime.date, datetime.date], effective: datetime.date
) -> float:
    """Fraction of the reference quarter's days at the post-meeting rate."""
    start, end = window
    total = (end - start).days
    covered = (end - max(start, effective)).days
    return min(max(covered, 0), total) / total


def _round_half_away(x: float) -> int:
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


def independent_move_table(
    meetings: Sequence[Tuple[datetime.date, Mapping[int, float]]],
    front_window: Tuple[datetime.date, datetime.date],
    belly_window: Tuple[datetime.date, datetime.date],
    back_window: Tuple[datetime.date, datetime.date],
    *,
    move_size_bp: float = 25.0,
    effective_lag_days: int = 1,
) -> Dict[str, object]:
    """Null P(N1-N2=j) for a fly triple under per-meeting independence.

    ``meetings``: (decision_date, {n_moves: prob}) per meeting (e.g. from
    ``mantissa_probs`` of curve-implied jumps). Quarter averages are day-weighted
    exactly as in settlement, so a meeting's effect on each window is fractional;
    move counts are N_k = round(Delta_k / move_size) as in Tier 2.
    """
    weights: List[Tuple[float, float, float]] = []
    for decision, _ in meetings:
        eff = decision + datetime.timedelta(days=effective_lag_days)
        weights.append((
            _window_weight(front_window, eff),
            _window_weight(belly_window, eff),
            _window_weight(back_window, eff),
        ))

    dn_table: Dict[int, float] = {}
    e_n1 = e_n2 = 0.0
    outcome_sets = [list(probs.items()) for _, probs in meetings]
    for combo in itertools.product(*outcome_sets):
        prob = 1.0
        d_front = d_belly = d_back = 0.0
        for (moves, p), (wf, wb, wk) in zip(combo, weights):
            prob *= p
            bump = moves * move_size_bp
            d_front += bump * wf
            d_belly += bump * wb
            d_back += bump * wk
        if prob <= 0:
            continue
        n1 = _round_half_away((d_belly - d_front) / move_size_bp)
        n2 = _round_half_away((d_back - d_belly) / move_size_bp)
        dn = n1 - n2
        dn_table[dn] = dn_table.get(dn, 0.0) + prob
        e_n1 += prob * n1
        e_n2 += prob * n2

    p_pos = sum(p for j, p in dn_table.items() if j > 0)
    p_neg = sum(p for j, p in dn_table.items() if j < 0)
    return {
        "dn_table": dict(sorted(dn_table.items())),
        "prob_delta": p_pos - p_neg,
        "p_dn_pos": p_pos,
        "p_dn_neg": p_neg,
        "p_dn_zero": dn_table.get(0, 0.0),
        "e_n1": e_n1,
        "e_n2": e_n2,
        "window_weights": weights,
    }
