r"""QuantLib fixed-rate bonds, and the par-par asset swap this repo did not have.

The QuantLib mirror of :mod:`MDP.CitiVelocityExcel.bonds.rl_bonds`: same
descriptor in, same metric keys out, same sign convention. Where the two
libraries genuinely disagree the difference is reported by ``_smoke.py`` rather
than papered over.

Asset swap: new code, and here is exactly what it computes
-----------------------------------------------------------
Nothing in this repo prices an asset swap. ``zspread()`` raises
``NotImplementedError`` on BOTH bond backends and ``SplineYAxis.ASW`` is an enum
value nothing reads. :func:`ql_asset_swap_spread` is therefore new, and it
implements the **par-par (par/par) asset swap spread**:

    the investor pays PAR for the package, receives the bond, pays the bond's
    coupons and receives floating + s on a par notional.

Setting the package value to zero at settlement gives

.. math::

    s \;=\; \frac{PV_{curve}(\text{all bond cashflows, incl. redemption})
                   \;-\; P_{dirty}}{\sum_i \tau_i \, df(t_i)\;\times\;100}

with everything valued forward to settlement. The floating leg does not appear
explicitly because, under a single curve (projection == discounting), its
coupons telescope: :math:`f_i \tau_i df(t_{i+1}) = df(t_i) - df(t_{i+1})`
exactly, whatever the day count.

**This was verified, not asserted.** Against ``ql.AssetSwap(...).fairSpread()``
on T 4.25 05/31/2033, clean 99.50, settle 2026-08-06, flat 4% continuous
Act/365 curve, USD-Libor-3M float leg:

===================================================  ==================
``ql.AssetSwap.fairSpread()``                        28.48844773818402 bp
this formula, same leg schedule                      28.48844773818407 bp
difference                                           4.8e-14 bp
===================================================  ==================

and pricing the bond ON the curve gives -2.4e-13 bp from QuantLib and exactly
0.0 here. The reconciliation only closes once the first floating fixing is set
to the curve-implied forward; leaving a stale 4% fixing in ``index.addFixing``
moved ``fairSpread()`` by 0.051 bp. That is a property of ``ql.AssetSwap``, not
of the formula, and is one reason this function does not use it: ``ql.AssetSwap``
requires an ``IborIndex`` **with a historical fixing loaded** and raises
``RuntimeError: Missing ... fixing`` without one, which is an unreasonable
demand when the input is a Citi OIS discount curve.

Single-curve assumption
-----------------------
Projection and discounting come from the same ``curve_handle``. With a Citi OIS
curve that is the natural OIS-discounted par-par ASW. It is **not** a
dual-curve Libor asset swap, and no tenor basis is applied.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, Optional

from MDP.CitiVelocityExcel.bonds.conventions import BondConvention, conventions_for
from MDP.CitiVelocityExcel.bonds.rl_bonds import pseudo_issue_date
from MDP.CitiVelocityExcel.bonds.universe import BondDescriptor, cross_currency_asw_legs

__all__ = [
    "build_ql_bond",
    "ql_bond_metrics",
    "ql_asset_swap_spread",
    "cross_currency_asw_legs",
    "to_ql_date",
]

_logger = logging.getLogger(__name__)

#: Default floating-leg conventions for the par-par asset swap. Quarterly Act/360
#: is the USD/EUR asset-swap market default. They only enter through the annuity
#: denominator, so a mis-set frequency changes the spread by roughly the
#: convexity of the annuity, not by a leg's worth of PV.
_DEFAULT_ASW_FLOAT_MONTHS = 3
_DEFAULT_ASW_FLOAT_DAY_COUNT = "Actual360"


def _ql() -> Any:
    import QuantLib as ql

    return ql


def to_ql_date(d: Any) -> Any:
    """Convert a ``date``/``datetime``/``ql.Date`` to a ``ql.Date``."""
    ql = _ql()
    if isinstance(d, ql.Date):
        return d
    return ql.Date(d.day, d.month, d.year)


def _from_ql_date(d: Any) -> datetime.date:
    return datetime.date(d.year(), d.month(), d.dayOfMonth())


# ------------------------------------------------------------------ #
#                             the builder                            #
# ------------------------------------------------------------------ #


def build_ql_bond(
    *,
    descriptor: BondDescriptor,
    evaluation_date: Optional[datetime.date] = None,
    conventions: Optional[BondConvention] = None,
    face: float = 100.0,
    issue_date: Optional[datetime.date] = None,
) -> Any:
    """Build a :class:`QuantLib.FixedRateBond` from a Velocity descriptor.

    Sets ``ql.Settings.instance().evaluationDate`` as a side effect, because
    QuantLib's settlement date, accrual and discounting all read that global.

    Parameters
    ----------
    descriptor
        A parsed :class:`~MDP.CitiVelocityExcel.bonds.universe.BondDescriptor`.
    evaluation_date
        Valuation date. Defaults to today. Settlement is this plus the country's
        settlement lag.
    conventions
        Override the per-country table.
    face
        Face amount. 100 keeps price and NPV in the same units.
    issue_date
        A known dated date instead of the rolled-back pseudo-issue. See
        :mod:`MDP.CitiVelocityExcel.bonds.rl_bonds` for the measured evidence
        that the pseudo-issue does not change any metric at settlement.

    Returns
    -------
    QuantLib.FixedRateBond

    Raises
    ------
    ValueError
        When the descriptor has no fixed coupon or no maturity - never silently
        priced as a 0% bond.
    """
    ql = _ql()

    if descriptor.coupon is None:
        raise ValueError(
            f"{descriptor.isin} ({descriptor.description!r}) has no fixed coupon - it is a "
            "floater or the description did not parse. QuantLib would happily build a 0% bond "
            "from it, which is why this raises instead."
        )
    if descriptor.maturity is None:
        raise ValueError(
            f"{descriptor.isin} ({descriptor.description!r}) has no parsed maturity. "
            "Supply one via dataclasses.replace(descriptor, maturity=...)."
        )

    conv = conventions or conventions_for(descriptor.country)
    eval_date = evaluation_date or datetime.date.today()
    ql.Settings.instance().evaluationDate = to_ql_date(eval_date)

    start = issue_date or pseudo_issue_date(maturity=descriptor.maturity, anchor=eval_date, conv=conv)
    bdc = conv.ql_bdc()
    schedule = ql.Schedule(
        to_ql_date(start),
        to_ql_date(descriptor.maturity),
        conv.ql_period(),
        conv.ql_calendar(),
        bdc,
        bdc,
        ql.DateGeneration.Backward,
        bool(conv.eom),
    )
    ex_period = ql.Period(int(conv.ex_div_days), ql.Days) if conv.ex_div_days else ql.Period()
    bond = ql.FixedRateBond(
        int(conv.settlement_days),
        float(face),
        schedule,
        [float(descriptor.coupon) / 100.0],
        conv.ql_day_count(schedule),
        bdc,
        100.0,
        ql.Date(),  # issueDate: left null, the schedule already carries the start
        conv.ql_calendar(),
        ex_period,
        conv.ql_ex_coupon_calendar(),
        ql.Unadjusted,
        False,
    )
    # A QuantLib bond does not carry its YIELD compounding frequency (BTPs pay
    # semi-annually and quote annually), so the convention record is stashed on
    # the SWIG proxy and picked up by ql_bond_metrics. Verified: SWIG proxies
    # accept arbitrary Python attributes.
    bond.citivelo_conventions = conv
    bond.citivelo_descriptor = descriptor
    return bond


# ------------------------------------------------------------------ #
#                              metrics                               #
# ------------------------------------------------------------------ #


def ql_bond_metrics(
    *,
    bond: Any,
    evaluation_date: datetime.date,
    clean_price: Optional[float] = None,
    ytm: Optional[float] = None,
    conventions: Optional[BondConvention] = None,
    curve_handle: Any = None,
    settlement_date: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """Yield-space analytics for a QuantLib bond, in this package's sign convention.

    Parameters
    ----------
    bond
        A :class:`QuantLib.FixedRateBond`, typically from :func:`build_ql_bond`.
    evaluation_date
        Valuation date; written to ``ql.Settings`` before anything is computed.
    clean_price
        Clean price per 100 face. Mutually exclusive with ``ytm``.
    ytm
        Yield to maturity in PERCENT. Mutually exclusive with ``clean_price``.
    conventions
        Supplies the YIELD compounding frequency and the YIELD day counter,
        neither of which a QuantLib bond carries. When ``None``, the record
        :func:`build_ql_bond` stashed on the bond is used; failing that the
        bond's own coupon frequency and accrual day counter are used, which is
        wrong for five countries - measured: ITA 2.93 bp (BTPs quote annually
        compounded), MEX 11.92 bp, BRA 6.07 bp, ZAF 1.00 bp, JPN 0.19 bp (all
        quote on coupon-period fractions while accruing Act/360, Bus/252 or
        Act/365F).
    curve_handle
        Optional ``ql.YieldTermStructureHandle``. When given, ``curve_clean``,
        ``curve_dirty`` and ``zspread`` are added.
    settlement_date
        Override the settlement QuantLib derives from the bond's settlement days.

    Returns
    -------
    dict
        The same keys as
        :func:`~MDP.CitiVelocityExcel.bonds.rl_bonds.rl_bond_metrics`: ``ytm``,
        ``clean``, ``dirty``, ``accrued``, ``mod_duration``, ``macaulay``,
        ``convexity``, ``bps``, ``dv01``, plus ``notional``, ``settlement`` and
        ``backend``.

        ``bps`` and ``dv01`` are POSITIVE for a long position. QuantLib's raw
        ``basisPointValue`` is negative for a long bond; this takes ``abs()``
        once, here, rather than leaving each caller to guess (the repo has a
        recorded case of that guess going wrong).

    Raises
    ------
    ValueError
        When neither or both of ``clean_price`` and ``ytm`` are given.

    Notes
    -----
    ``ql.BondFunctions.bps`` is deliberately NOT used. On an ActAct(ISMA) day
    counter bound to the coupon schedule it raises
    ``RuntimeError: Dates out of range of schedule: ... date 2: December 31st,
    2199``, because it prices against an internally constructed far-dated flat
    curve. ``basisPointValue`` computes the same sensitivity without that step
    and was verified to agree with rateslib's ``duration(..., "risk")/100``.
    """
    ql = _ql()

    if (clean_price is None) == (ytm is None):
        raise ValueError(
            "Pass exactly one of clean_price= (per 100) or ytm= (percent). "
            "Passing neither leaves the bond unpriced; passing both is ambiguous."
        )

    ql.Settings.instance().evaluationDate = to_ql_date(evaluation_date)
    settle = to_ql_date(settlement_date) if settlement_date is not None else bond.settlementDate()

    conv = conventions if conventions is not None else getattr(bond, "citivelo_conventions", None)
    if conv is not None:
        frequency = conv.ql_yield_frequency()
        day_counter = conv.ql_yield_day_counter(None)
    else:
        frequency = bond.frequency()
        day_counter = bond.dayCounter()

    if ytm is None:
        y = bond.bondYield(
            ql.BondPrice(float(clean_price), ql.BondPrice.Clean),
            day_counter,
            ql.Compounded,
            frequency,
            settle,
        )
    else:
        y = float(ytm) / 100.0

    rate = ql.InterestRate(y, day_counter, ql.Compounded, frequency)
    accrued = float(bond.accruedAmount(settle))
    clean = float(ql.BondFunctions.cleanPrice(bond, y, day_counter, ql.Compounded, frequency, settle))
    bpv = float(ql.BondFunctions.basisPointValue(bond, rate, settle))
    face = float(bond.notional(settle)) or float(bond.notional())

    out: Dict[str, Any] = {
        "backend": "quantlib",
        "settlement": _from_ql_date(settle),
        "notional": face,
        "ytm": y * 100.0,
        "clean": clean,
        "dirty": clean + accrued,
        "accrued": accrued,
        "mod_duration": float(ql.BondFunctions.duration(bond, rate, ql.Duration.Modified, settle)),
        "macaulay": float(ql.BondFunctions.duration(bond, rate, ql.Duration.Macaulay, settle)),
        "convexity": float(ql.BondFunctions.convexity(bond, rate, settle)),
        # basisPointValue is quoted on the bond's face; normalise to 100 face so
        # `bps` means the same thing on both backends, then scale back for dv01.
        "bps": abs(bpv) * 100.0 / face,
        "dv01": abs(bpv),
    }

    if curve_handle is not None:
        ts = curve_handle.currentLink() if hasattr(curve_handle, "currentLink") else curve_handle
        pv = _pv_at(bond, curve_handle, settle)
        out["curve_dirty"] = pv
        out["curve_clean"] = pv - accrued
        try:
            out["zspread"] = float(
                ql.BondFunctions.zSpread(
                    bond,
                    ql.BondPrice(clean, ql.BondPrice.Clean),
                    ts,
                    ql.Actual365Fixed(),
                    ql.Continuous,
                    ql.NoFrequency,
                    settle,
                )
            )
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            out["zspread"] = None
            out["zspread_error"] = f"{type(exc).__name__}: {exc}"
            _logger.warning("QuantLib zSpread failed at settlement %s: %s", _from_ql_date(settle), exc)

    return out


def _pv_at(bond: Any, curve_handle: Any, settle: Any) -> float:
    """PV of every bond cashflow after ``settle``, valued forward TO ``settle``.

    Per 100 face, so it is directly comparable with a quoted dirty price.
    """
    face = float(bond.notional(settle)) or 100.0
    df_settle = curve_handle.discount(settle)
    total = 0.0
    for cf in bond.cashflows():
        if cf.date() > settle:
            total += float(cf.amount()) * curve_handle.discount(cf.date())
    return total / df_settle * 100.0 / face


# ------------------------------------------------------------------ #
#                          par-par asset swap                        #
# ------------------------------------------------------------------ #


def ql_asset_swap_spread(
    *,
    bond: Any,
    clean_price: float,
    curve_handle: Any,
    evaluation_date: datetime.date,
    settlement_date: Optional[datetime.date] = None,
    float_frequency_months: int = _DEFAULT_ASW_FLOAT_MONTHS,
    float_day_count: Optional[Any] = None,
    float_calendar: Optional[Any] = None,
    float_convention: Optional[Any] = None,
    float_schedule: Optional[Any] = None,
) -> float:
    """The par-par asset swap spread, in basis points.

    See the module docstring for the derivation, the exact reconciliation
    against ``ql.AssetSwap.fairSpread()`` (4.8e-14 bp) and the single-curve
    assumption.

    Parameters
    ----------
    bond
        A :class:`QuantLib.FixedRateBond`.
    clean_price
        Market clean price per 100 face.
    curve_handle
        ``ql.YieldTermStructureHandle`` used for BOTH discounting and floating
        projection. With a Citi OIS curve this is an OIS-discounted par-par ASW.
    evaluation_date
        Valuation date; written to ``ql.Settings``.
    settlement_date
        Override the bond's own settlement date.
    float_frequency_months
        Floating coupon period in months. Default 3.
    float_day_count
        ``ql.DayCounter`` for the floating accruals. Default ``ql.Actual360()``.
    float_calendar
        Calendar for the floating schedule. Defaults to the bond's calendar.
    float_convention
        Business day convention for the floating schedule. Default
        ``ql.ModifiedFollowing``.
    float_schedule
        An explicit ``ql.Schedule`` (or any sequence of ``ql.Date``) for the
        floating leg, overriding the four parameters above. Used by ``_smoke.py``
        to reconcile exactly against ``ql.AssetSwap``'s own leg: with the
        generated default schedule the two agree to 3.3e-05 bp, and with the
        identical leg to 4.8e-14 bp. The residual is a leg-schedule difference,
        not a formula difference.

    Returns
    -------
    float
        Spread in basis points. Positive means the bond is CHEAP to the curve:
        the asset swap buyer receives floating plus that spread.

    Raises
    ------
    ValueError
        When the bond has already matured at settlement, or when the floating
        annuity is non-positive - both cases would otherwise divide by ~0 and
        return a huge finite number that reads like a signal.
    """
    ql = _ql()

    ql.Settings.instance().evaluationDate = to_ql_date(evaluation_date)
    settle = to_ql_date(settlement_date) if settlement_date is not None else bond.settlementDate()
    maturity = bond.maturityDate()
    if maturity <= settle:
        raise ValueError(
            f"Bond matures {_from_ql_date(maturity)} which is on or before settlement "
            f"{_from_ql_date(settle)}; there is no asset swap to price."
        )

    day_count = float_day_count or getattr(ql, _DEFAULT_ASW_FLOAT_DAY_COUNT)()
    if float_schedule is not None:
        dates = [to_ql_date(d) for d in float_schedule]
    else:
        cal = float_calendar or bond.calendar()
        bdc = ql.ModifiedFollowing if float_convention is None else float_convention
        dates = list(
            ql.Schedule(
                settle,
                maturity,
                ql.Period(int(float_frequency_months), ql.Months),
                cal,
                bdc,
                bdc,
                ql.DateGeneration.Forward,
                False,
            )
        )
    if len(dates) < 2:
        raise ValueError(
            f"The floating schedule has {len(dates)} date(s); at least two are needed to form an "
            "annuity. Check float_frequency_months against the time to maturity."
        )
    df_settle = curve_handle.discount(settle)
    annuity = 0.0
    for i in range(len(dates) - 1):
        tau = day_count.yearFraction(dates[i], dates[i + 1])
        annuity += tau * curve_handle.discount(dates[i + 1]) / df_settle
    if annuity <= 0.0:
        raise ValueError(
            "The floating-leg annuity came out non-positive "
            f"({annuity:.6g}) for a bond maturing {_from_ql_date(maturity)}. "
            "Check float_frequency_months and the curve handle - a zero annuity would make the "
            "spread arbitrarily large rather than undefined."
        )

    pv = _pv_at(bond, curve_handle, settle)
    dirty = float(clean_price) + float(bond.accruedAmount(settle))
    return (pv - dirty) / (100.0 * annuity) * 1e4
