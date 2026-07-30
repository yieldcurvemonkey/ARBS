"""The settlement transform: meeting lattices -> distribution of the SR3 price at expiry.

For SR3 contract C with reference window [S, E) and option expiry X (< S for
quarterlies), a meeting with effective date e and decision date d contributes:

* **resolved-by-expiry** (d <= X): an outcome the option settles against.
  Day weight w = 1 if e <= S (the move shifts the whole window's base), else
  (E - e).days / (E - S).days.
* **unresolved** (d > X, e < E): at expiry the futures price carries only the
  then-conditional expectation of this meeting — a *smear* around each atom,
  not an outcome. Its ZQ-implied mean is already inside today's forward.

Anchoring (deliberate; see the design doc): atoms are displacements around
**today's SR3 forward**, using the *fitted or ZQ* expected move per meeting, so

    mean(atom distribution) == forward,   exactly, for ANY q-vector.

Parity pins the option surface's mean to the same forward, so with this anchor
every divergence between the two distributions is shape. The SOFR-EFFR spread,
the year-end turn and the windowing algebra drop out of the comparison; the
level tie-out is a separate gate, not a contaminant of the refit.
"""
from __future__ import annotations

import dataclasses
import datetime
import itertools
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from RVUtils.MeetingProb.ladder import MeetingLattice

__all__ = ["ResolvedMeeting", "ContractMeetings", "split_meetings", "atom_distribution"]


@dataclasses.dataclass(frozen=True)
class ResolvedMeeting:
    """A meeting the option settles against, with its day weight."""

    effective: datetime.date
    decision: datetime.date
    weight: float
    support: Tuple[int, int]
    q_zq: float                        # ZQ's mantissa (prob of second support point)
    jump_bp: float
    stale: bool

    def probs(self, q: Optional[float] = None) -> Dict[int, float]:
        qq = self.q_zq if q is None else q
        a, b = self.support
        if a == b:
            return {a: 1.0}
        return {a: 1.0 - qq, b: qq}

    def e_moves(self, q: Optional[float] = None) -> float:
        qq = self.q_zq if q is None else q
        a, b = self.support
        return a * (1.0 - qq) + b * qq


@dataclasses.dataclass(frozen=True)
class ContractMeetings:
    """One (as_of, contract)'s meeting decomposition."""

    symbol: str
    as_of: datetime.date
    window: Tuple[datetime.date, datetime.date]
    expiry: datetime.date
    resolved: Tuple[ResolvedMeeting, ...]
    unresolved_var_bp2: float          # ZQ-implied outcome variance of post-expiry,
                                       # in-window meetings (upper bound on smear^2)
    any_stale: bool

    @property
    def n_resolved(self) -> int:
        return len(self.resolved)


def split_meetings(
    as_of: datetime.date,
    symbol: str,
    ladder: Sequence[MeetingLattice],
    *,
    move_size_bp: float = 25.0,
) -> Optional[ContractMeetings]:
    """Classify a ladder's meetings for one contract; None when inputs are unusable."""
    from MDP.STIRFutures._sofr_option_contracts import (
        quarterly_reference_window,
        sofr_option_last_trade_date,
    )

    try:
        S, E = quarterly_reference_window(symbol)
        X = sofr_option_last_trade_date(symbol)
    except Exception:
        return None
    if X is None or X <= as_of:
        return None
    total = (E - S).days
    if total <= 0:
        return None

    resolved: List[ResolvedMeeting] = []
    unresolved_var = 0.0
    any_stale = False
    for m in ladder:
        if m.effective <= as_of or m.effective >= E:
            continue                          # already in the base / after the window
        w = 1.0 if m.effective <= S else (E - m.effective).days / total
        if w <= 0.0:
            continue
        if m.decision <= X:
            resolved.append(ResolvedMeeting(
                effective=m.effective, decision=m.decision, weight=w,
                support=m.support, q_zq=m.q, jump_bp=m.jump_bp, stale=m.stale,
            ))
            any_stale |= m.stale
        else:
            unresolved_var += m.variance_bp2(w, move_size_bp)
            any_stale |= m.stale
    resolved.sort(key=lambda r: r.effective)
    return ContractMeetings(
        symbol=symbol, as_of=as_of, window=(S, E), expiry=X,
        resolved=tuple(resolved), unresolved_var_bp2=unresolved_var,
        any_stale=any_stale,
    )


def atom_distribution(
    cm: ContractMeetings,
    forward_rate: float,
    *,
    q: Optional[Sequence[float]] = None,
    move_size_bp: float = 25.0,
    merge_bp: float = 0.05,
) -> Tuple[np.ndarray, np.ndarray]:
    """Atoms (rates in percent) and probabilities of the price at option expiry.

    ``q`` overrides the per-meeting mantissas (the refit's free parameters);
    None uses ZQ's. The anchor recentres on the E[moves] implied by the SAME
    ``q`` vector, so the distribution's mean equals ``forward_rate`` for any
    ``q`` — the mean-preserving construction the design doc commits to.
    """
    R = cm.n_resolved
    if q is not None and len(q) != R:
        raise ValueError(f"q has length {len(q)}, expected {R}")
    if R == 0:
        return np.array([forward_rate]), np.array([1.0])

    qs = [cm.resolved[i].q_zq if q is None else float(q[i]) for i in range(R)]
    outcome_sets = []
    e_disp = 0.0
    for r, qq in zip(cm.resolved, qs):
        probs = r.probs(qq)
        outcome_sets.append([(n, p) for n, p in probs.items() if p > 0.0])
        e_disp += r.weight * move_size_bp * r.e_moves(qq)

    acc: Dict[float, float] = {}
    for combo in itertools.product(*outcome_sets):
        disp = 0.0
        prob = 1.0
        for (n, p), r in zip(combo, cm.resolved):
            disp += r.weight * move_size_bp * n
            prob *= p
        key = round((disp - e_disp) / max(merge_bp, 1e-9)) * merge_bp
        acc[key] = acc.get(key, 0.0) + prob

    keys = np.array(sorted(acc), dtype=float)
    probs = np.array([acc[k] for k in sorted(acc)], dtype=float)
    probs = probs / probs.sum()
    rates = forward_rate + keys / 100.0
    # exact mean re-pin (kills the merge-grid rounding residue)
    rates = rates - (float(np.dot(rates, probs)) - forward_rate)
    return rates, probs
