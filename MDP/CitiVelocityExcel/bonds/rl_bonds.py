r"""rateslib fixed-rate bonds built from a Citi Velocity :class:`BondDescriptor`.

Velocity gives quotes, never instruments: ``RATES.BOND.<ISIN>.PRICE`` is a
number and ``CVCURVEBOND`` gives ``T 4.25 05/31/2033``. The bond object has to be
assembled here, from the parsed description plus the per-country table in
:mod:`MDP.CitiVelocityExcel.bonds.conventions`.

There is no issue date, and it does not matter
----------------------------------------------
``CVCURVEBOND`` returns no issue or dated date, so the coupon schedule is rolled
**backward from maturity** to a pseudo-issue two whole coupon periods before
settlement. Every metric quoted at settlement is invariant to that choice, and
this was measured rather than assumed - on T 4.25 05/31/2033 at 99.50 clean,
settle 2026-08-06, the true issue (2023-05-31) and pseudo-issues at 2025-11-30,
2026-05-31 and 2013-05-31 all give ytm 4.333684051098%, accrued 0.778005464481
and risk 5.834566571 to twelve decimal places. The same held on the QuantLib
side. Any front stub the roll-back creates lies entirely before settlement and
so cannot touch the current accrual period or any surviving cashflow.

Sign convention - ONE, and it is positive for a long
-----------------------------------------------------
This repo has a recorded sign trap: QuantLib's raw ``basisPointValue`` is
NEGATIVE for a long bond and ``QLFixedRateBondPricer`` patches it with
``np.copysign(|BPV|, notional)``, while rateslib's ``duration(..., "risk")`` is
already positive. Rather than inherit either, both backends in this package
report

* ``bps``  - price points lost per 100 face for a **+1bp** move in yield,
* ``dv01`` - currency lost on the bond's own notional for a **+1bp** move,

both **positive for a long position**. A short is expressed by negating the
position, never by flipping the metric.

What rateslib 2.1.1 will and will not do here
----------------------------------------------
``FixedRateBond`` is real and complete for yield-space analytics. There is no
rateslib asset-swap machinery, so par-par ASW lives on the QuantLib side in
:func:`~MDP.CitiVelocityExcel.bonds.ql_bonds.ql_asset_swap_spread`. The
``curve=`` argument here uses ``npv`` and ``oaspread``, which are curve-space
and *not* the same quantity as an asset-swap spread.
"""

from __future__ import annotations

import calendar as _calendar
import datetime
import logging
from typing import Any, Dict, Optional

from MDP.CitiVelocityExcel.bonds.conventions import BondConvention, conventions_for
from MDP.CitiVelocityExcel.bonds.universe import BondDescriptor

__all__ = [
    "build_rl_bond",
    "rl_bond_metrics",
    "rl_settlement_date",
    "pseudo_issue_date",
    "SCHEDULE_BACKSTOP_PERIODS",
]

_logger = logging.getLogger(__name__)

#: Extra whole coupon periods the pseudo-issue is pushed beyond settlement, so
#: any front stub the roll-back creates sits strictly before the current accrual
#: period. Two is belt and braces: invariance was measured at zero extra periods.
SCHEDULE_BACKSTOP_PERIODS = 2

#: Hard cap on the roll-back loop. The longest bond in the Velocity universe is
#: ``NRW 2.15 03/21/2119`` at ~93 annual periods; 2,000 leaves room for a
#: monthly schedule on a century bond and still terminates on a malformed input.
_MAX_ROLLBACK_PERIODS = 2_000


def _add_months(d: datetime.date, months: int, *, eom: bool) -> datetime.date:
    """Shift a date by whole months, honouring an end-of-month roll rule."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    last = _calendar.monthrange(year, month)[1]
    if eom and d.day == _calendar.monthrange(d.year, d.month)[1]:
        return datetime.date(year, month, last)
    return datetime.date(year, month, min(d.day, last))


def pseudo_issue_date(
    *,
    maturity: datetime.date,
    anchor: datetime.date,
    conv: BondConvention,
    backstop: int = SCHEDULE_BACKSTOP_PERIODS,
) -> datetime.date:
    """A schedule start on the coupon grid, safely before ``anchor``.

    Rolls ``maturity`` backward one coupon period at a time until it is at or
    before ``anchor``, then ``backstop`` periods further. See the module
    docstring for the measured invariance that makes this sound.
    """
    step = conv.months_per_period
    k = 0
    date = maturity
    while date > anchor and k < _MAX_ROLLBACK_PERIODS:
        k += 1
        date = _add_months(maturity, -k * step, eom=conv.eom)
    if k >= _MAX_ROLLBACK_PERIODS:
        raise ValueError(
            f"Rolling {maturity} back to {anchor} at {step}-month steps exceeded "
            f"{_MAX_ROLLBACK_PERIODS} periods. Check the maturity parsed from the description."
        )
    return _add_months(maturity, -(k + max(0, int(backstop))) * step, eom=conv.eom)


def rl_settlement_date(
    *,
    descriptor: BondDescriptor,
    as_of: Optional[datetime.date] = None,
    conventions: Optional[BondConvention] = None,
) -> Any:
    """The rateslib settlement date for ``as_of`` under the country's lag.

    Returns a ``datetime.datetime``, which is what every rateslib bond method
    expects for ``settlement``.
    """
    import rateslib as rl

    conv = conventions or conventions_for(descriptor.country)
    ref = as_of or datetime.date.today()
    return rl.add_tenor(
        rl.dt(ref.year, ref.month, ref.day),
        f"{conv.settlement_days}B",
        "F",
        conv.rl_calendar_object(),
    )


# ------------------------------------------------------------------ #
#                             the builder                            #
# ------------------------------------------------------------------ #


def build_rl_bond(
    *,
    descriptor: BondDescriptor,
    settlement_date: Optional[datetime.date] = None,
    conventions: Optional[BondConvention] = None,
    notional: float = 100.0,
    issue_date: Optional[datetime.date] = None,
) -> Any:
    """Build a :class:`rateslib.FixedRateBond` from a Velocity descriptor.

    Parameters
    ----------
    descriptor
        A parsed :class:`~MDP.CitiVelocityExcel.bonds.universe.BondDescriptor`.
        Must be ``priceable`` - both a fixed coupon and a maturity are required.
    settlement_date
        Date the schedule must reach back past. Defaults to today. This is the
        anchor for the pseudo-issue roll-back, not a property of the bond.
    conventions
        Override the per-country table, e.g. to price a CGB as an annual payer.
    notional
        Face amount. Defaults to 100 so that price and NPV are in the same
        units; ``dv01`` from :func:`rl_bond_metrics` scales with it.
    issue_date
        Use a known dated date instead of the rolled-back pseudo-issue.

    Returns
    -------
    rateslib.FixedRateBond

    Raises
    ------
    ValueError
        When the descriptor has no coupon or no maturity. It does NOT substitute
        a zero coupon: ten bonds in the universe are floaters (``CCTS Float
        04/15/29``) and pricing one as a 0% fixed bond would be silently wrong.
    UnknownTagError
        When the descriptor's country is not in the convention table.
    """
    import rateslib as rl

    if descriptor.coupon is None:
        raise ValueError(
            f"{descriptor.isin} ({descriptor.description!r}) has no fixed coupon - it is a "
            "floater or the description did not parse. Pass a BondDescriptor with an explicit "
            "coupon, or fetch RATES.BOND.<ISIN>.YIELD and use the quote directly."
        )
    if descriptor.maturity is None:
        raise ValueError(
            f"{descriptor.isin} ({descriptor.description!r}) has no parsed maturity. "
            "Supply one via dataclasses.replace(descriptor, maturity=...)."
        )

    conv = conventions or conventions_for(descriptor.country)
    anchor = settlement_date or datetime.date.today()
    start = issue_date or pseudo_issue_date(maturity=descriptor.maturity, anchor=anchor, conv=conv)

    kwargs: Dict[str, Any] = {
        "effective": rl.dt(start.year, start.month, start.day),
        "termination": rl.dt(
            descriptor.maturity.year, descriptor.maturity.month, descriptor.maturity.day
        ),
        "fixed_rate": float(descriptor.coupon),
        "notional": float(notional),
    }
    if conv.rl_spec is not None:
        kwargs["spec"] = conv.rl_spec
    else:
        # No rateslib spec for this country: every field has to be explicit, and
        # the calendar is synthesised from QuantLib when rateslib has none.
        kwargs.update(
            frequency=conv.frequency,
            convention=conv.convention,
            calendar=conv.rl_calendar_object(),
            currency=conv.currency.lower(),
            modifier="none" if conv.business_day_convention == "Unadjusted" else "MF",
            payment_lag=0,
            settle=conv.settlement_days,
            ex_div=conv.ex_div_days,
            eom=conv.eom,
            stub=conv.rl_stub,
            calc_mode=conv.rl_calc_mode,
        )
    return rl.FixedRateBond(**kwargs)


# ------------------------------------------------------------------ #
#                              metrics                               #
# ------------------------------------------------------------------ #


def _rl_notional(bond: Any) -> float:
    try:
        return float(bond.kwargs.leg1["notional"])
    except Exception:  # pragma: no cover - defensive, rateslib always sets it
        return 100.0


def rl_bond_metrics(
    *,
    bond: Any,
    settlement: Any,
    price: Optional[float] = None,
    ytm: Optional[float] = None,
    curve: Any = None,
) -> Dict[str, Any]:
    """Yield-space analytics for a rateslib bond, in this package's sign convention.

    Parameters
    ----------
    bond
        A :class:`rateslib.FixedRateBond`, typically from :func:`build_rl_bond`.
    settlement
        Settlement date. A ``date`` is accepted and promoted to ``datetime``.
    price
        Clean price per 100 face. Mutually exclusive with ``ytm``.
    ytm
        Yield to maturity in PERCENT. Mutually exclusive with ``price``.
    curve
        Optional rateslib curve (or ``Curves`` input). When given, ``npv``,
        ``curve_dirty``, ``curve_clean`` and ``zspread`` are added. ``npv`` is
        sign-flipped from rateslib's own output so that a long position is
        POSITIVE, matching the QuantLib side; the untouched number is kept as
        ``npv_rl_raw``. ``zspread`` is a curve-space z-spread from ``oaspread``;
        it is NOT an asset-swap spread - use
        :func:`~MDP.CitiVelocityExcel.bonds.ql_bonds.ql_asset_swap_spread` for
        that.

    Returns
    -------
    dict
        ``ytm`` (percent), ``clean``, ``dirty``, ``accrued`` (all per 100 face),
        ``mod_duration``, ``macaulay`` (years), ``convexity``, ``bps``, ``dv01``,
        ``notional``, ``settlement``, ``backend``.

        ``convexity`` is normalised to the textbook / QuantLib convention
        ``(1/P_dirty) d2P/dy2`` with ``y`` in decimal. rateslib's native
        ``convexity()`` is ``d2P/dy2`` with ``y`` in PERCENT and no division by
        price, so it is multiplied by ``10000 / dirty``; the raw number is kept
        as ``convexity_rl_raw``.

        ``bps`` and ``dv01`` are POSITIVE for a long position - see the module
        docstring.

    Raises
    ------
    ValueError
        When neither or both of ``price`` and ``ytm`` are given.
    """
    if (price is None) == (ytm is None):
        raise ValueError(
            "Pass exactly one of price= (clean, per 100) or ytm= (percent). "
            "Passing neither leaves the bond unpriced; passing both is ambiguous."
        )

    if isinstance(settlement, datetime.date) and not isinstance(settlement, datetime.datetime):
        settlement = datetime.datetime(settlement.year, settlement.month, settlement.day)

    y = float(bond.ytm(price=float(price), settlement=settlement, dirty=False)) if ytm is None else float(ytm)
    clean = float(bond.price(ytm=y, settlement=settlement, dirty=False))
    dirty = float(bond.price(ytm=y, settlement=settlement, dirty=True))
    accrued = float(bond.accrued(settlement))

    risk = float(bond.duration(y, settlement, "risk"))  # -dP/dy, y in percent, per 100 face
    bps = abs(risk) / 100.0  # price points per 1bp per 100 face
    notional = _rl_notional(bond)
    convexity_raw = float(bond.convexity(y, settlement))

    out: Dict[str, Any] = {
        "backend": "rateslib",
        "settlement": settlement.date() if isinstance(settlement, datetime.datetime) else settlement,
        "notional": notional,
        "ytm": y,
        "clean": clean,
        "dirty": dirty,
        "accrued": accrued,
        "mod_duration": float(bond.duration(y, settlement, "modified")),
        "macaulay": float(bond.duration(y, settlement, "duration")),
        "convexity": convexity_raw * 10_000.0 / dirty if dirty else float("nan"),
        "convexity_rl_raw": convexity_raw,
        "bps": bps,
        "dv01": bps * notional / 100.0,
    }

    if curve is not None:
        # rateslib prices a bond as the ISSUER's leg: npv is NEGATIVE for a
        # positive notional (measured -101.981374 where QuantLib's PV of the same
        # cashflows is +101.99). Both backends here report the value of HOLDING
        # the bond, so the sign is flipped once, here.
        raw_npv = float(bond.npv(curves=curve))
        out["npv"] = -raw_npv
        out["npv_rl_raw"] = raw_npv
        out["curve_dirty"] = -raw_npv * 100.0 / notional if notional else float("nan")
        out["curve_clean"] = out["curve_dirty"] - accrued
        try:
            out["zspread"] = float(bond.oaspread(curves=curve, price=clean, metric="clean_price"))
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            # A failed root-find is reported, not defaulted: a NaN z-spread that
            # looks like a number is exactly the failure mode _assert_risk_populated
            # exists to prevent.
            out["zspread"] = None
            out["zspread_error"] = f"{type(exc).__name__}: {exc}"
            _logger.warning("rateslib oaspread failed for a bond at settlement %s: %s", settlement, exc)

    return out
