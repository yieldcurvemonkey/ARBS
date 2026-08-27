"""CvxSuite grids: the 17-point kink comb, its labels, coordinates and zones.

Pure logic — no market data, no stores. The load-bearing facts pinned here:

* KINK_GRID is EXACTLY the DESIGN.md section-3 comb (17 points, in order);
* ``leg_label`` produces the CurveFlyScreener cache form verbatim (lowercase,
  ``:g``-trimmed) — the form ``TB/IRSwapsTB`` fingerprints into cache symbols,
  where ``"10Y10Y" != "10y10y"`` means a second full history fetch;
* ``classify_point`` boundaries are strict-< (meeting) / inclusive->= (convexity);
* CURVEFLY_UNION_LEGS is the exact union of the grid and the screener universe.
"""
from __future__ import annotations

import math

import pytest

from RVUtils.CurveFlyScreener.screener import Leg
from RVUtils.CurveFlyScreener.universe import leg_label as cfs_leg_label
from RVUtils.CurveFlyScreener.universe import leg_universe as cfs_leg_universe
from RVUtils.CvxSuite.grids import (
    CURVEFLY_UNION_LEGS,
    KINK_GRID,
    KinkPoint,
    classify_point,
    k_coord,
    leg_label,
    t1_t2,
)

#: The DESIGN.md section-3 comb, written out by hand (NOT computed from the
#: module under test). Order matters: it is the screen's row order.
EXPECTED_LABELS = [
    "1y",
    "1y1y", "2y1y", "3y1y", "4y1y", "5y1y", "6y1y", "7y1y", "8y1y", "9y1y",
    "10y2y", "12y3y", "15y5y", "20y5y", "25y5y", "30y10y", "40y10y",
]


# --------------------------------------------------------------------- KINK_GRID

def test_kink_grid_is_the_17_point_comb():
    """MUTATION: drop, reorder or alter any grid point — the exact list equality
    catches it; so does the count."""
    assert len(KINK_GRID) == 17
    assert [leg_label(p) for p in KINK_GRID] == EXPECTED_LABELS
    # negative control: the check can fail — a 16-point comb is not this comb
    assert [leg_label(p) for p in KINK_GRID] != EXPECTED_LABELS[:-1]
    # spot 1y is the only spot point; everything else is a genuine forward
    assert sum(1 for p in KINK_GRID if p.fwd == 0.0) == 1
    assert all(isinstance(p, KinkPoint) for p in KINK_GRID)


def test_kink_grid_abscissa_is_strictly_increasing():
    """The comb is a valid fit abscissa: k_coord strictly increases along it.

    MUTATION: swap two grid points, or change k_coord to fwd + tenor — the
    known-answer endpoints below catch the formula, this catches the order."""
    ks = [k_coord(p) for p in KINK_GRID]
    assert all(b > a for a, b in zip(ks, ks[1:]))
    assert ks[0] == 0.5 and ks[-1] == 45.0


# --------------------------------------------------------------------- leg_label

def test_leg_label_matches_curvefly_convention_exactly():
    """Every union leg's label equals RVUtils.CurveFlyScreener.universe.leg_label.

    MUTATION: reimplement the f-string locally with uppercase Y, zero padding,
    or a spurious '0y' prefix on spot legs — the verbatim-equality loop fails."""
    for p in CURVEFLY_UNION_LEGS:
        assert leg_label(p) == cfs_leg_label(Leg(p.fwd, p.tenor))


def test_leg_label_known_answers_and_case_trap_controls():
    """MUTATION: any deviation from the lowercase :g form breaks a literal here."""
    assert leg_label(KinkPoint(7.0, 1.0)) == "7y1y"
    assert leg_label(KinkPoint(0.0, 10.0)) == "10y"
    assert leg_label(KinkPoint(40.0, 10.0)) == "40y10y"
    # negative controls — the cache-splitting forms this must NEVER produce:
    assert leg_label(KinkPoint(7.0, 1.0)) != "7Y1Y"        # case forks the cache symbol
    assert leg_label(KinkPoint(7.0, 1.0)) != "07y1y"       # zero padding
    assert leg_label(KinkPoint(7.0, 1.0)) != "7.0y1.0y"    # un-trimmed floats
    assert leg_label(KinkPoint(0.0, 10.0)) != "0y10y"      # spot legs have no fwd prefix


def test_leg_label_rejects_invalid_points():
    """Error paths raise loudly — never a silent 'nanynany' cache key."""
    with pytest.raises(ValueError):
        leg_label(KinkPoint(0.0, 0.0))          # zero tenor is not a swap
    with pytest.raises(ValueError):
        leg_label(KinkPoint(-1.0, 5.0))         # negative forward start
    with pytest.raises(ValueError):
        leg_label(KinkPoint(float("nan"), 5.0))
    with pytest.raises(ValueError):
        leg_label(KinkPoint(5.0, float("inf")))


# ------------------------------------------------------------- k_coord and t1_t2

def test_k_coord_known_answers():
    """MUTATION: fwd + tenor (no /2), or tenor alone — every literal fails."""
    assert k_coord(KinkPoint(0.0, 1.0)) == 0.5
    assert k_coord(KinkPoint(7.0, 1.0)) == 7.5
    assert k_coord(KinkPoint(10.0, 2.0)) == 11.0
    assert k_coord(KinkPoint(40.0, 10.0)) == 45.0
    with pytest.raises(ValueError):
        k_coord(KinkPoint(1.0, -1.0))


def test_t1_t2_known_answers_and_holee_consumption():
    """(fwd, fwd+tenor), consumed by the plain two-time Ho-Lee CA.

    ``ho_lee_ca_bp(100, 1, 2) = 0.5 * (100/1e4)^2 * 1 * 2 * 1e4 = 1.0`` bp —
    an external closed-form anchor (Ho-Lee), computed by hand here.
    MUTATION: return (fwd, tenor) instead of (fwd, fwd+tenor) — both the tuple
    literals and the 1.0 bp anchor fail."""
    from RVUtils.ConvexityRV.holee import ho_lee_ca_bp

    assert t1_t2(KinkPoint(7.0, 1.0)) == (7.0, 8.0)
    assert t1_t2(KinkPoint(40.0, 10.0)) == (40.0, 50.0)
    for p in KINK_GRID:
        t1, t2 = t1_t2(p)
        assert t1 == p.fwd
        assert t2 - t1 == pytest.approx(p.tenor)
    assert ho_lee_ca_bp(100.0, *t1_t2(KinkPoint(1.0, 1.0))) == pytest.approx(1.0)
    # negative control: the wrong tuple (fwd, tenor) gives 0.5 bp, not 1.0
    assert ho_lee_ca_bp(100.0, 1.0, 1.0) != pytest.approx(1.0)
    with pytest.raises(ValueError):
        t1_t2(KinkPoint(1.0, 0.0))


# ------------------------------------------------------------------ classify_point

def test_classify_point_default_zones_exact_membership():
    """The default knobs put EXACTLY these points in each zone.

    MUTATION: '<=' instead of '<' on the meeting boundary moves 2y1y into
    "meeting"; '>' instead of '>=' on the convexity boundary drops 20y5y —
    either breaks the set equalities."""
    zones = {leg_label(p): classify_point(p) for p in KINK_GRID}
    meeting = {k for k, v in zones.items() if v == "meeting"}
    convexity = {k for k, v in zones.items() if v == "convexity"}
    clean = {k for k, v in zones.items() if v == "clean"}
    assert meeting == {"1y", "1y1y"}
    assert convexity == {"20y5y", "25y5y", "30y10y", "40y10y"}
    assert len(clean) == 11 and "2y1y" in clean and "15y5y" in clean
    assert set(zones.values()) == {"meeting", "convexity", "clean"}


def test_classify_point_boundary_semantics():
    """fwd < meeting_max_fwd is STRICT; fwd >= convexity_min_fwd is INCLUSIVE."""
    assert classify_point(KinkPoint(2.0, 1.0)) == "clean"          # not meeting
    assert classify_point(KinkPoint(1.999, 1.0)) == "meeting"
    assert classify_point(KinkPoint(20.0, 5.0)) == "convexity"     # inclusive
    assert classify_point(KinkPoint(19.999, 5.0)) == "clean"
    # knobs are honoured
    assert classify_point(KinkPoint(3.0, 1.0), meeting_max_fwd=3.5) == "meeting"
    assert classify_point(KinkPoint(15.0, 5.0), convexity_min_fwd=15.0) == "convexity"


def test_classify_point_overlapping_zones_raise():
    """A point cannot be meeting- and convexity-dominated at once; equal knobs
    (no clean zone) are legal, strictly-overlapping knobs are a config error."""
    with pytest.raises(ValueError):
        classify_point(KinkPoint(5.0, 1.0), meeting_max_fwd=25.0, convexity_min_fwd=20.0)
    # equal knobs partition without ambiguity — allowed
    assert classify_point(KinkPoint(1.0, 1.0), meeting_max_fwd=2.0,
                          convexity_min_fwd=2.0) == "meeting"
    assert classify_point(KinkPoint(2.0, 1.0), meeting_max_fwd=2.0,
                          convexity_min_fwd=2.0) == "convexity"
    with pytest.raises(ValueError):
        classify_point(KinkPoint(1.0, 1.0), meeting_max_fwd=float("nan"))


# ------------------------------------------------------------ CURVEFLY_UNION_LEGS

def test_union_is_exactly_grid_union_universe():
    """Set identity against an INDEPENDENT recomputation from the two sources.

    MUTATION: dedup by label instead of coordinates, drop the grid-only points,
    or apply the universe's fwd+tenor<=40 cap to the grid — the set equality
    fails (40y10y sums to 50 and must survive)."""
    expected = {(float(p.fwd), float(p.tenor)) for p in KINK_GRID}
    expected |= {(float(l.fwd), float(l.tenor)) for l in cfs_leg_universe()}
    got = {(float(p.fwd), float(p.tenor)) for p in CURVEFLY_UNION_LEGS}
    assert got == expected
    # no duplicates
    assert len(CURVEFLY_UNION_LEGS) == len(got)
    # deterministic order: the 17 grid points come first, in grid order
    assert CURVEFLY_UNION_LEGS[:17] == KINK_GRID
    assert all(isinstance(p, KinkPoint) for p in CURVEFLY_UNION_LEGS)


def test_union_current_size_and_grid_only_points():
    """80 legs at the CURRENT universe bounds: 71 screener legs + 9 grid-only.

    This literal moves if CurveFlyScreener's universe bounds change — that is
    deliberate: the leg warm's cost is keyed to this count, and a silent
    universe change should fail here, get re-measured, and be re-pinned."""
    assert len(cfs_leg_universe()) == 71
    assert len(CURVEFLY_UNION_LEGS) == 80
    universe_labels = {cfs_leg_label(l) for l in cfs_leg_universe()}
    grid_only = {leg_label(p) for p in KINK_GRID} - universe_labels
    assert grid_only == {"4y1y", "6y1y", "7y1y", "8y1y", "9y1y",
                         "12y3y", "25y5y", "30y10y", "40y10y"}
    # negative control: the comb's screener-covered points are NOT in grid_only
    assert "10y2y" not in grid_only and "15y5y" not in grid_only
