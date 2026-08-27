"""Repriced carry-and-roll: the suite's ONLY carry conventions, both repriced.

Two validated paths, one sign convention:

* ``carry_roll_bp`` — the **aged-rate identity** (delegates verbatim to
  ``RVUtils.CurveFlyScreener.screener.carry_roll_bp``):
  ``CR = R(aged structure | today's curve) - R(structure | today's curve)``,
  spot legs ageing to the SHORTER SPOT, forward legs to the NEARER FORWARD.
* ``leg_roll_bp`` — the **rolled-curve reprice** via
  ``ConvexityRV.strat3_strikeless_vol.leg_metrics``: per +1 notional payer,
  ``NPV(handle.roll(horizon)) - NPV(today)`` divided by the leg's repriced
  DV01, i.e. bp of rate.

Why repriced (measured, Citi Figure-7 close of 2019-05-08,
``strat3_strikeless_vol.CARRY_TIEOUT_2019_05_08``): the repriced 1y roll
scores corr **+0.991** / MAE **0.35 bp** against the published carries. When
this module was written ``IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING`` scored corr
**-0.136** / MAE 1.28 bp and got the rank order wrong, which is the reason
these two paths exist at all. That defect is fixed: since 2026-08-27 the query
value ages a forward leg by bringing its START nearer rather than shortening
its TAIL (``Query.IRSwaps._carry_roll``) and scores +0.991 / 0.338 bp on the
same eight pairs. What this module is NOT: it is still not a wrapper over
``CARRY_AND_ROLL_BPS_RUNNING`` — it is the independent second path, and the
agreement between them is the check (DESIGN.md section 1).

Agreement of the two paths, measured on this machine (offline curve store,
USD-SOFR-1D, 1y horizon; probe 2026-08-26): on 2026-08-21 the worst forward-leg
gap |identity - roll/dv01| is **0.44 bp** (40Yx10Y) and the worst (-1,+1) pair
gap **0.42 bp**; on 2019-05-08 the worst leg gap is 0.19 bp and the worst pair
gap 0.04 bp. Both paths reproduce the eight published Fig-7 pair carries to a
worst error of 0.48 bp (leg path) / 0.44 bp (identity path) — mean 0.354 bp,
matching the recorded tie-out. The curvefly G1 gate precedent is 1.5 bp on
forward legs (``scripts/_curvefly_gates.py``). SPOT legs are NOT expected to
agree across the two paths: the rolled-curve reprice books the accrued
floating coupon (carry), the aged-rate identity deliberately does not — the
tie-out is a FORWARD-leg statement.

Units and signs: everything is **bp of the structure's quoted level over the
horizon**; positive means the quoted level rolls UP, so a LONG position in the
quoted level earns it. A Citi-style flattener (pay front, receive back) is
SHORT the ``back - front`` quoted spread, so its published carry equals
``-carry_roll_bp(pair)`` == ``leg_roll_bp(front) - leg_roll_bp(back)``.
``carry_ccy`` is ``carry_roll_bp x dv01_usd`` — USD over the horizon, the
``carry_ccy`` level input of ``ConvexityRV.curve_ops.payoff_profile`` (carry
must enter that profile as a level, never via ``horizon_date``, which raises).

Horizon caveat at the grid's front: a SPOT leg cannot age past zero — the
aged-rate identity RAISES on e.g. the spot 1y point at a 1y horizon (a swap
with no time left is not a rate). Screens over the meeting zone use shorter
horizons or catch the raise per-row; nothing here substitutes a zero.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from RVUtils.ConvexityRV.strat3_strikeless_vol import leg_metrics as _leg_metrics
from RVUtils.CurveFlyScreener.screener import Leg, Structure
from RVUtils.CurveFlyScreener.screener import carry_roll_bp as _cfs_carry_roll_bp

__all__ = [
    "carry_roll_bp",
    "leg_roll_bp",
    "carry_ccy",
    "leg_structure",
    "pair_structure",
]

# "20Yx10Y" (strat3) — forward start x tail, case-insensitive.
_STRAT3_LABEL = re.compile(r"^(\d+(?:\.\d+)?)\s*Y\s*X\s*(\d+(?:\.\d+)?)\s*Y$", re.IGNORECASE)
# "10y10y" / "10y" (CurveFlyScreener cache form).
_CFS_LABEL = re.compile(r"^(?:(\d+(?:\.\d+)?)y)?(\d+(?:\.\d+)?)y$")
# "1Y" / "6M" / "2W" / "30D" — integer count + calendar unit.
_HORIZON = re.compile(r"^(\d+)\s*([YMWD])$", re.IGNORECASE)

_HORIZON_UNITS = {"Y": "years", "M": "months", "W": "weeks", "D": "days"}


def _parse_leg_label(label: str) -> Tuple[float, float]:
    """``"20Yx10Y"`` | ``"20y10y"`` | ``"10y"`` -> (fwd, tenor) years; loud otherwise."""
    s = str(label).strip()
    m = _STRAT3_LABEL.match(s)
    if m is None:
        m = _CFS_LABEL.match(s.lower())
    if m is None:
        raise ValueError(
            f"unparseable leg label {label!r}: expected '20Yx10Y', '20y10y' or '10y'")
    fwd = float(m.group(1)) if m.group(1) is not None else 0.0
    tenor = float(m.group(2))
    if not (math.isfinite(fwd) and math.isfinite(tenor)):
        raise ValueError(f"leg label {label!r} has non-finite coordinates")
    if fwd < 0.0:
        raise ValueError(f"leg label {label!r}: forward start must be >= 0")
    if tenor <= 0.0:
        raise ValueError(f"leg label {label!r}: tenor must be > 0")
    return fwd, tenor


def _horizon_date(pricer: Any, horizon: str) -> pd.Timestamp:
    """Reference date + parsed calendar offset; the roll target for ``handle.roll``.

    ``"1Y"`` -> ``pd.DateOffset(years=1)`` (the strat3 ``screen_frame``
    convention), ``"1D"`` -> one calendar day. Integer counts >= 1 only; a
    fractional or zero horizon raises rather than rounding silently.
    """
    m = _HORIZON.match(str(horizon).strip())
    if m is None:
        raise ValueError(
            f"unparseable horizon {horizon!r}: expected '<n><Y|M|W|D>' e.g. '1Y', '6M'")
    n = int(m.group(1))
    if n < 1:
        raise ValueError(f"horizon {horizon!r} must be at least 1 unit")
    unit = _HORIZON_UNITS[m.group(2).upper()]
    ref = pd.Timestamp(pricer.reference_date()).normalize()
    return ref + pd.DateOffset(**{unit: n})


def leg_structure(fwd: float, tenor: float) -> Structure:
    """A 1-leg ``Structure`` (weight +1, kind ``"outright"``), labelled ``"10y10y"``.

    Long the quoted RATE: ``carry_roll_bp`` of this structure is the leg's own
    roll — negative for a payer on an upward-sloping segment (the rate rolls
    down and the payer bleeds; the receiver earns it).
    """
    leg = Leg(float(fwd), float(tenor))
    if not (math.isfinite(leg.fwd) and math.isfinite(leg.tenor)):
        raise ValueError(f"leg_structure coordinates must be finite, got ({fwd!r}, {tenor!r})")
    if leg.fwd < 0.0:
        raise ValueError(f"leg_structure forward start must be >= 0, got {fwd!r}")
    if leg.tenor <= 0.0:
        raise ValueError(f"leg_structure tenor must be > 0, got {tenor!r}")
    return Structure(leg.label, (leg,), (1.0,), "outright")


def pair_structure(front: Tuple[float, float], back: Tuple[float, float]) -> Structure:
    """A 2-leg curve ``Structure``: weights (-1 front, +1 back), kind ``"curve"``.

    LONG the quoted spread ``rate(back) - rate(front)`` — the CurveFlyScreener
    ``curve_pairs`` orientation and strat3's ``level_from_rates`` sign. A
    flattener (pay front, receive back) is SHORT this structure, so the
    flattener's carry is ``-carry_roll_bp(pair_structure(front, back))``.
    """
    f = leg_structure(*front).legs[0]
    b = leg_structure(*back).legs[0]
    return Structure(f"{f.label}/{b.label}", (f, b), (-1.0, 1.0), "curve")


def carry_roll_bp(pricer: Any, structure: Structure, horizon_y: float = 1.0,
                  cache: Optional[Dict] = None) -> float:
    """Static-curve carry-and-roll of ``structure`` over ``horizon_y``, bp of level.

    Delegates verbatim to ``RVUtils.CurveFlyScreener.screener.carry_roll_bp``
    (the aged-rate identity). Positive = the quoted level rolls up = a long
    position earns it. Raises (from ``screener.age``) when any leg would age
    past zero — never a substituted 0.

    ``cache`` memoises par rates by (fwd, tenor) across calls — pass one dict
    per pricer date; ~70 distinct legs serve 1,000+ structures.
    """
    return float(_cfs_carry_roll_bp(pricer, structure, horizon_y, cache))


def leg_roll_bp(pricer: Any, label: str, horizon: str = "1Y") -> float:
    """Rolled-curve roll of one leg, bp of rate, via ``strat3.leg_metrics``.

    ``NPV(handle.roll(ref + horizon)) - NPV(today)`` per +1 notional payer,
    divided by the leg's repriced DV01 (central difference, deliberately not
    the analytic annuity). Same sign convention as ``carry_roll_bp`` of the
    1-leg structure: negative = the rate rolls down = a payer bleeds. Measured
    agreement with the identity path on forward legs: worst 0.44 bp
    (2026-08-21), G1 precedent 1.5 bp; SPOT legs differ by the accrued float
    coupon and are not expected to agree.

    ``label`` accepts ``"20Yx10Y"`` (strat3), ``"20y10y"`` or ``"10y"``
    (CurveFlyScreener cache form). ``horizon`` is ``"<n><Y|M|W|D>"``.
    """
    fwd, tenor = _parse_leg_label(label)
    canon = f"{fwd:g}Yx{tenor:g}Y"
    when = _horizon_date(pricer, horizon)
    m = _leg_metrics(pricer, canon, roll_horizons=(("h", when),))
    dv01 = m["dv01"]
    if not math.isfinite(dv01) or abs(dv01) < 1e-12:
        raise ValueError(
            f"degenerate repriced DV01 {dv01!r} for leg {canon}: cannot express "
            "the roll in bp of rate")
    return float(m["roll_h"] / dv01)


def carry_ccy(pricer: Any, structure: Structure, dv01_usd: float,
              horizon_y: float = 1.0) -> float:
    """Horizon carry in USD: ``carry_roll_bp x dv01_usd``.

    ``dv01_usd`` is the position's dollar DV01 per bp of the structure's quoted
    level, SIGNED for the direction held (+ = long the quoted level, so a
    flattener on ``pair_structure(front, back)`` passes a negative
    ``dv01_usd``). This is the ``carry_ccy`` level input of
    ``ConvexityRV.curve_ops.payoff_profile`` — carry enters the profile as a
    level, never via ``horizon_date`` (which raises by design). A NaN input
    propagates to a NaN output; it is never coerced to zero.
    """
    return float(carry_roll_bp(pricer, structure, horizon_y) * float(dv01_usd))
