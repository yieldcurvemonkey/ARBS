"""Parallel-shift and horizon-ageing repricing on a Citi Velocity swap curve.

This is the kernel every convexity strategy in this package is built on. The
JPM framework ("An option by any other name", 03-Feb-2017) needs the *payoff
profile* of a curve package under parallel shifts in rates -- Exhibit 3 -- not a
single greek, and the rateslib backend this repo uses deliberately does not
implement ``gamma``/``dv01``::

    IRSwapValue.GAMMA_01 is not available on the rateslib backend (needs a
    calibrated rl.Solver, which this curve does not carry).

So convexity here is measured the way the note measures it: **reprice the whole
package on a shifted curve**. That is exact rather than a second-order
approximation, and it is the same number a risk system would show.

Two curve transforms are used, both native to rateslib:

``shift(bp)``
    Parallel shift of the zero curve. Gives the terminal-rate axis of the
    payoff profile.

``translate(date)``
    The curve as seen from a future date, holding discount factors fixed --
    i.e. the forwards are *realised*. This is what ages a position to the
    horizon and is what makes carry show up in the profile: a flattener struck
    at market today has NPV 0 today, but its aged NPV at horizon under a zero
    shift is exactly its carry-and-roll.
"""

from __future__ import annotations

import datetime
from typing import Any, Iterable, List, Optional, Sequence

import numpy as np
import rateslib as rl

__all__ = [
    "shifted_handle",
    "horizon_handle",
    "npv_on_handle",
    "package_npv",
    "payoff_profile",
]


def _as_date(d: Any) -> datetime.date:
    if isinstance(d, datetime.datetime):
        return d.date()
    if isinstance(d, datetime.date):
        return d
    # pandas Timestamp and friends
    return d.date()


def shifted_handle(pricer: Any, shift_bp: float) -> Any:
    """The pricer's curve shifted in parallel by *shift_bp* basis points."""
    handle = pricer._rl_curve_handle
    if not shift_bp:
        return handle
    return handle.shift(float(shift_bp))


def horizon_handle(
    pricer: Any,
    horizon_date: Optional[datetime.date] = None,
    shift_bp: float = 0.0,
) -> Any:
    """Curve aged to *horizon_date* (forwards realised), then shifted.

    Order matters: translate first, then shift. Translating a shifted curve and
    shifting a translated curve differ, and the economically meaningful one is
    "roll to the horizon along today's forwards, then apply the terminal shock".
    """
    handle = pricer._rl_curve_handle
    if horizon_date is not None:
        handle = handle.translate(_as_date(horizon_date))
    if shift_bp:
        handle = handle.shift(float(shift_bp))
    return handle


def npv_on_handle(pricer: Any, irswap: Any, handle: Any) -> float:
    """Reprice one already-struck swap on an arbitrary curve *handle*.

    Mirrors ``RLIRSwapCurve.npv`` exactly, except the curve is injected. The
    swap's ``fixed_rate`` and ``notional`` are preserved, which is what makes
    this an *aged, fixed-coupon* revaluation rather than a fresh at-market one.
    """
    curve_def = pricer._curve_definition()
    effective = pricer.effective_date(irswap)
    swap = rl.IRS(
        effective=effective,
        termination=pricer.maturity_date(irswap),
        fixed_rate=irswap.fixed_rate,
        curves=handle,
        spec=curve_def["ReferenceRate"],
        notional=pricer.notional(irswap),
        **pricer._fixings_kwargs(effective=effective),
    )
    return float(swap.npv(curves=handle).real)


def package_npv(
    pricer: Any,
    package: Sequence[Any],
    horizon_date: Optional[datetime.date] = None,
    shift_bp: float = 0.0,
) -> float:
    """NPV of a whole resolved package, aged and shifted."""
    handle = horizon_handle(pricer, horizon_date, shift_bp)
    return float(sum(npv_on_handle(pricer, s, handle) for s in package))


def payoff_profile(
    pricer: Any,
    package: Sequence[Any],
    shifts: Iterable[float],
    horizon_date: Optional[datetime.date] = None,
    *,
    net_of_spot: bool = True,
) -> np.ndarray:
    """P&L of *package* across terminal parallel shifts, in currency.

    ``net_of_spot=True`` subtracts today's NPV so the profile is a P&L relative
    to inception. For a package struck at market today that subtraction is ~0,
    but for an aged book it is the difference that matters.

    The returned array INCLUDES carry: at ``shift=0`` the value is the aged
    package's NPV, which for a negative-carry flattener is negative. That is
    the whole point -- the option-like payoff has to pay for its premium.
    """
    shifts = np.asarray(list(shifts), dtype=float)
    base = package_npv(pricer, package, horizon_date=None, shift_bp=0.0) if net_of_spot else 0.0
    out = np.empty(shifts.shape[0], dtype=float)
    for i, s in enumerate(shifts):
        out[i] = package_npv(pricer, package, horizon_date=horizon_date, shift_bp=float(s)) - base
    return out
