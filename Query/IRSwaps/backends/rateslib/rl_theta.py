r"""Daily theta of a swap, split into cashflows / forwarding / rolldown / option.

The quantity
------------
``theta = PV(start of day) - PV(end of day)``, in the curve's currency, over one
business day by default. **Positive theta means the position's PV decays over
the day.** (Opposite to the ``*_BPS_RUNNING`` family in
:mod:`Query.IRSwaps._carry_roll`, which is quoted receiver-positive in bp of
rate. These are different measurements in different units; do not add them.)

The three PVs
-------------
Write ``T`` for the curve's reference date, ``T+h`` for the horizon date,
``D(T,t)`` for today's discount factor and ``D1 = D(T, T+h)``.

``pv_sod``
    ``npv(swap)`` on today's curve, valued at ``T``.

``pv_fwd`` — *the forwards are realised.*
    The curve at ``T+h`` becomes exactly what today's curve implied:
    ``D_fwd(T+h, t) = D(T,t)/D1``. So

        pv_fwd = (pv_sod - CF) / D1,   CF = PV at T of cashflows paying in (T, T+h]

    This is computed from the identity, not from ``Curve.translate`` — but it is
    the same number: measured 2019-05-08 USD-SOFR-1D on a 10Y struck 10 bp off
    par, ``npv(curves=handle.translate(T+1b))`` and ``(pv_sod - CF)/D1`` agree to
    the cent (-903,724.70 both). ``translate`` is not used because this repo has
    it recorded as defective for seasoned swaps over long horizons
    (``docs/convexityrv/results/strat1-jpm-curve-as-gamma.md``); the closed form
    has no such failure mode.

``pv_eod`` — *nothing happens.*
    The curve keeps today's shape as a function of tenor, so at ``T+h`` a flow
    ``u`` years out is discounted at today's ``u``-year rate. ``Curve.roll(h)``
    produces that shape while keeping its anchor at ``T``, i.e.
    ``R(T, t) = D(T, t-h) * k`` for some normalisation ``k``. Re-anchoring
    divides ``k`` out::

        pv_eod = (npv(swap | R) - CF_R) / R(T, T+h)

    ``R(T,T+h)`` is NOT 1 — measured 2019-05-08 it is 0.9999403610573026, and
    dividing by it is what makes every number below independent of ``k``
    (``tests/test_irswap_theta.py`` pins that). Keeping the anchor at ``T`` is
    the point of using ``roll``: no elapsed fixing is ever consulted, at any
    horizon, because the valuation date never moves.

The decomposition
-----------------
::

    cashflows  = CF / D1                       the cash that left the PV, at T+h
    forwarding = -pv_sod * (1/D1 - 1)          the funding accretion of the MtM
    rolldown   = pv_fwd - pv_eod               forwarded curve -> rolled curve
    option     = 0                             a vanilla IRS has no optionality
    ---------------------------------------------------------------------------
    theta      = pv_sod - pv_eod               exactly, with no residual

``forwarding`` is ``-MtM x (1/D1 - 1) ~= -MtM x r_1b x dcf``: an in-the-money
position accretes, so its theta contribution is negative. ``rolldown`` is
``~ delta x (today's rates - the h-forward-implied rates)``. Measured on the 1b
horizon, 2019-05-08 USD-SOFR-1D, $100mm 10Y payer: rolldown 632.91 against
``pv01 x roll_bps_running("1b")`` of 607.71. Those two are NOT the same measure
and only sometimes agree to a few percent — see fact 1 below before reading
anything into their ratio.

``option`` is structurally zero here and exists so the four parts sum to
``theta`` for any package this module is asked about; a package carrying real
optionality does not come through :class:`IRSwapValue`.

``cashflows`` is the cash **valued at the horizon date** — ``cf * D(T,t_pay)/D1``
is the flow carried forward from its payment date at the curve's own rate. It
carries the sign of the cash: a payer that pays a net coupon reports a negative
``cashflows``, and its PV decays LESS because a liability left the book.

Theta is PV decay, not P&L, and the two differ by exactly that term::

    P&L over the horizon = (pv_eod - pv_sod) + cash received
                         = -(forwarding + rolldown + option)

so the cashflow term cancels out of P&L — receiving a coupon moves value from
the PV to the bank account, it does not create any. Do not add ``cashflows`` to
a P&L that already nets ``theta``.

Three measured facts about the rolled curve
-------------------------------------------
**1. It is accurate in bp and noisy in ratio.** ``Curve.roll`` re-derives
discount factors at the curve's EXISTING node dates, so it resamples the
translated shape rather than reproducing it. Measured at a 1b horizon,
``rate(swap | roll("1b"))`` against the aged-instrument par rate
(``roll_bps_running``), USD-SOFR-1D, nine legs from 2Y to 40Yx10Y:

===========  ==========  ==============  ==================
date         nodes       worst gap (bp)  typical gap (bp)
===========  ==========  ==============  ==================
2019-05-08   26          0.007           0.001 - 0.003
2026-08-21   45          0.040           0.001 - 0.013
===========  ==========  ==============  ==================

That is small in bp and can be enormous as a RATIO, because a one-day rolldown
is itself only 0.001 - 0.04 bp. On 2019-05-08 the spot 5Y's rolldown is +0.0012
bp by the aged-instrument measure and -0.0056 bp by this one — the two disagree
on the SIGN of a number that neither resolves. Read a one-day rolldown as
dollars with a ~0.04 bp/pv01 uncertainty band, not as a precise rate.
Aggregating a month of them is fine; ranking two similar legs on one day is not.

**2. Fidelity degrades with the horizon**, because the resampling error grows
while the signal grows only linearly. Measured against the aged-instrument rate:
0.04 bp worst at ``1b``, 0.30 bp at ``1M``, 2.35 bp at ``1Y``. The default
horizon is one business day; past a month use
``CARRY_AND_ROLL_BPS_RUNNING``, which ages the instrument instead of resampling
the curve.

**3. Do not "fix" it by shifting the node dates.** Building the static curve
directly — nodes ``{d_i + h: D(T, d_i)}`` — looks exact and measures worse:
the business-day adjustment merges and distorts the front nodes, and the anchor
stub swallows the first segment. Measured at 1b on the same nine legs, worst
error 0.43 bp anchored at ``T+h`` and 0.21 bp anchored at ``T``, against
``roll``'s 0.04. It also reseasons every spot swap the moment the horizon
exceeds the settlement lag, which ``roll`` never does because its anchor never
moves.

One consequence of the node set worth knowing: the 2019-05-08 curve's first node
interval runs to 2021-05-10 as a single flat forward, so a shape translation
moves nothing inside it and the spot 2Y's rolldown is **exactly 0.00** on that
date. The 2026-08-21 curve has 45 nodes and its 2Y reports 1,171 on $100mm. That
is the curve's node set talking, not this code.

"""
from __future__ import annotations

import datetime
from typing import Any, Dict

import pandas as pd
import rateslib as rl

__all__ = ["theta_components", "THETA_KEYS"]

#: The dict keys :func:`theta_components` returns, in decomposition order.
THETA_KEYS = ("cashflows", "forwarding", "rolldown", "option", "theta")

#: One business day. The measurement this module is built for.
DEFAULT_HORIZON = "1b"


def _rl_dt(value: Any) -> datetime.datetime:
    ts = pd.Timestamp(value)
    return rl.dt(ts.year, ts.month, ts.day)


def _pv_and_window_cashflows(irswap: Any, curve: Any, start: pd.Timestamp,
                             end: pd.Timestamp) -> tuple:
    """``(total PV, PV of cashflows paying in (start, end])`` on ``curve``.

    Read off one ``cashflows`` table rather than an ``npv`` call plus a separate
    table, so the two are guaranteed to be the same valuation.
    """
    table = irswap.cashflows(curves=curve)
    # Not ``pd.to_numeric(..., errors="coerce")``: that turns anything it cannot
    # read into NaN, and a NaN row would silently drop a cashflow out of the
    # total instead of saying so. ``.real`` handles a Dual-valued column.
    npv = table["NPV"].map(lambda v: float(getattr(v, "real", v)))
    if bool(npv.isna().any()):
        raise ValueError(
            f"{int(npv.isna().sum())} of {len(npv)} cashflow rows priced to NaN on this "
            "curve; theta would be attributing a PV that is missing legs. Check the "
            "curve's span against the instrument's maturity."
        )
    payment = pd.to_datetime(table["Payment"])
    total = float(npv.sum())
    in_window = (payment > start) & (payment <= end)
    window = float(npv[in_window].sum()) if bool(in_window.any()) else 0.0
    return total, window


def theta_components(curve: Any, irswap: Any, horizon: str = DEFAULT_HORIZON) -> Dict[str, float]:
    """The four components and their total, in the curve's currency.

    ``curve`` is an :class:`RLIRSwapCurve`; ``irswap`` an ``rl.IRS`` it built.
    Sign convention and definitions are in the module docstring.
    """
    handle = curve.handle()
    reference = pd.Timestamp(curve.reference_date())
    horizon_date = pd.Timestamp(curve.calendar_advance(curve.reference_date(), horizon))
    if horizon_date <= reference:
        raise ValueError(
            f"theta horizon {horizon!r} does not advance the curve's reference date "
            f"({reference.date()} -> {horizon_date.date()}); theta over no elapsed time "
            "is not a measurement."
        )

    rolled = curve.roll_curve(horizon)

    pv_sod, cf_today = _pv_and_window_cashflows(irswap, handle, reference, horizon_date)
    pv_rolled, cf_rolled = _pv_and_window_cashflows(irswap, rolled, reference, horizon_date)

    d1 = float(handle[_rl_dt(horizon_date)])
    if not d1 > 0.0:
        raise ValueError(
            f"today's curve returned a non-positive discount factor {d1!r} at the horizon "
            f"date {horizon_date.date()}; theta cannot be attributed against it."
        )

    # Dividing by the ROLLED curve's own horizon discount factor is what
    # re-anchors it at T+h, and it is required, not cosmetic. The rolled curve
    # keeps its anchor at T and carries the translated shape times some constant
    # k: R(T, t) = D(T, t-h) * k. Re-anchoring divides that constant out,
    # R(T,t)/R(T,T+h) = D(T,t-h), which is the static curve seen from T+h.
    # (Measured 2019-05-08 USD-SOFR-1D: R(T,T+1b) = 0.9999403610573026, equal to
    # today's D1 to the last digit but ONLY because that curve's first node
    # interval is a single flat forward - do not read it as 1.)
    d1_rolled = float(rolled[_rl_dt(horizon_date)])
    if not d1_rolled > 0.0:
        raise ValueError(
            f"the rolled curve returned a non-positive discount factor {d1_rolled!r} at "
            f"{horizon_date.date()}."
        )

    pv_fwd = (pv_sod - cf_today) / d1
    pv_eod = (pv_rolled - cf_rolled) / d1_rolled

    cashflows = cf_today / d1
    forwarding = -pv_sod * (1.0 / d1 - 1.0)
    rolldown = pv_fwd - pv_eod
    option = 0.0
    theta = pv_sod - pv_eod

    return {
        "cashflows": cashflows,
        "forwarding": forwarding,
        "rolldown": rolldown,
        "option": option,
        "theta": theta,
        # Provenance, so a caller can see the three PVs the split came from.
        "pv_sod": pv_sod,
        "pv_fwd": pv_fwd,
        "pv_eod": pv_eod,
        "horizon_date": horizon_date,
    }
