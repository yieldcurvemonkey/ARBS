r"""Cross-currency basis in QuantLib, built from cashflows because there is no instrument.

QuantLib 1.41 has **no** cross-currency swap class. There is no ``CrossCcySwap``,
no ``CrossCurrencyBasisSwapRateHelper``, and no bootstrap helper that takes a
basis spread. So the swap here is assembled from primitives that do exist -
``ql.OvernightLeg`` for each side and ``ql.SimpleCashFlow`` for the notional
exchanges - and the discount curve is bootstrapped by a sequential root solve
rather than by ``PiecewiseYieldCurve``.

The contract this module prices
-------------------------------
Long the base leg, per unit of base notional ``N``::

    base leg  (ccy1) :  -N        at effective
                        +coupons  (RFR compounded + spread, if the spread is here)
                        +N        at maturity
    quote leg (ccy2) :  +N*S      at effective          S = fx_spot, ccy2 per ccy1
                        -coupons  (RFR compounded + spread, if the spread is here)
                        -N*S      at maturity

    NPV (in ccy1) = NPV(base flows | base_discount) + NPV(quote flows | quote_discount) / S

Collateral and discounting
--------------------------
The collateral currency's leg discounts on its **own** OIS curve. The other
leg discounts on the curve implied by the basis - the curve
:func:`bootstrap_ql_xccy_discount_curve` solves for. Hand both in explicitly;
this module never guesses which handle is which.

What is NOT modelled, and why it matters
----------------------------------------
**No MTM notional reset.** Traded cross-currency basis swaps reset the USD leg's
notional against the FX forward each period; rateslib's ``*_xcs`` specs all set
``leg2_mtm=True``. Building that reset by hand in QuantLib means synthesising an
FX-forward-dependent notional schedule with the compensating FX flows, which is
a large surface for silent error, so it is deliberately absent. The consequence
is real: the fair basis from this module and the fair basis from
:mod:`~MDP.CitiVelocityExcel.xccy.rl_xccy` with ``mtm=True`` are **not** the same
number. ``_smoke.py`` measures the gap at 1Y/5Y/10Y/30Y, and the like-for-like
comparison (rateslib with ``mtm=False``) is reported alongside it so the MTM
effect and any construction difference can be told apart.

**No convexity / quanto adjustment** on the compounded RFR legs, and no FX
volatility anywhere: the notional exchanges are converted at spot.

Every QuantLib signature used here was verified by calling it under QuantLib
1.41 - the SWIG overloads are strict, and this repo has a recorded case of an
``except TypeError`` fallback branch that was dead because both overloads were
wrong.
"""

from __future__ import annotations

import datetime
import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

import pandas as pd

from MDP.CitiVelocityExcel.catalog import tenor_years
from MDP.CitiVelocityExcel.xccy.basis_data import (
    XccyBasisCurve,
    assert_ois_pair,
    default_collateral_ccy,
    iso_currency,
)

__all__ = [
    "QLCrossCurrencySwap",
    "bootstrap_ql_xccy_discount_curve",
    "build_ql_xccy_swap",
    "ql_curve_from_rl",
    "ql_fair_basis_spread",
    "ql_xccy_reprice_errors_bp",
]

_logger = logging.getLogger(__name__)

#: Cross-currency basis swaps pay quarterly on both legs.
_DEFAULT_TENOR_MONTHS = 3
#: Coupons settle 2 business days after the period end, matching the rateslib specs.
_DEFAULT_PAYMENT_LAG = 2
#: Spot lag on both legs of a cross-currency swap.
_DEFAULT_SPOT_LAG = 2
#: Widest continuous spread the bootstrap brackets, in decimal (+-2000bp). A
#: cross-currency basis has never traded outside this; a solve that needs more
#: is a units error, not a market.
_BRACKET = 0.20
#: Bootstrap accepts a pillar only when the swap reprices inside this, in bp.
_DEFAULT_TOL_BP = 1e-6


def _ql() -> Any:
    import QuantLib as ql  # imported lazily: QuantLib is slow to import

    return ql


# ------------------------------------------------------------------ #
#                              the record                            #
# ------------------------------------------------------------------ #


@dataclass(frozen=True, eq=False)
class QLCrossCurrencySwap:
    """One cross-currency basis swap, priced from explicit cashflows.

    Attributes
    ----------
    legs
        ``{"base_coupons", "base_exchanges", "quote_coupons", "quote_exchanges"}``
        -> QuantLib ``Leg``. Signs are as received by the long-base-leg holder.
    npv
        Total NPV in **base currency** units, at ``fx_spot``.
    npv_base, npv_quote
        Per-leg NPV, each in its own currency, exchanges included.
    fair_basis_spread
        The spread in bp on ``spread_ccy``'s leg that sets ``npv`` to zero,
        computed analytically from the annuity and then verified by repricing.
    annuity_bp
        NPV in base currency of 1bp on the spread leg. Never zero on return.
    spread_bp, spread_ccy
        The spread that was priced, and the leg it sat on.
    base_ccy, quote_ccy, effective, maturity, fx_spot, notional_base,
    notional_quote
        The trade as built.
    """

    legs: Dict[str, Any]
    npv: float
    npv_base: float
    npv_quote: float
    fair_basis_spread: float
    annuity_bp: float
    spread_bp: float
    spread_ccy: str
    base_ccy: str
    quote_ccy: str
    effective: datetime.date
    maturity: datetime.date
    fx_spot: float
    notional_base: float
    notional_quote: float

    def __repr__(self) -> str:  # pragma: no cover - display only
        return (
            f"<QLCrossCurrencySwap {self.base_ccy}/{self.quote_ccy} "
            f"{self.effective}->{self.maturity} spread={self.spread_bp:+.3f}bp on "
            f"{self.spread_ccy} npv={self.npv:,.2f} fair={self.fair_basis_spread:+.4f}bp>"
        )


# ------------------------------------------------------------------ #
#                          QuantLib plumbing                         #
# ------------------------------------------------------------------ #


def _to_ql_date(when: datetime.date | datetime.datetime | Any) -> Any:
    ql = _ql()
    if isinstance(when, ql.Date):
        return when
    if isinstance(when, datetime.datetime):
        when = when.date()
    return ql.Date(when.day, when.month, when.year)


def _from_ql_date(d: Any) -> datetime.date:
    return datetime.date(d.year(), d.month(), d.dayOfMonth())


def ql_curve_from_rl(
    curve: Any,
    *,
    ref_date: datetime.datetime,
    calendar: Any,
    years: float = 51.0,
    day_count: Any = None,
) -> Any:
    """Sample a rateslib curve daily and rebuild it as a ``ql.DiscountCurve``.

    Daily sampling makes the interpolation difference between the two libraries
    negligible: rateslib's default is log-linear on discount factors and
    ``ql.DiscountCurve`` is ``InterpolatedDiscountCurve<LogLinear>``, so on a
    shared daily grid the two agree to machine precision between nodes.

    Parameters
    ----------
    curve
        Any object supporting ``curve[datetime] -> discount factor``.
    ref_date
        Curve reference date; becomes the QuantLib curve's node 0.
    calendar
        A QuantLib calendar (only used for the curve's own business-day logic).
    years
        How far to sample. Must cover the longest cashflow **plus its payment
        lag**, else the curve extrapolates.

    Returns
    -------
    QuantLib.DiscountCurve
        With extrapolation enabled, so a payment-lag day past the last sample
        does not raise.
    """
    ql = _ql()
    dc = day_count if day_count is not None else ql.Actual365Fixed()
    dates: list[Any] = []
    dfs: list[float] = []
    day = ref_date if isinstance(ref_date, datetime.datetime) else datetime.datetime(
        ref_date.year, ref_date.month, ref_date.day
    )
    last = day + datetime.timedelta(days=int(365.25 * float(years)) + 10)
    while day <= last:
        dates.append(_to_ql_date(day))
        dfs.append(float(curve[day]))
        day += datetime.timedelta(days=1)
    out = ql.DiscountCurve(dates, dfs, dc, calendar)
    out.enableExtrapolation()
    return out


def _require_overnight_index(index: Any, which: str) -> None:
    ql = _ql()
    if not isinstance(index, ql.OvernightIndex):
        raise ValueError(
            f"{which} is a {type(index).__name__}, not a ql.OvernightIndex. This builder "
            "constructs compounded RFR legs via ql.OvernightLeg; an IBOR-indexed leg "
            "(3M BBSW, 3M BKBM) needs ql.IborLeg and a different schedule, and pricing it "
            f"as OIS would be wrong. Pass an OvernightIndex for {which}, or price that pair "
            "outside this module."
        )


# ------------------------------------------------------------------ #
#                            the instrument                          #
# ------------------------------------------------------------------ #


def build_ql_xccy_swap(
    *,
    notional: float,
    fx_spot: float,
    start: datetime.date | datetime.datetime | Any,
    maturity: datetime.date | datetime.datetime | Any,
    base_index: Any,
    quote_index: Any,
    base_discount: Any,
    quote_discount: Any,
    spread_bp: float,
    base_ccy: str = "",
    quote_ccy: str = "",
    spread_ccy: str = "",
    calendar: Any = None,
    frequency_months: int = _DEFAULT_TENOR_MONTHS,
    payment_lag: int = _DEFAULT_PAYMENT_LAG,
    business_day_convention: Any = None,
    base_day_count: Any = None,
    quote_day_count: Any = None,
    eval_date: Optional[datetime.date] = None,
    telescopic_value_dates: bool = False,
) -> QLCrossCurrencySwap:
    """Build and price one cross-currency basis swap from explicit cashflows.

    Constant notional on both legs - see the module docstring on MTM.

    Parameters
    ----------
    notional
        Base-currency notional. The quote leg carries ``notional * fx_spot``.
    fx_spot
        Units of quote currency per unit of base currency.
    start, maturity
        Effective and maturity dates. Dates, datetimes or ``ql.Date``. Pass
        ``maturity`` **unadjusted** (``effective + tenor``); the schedule's
        termination-date convention adjusts it, and the returned record reports
        the adjusted dates.
    base_index, quote_index
        ``ql.OvernightIndex`` instances already linked to their **forecast**
        curves. Anything else raises.
    base_discount, quote_discount
        ``ql.YieldTermStructureHandle`` for each leg. The collateral currency's
        leg gets its own OIS curve; the other gets the basis-implied curve.
    spread_bp
        Basis spread in basis points, applied to ``spread_ccy``'s leg.
    spread_ccy
        Which leg the spread sits on. Defaults to the non-USD currency of the
        pair when the currencies are named, else the base currency.
    calendar
        Payment/roll calendar. Defaults to the joint calendar of both indices.
    eval_date
        Sets ``ql.Settings.instance().evaluationDate``. This is GLOBAL QuantLib
        state and is not restored; every QuantLib object in the process sees it.

    Returns
    -------
    QLCrossCurrencySwap

    Raises
    ------
    ValueError
        A non-overnight index, a non-positive notional or FX rate, a degenerate
        schedule, or a zero spread annuity (which would make the fair spread
        undefined rather than merely large).
    """
    ql = _ql()
    _require_overnight_index(base_index, "base_index")
    _require_overnight_index(quote_index, "quote_index")
    if float(notional) <= 0.0:
        raise ValueError(f"notional must be positive, got {notional!r}.")
    if float(fx_spot) <= 0.0:
        raise ValueError(
            f"fx_spot must be positive and quoted as quote-per-base units, got {fx_spot!r}."
        )

    base_ccy = iso_currency(base_ccy) if base_ccy else str(base_index.currency().code())
    quote_ccy = iso_currency(quote_ccy) if quote_ccy else str(quote_index.currency().code())
    if not spread_ccy:
        from MDP.CitiVelocityExcel.xccy.basis_data import default_spread_ccy

        spread_ccy = default_spread_ccy(base_ccy, quote_ccy)
    spread_ccy = iso_currency(spread_ccy)
    if spread_ccy not in (base_ccy, quote_ccy):
        raise ValueError(
            f"spread_ccy={spread_ccy!r} is not one of ({base_ccy}, {quote_ccy}). The basis has to "
            "sit on one of the two legs."
        )

    if eval_date is not None:
        ql.Settings.instance().evaluationDate = _to_ql_date(eval_date)

    cal = calendar if calendar is not None else ql.JointCalendar(
        base_index.fixingCalendar(), quote_index.fixingCalendar()
    )
    bdc = business_day_convention if business_day_convention is not None else ql.ModifiedFollowing
    base_dc = base_day_count if base_day_count is not None else base_index.dayCounter()
    quote_dc = quote_day_count if quote_day_count is not None else quote_index.dayCounter()

    eff = _to_ql_date(start)
    mat_in = _to_ql_date(maturity)
    if mat_in <= eff:
        raise ValueError(
            f"maturity {_from_ql_date(mat_in)} is not after effective {_from_ql_date(eff)}."
        )
    # Pass the maturity through UNADJUSTED and let ``terminationDateConvention``
    # adjust it. Backward generation rolls off the termination date, so handing
    # in an already-adjusted maturity moves every intermediate roll and inserts a
    # spurious front stub whenever the adjustment moved the date: measured at a
    # 3-day stub and 0.015bp of fair basis on the 1Y EUR/USD point.
    schedule = ql.Schedule(
        eff,
        mat_in,
        ql.Period(int(frequency_months), ql.Months),
        cal,
        bdc,
        bdc,
        ql.DateGeneration.Backward,
        False,
    )
    dates = list(schedule)
    eff, mat = dates[0], dates[-1]

    n_base = float(notional)
    n_quote = float(notional) * float(fx_spot)
    base_spread = float(spread_bp) / 1e4 if spread_ccy == base_ccy else 0.0
    quote_spread = float(spread_bp) / 1e4 if spread_ccy == quote_ccy else 0.0

    base_coupons = ql.OvernightLeg(
        [n_base],
        schedule,
        base_index,
        base_dc,
        bdc,
        [],
        [base_spread],
        bool(telescopic_value_dates),
        ql.RateAveraging.Compound,
        cal,
        int(payment_lag),
    )
    quote_coupons = ql.OvernightLeg(
        [n_quote],
        schedule,
        quote_index,
        quote_dc,
        bdc,
        [],
        [quote_spread],
        bool(telescopic_value_dates),
        ql.RateAveraging.Compound,
        cal,
        int(payment_lag),
    )
    base_exchanges = [ql.SimpleCashFlow(-n_base, eff), ql.SimpleCashFlow(n_base, mat)]
    quote_exchanges = [ql.SimpleCashFlow(n_quote, eff), ql.SimpleCashFlow(-n_quote, mat)]

    settle = ql.Settings.instance().evaluationDate
    npv_base = ql.CashFlows.npv(
        list(base_coupons) + base_exchanges, base_discount, False, settle, settle
    )
    npv_quote = -ql.CashFlows.npv(
        list(quote_coupons), quote_discount, False, settle, settle
    ) + ql.CashFlows.npv(quote_exchanges, quote_discount, False, settle, settle)
    npv = float(npv_base) + float(npv_quote) / float(fx_spot)

    # ql.CashFlows.bps returns NPV per 1bp of coupon rate, sign as the leg pays.
    # The base leg is received (+), the quote leg is paid (-).
    if spread_ccy == base_ccy:
        annuity_bp = float(ql.CashFlows.bps(list(base_coupons), base_discount, False, settle, settle))
    else:
        annuity_bp = -float(
            ql.CashFlows.bps(list(quote_coupons), quote_discount, False, settle, settle)
        ) / float(fx_spot)
    if annuity_bp == 0.0:
        raise ValueError(
            f"Zero spread annuity for {base_ccy}/{quote_ccy} {_from_ql_date(eff)}->"
            f"{_from_ql_date(mat)}: every coupon on the {spread_ccy} leg has already settled or "
            "been excluded, so the fair basis spread is undefined. Check start/maturity against "
            "the evaluation date."
        )
    fair = float(spread_bp) - npv / annuity_bp

    return QLCrossCurrencySwap(
        legs={
            "base_coupons": base_coupons,
            "base_exchanges": base_exchanges,
            "quote_coupons": quote_coupons,
            "quote_exchanges": quote_exchanges,
        },
        npv=npv,
        npv_base=float(npv_base),
        npv_quote=float(npv_quote),
        fair_basis_spread=fair,
        annuity_bp=annuity_bp,
        spread_bp=float(spread_bp),
        spread_ccy=spread_ccy,
        base_ccy=base_ccy,
        quote_ccy=quote_ccy,
        effective=_from_ql_date(eff),
        maturity=_from_ql_date(mat),
        fx_spot=float(fx_spot),
        notional_base=n_base,
        notional_quote=n_quote,
    )


def ql_fair_basis_spread(
    *,
    verify_tol_bp: float = 1e-8,
    **kwargs: Any,
) -> float:
    """The par cross-currency basis spread, in bp, verified by repricing.

    Takes exactly the keywords of :func:`build_ql_xccy_swap`. The analytic
    ``-NPV/annuity`` answer is rebuilt at the solved spread and the residual NPV
    checked, because "linear in the spread" is an assumption about the leg
    construction, not a theorem about it.

    Raises
    ------
    ValueError
        Repricing at the returned spread leaves a residual worth more than
        ``verify_tol_bp`` of spread.
    """
    trade = build_ql_xccy_swap(**kwargs)
    check = build_ql_xccy_swap(**{**kwargs, "spread_bp": trade.fair_basis_spread})
    residual_bp = abs(check.npv / check.annuity_bp)
    if residual_bp > float(verify_tol_bp):
        raise ValueError(
            f"QuantLib cross-currency fair spread failed its own verification: repricing at "
            f"{trade.fair_basis_spread:.6f}bp leaves {check.npv:,.4f} NPV, worth "
            f"{residual_bp:.3g}bp (tol {verify_tol_bp:g}). The NPV is not linear in the spread, "
            "which means a leg is mis-built - do not use this number."
        )
    return float(trade.fair_basis_spread)


# ------------------------------------------------------------------ #
#                             the bootstrap                          #
# ------------------------------------------------------------------ #


def bootstrap_ql_xccy_discount_curve(
    *,
    basis: XccyBasisCurve,
    base_index: Any,
    quote_index: Any,
    base_discount: Any,
    quote_discount: Any,
    fx_spot: float,
    ref_date: datetime.date,
    collateral_ccy: Optional[str] = None,
    tenors: Optional[Sequence[str]] = None,
    notional: float = 100_000_000.0,
    calendar: Any = None,
    spot_lag: int = _DEFAULT_SPOT_LAG,
    frequency_months: int = _DEFAULT_TENOR_MONTHS,
    payment_lag: int = _DEFAULT_PAYMENT_LAG,
    day_count: Any = None,
    tol_bp: float = _DEFAULT_TOL_BP,
    return_diagnostics: bool = False,
) -> Any:
    """Bootstrap the basis-implied discount curve, tenor by tenor.

    QuantLib has no cross-currency rate helper, so this is a hand-rolled
    sequential bootstrap: at each tenor in ascending order, Brent-solve the one
    unknown - a continuous spread ``z`` over the leg's own OIS discount curve at
    that pillar - so the quoted swap prices to zero. Earlier pillars are frozen,
    so each solve is one-dimensional and the fit is exact by construction.

    The pillar sits at the **last payment date**, not at maturity. With a 2
    business-day payment lag the final coupon settles after maturity, and a
    pillar at maturity would leave that flow extrapolated during the solve and
    interpolated afterwards - measured at 1e-4bp of drift on the front tenor,
    versus 1e-13bp with the pillar at the payment date.

    Parameters
    ----------
    basis
        The quoted strip. Validated before use.
    base_index, quote_index
        Overnight indices linked to their forecast curves.
    base_discount, quote_discount
        Handles for both legs. The one belonging to the currency being solved for
        is **replaced** by the bootstrapped curve; the other is used as given.
    fx_spot
        Quote currency per base currency.
    ref_date
        Curve reference date and QuantLib evaluation date.
    collateral_ccy
        Which currency's own curve is taken as given. The other currency's
        discount curve is the unknown. Defaults to USD for a USD pair.
    tol_bp
        Each pillar must reprice its own quote inside this, in bp.
    return_diagnostics
        Also return the per-pillar frame.

    Returns
    -------
    QuantLib.YieldTermStructureHandle
        The bootstrapped curve, with extrapolation enabled (the final coupon
        settles after the last pillar only when the payment lag pushes it there,
        which the pillar placement already avoids).
    tuple
        When ``return_diagnostics`` is True, ``(handle, frame)`` where ``frame``
        is indexed by tenor with the pillar date, the solved ``z`` in bp, the
        Brent residual NPV and the reprice error in bp.

    Raises
    ------
    ValueError
        The strip fails validation, Brent cannot bracket a root (the message
        gives the bracket that failed), or a pillar misses its quote by more than
        ``tol_bp``.
    UnknownTagError
        Either leg of the strip is an IBOR-indexed Velocity token (``AUD_BBSW``,
        ``NZD_BKBM``); this bootstrap builds compounded RFR legs on both sides.
    """
    from scipy.optimize import brentq

    ql = _ql()
    basis.validate()
    # _require_overnight_index below can only police the indices it is HANDED. A
    # caller who passes ql.Aonia for an AUD_BBSW strip passes that check while
    # still pricing a 3M BBSW leg as compounded RFR, so the strip's own raw
    # tokens are checked too - before iso_currency() erases the distinction.
    assert_ois_pair(basis.base_ccy, basis.quote_ccy)
    _require_overnight_index(base_index, "base_index")
    _require_overnight_index(quote_index, "quote_index")

    base_iso = iso_currency(basis.base_ccy)
    quote_iso = iso_currency(basis.quote_ccy)
    coll = iso_currency(
        collateral_ccy or default_collateral_ccy(basis.base_ccy, basis.quote_ccy)
    )
    if coll not in (base_iso, quote_iso):
        raise ValueError(
            f"collateral_ccy={coll!r} is not one of the pair ({base_iso}, {quote_iso})."
        )
    solve_base = coll == quote_iso  # solve the base-currency discount curve

    ql.Settings.instance().evaluationDate = _to_ql_date(ref_date)
    d0 = _to_ql_date(ref_date)
    dc = day_count if day_count is not None else ql.Actual365Fixed()
    cal = calendar if calendar is not None else ql.JointCalendar(
        base_index.fixingCalendar(), quote_index.fixingCalendar()
    )
    own = base_discount if solve_base else quote_discount

    axis = [str(t).strip().upper() for t in (tenors if tenors is not None else basis.tenors())]
    missing = [t for t in axis if t not in basis.spreads.index]
    if missing:
        raise ValueError(
            f"tenors={missing} are not in the {basis.pair} strip. Present: "
            f"{', '.join(basis.tenors())}."
        )
    axis = sorted(axis, key=tenor_years)

    eff = cal.advance(d0, int(spot_lag), ql.Days)
    pillars: list[Any] = []
    zs: list[float] = []
    rows: list[Dict[str, Any]] = []

    def _curve(extra_date: Any = None, extra_z: float = 0.0) -> Any:
        dates = [d0] + list(pillars) + ([extra_date] if extra_date is not None else [])
        vals = list(zs) + ([extra_z] if extra_date is not None else [])
        dfs = [1.0]
        for d, z in zip(dates[1:], vals):
            dfs.append(own.discount(d) * math.exp(-float(z) * dc.yearFraction(d0, d)))
        curve = ql.DiscountCurve(dates, dfs, dc, cal)
        curve.enableExtrapolation()
        return curve

    def _price(tenor: str, mat: Any, handle: Any, spread_bp: float) -> QLCrossCurrencySwap:
        return build_ql_xccy_swap(
            notional=notional,
            fx_spot=fx_spot,
            start=eff,
            maturity=mat,
            base_index=base_index,
            quote_index=quote_index,
            base_discount=handle if solve_base else base_discount,
            quote_discount=quote_discount if solve_base else handle,
            spread_bp=spread_bp,
            base_ccy=base_iso,
            quote_ccy=quote_iso,
            spread_ccy=basis.spread_ccy,
            calendar=cal,
            frequency_months=frequency_months,
            payment_lag=payment_lag,
        )

    for tenor in axis:
        mat = eff + ql.Period(tenor)  # unadjusted; the schedule adjusts it
        quote = float(basis.at(tenor))
        # Probe once to learn the last payment date, then pin the pillar there so
        # no flow is ever extrapolated during the solve.
        probe = _price(tenor, mat, ql.YieldTermStructureHandle(_curve(cal.adjust(mat, ql.ModifiedFollowing), 0.0)), quote)
        pillar = max(
            [_to_ql_date(probe.maturity)]
            + [cf.date() for cf in probe.legs["base_coupons"]]
            + [cf.date() for cf in probe.legs["quote_coupons"]]
        )
        if pillars and pillar <= pillars[-1]:
            raise ValueError(
                f"{basis.pair} {tenor}: its last payment {_from_ql_date(pillar)} is not after the "
                f"previous pillar {_from_ql_date(pillars[-1])}, so the bootstrap pillars would not "
                "be strictly increasing. Drop the overlapping tenor from tenors=."
            )

        def objective(z: float, tenor: str = tenor, pillar: Any = pillar, mat: Any = mat, quote: float = quote) -> float:
            handle = ql.YieldTermStructureHandle(_curve(pillar, z))
            return _price(tenor, mat, handle, quote).npv

        lo, hi = -_BRACKET, _BRACKET
        f_lo, f_hi = objective(lo), objective(hi)
        if f_lo * f_hi > 0.0:
            raise ValueError(
                f"{basis.pair} {tenor}: no root for the discount spread in "
                f"[{lo * 1e4:.0f}bp, {hi * 1e4:.0f}bp] - NPV is {f_lo:,.1f} at the low end and "
                f"{f_hi:,.1f} at the high end. The quote ({quote:+.2f}bp), fx_spot ({fx_spot}) or "
                "the sign convention is wrong; widen the bracket only after checking those."
            )
        z = float(brentq(objective, lo, hi, xtol=1e-15, rtol=8.9e-16, maxiter=200))
        residual = objective(z)
        pillars.append(pillar)
        zs.append(z)

        priced = _price(tenor, mat, ql.YieldTermStructureHandle(_curve()), quote)
        err_bp = -priced.npv / priced.annuity_bp
        if abs(err_bp) > float(tol_bp):
            raise ValueError(
                f"{basis.pair} {tenor}: bootstrapped pillar misses its own quote by "
                f"{err_bp:+.3g}bp (tol_bp={tol_bp:g}). The bootstrap is refusing to return a "
                "curve that does not reprice its inputs."
            )
        rows.append(
            {
                "tenor": tenor,
                "pillar": _from_ql_date(pillar),
                "quote_bp": quote,
                "z_bp": z * 1e4,
                "solve_residual_npv": residual,
                "reprice_error_bp": err_bp,
            }
        )

    curve = _curve()
    handle = ql.YieldTermStructureHandle(curve)
    diagnostics = pd.DataFrame(rows).set_index("tenor")
    _logger.debug(
        "bootstrap_ql_xccy_discount_curve %s: %d pillars, max reprice err %.3gbp",
        basis.pair,
        len(axis),
        float(diagnostics["reprice_error_bp"].abs().max()),
    )
    return (handle, diagnostics) if return_diagnostics else handle


def ql_xccy_reprice_errors_bp(
    *,
    basis: XccyBasisCurve,
    handle: Any,
    base_index: Any,
    quote_index: Any,
    base_discount: Any,
    quote_discount: Any,
    fx_spot: float,
    ref_date: datetime.date,
    collateral_ccy: Optional[str] = None,
    notional: float = 100_000_000.0,
    calendar: Any = None,
    spot_lag: int = _DEFAULT_SPOT_LAG,
    frequency_months: int = _DEFAULT_TENOR_MONTHS,
    payment_lag: int = _DEFAULT_PAYMENT_LAG,
) -> pd.Series:
    """Reprice a basis strip off a QuantLib discount curve; ``model - quote`` in bp.

    ``handle`` replaces the discount curve of whichever currency is NOT the
    collateral currency, exactly as in
    :func:`bootstrap_ql_xccy_discount_curve`.
    """
    ql = _ql()
    basis.validate()
    assert_ois_pair(basis.base_ccy, basis.quote_ccy)
    base_iso = iso_currency(basis.base_ccy)
    quote_iso = iso_currency(basis.quote_ccy)
    coll = iso_currency(
        collateral_ccy or default_collateral_ccy(basis.base_ccy, basis.quote_ccy)
    )
    solve_base = coll == quote_iso

    ql.Settings.instance().evaluationDate = _to_ql_date(ref_date)
    d0 = _to_ql_date(ref_date)
    cal = calendar if calendar is not None else ql.JointCalendar(
        base_index.fixingCalendar(), quote_index.fixingCalendar()
    )
    eff = cal.advance(d0, int(spot_lag), ql.Days)

    out: Dict[str, float] = {}
    for tenor in basis.tenors():
        mat = eff + ql.Period(tenor)  # unadjusted; the schedule adjusts it
        quote = float(basis.at(tenor))
        trade = build_ql_xccy_swap(
            notional=notional,
            fx_spot=fx_spot,
            start=eff,
            maturity=mat,
            base_index=base_index,
            quote_index=quote_index,
            base_discount=handle if solve_base else base_discount,
            quote_discount=quote_discount if solve_base else handle,
            spread_bp=quote,
            base_ccy=base_iso,
            quote_ccy=quote_iso,
            spread_ccy=basis.spread_ccy,
            calendar=cal,
            frequency_months=frequency_months,
            payment_lag=payment_lag,
        )
        out[tenor] = float(trade.fair_basis_spread) - quote
    return pd.Series(out, dtype="float64", name="reprice_error_bp").reindex(basis.tenors())
