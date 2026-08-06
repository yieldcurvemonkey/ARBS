r"""rateslib-native IR vol cube backend (``rl.IRSplineCube`` / ``rl.IRSabrCube``).

These classes arrived in **rateslib 2.7.0** - they do not exist in 2.1.x, which is
why :mod:`MDP.CitiVelocityExcel.vol.rl_cube` builds its surface from
``PPSplineF64`` primitives instead. This module is the native path, kept separate
so the hand-built one stays the tested default.

Status: NOT YET USABLE, and it says so rather than serving numbers
-------------------------------------------------------------------
:func:`build_rl_native_cube` constructs an ``rl.IRSplineCube`` from a Citi
:class:`~MDP.CitiVelocityExcel.vol.cube_data.SwaptionCubeData` successfully, and
the **ATM node round-trips exactly** (measured 0.0 error). The off-ATM nodes do
not, and the cause is not a unit mismatch: passing the strike axis in basis
points, in percent moneyness and in decimal moneyness produced **byte-identical**
wrong off-ATM values, which rules out scaling and points at a parameterisation of
the smile's strike axis that this probe did not identify. Measured on a
3 x 3 x 5 synthetic cube, the worst off-ATM node came back 453.80 against an
input of 82.55 bp.

Rather than ship a cube whose smile is wrong in a way no downstream assertion
would catch, :func:`build_rl_native_cube` runs
:func:`assert_native_cube_round_trips` and RAISES unless every node reproduces its
input. Today that means it raises for any cube with off-ATM strikes. Pass
``verify=False`` only if you have separately established the convention.

This mirrors how the rest of this package treats a convention it cannot confirm:
``NormalSabrVolCube._normalize_normal_vol`` in the sibling swaption code silently
divides by 10,000 when a magnitude "looks wrong", and leaves no record of the
decision; the whole point of the guards here is that a wrong number should be an
exception, not a plausible-looking output.

What would settle it
--------------------
One worked example from the rateslib docs or test-suite showing
``IRSplineCube(strikes=..., parameters=...)`` read back through
``get_smile(...).get_from_strike(k, f=...)`` at a NON-ATM strike. Everything else
here is already in place.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np

from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.vol.cube_data import SwaptionCubeData

__all__ = [
    "RATESLIB_NATIVE_AVAILABLE",
    "NativeCubeUnverifiedError",
    "build_rl_native_cube",
    "assert_native_cube_round_trips",
    "irs_series_for",
]

_logger = logging.getLogger(__name__)


def _native_available() -> bool:
    import rateslib as rl

    return hasattr(rl, "IRSplineCube") and hasattr(rl, "IRSabrCube")


#: True when the installed rateslib exposes the IR vol cubes (>= 2.7.0).
RATESLIB_NATIVE_AVAILABLE: bool = _native_available()


class NativeCubeUnverifiedError(CitiVelocityError):
    """The native cube did not reproduce its own input nodes."""


def irs_series_for(citi_index: str) -> Any:
    """Build an ``IRSSeries`` describing the underlying swap for a Citi curve.

    Reads the same convention row the curve builders use, so the cube's notion of
    the underlying cannot drift from the curve it is priced against.
    """
    if not RATESLIB_NATIVE_AVAILABLE:
        raise CitiVelocityError(
            "rl.IRSplineCube requires rateslib >= 2.7.0; this environment has an older one."
        )
    from rateslib.volatility.ir.spline import IRSSeries

    from MDP.CitiVelocityExcel.curves.conventions import conventions_for

    conv = conventions_for(citi_index)
    calendar = conv.rl_calendar or conv.rl_calendar_object()
    return IRSSeries(
        currency=conv.currency.lower(),
        settle=int(conv.spot_lag),
        frequency=conv.fixed_frequency.upper(),
        convention=conv.convention,
        calendar=calendar,
        leg2_fixing_method="rfr_payment_delay",
    )


def assert_native_cube_round_trips(
    native: Any,
    cube: SwaptionCubeData,
    forwards: Dict[Tuple[str, str], float],
    *,
    tol: float = 1e-6,
) -> float:
    """Read every node back out of the native cube and compare it to the input.

    Returns the worst absolute error in basis points of vol.

    Raises
    ------
    NativeCubeUnverifiedError
        When any node differs by more than ``tol``. This is the only thing
        standing between a mis-parameterised smile and a plausible-looking wrong
        premium, so it is not optional and it is not warned - it raises.
    """
    worst = 0.0
    worst_key: Optional[Tuple[str, str, float]] = None
    for expiry in cube.expiries():
        for tenor in cube.tenors():
            forward = forwards.get((expiry, tenor))
            if forward is None:
                continue
            smile = native.get_smile(expiry, tenor)
            for offset in cube.offsets():
                expected = cube.vol(expiry, tenor, offset)
                got = float(smile.get_from_strike(forward + offset / 100.0, f=forward).vol)
                err = abs(got - expected)
                if err > worst:
                    worst, worst_key = err, (expiry, tenor, offset)
    if worst > tol:
        expiry, tenor, offset = worst_key or ("?", "?", 0.0)
        raise NativeCubeUnverifiedError(
            f"rl.IRSplineCube did not reproduce its own input nodes: worst error {worst:.6g} bp "
            f"at expiry={expiry}, tenor={tenor}, offset={offset:+.0f}bp (tolerance {tol:g}). "
            "The ATM node round-trips exactly while off-ATM nodes do not, and the strike axis "
            "is scale-invariant across bp / percent / decimal, so this is a parameterisation "
            "convention that has not been identified rather than a unit error. Use the "
            "PPSplineF64-based CitiVeloNormalVolCube (the default) until it is settled."
        )
    return worst


def build_rl_native_cube(
    *,
    cube: SwaptionCubeData,
    forwards: Dict[Tuple[str, str], float],
    citi_index: str,
    eval_date: Any = None,
    pricing_model: str = "normal_vol",
    verify: bool = True,
    tol: float = 1e-6,
) -> Any:
    """Build an ``rl.IRSplineCube`` from a Citi swaption cube.

    Parameters
    ----------
    cube
        The Citi cube: expiry x tenor x strike-offset normal vols, in basis points.
    forwards
        ``{(expiry, tenor): forward_percent}`` - the ATM forwards the strike
        offsets are measured from. Citi measures its offsets from CITI's ATM
        forward, which is not published on that branch, so these come from the
        curve we built; a forward mismatch shifts the whole smile along the
        strike axis and nothing in the data reveals it.
    verify
        Round-trip every node and raise unless they reproduce. Leave it True.

    Raises
    ------
    NativeCubeUnverifiedError
        When the node round trip fails - see the module docstring.
    """
    if not RATESLIB_NATIVE_AVAILABLE:
        raise CitiVelocityError(
            "rl.IRSplineCube requires rateslib >= 2.7.0. Use build_rl_vol_cube(), which is "
            "built from rateslib primitives and works on every supported version."
        )
    import rateslib as rl

    expiries = list(cube.expiries())
    tenors = list(cube.tenors())
    offsets = list(cube.offsets())
    if eval_date is None:
        import datetime

        as_of = cube.as_of
        eval_date = datetime.datetime(as_of.year, as_of.month, as_of.day)

    parameters = np.zeros((len(expiries), len(tenors), len(offsets)), dtype=float)
    for i, expiry in enumerate(expiries):
        for j, tenor in enumerate(tenors):
            for k, offset in enumerate(offsets):
                parameters[i, j, k] = float(cube.vol(expiry, tenor, offset))

    native = rl.IRSplineCube(
        expiries=expiries,
        tenors=tenors,
        strikes=[o / 100.0 for o in offsets],
        eval_date=eval_date,
        irs_series=irs_series_for(citi_index),
        parameters=parameters,
        pricing_model=pricing_model,
        id=f"{citi_index}-CITIVELO-VOL",
    )
    if verify:
        worst = assert_native_cube_round_trips(native, cube, forwards, tol=tol)
        _logger.info(
            "rl.IRSplineCube for %s round-tripped %d nodes, worst %.3e bp",
            citi_index,
            len(expiries) * len(tenors) * len(offsets),
            worst,
        )
    return native
