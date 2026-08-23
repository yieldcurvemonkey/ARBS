"""Curve-fly screener: every butterfly on the swap curve, spot and forward,
ranked on risk-adjusted carry-and-roll.

See ``docs/curvefly/DESIGN.md``. The short version:

* carry-and-roll uses the **static-curve** convention via the aged-rate identity
  ``CR = R(aged structure | today's curve) - R(structure | today's curve)``.
  Ageing moves the start closer by the horizon and leaves the maturity fixed, so
  a spot ``T``y becomes ``h x (T-h)`` and a forward ``f x T`` becomes ``(f-h) x T``.
* the forwards-realised convention is deliberately NOT used: it is identically
  zero for a par swap, so it ranks nothing.
* ``IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING`` is reported for comparison only. It
  correlates -0.136 with the published bank screen this is graded against.

One curve build per date; every rate after that is a cheap ``fair_rate`` call.
"""
from __future__ import annotations

import dataclasses
import itertools
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "Leg",
    "Structure",
    "par_rate_bp",
    "age",
    "structure_rate_bp",
    "carry_roll_bp",
    "dv01_bp",
    "neutral_weights",
    "spot_flies",
    "forward_flies",
    "curve_pairs",
    "screen",
]

BUSINESS_DAYS = 252.0


@dataclasses.dataclass(frozen=True)
class Leg:
    """A par swap leg: ``fwd`` years forward, ``tenor`` years long."""

    fwd: float
    tenor: float

    @property
    def label(self) -> str:
        return f"{self.fwd:g}y{self.tenor:g}y" if self.fwd else f"{self.tenor:g}y"


@dataclasses.dataclass(frozen=True)
class Structure:
    """A weighted package of par swap legs, quoted in bp."""

    label: str
    legs: Tuple[Leg, ...]
    weights: Tuple[float, ...]
    kind: str  # "fly" | "curve" | "outright"

    def __post_init__(self):
        if len(self.legs) != len(self.weights):
            raise ValueError("legs and weights must be the same length")


# --------------------------------------------------------------------- pricing

def par_rate_bp(pricer: Any, leg: Leg) -> float:
    """Par swap rate in bp for ``leg`` on the pricer's curve."""
    swap = pricer.build_irswap(fwd=f"{leg.fwd:g}Y", tenor=f"{leg.tenor:g}Y", notional=1.0)
    return float(pricer.fair_rate(swap)) * 1e4


def dv01_bp(pricer: Any, leg: Leg, h_bp: float = 1.0) -> float:
    """Repriced DV01 per unit notional: central difference on a parallel shift.

    Deliberately not the analytic annuity, which diverges by up to 10% on an
    inverted long end. Sizing on one measure and checking neutrality on the
    other is how a directional residual gets into a package that is supposed to
    have none.
    """
    swap = pricer.build_irswap(fwd=f"{leg.fwd:g}Y", tenor=f"{leg.tenor:g}Y", notional=1.0)
    handle = pricer.handle()
    up = float(swap.npv(curves=handle.shift(h_bp)).real)
    dn = float(swap.npv(curves=handle.shift(-h_bp)).real)
    return (up - dn) / (2.0 * h_bp)


def age(leg: Leg, horizon_y: float) -> Leg:
    """The aged instrument's coordinates under an UNCHANGED curve.

    The static-curve convention asks: ``horizon_y`` from now, with the curve
    exactly as it is today, what is my position worth? At that point the trade
    has ``horizon_y`` less time to run, and the curve it is read off is today's.
    So both the start and the remaining life shift toward zero:

        spot     ``0 x T``  ->  ``0 x (T-h)``      the SHORTER SPOT rate
        forward  ``f x T``  ->  ``(f-h) x T``      the NEARER FORWARD rate

    The spot case is the one that is easy to get wrong. Comparing a struck ``T``y
    swap against the ``h x (T-h)`` FORWARD instead of the ``(T-h)`` spot silently
    implements the *forwards-realised* convention, under which a par swap's
    carry-and-roll is identically zero and the screen ranks nothing. Nordea's
    note uses the forward because it is quoting carry-and-roll inclusive of
    financing; the pure static-curve roll this screener ranks on uses the spot.
    """
    if leg.fwd > 0:
        new_fwd = leg.fwd - horizon_y
        if new_fwd < -1e-9:
            raise ValueError(f"cannot age {leg.label} by {horizon_y}y: start goes negative")
        return Leg(max(new_fwd, 0.0), leg.tenor)
    new_tenor = leg.tenor - horizon_y
    if new_tenor <= 0:
        raise ValueError(f"cannot age {leg.label} by {horizon_y}y: tenor goes non-positive")
    return Leg(0.0, new_tenor)


def structure_rate_bp(pricer: Any, s: Structure) -> float:
    return float(sum(w * par_rate_bp(pricer, l) for l, w in zip(s.legs, s.weights)))


def carry_roll_bp(pricer: Any, s: Structure, horizon_y: float = 1.0) -> float:
    """Static-curve carry-and-roll of ``s`` over ``horizon_y``, in bp of structure.

    The aged-rate identity. Sign convention: positive means the structure's own
    quoted level rolls UP over the horizon, i.e. a long position in the quoted
    spread earns it.
    """
    aged = Structure(s.label, tuple(age(l, horizon_y) for l in s.legs), s.weights, s.kind)
    return structure_rate_bp(pricer, aged) - structure_rate_bp(pricer, s)


def neutral_weights(pricer: Any, legs: Sequence[Leg], belly: int = 1) -> Tuple[float, ...]:
    """DV01-neutral weights, belly carrying 2x, normalised so the belly is +2.

    For a 3-leg fly returns weights whose DV01s satisfy
    ``w_belly*dv_belly + w_front*dv_front + w_back*dv_back == 0`` with the wings
    split evenly in DV01 terms.
    """
    dv = [dv01_bp(pricer, l) for l in legs]
    if len(legs) == 3:
        f, b, k = dv[0], dv[belly], dv[2]
        wf = -1.0 * b / f
        wk = -1.0 * b / k
        return (wf, 2.0, wk)
    if len(legs) == 2:
        return (-dv[1] / dv[0], 1.0)
    raise ValueError("neutral_weights supports 2 or 3 legs")


# ------------------------------------------------------------------- universes

def _grid(tenors: Sequence[float]) -> List[float]:
    return sorted(set(float(t) for t in tenors))


def spot_flies(tenors: Sequence[float] = (2, 3, 4, 5, 7, 10, 15, 20, 30),
               min_front: float = 2.0) -> List[Structure]:
    out = []
    for a, b, c in itertools.combinations(_grid(tenors), 3):
        if a < min_front:
            continue
        legs = (Leg(0, a), Leg(0, b), Leg(0, c))
        out.append(Structure(f"{a:g}s{b:g}s{c:g}s", legs, (-1.0, 2.0, -1.0), "fly"))
    return out


def forward_flies(starts: Sequence[float] = (1, 2, 3, 5, 10),
                  tenors: Sequence[float] = (1, 2, 3, 5, 7, 10, 15, 20, 30),
                  min_start: float = 1.0) -> List[Structure]:
    out = []
    g = _grid(tenors)
    for f in _grid(starts):
        if f < min_start:
            continue
        for a, b, c in itertools.combinations(g, 3):
            legs = (Leg(f, a), Leg(f, b), Leg(f, c))
            out.append(Structure(f"{f:g}y({a:g}s{b:g}s{c:g}s)", legs,
                                 (-1.0, 2.0, -1.0), "fly"))
    return out


def curve_pairs(legs: Sequence[Tuple[Leg, Leg]]) -> List[Structure]:
    return [Structure(f"{a.label}/{b.label}", (a, b), (-1.0, 1.0), "curve")
            for a, b in legs]


# ---------------------------------------------------------------------- screen

def screen(
    pricer: Any,
    structures: Sequence[Structure],
    *,
    horizon_y: float = 1.0,
    level_hist: Optional[pd.DataFrame] = None,
    business_days: float = BUSINESS_DAYS,
    dv01_neutral: bool = False,
) -> pd.DataFrame:
    """One row per structure on the pricer's date.

    ``level_hist`` is an optional wide frame of historical structure levels in bp
    (index dates, columns structure labels) used for the realised-vol and
    z-score columns. Without it ``rac`` is NaN and only carry is reported --
    the screen never silently substitutes a constant volatility.
    """
    rows = []
    for s in structures:
        try:
            if dv01_neutral:
                w = neutral_weights(pricer, s.legs)
                s = dataclasses.replace(s, weights=w)
            lvl = structure_rate_bp(pricer, s)
            cr = carry_roll_bp(pricer, s, horizon_y)
        except Exception as exc:            # a leg the curve cannot express
            rows.append(dict(label=s.label, kind=s.kind, level_bp=np.nan,
                             cr_bp=np.nan, error=str(exc)[:80]))
            continue
        rows.append(dict(label=s.label, kind=s.kind, level_bp=lvl, cr_bp=cr, error=""))
    df = pd.DataFrame(rows)

    df["rlzd_vol_bp"] = np.nan
    df["zs_1y"] = np.nan
    if level_hist is not None and len(level_hist):
        d = level_hist.diff()
        vol = d.std()
        df["rlzd_vol_bp"] = df.label.map(vol)
        mu, sd = level_hist.mean(), level_hist.std()
        df["zs_1y"] = df.apply(
            lambda r: (r.level_bp - mu.get(r.label, np.nan)) / sd.get(r.label, np.nan)
            if r.label in mu.index and sd.get(r.label, 0) else np.nan, axis=1)

    ann = df["rlzd_vol_bp"] * math.sqrt(business_days)
    df["rac"] = np.where(ann > 0, df["cr_bp"] / ann, np.nan)
    return df.sort_values("rac", ascending=False, na_position="last").reset_index(drop=True)
