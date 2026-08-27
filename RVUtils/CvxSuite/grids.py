"""The kink-screen grid: 17 forward-swap points spanning the curve, as LEGS.

``KINK_GRID`` is the cross-sectional comb the kink ledger fits and screens on
(docs/cvxsuite/DESIGN.md section 3, docs/convexityrv/kink_ledger.md): a dense
1y-tenor run over the front ten years, then widening tenors out to 40y10y so
the abscissa ``k_coord = fwd + tenor/2`` climbs 0.5 -> 45 years in strictly
increasing steps. Points are (forward start, tenor) pairs in YEARS — the same
coordinates ``RVUtils.CurveFlyScreener.screener.Leg`` uses, and ``k_coord`` is
the same "midpoint maturity" measure as strat3's ``delta_m_years``
(``M = forward_start + tail/2``).

Label discipline (load-bearing): ``leg_label`` delegates to
``RVUtils.CurveFlyScreener.universe.leg_label`` — the lowercase-concatenated
form ``"7y1y"`` / ``"10y"`` that the curve cache keys on
(``RVUtils/CurveFlyScreener/universe.py:36-38``). The case matters:
``TB/IRSwapsTB.py`` fingerprints ``str(q.tenor)`` VERBATIM into the cache
symbol, so ``"10Y10Y"`` and ``"10y10y"`` are DIFFERENT symbols — an uppercase
label triggers a second full history fetch and splits the history in two
(recorded trap; see docs/curvefly and the IRSwapsTB cache notes).

Zone tags (``classify_point``): ``"meeting"`` for ``fwd < 2.0`` (the front end
where FOMC meeting-date structure, not curve convexity, drives the residual),
``"convexity"`` for ``fwd >= 20.0`` (the ultra-long end where the Ho-Lee CA
``0.5*sigma^2*t1*t2`` dominates — CA grows with the product of the segment
times, so these residuals are model statements before they are RV statements),
``"clean"`` between. There is NO ``"delivery"`` tag in v1: this is a
swap-derived grid with no futures CTD points on it.

``t1_t2`` returns ``(fwd, fwd + tenor)`` — the two times of the plain
forward-segment Ho-Lee CA ``ConvexityRV.holee.ho_lee_ca_bp(sigma_bp, t1, t2)``
(the documented model choice for a t1->t2 forward; the ``convention=`` pack
forms are for SR3 packs, not for these swap segments).

``CURVEFLY_UNION_LEGS`` is the leg warm's shopping list: KINK_GRID union the
CurveFlyScreener ``leg_universe()`` (71 legs at the current universe bounds;
the union is 80 — 9 grid points sit outside the screener universe: 4y1y, 6y1y,
7y1y, 8y1y, 9y1y, 12y3y, 25y5y, 30y10y, 40y10y). One warm over these serves
both the kink screen and every composed CurveFlyScreener structure
(``screener.compose_levels``).

What this is NOT: not the CurveFlyScreener STRUCTURE universe (1,075 curves
and flies) — every entry here is a single LEG; packages are built downstream
on adjacent grid points. And 40y10y deliberately exceeds the screener
universe's ``fwd + tenor <= 40`` liquidity cap: it is on the grid for the
convexity zone's sake, tagged ``"convexity"``, never ``"clean"``.
"""
from __future__ import annotations

import math
from typing import NamedTuple

from RVUtils.CurveFlyScreener.screener import Leg
from RVUtils.CurveFlyScreener.universe import leg_label as _cfs_leg_label
from RVUtils.CurveFlyScreener.universe import leg_universe as _cfs_leg_universe

__all__ = [
    "KinkPoint",
    "KINK_GRID",
    "CURVEFLY_UNION_LEGS",
    "leg_label",
    "k_coord",
    "t1_t2",
    "classify_point",
]


class KinkPoint(NamedTuple):
    """A grid point: ``fwd`` years forward, ``tenor`` years long. Both in YEARS."""

    fwd: float
    tenor: float


#: The 17-point cross-sectional comb (DESIGN.md section 3): spot 1y; 1y1y..9y1y;
#: 10y2y; 12y3y; 15y5y; 20y5y; 25y5y; 30y10y; 40y10y.
KINK_GRID: tuple[KinkPoint, ...] = (
    KinkPoint(0.0, 1.0),
    KinkPoint(1.0, 1.0),
    KinkPoint(2.0, 1.0),
    KinkPoint(3.0, 1.0),
    KinkPoint(4.0, 1.0),
    KinkPoint(5.0, 1.0),
    KinkPoint(6.0, 1.0),
    KinkPoint(7.0, 1.0),
    KinkPoint(8.0, 1.0),
    KinkPoint(9.0, 1.0),
    KinkPoint(10.0, 2.0),
    KinkPoint(12.0, 3.0),
    KinkPoint(15.0, 5.0),
    KinkPoint(20.0, 5.0),
    KinkPoint(25.0, 5.0),
    KinkPoint(30.0, 10.0),
    KinkPoint(40.0, 10.0),
)


def _validate(p: KinkPoint) -> None:
    """Refuse a point the curve cannot express, loudly.

    A non-positive tenor is not a swap; a negative forward start is not a
    tradeable leg; a NaN coordinate would otherwise flow silently into a label
    like ``"nanynany"`` and key a cache entry no one can ever find again.
    """
    fwd, tenor = float(p.fwd), float(p.tenor)
    if not (math.isfinite(fwd) and math.isfinite(tenor)):
        raise ValueError(f"KinkPoint coordinates must be finite, got {p!r}")
    if fwd < 0.0:
        raise ValueError(f"KinkPoint forward start must be >= 0, got {p!r}")
    if tenor <= 0.0:
        raise ValueError(f"KinkPoint tenor must be > 0, got {p!r}")


def leg_label(p: KinkPoint) -> str:
    """``"7y1y"`` (or ``"10y"`` for spot) — the exact CurveFlyScreener form.

    Delegates to ``RVUtils.CurveFlyScreener.universe.leg_label`` so this can
    never drift from the form the leg-history cache keys on. Lowercase and
    ``:g``-trimmed (``2.0 -> "2"``) by construction.
    """
    _validate(p)
    return _cfs_leg_label(Leg(float(p.fwd), float(p.tenor)))


def k_coord(p: KinkPoint) -> float:
    """Fit abscissa: ``fwd + tenor/2`` — the segment midpoint, in years.

    The same measure as strat3's ``delta_m_years`` midpoint ``M``; the
    cross-sectional fits (spline hat matrix, PCA panel ordering) sit on it.
    """
    _validate(p)
    return float(p.fwd) + float(p.tenor) / 2.0


def t1_t2(p: KinkPoint) -> tuple[float, float]:
    """``(fwd, fwd + tenor)`` — the two times of the Ho-Lee forward-segment CA.

    Feed straight into ``ConvexityRV.holee.ho_lee_ca_bp(sigma_bp, t1, t2)``:
    the plain two-time form, NOT the ``pack_ca`` SR3 conventions.
    """
    _validate(p)
    return (float(p.fwd), float(p.fwd) + float(p.tenor))


def classify_point(p: KinkPoint, *, meeting_max_fwd: float = 2.0,
                   convexity_min_fwd: float = 20.0) -> str:
    """Zone tag: ``"meeting"`` | ``"convexity"`` | ``"clean"``.

    ``"meeting"`` when ``fwd < meeting_max_fwd`` (strict — a 2y-forward point
    with the default knob is already "clean"); ``"convexity"`` when
    ``fwd >= convexity_min_fwd`` (inclusive); else ``"clean"``. Evaluated in
    that order. No ``"delivery"`` tag in v1 (swap-derived grid).

    Raises ``ValueError`` if the two knobs overlap (``meeting_max_fwd >
    convexity_min_fwd``): a point that is simultaneously meeting-dominated and
    convexity-dominated is a configuration error, and answering ``"meeting"``
    by evaluation order would hide it.
    """
    _validate(p)
    m, c = float(meeting_max_fwd), float(convexity_min_fwd)
    if not (math.isfinite(m) and math.isfinite(c)):
        raise ValueError(
            f"classify_point knobs must be finite, got meeting_max_fwd={meeting_max_fwd!r}, "
            f"convexity_min_fwd={convexity_min_fwd!r}")
    if m > c:
        raise ValueError(
            f"zone knobs overlap: meeting_max_fwd={m:g} > convexity_min_fwd={c:g} "
            "(the meeting and convexity zones must not intersect)")
    fwd = float(p.fwd)
    if fwd < m:
        return "meeting"
    if fwd >= c:
        return "convexity"
    return "clean"


def _union_legs() -> tuple[KinkPoint, ...]:
    """KINK_GRID first (grid order), then universe legs not already present."""
    out: list[KinkPoint] = []
    seen: set[tuple[float, float]] = set()
    for p in KINK_GRID:
        key = (float(p.fwd), float(p.tenor))
        if key not in seen:
            seen.add(key)
            out.append(KinkPoint(*key))
    for leg in _cfs_leg_universe():
        key = (float(leg.fwd), float(leg.tenor))
        if key not in seen:
            seen.add(key)
            out.append(KinkPoint(*key))
    return tuple(out)


#: KINK_GRID union CurveFlyScreener ``leg_universe()`` — the leg warm's target
#: set (80 legs at the current universe bounds: 71 screener legs + 9 grid-only
#: points). Deterministic order: the 17 grid points first, then the screener
#: universe in its own order.
CURVEFLY_UNION_LEGS: tuple[KinkPoint, ...] = _union_legs()
