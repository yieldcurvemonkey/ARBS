"""Static-curve carry and roll for a single swap leg — one kernel, both backends.

Why this module exists
----------------------
``carry_bps_running`` / ``roll_bps_running`` / ``carry_and_roll_bps_running``
were implemented twice, once per backend, and both copies aged the instrument
the same wrong way: they rolled the MATURITY back by the horizon and left the
EFFECTIVE date where it was. For a spot-starting swap that is right by accident
— the effective date is the spot date before and after, so shortening the
maturity does produce the shorter spot swap. For a FORWARD-starting swap it is
a different instrument entirely::

    10Yx10Y aged by 1Y      was  10Y x 9Y     (tail shortened)
                            is    9Y x 10Y     (start brought nearer)

Measured against Citi's published Figure-7 carry screen (close of 2019-05-08,
USD, eight forward-forward pairs, 1Y horizon —
``RVUtils.ConvexityRV.strat3_strikeless_vol.CITI_FIG7_SCREEN``), the shipped
maturity-only roll scored **|corr| 0.136 / MAE 1.578 bp** and got the rank
order wrong; the rule below scores **corr +0.991 / MAE 0.338 bp**, matching the
independently-validated rolled-curve reprice (0.991 / 0.354) that
``RVUtils.CvxSuite.carry`` had to be written to work around.

Two failures beyond the level error, both measured on the same curve:

* **Wrong sign, not just wrong size.** 20Yx1Y at a 3M horizon: shipped
  ``+0.702`` bp, correct ``-1.566`` bp, rolled-curve referee ``-1.622``.
* **Short tails blew up.** Any ``f x T`` with ``T <= horizon`` aged to a
  zero-or-negative-length swap: 10Yx1Y / 20Yx1Y / 5Yx1Y at a 1Y horizon all
  raised rateslib ``Schedule`` errors, and spot ``1Y`` at a 1Y horizon returned
  a spurious *exact* ``0.000`` (carry ``-2.348`` + roll ``+2.348``) rather than
  saying the quantity does not exist.

The ageing rule
---------------
One rule covers every start date. Under an UNCHANGED curve, ``h`` from now the
instrument's own calendar dates sit ``h`` nearer, so **both** ends move::

    spot      ``spot x T``   ->  ``spot x (T-h)``     the SHORTER SPOT rate
    forward   ``f x T``      ->  ``(f-h) x T``        the NEARER FORWARD rate
    partial   ``f x T``, ``f < h``  ->  ``spot x (T - (h-f))``   start floored at spot

The effective date is floored at the spot date because a swap cannot start in
the past on a par-rate curve; that floor is what makes the spot row fall out of
the same construction rather than needing a special case. This is the same
convention as ``RVUtils.CurveFlyScreener.screener.age`` — deliberately, so the
Query value and the screener kernel cannot drift apart.

The decomposition
-----------------
With ``R_today`` the swap's par rate, ``R_fwd`` the par rate of the piece that
is still outstanding at the horizon (start ``max(effective, spot+h)``, same
maturity) and ``R_aged`` the aged instrument's par rate::

    carry = R_fwd  - R_today          the accrual: what the forwards pay you
    roll  = R_today - R_aged          the slide down today's curve
    total = R_fwd  - R_aged           carry + roll, exactly

**Sign is RECEIVER-of-this-leg**: positive means the leg's rate falls over the
horizon, which is what a receiver of fixed earns. A package aggregates as
``sum(risk_weight_i * value_i)`` in :mod:`Query.IRSwaps.IRSwapValue`, so the
package number is the P&L of the position those risk weights describe, in bp of
the package's own quoted level. (Note the asymmetry with ``IRSwapValue.RATE``,
which for a FLY normalises the direction through ``_swap_structure_sign_mapper``
so the quoted level is always belly-positive. Carry does NOT normalise: it
follows the position. A fly quoted long-belly and a fly quoted short-belly
therefore share a RATE and carry equal and opposite carries.)

``carry`` is identically zero for a swap that has not started by the horizon —
nothing has accrued — and that falls out of ``R_fwd == R_today`` rather than
being asserted by a guard, so it stays continuous as the start date crosses
``spot + h``.

This is the STATIC-CURVE convention, not forwards-realised. Comparing a spot
``T``y swap against the ``h x (T-h)`` forward *is* the forwards-realised
convention in disguise: under it a par swap's carry-and-roll is identically
zero and a screen ranks nothing. Here the ``h x (T-h)`` forward appears only as
``R_fwd``, one of the two terms.

What this is NOT
----------------
Not a full revaluation. ``R_aged`` prices a par instrument with the aged
coordinates; it does not book the accrued floating coupon of the elapsed
segment, which is why a spot leg's number here and a ``curve.roll(h)`` reprice
of the same seasoned swap differ by that wedge (measured 2019-05-08 USD-SOFR-1D:
forward legs agree to <= 0.06 bp, spot legs do not agree by construction). For
a dollar P&L attribution that must include the accrued coupon, reprice; for the
bp-of-rate number every screen and every published bank carry table quotes, this
is it.
"""
from __future__ import annotations

import datetime
from typing import Any, Tuple

__all__ = [
    "aged_dates",
    "carry_bps_running",
    "roll_bps_running",
    "carry_and_roll_bps_running",
]


def _as_date(value: Any) -> datetime.date:
    """Anything date-shaped -> ``datetime.date``, for ORDERING only.

    The originals are what get handed back to ``build_irswap`` — the backends
    read ``.year/.month/.day`` off them and a normalised copy would be an extra
    place for a timezone or a ``Timestamp`` nanosecond to go missing.
    """
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    to_pydatetime = getattr(value, "to_pydatetime", None)
    if to_pydatetime is not None:
        return to_pydatetime().date()
    raise TypeError(f"cannot order a date of type {type(value).__name__}: {value!r}")


def _describe(curve: Any, irswap: Any) -> str:
    try:
        return f"{_as_date(curve.effective_date(irswap))} -> {_as_date(curve.maturity_date(irswap))}"
    except Exception:  # noqa: BLE001 - only used to decorate an error message
        return "<unprintable swap>"


def horizon_start(curve: Any, horizon: str) -> Any:
    """The spot date ``horizon`` forward — where a swap traded then would start.

    Measured from the SPOT date, not the curve's reference date. The two differ
    by the settlement lag (2 business days in USD), which is worth 0.02 bp of
    carry on a 2Y and 0.023 bp on a 5Y — immaterial to any decision, but taking
    the spot base is what makes ``carry == 0`` switch on at exactly the start
    date where ``roll``'s effective-date floor stops binding.
    """
    return curve.calendar_advance(curve.spot_date(), horizon)


def aged_dates(curve: Any, irswap: Any, horizon: str) -> Tuple[Any, Any]:
    """``(effective, maturity)`` of the instrument aged by ``horizon``.

    Both ends move back by the horizon; the effective date is floored at the
    curve's spot date. Raises when the aged instrument would have no life left
    — a swap with nothing to run is not a rate, and returning a number there is
    how ``0Dx1Y`` at a 1Y horizon used to report an exact ``0.000``.
    """
    spot = curve.spot_date()
    effective = curve.effective_date(irswap)
    maturity = curve.maturity_date(irswap)

    aged_effective = curve.calendar_advance(effective, f"-{horizon}")
    if _as_date(aged_effective) < _as_date(spot):
        aged_effective = spot
    aged_maturity = curve.calendar_advance(maturity, f"-{horizon}")

    if _as_date(aged_maturity) <= _as_date(aged_effective):
        raise ValueError(
            f"cannot age {_describe(curve, irswap)} by {horizon}: the aged swap would run "
            f"{_as_date(aged_effective)} -> {_as_date(aged_maturity)}, i.e. no time left. "
            "The instrument does not survive the horizon, so its static-curve roll is not "
            "a rate. Use a shorter horizon or drop the point."
        )
    return aged_effective, aged_maturity


def carry_bps_running(curve: Any, irswap: Any, horizon: str) -> float:
    """``R_fwd - R_today`` in bp; receiver sign. Zero before the swap starts."""
    start = horizon_start(curve, horizon)
    effective = curve.effective_date(irswap)
    if _as_date(effective) >= _as_date(start):
        # Nothing has accrued by the horizon: R_fwd IS R_today.
        return 0.0

    maturity = curve.maturity_date(irswap)
    if _as_date(maturity) <= _as_date(start):
        raise ValueError(
            f"cannot compute carry for {_describe(curve, irswap)} over {horizon}: the swap "
            f"matures on {_as_date(maturity)}, on or before the horizon date {_as_date(start)}, "
            "so there is no outstanding swap left to quote a running rate on."
        )
    fwd = curve.build_irswap(effective_date=start, maturity_date=maturity)
    return (float(curve.fair_rate(fwd)) - float(curve.fair_rate(irswap))) * 10_000.0


def roll_bps_running(curve: Any, irswap: Any, horizon: str) -> float:
    """``R_today - R_aged`` in bp; receiver sign."""
    aged_effective, aged_maturity = aged_dates(curve, irswap, horizon)
    aged = curve.build_irswap(effective_date=aged_effective, maturity_date=aged_maturity)
    return (float(curve.fair_rate(irswap)) - float(curve.fair_rate(aged))) * 10_000.0


def carry_and_roll_bps_running(curve: Any, irswap: Any, horizon: str) -> float:
    """``R_fwd - R_aged`` in bp; receiver sign. Exactly ``carry + roll``."""
    return carry_bps_running(curve, irswap, horizon) + roll_bps_running(curve, irswap, horizon)
