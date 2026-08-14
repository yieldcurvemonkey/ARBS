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

**Ageing is NOT done with ``Curve.translate``.** That was the obvious approach
and it is wrong here; it was measured rather than assumed, and the measurement
killed it. Repricing an already-struck swap on ``handle.translate(horizon)``
gives, as of 2022-09-13 at a 1y horizon and $100k DV01:

======================  =====================================================
package                 aged NPV at zero shift
======================  =====================================================
20Yx5Y/25Yx5Y            -0.000 bp   (carry-and-roll says +0.006 -- ~nothing)
10Yx10Y/20Yx10Y           0.000 bp   (carry-and-roll says -2.840)
30Y/50Y                -147.739 bp   (carry-and-roll says +0.363)
30Y outright           -531.94  bp   (a $100k DV01 payer cannot lose 532bp to
                                      one year of ageing with rates unchanged)
======================  =====================================================

``translate`` renormalises discount factors onto a new initial node. For a
DV01-neutral forward package that renormalisation cancels and no carry is
captured at all; for a swap whose effective date now sits *behind* the curve's
initial node it needs a year of intervening fixings that are not there, and the
number becomes meaningless. Silently, in the direction that would have flattered
or wrecked whichever structure happened to be spot.

So carry enters the profile the way the JPM note actually describes it -- as the
level of an otherwise-spot payoff profile::

    "the payoff profile of an aged flattener at fixed coupon -- primarily to
     incorporate carry costs"

i.e. pass ``carry_ccy`` to :func:`payoff_profile`, sourced from
``IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING`` (an independent, validated code path)
times the package DV01. Two verified paths, no broken third one.
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
    "matched_forward_swap_rate",
    "HorizonAgeingUnsupported",
]


def _as_dt(d: Any) -> datetime.datetime:
    """Normalise to a midnight ``datetime.datetime``.

    rateslib curve nodes are keyed by ``datetime.datetime``, and
    ``Curve.translate`` compares ``start < curve.nodes.initial`` directly, so a
    ``datetime.date`` raises ``TypeError: '<' not supported between instances of
    'datetime.date' and 'datetime.datetime'``. Everything upstream here (pandas
    Timestamps, ``datetime.date`` horizons) funnels through this.
    """
    if isinstance(d, datetime.datetime):
        return datetime.datetime(d.year, d.month, d.day)
    if isinstance(d, datetime.date):
        return datetime.datetime(d.year, d.month, d.day)
    # pandas Timestamp and friends
    return datetime.datetime(d.year, d.month, d.day)


def shifted_handle(pricer: Any, shift_bp: float) -> Any:
    """The pricer's curve shifted in parallel by *shift_bp* basis points."""
    handle = pricer._rl_curve_handle
    if not shift_bp:
        return handle
    return handle.shift(float(shift_bp))


class HorizonAgeingUnsupported(NotImplementedError):
    """Raised on the ``translate``-based ageing path. See the module docstring."""


def horizon_handle(
    pricer: Any,
    horizon_date: Optional[datetime.date] = None,
    shift_bp: float = 0.0,
) -> Any:
    """Shift the curve. ``horizon_date`` is refused -- see the module docstring.

    Kept as a named failure rather than deleted: ``translate``-based ageing is
    the intuitive thing to reach for, it runs without complaint, and it returns
    numbers that are merely wrong (0.000 bp of carry on a forward flattener,
    -531.94 bp on a 1y-aged 30Y payer). A loud refusal is the only safe
    behaviour. Use ``payoff_profile(..., carry_ccy=...)`` instead.
    """
    if horizon_date is not None:
        raise HorizonAgeingUnsupported(
            "Curve.translate() does not age a struck swap correctly here: it "
            "renormalises discount factors, which cancels for a DV01-neutral "
            "forward package (0.000bp of carry) and is meaningless once the "
            "swap's effective date precedes the translated curve's initial node "
            "(-531.94bp on a 1y-aged 30Y payer). Pass the horizon carry to "
            "payoff_profile(carry_ccy=...) instead, sourced from "
            "IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING x package DV01."
        )
    handle = pricer._rl_curve_handle
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


def matched_forward_swap_rate(
    pricer: Any,
    start: datetime.date,
    end: datetime.date,
    *,
    frequency: str = "Q",
    leg2_frequency: Optional[str] = "Q",
) -> float:
    """Par rate (in %) of an explicit-dated forward swap, at a chosen frequency.

    Exists because the frequency is not a detail here. Citi's matched-maturity
    swap is specified verbatim as *"both fixed and floating legs of this swap
    have a quarterly payment frequency"*, while the ``usd_irs`` rateslib spec
    this curve carries quotes **annual** fixed (``spec frequency: 'a'``). At a
    ~3.2% rate the compounding difference is ~3q^2/8 ~ 3.8bp -- the same order
    as the convexity adjustment being measured, so getting it wrong does not
    perturb the answer, it *is* the answer.

    Measured against Citi's published 13-pack SOFR screen (close 6/9/2023),
    computing the adjustment as ``pack_rate - this_rate``:

    ==================  ===================  ===================
    matched swap        mean error vs Citi   median error
    ==================  ===================  ===================
    spec default (ann)        -3.89 bp             -4.31 bp
    quarterly/quarterly       -0.11 bp             -0.58 bp
    ==================  ===================  ===================

    Pass ``frequency=None`` to fall back to the spec's own default.
    """
    handle = pricer._rl_curve_handle
    curve_def = pricer._curve_definition()
    kwargs: dict = {}
    if frequency is not None:
        kwargs["frequency"] = frequency
    if leg2_frequency is not None:
        kwargs["leg2_frequency"] = leg2_frequency
    swap = rl.IRS(
        effective=_as_dt(start),
        termination=_as_dt(end),
        spec=curve_def["ReferenceRate"],
        curves=handle,
        notional=1e6,
        **kwargs,
    )
    return float(swap.rate(curves=handle).real)


def payoff_profile(
    pricer: Any,
    package: Sequence[Any],
    shifts: Iterable[float],
    horizon_date: Optional[datetime.date] = None,
    *,
    net_of_spot: bool = True,
    carry_ccy: float = 0.0,
) -> np.ndarray:
    """P&L of *package* across terminal parallel shifts, in currency.

    ``net_of_spot=True`` subtracts today's NPV so the profile is a P&L relative
    to inception -- ~0 for a package struck at market today.

    ``carry_ccy`` is the horizon carry-and-roll of the package **in currency**,
    added as a level to every point. This is how the note's "aged flattener at
    fixed coupon" enters: the convexity is the *shape* of the profile and the
    carry is its *level*, and a long-gamma position only pays if the shape beats
    the level. For a negative-carry flattener pass a negative number; the
    resulting profile then sits below zero at small shifts and lifts in both
    tails, which is exactly the option-like payoff Exhibit 3 draws.

    Source it from ``IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING`` (with ``horizon``
    in ``structure_kwargs``) times the package DV01 -- an independent, validated
    code path. Do NOT try to get it from ``horizon_date``; see the module
    docstring for why that path is refused.
    """
    shifts = np.asarray(list(shifts), dtype=float)
    base = package_npv(pricer, package, horizon_date=None, shift_bp=0.0) if net_of_spot else 0.0
    out = np.empty(shifts.shape[0], dtype=float)
    for i, s in enumerate(shifts):
        out[i] = package_npv(pricer, package, horizon_date=horizon_date, shift_bp=float(s)) - base
    return out + float(carry_ccy)
