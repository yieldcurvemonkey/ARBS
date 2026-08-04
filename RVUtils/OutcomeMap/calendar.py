"""Adjacent-expiry fly against fly: the vol-vs-vol leg.

Consecutive SR3 quarterlies **nest**. A meeting resolved by the near contract's
option expiry is also resolved by the far one's, and is effective inside the far
reference window, so the near contract's resolved-meeting set is a subset of the
far one's. A butterfly on the far expiry therefore carries the same shared-meeting
exposure as one on the near expiry, plus the extra meetings between them — which
is what makes it a candidate hedge for a payoff the linear market cannot hedge.

The claim that motivated this module is refuted (see the design doc): the
market-vs-lattice sensitivity mis-scaling is contract-specific rather than a
common factor, so it does not cancel in the ratio and the tree-implied lambda
measures beta ~0.26 instead of 1. The module is still the right object to have —
it quantifies the ceiling, and the same pairing defines the cross-expiry
*signal*, which is a different question from the hedge.

Two matching conventions are provided and both are kept:

* **absolute rate** (default) — the mirror package sits at the same strikes, so
  the two legs see the same absolute outcome bucket. This is the frame-freezing
  convention the whole program stands on, and it wins by an order of magnitude.
* **moneyness** — shifted by the forward difference, so each leg sits at the same
  signed distance from its own forward. Retained so the losing arm stays
  reproducible rather than asserted.
"""
from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.MeetingProb.atoms import ContractMeetings
from RVUtils.OutcomeMap.cells import snap_center
from RVUtils.OutcomeMap.structures import FLY_WING, fly_legs

__all__ = ["adjacent", "mirror_package", "align_exposure", "tree_ratio",
           "residual_exposure", "empirical_ratio", "MIN_SHARED_MEETINGS",
           "LAMBDA_CAP"]

#: with one shared meeting the least squares is exactly solvable and lambda is
#: arbitrary (measured up to 6.3); two makes it over-determined and its residual
#: meaningful
MIN_SHARED_MEETINGS = 2

#: a hedge needing more far-expiry flies than this is not cheap enough to be a
#: hedge; such contract-days are recorded as unhedgeable rather than traded
LAMBDA_CAP = 3.0

Leg = Tuple[str, float, float]


def adjacent(expiries: Dict[str, datetime.date], as_of: datetime.date,
             sym: str) -> Tuple[Optional[str], Optional[str]]:
    """(previous, next) listed quarterly by expiry order, both still alive."""
    alive = sorted((x, s) for s, x in expiries.items()
                   if x is not None and x > as_of)
    names = [s for _, s in alive]
    if sym not in names:
        return None, None
    i = names.index(sym)
    return (names[i - 1] if i > 0 else None,
            names[i + 1] if i + 1 < len(names) else None)


def mirror_package(centers: Sequence[float], weights: Sequence[float],
                   strikes: Sequence[float], *, shift: float = 0.0,
                   max_offset: float = 0.125) -> Optional[List[Leg]]:
    """The same CELL package on another expiry, snapped to ITS listed strikes.

    Mirrors cell CENTRES rather than raw legs, so the result is guaranteed to be
    a set of valid butterflies (both wings listed) rather than a package whose
    legs drifted apart under independent snapping.

    ``shift = 0`` mirrors at the same ABSOLUTE strikes (the frame-frozen
    convention, which wins by an order of magnitude); ``shift = f1 - f2`` mirrors
    at the same moneyness. Returns None if any cell has no mirrorable centre
    within ``max_offset`` — the contract-day is then skipped, not approximated.
    """
    out: List[Leg] = []
    for c, w in zip(centers, weights):
        c2 = snap_center(float(c) - shift, strikes, max_offset=max_offset)
        if c2 is None:
            return None
        out.extend(fly_legs(c2, weight=float(w)))
    return out


def align_exposure(cm1: ContractMeetings, h1: Sequence[float],
                   cm2: ContractMeetings, h2: Sequence[float]
                   ) -> Tuple[np.ndarray, np.ndarray, List[datetime.date],
                              List[datetime.date]]:
    """Line two packages' hedge ratios up by meeting effective date.

    Returns ``(v1, v2, shared, extra)`` — the shared-meeting exposure vectors and
    the meeting lists. ``extra`` is what the far expiry carries and the near one
    does not; it is the part no calendar hedge can remove, and it is exactly the
    cross-expiry conditional the impdist study could only measure indicatively.
    """
    m1 = {r.effective: float(h1[i]) for i, r in enumerate(cm1.resolved)}
    m2 = {r.effective: float(h2[i]) for i, r in enumerate(cm2.resolved)}
    shared = sorted(set(m1) & set(m2))
    extra = sorted(set(m2) - set(m1))
    v1 = np.array([m1[e] for e in shared], dtype=float)
    v2 = np.array([m2[e] for e in shared], dtype=float)
    return v1, v2, shared, extra


def tree_ratio(v1: np.ndarray, v2: np.ndarray, *,
               min_shared: int = MIN_SHARED_MEETINGS) -> float:
    """Least-squares hedge ratio over the SHARED meetings.

    NaN when the fit is under-determined (fewer than ``min_shared`` meetings) or
    the hedge leg has no shared exposure to fit against.
    """
    if v1.size < min_shared or v2.size != v1.size:
        return float("nan")
    den = float(np.dot(v2, v2))
    if den <= 1e-12:
        return float("nan")
    return float(np.dot(v1, v2) / den)


def residual_exposure(v1: np.ndarray, v2: np.ndarray, lam: float) -> float:
    """Fraction of the package's shared-meeting exposure the hedge leaves."""
    if v1.size == 0 or not np.isfinite(lam):
        return float("nan")
    base = float(np.abs(v1).sum())
    if base <= 1e-12:
        return float("nan")
    return float(np.abs(v1 - lam * v2).sum() / base)


def empirical_ratio(s1: pd.Series, s2: pd.Series, *, window: int = 40,
                    min_obs: int = 15) -> float:
    """Causal trailing regression of one package's changes on the other's.

    Uses only data strictly BEFORE the series end — the caller passes history up
    to (and excluding) the entry day, so nothing from the holding period informs
    the ratio. NaN when there is not enough history, which the caller must treat
    as "no hedge available" rather than as zero.
    """
    j = pd.concat([s1.rename("a"), s2.rename("b")], axis=1).dropna()
    if len(j) < min_obs + 1:
        return float("nan")
    d = j.diff().dropna().iloc[-window:]
    if len(d) < min_obs:
        return float("nan")
    x = d["b"].to_numpy()
    y = d["a"].to_numpy()
    den = float(np.dot(x, x))
    if den <= 1e-12:
        return float("nan")
    return float(np.dot(x, y) / den)
