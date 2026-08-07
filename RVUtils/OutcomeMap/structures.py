"""Listed packages over the cell map: butterflies, telescoping, contract counts.

The cell instrument is the 25bp butterfly centred on an atom. On a pure lattice
its payoff is the triangular kernel that vanishes at the neighbouring atoms, so
its price is ``25bp * P(cell)``: four contracts for 25bp of payoff scale, against
the digital-difference's sixteen lots for 6.25bp. That ratio — 4pp of
probability to break even instead of 16pp — is the whole cost thesis of this
study, so the contract count is a first-class output, never an afterthought.

Legs are ``(right, strike_price, weight)`` with ``right`` always ``"C"``: the
quote panel is OTM-only and is parity-completed upstream
(``famb_common.premium_surface``), so an all-call representation is legitimate
for a package that is delta-flat by construction. It is NOT legitimate for a
strangle (that would smuggle a forward leg in) — hence flies only here.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

__all__ = ["FLY_WING", "fly_legs", "telescope", "package_contracts",
           "package_mark", "scale_legs", "combine_legs"]

#: butterfly wing in price points; 0.25 = 25bp = one lattice cell
FLY_WING = 0.25

Leg = Tuple[str, float, float]


def fly_legs(center_px: float, *, wing: float = FLY_WING,
             weight: float = 1.0) -> List[Leg]:
    """The 1/-2/1 call butterfly centred at ``center_px`` (price points)."""
    return [("C", round(center_px - wing, 6), 1.0 * weight),
            ("C", round(center_px, 6), -2.0 * weight),
            ("C", round(center_px + wing, 6), 1.0 * weight)]


def scale_legs(legs: Sequence[Leg], factor: float) -> List[Leg]:
    return [(r, k, w * factor) for r, k, w in legs]


def combine_legs(*leg_sets: Iterable[Leg]) -> List[Leg]:
    """Concatenate leg sets without netting (see :func:`telescope` for that)."""
    out: List[Leg] = []
    for ls in leg_sets:
        out.extend(ls)
    return out


def telescope(legs: Sequence[Leg], *, tol: float = 1e-9) -> List[Leg]:
    """Net weights by (right, strike) and drop the cancellations.

    Adjacent cell butterflies share strikes: two flies two cells apart cancel
    one leg outright, and a full-map book collapses to the SECOND DIFFERENCE of
    its cell weights. Costing the un-netted legs would overstate the bill of
    every multi-cell expression, so netting happens before contracts are counted.
    """
    acc: Dict[Tuple[str, float], float] = {}
    for right, k, w in legs:
        key = (right, round(float(k), 6))
        acc[key] = acc.get(key, 0.0) + float(w)
    out = [(r, k, w) for (r, k), w in sorted(acc.items()) if abs(w) > tol]
    return out


def package_contracts(legs: Sequence[Leg]) -> float:
    """Contract count (lots) of a package: the netted absolute weight sum."""
    return float(sum(abs(w) for _, _, w in telescope(legs)))


def package_mark(legs: Sequence[Leg], mark_fn) -> float:
    """Premium of a package in bp; NaN if any leg is unmarked.

    ``mark_fn(right, strike_price) -> premium_bp or NaN``.
    """
    total = 0.0
    for right, k, w in telescope(legs):
        v = mark_fn(right, k)
        if v is None or not np.isfinite(v):
            return float("nan")
        total += w * float(v)
    return float(total)
