"""Structure universe: legs, two-leg curves, and three-leg flies, spot and forward.

One LEG universe serves everything. Every structure level is linear in its legs
(``curve = r_b - r_a``, ``fly = 2*r_b - r_a - r_c``), so a single history warm over
the legs composes into every structure without a second fetch.

Bounds, stated rather than silently applied:

* forward legs are capped at ``start + tenor <= 40`` so the screen stays on the
  liquid curve instead of manufacturing 45y and 50y points;
* two-leg forward curves are enumerated as **same-start** (``f x t1`` vs ``f x t2``)
  and **same-tenor** (``f1 x t`` vs ``f2 x t``) families only. The general
  ``f1 x t1`` vs ``f2 x t2`` cross product is ~2,000 structures, almost all of
  which are names no one quotes, and it would dominate any ranking by sheer count.
"""
from __future__ import annotations

import itertools
from typing import List, Sequence, Tuple

from RVUtils.CurveFlyScreener.screener import Leg, Structure

__all__ = [
    "SPOT_TENORS", "FWD_STARTS", "FWD_TENORS", "MAX_FWD_END",
    "leg_label", "leg_universe", "spot_curves", "forward_curves_same_start",
    "forward_curves_same_tenor", "spot_flies_uni", "forward_flies_uni",
    "full_universe",
]

SPOT_TENORS: Tuple[float, ...] = (1, 2, 3, 4, 5, 7, 10, 15, 20, 30)
FWD_STARTS: Tuple[float, ...] = (1, 2, 3, 5, 10, 15, 20)
FWD_TENORS: Tuple[float, ...] = (1, 2, 3, 5, 7, 10, 15, 20, 30)
MAX_FWD_END: float = 40.0


def leg_label(leg: Leg) -> str:
    """Lowercase-concatenated shorthand, the form the curve cache keys on."""
    return f"{leg.fwd:g}y{leg.tenor:g}y" if leg.fwd else f"{leg.tenor:g}y"


def leg_universe() -> List[Leg]:
    legs = [Leg(0, t) for t in SPOT_TENORS]
    for f in FWD_STARTS:
        for t in FWD_TENORS:
            if f + t <= MAX_FWD_END:
                legs.append(Leg(f, t))
    return legs


# ------------------------------------------------------------------ two legs

def spot_curves(tenors: Sequence[float] = SPOT_TENORS) -> List[Structure]:
    out = []
    for a, b in itertools.combinations(sorted(tenors), 2):
        out.append(Structure(f"{a:g}s{b:g}s", (Leg(0, a), Leg(0, b)),
                             (-1.0, 1.0), "curve_spot"))
    return out


def forward_curves_same_start() -> List[Structure]:
    """``f x t1`` vs ``f x t2`` -- the curve seen from a forward date."""
    out = []
    for f in FWD_STARTS:
        ts = [t for t in FWD_TENORS if f + t <= MAX_FWD_END]
        for a, b in itertools.combinations(ts, 2):
            out.append(Structure(f"{f:g}y({a:g}s{b:g}s)",
                                 (Leg(f, a), Leg(f, b)), (-1.0, 1.0), "curve_fwd_start"))
    return out


def forward_curves_same_tenor() -> List[Structure]:
    """``f1 x t`` vs ``f2 x t`` -- the forward curve of a fixed tenor.

    This is the family the desk trades as ``10y10y/20y10y``: same instrument,
    two start dates, so the package is a pure statement about the shape of the
    forward curve rather than about term structure at a point.
    """
    out = []
    for t in FWD_TENORS:
        fs = [f for f in FWD_STARTS if f + t <= MAX_FWD_END]
        for a, b in itertools.combinations(fs, 2):
            out.append(Structure(f"{a:g}y{t:g}y/{b:g}y{t:g}y",
                                 (Leg(a, t), Leg(b, t)), (-1.0, 1.0), "curve_fwd_tenor"))
    return out


# ---------------------------------------------------------------- three legs

def spot_flies_uni(tenors: Sequence[float] = SPOT_TENORS,
                   min_front: float = 2.0) -> List[Structure]:
    out = []
    for a, b, c in itertools.combinations(sorted(tenors), 3):
        if a < min_front:            # must survive a 1y ageing
            continue
        out.append(Structure(f"{a:g}s{b:g}s{c:g}s",
                             (Leg(0, a), Leg(0, b), Leg(0, c)),
                             (-1.0, 2.0, -1.0), "fly_spot"))
    return out


def forward_flies_uni() -> List[Structure]:
    out = []
    for f in FWD_STARTS:
        ts = [t for t in FWD_TENORS if f + t <= MAX_FWD_END]
        for a, b, c in itertools.combinations(ts, 3):
            out.append(Structure(f"{f:g}y({a:g}s{b:g}s{c:g}s)",
                                 (Leg(f, a), Leg(f, b), Leg(f, c)),
                                 (-1.0, 2.0, -1.0), "fly_fwd"))
    return out


def full_universe() -> List[Structure]:
    return (spot_curves() + forward_curves_same_start() + forward_curves_same_tenor()
            + spot_flies_uni() + forward_flies_uni())
