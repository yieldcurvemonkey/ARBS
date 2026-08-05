"""Bootstrapped QuantLib OIS curves from Citi Velocity par grids.

This is a genuinely new capability in this repo: every other QuantLib curve here
is an *interpolation of published discount factors*, never a bootstrap from rate
helpers. So the conventions below are load-bearing in a way they have not been
before, and two of them are worth stating outright.

**The fixed-leg day count comes from the index, not from an argument.**
``ql.OISRateHelper`` exposes no fixed-leg day count; it builds its swap through
``MakeOIS``, whose fixed day count defaults to ``overnightIndex->dayCounter()``.
:func:`build_ql_ois_curve` therefore *checks* that the QuantLib index's day count
equals the convention table's ``convention`` and raises when it does not, rather
than bootstrapping a curve whose fixed leg accrues on the wrong basis. All twenty
currently agree.

**The bootstrapped curve is frozen onto its own pillars before it is returned.**
``OISRateHelper`` is a ``RelativeDateRateHelper``: it observes
``Settings::evaluationDate`` and recomputes its dates whenever that global moves.
A ``Piecewise*`` curve built from such helpers therefore silently re-bootstraps
against whatever the evaluation date happens to be at the moment it is next
queried - measured here at **-8.8e-4 on a 10Y discount factor (~13 bp of 10Y zero
rate)** after moving the evaluation date six months. Since :func:`build_ql_ois_curve`
restores the evaluation date on the way out (the repo has a recorded bug where a
bulk build left that global mutated), returning the live ``Piecewise*`` object
would hand back exactly that failure. Instead the bootstrap output is copied onto
an absolute ``ql.DiscountCurve`` / ``ql.MonotonicLogCubicDiscountCurve`` over the
same pillars and the same interpolator, which reproduces it **exactly** (measured
0.0 for log-linear, 1.7e-16 for log-cubic) and is immune to the evaluation date.
The rate helpers ride along on the result for provenance.

Pillars sit at the swap **maturity** date (``Pillar::MaturityDate``) rather than
at the payment date, which is what puts the QuantLib nodes on the same dates as
the rateslib builder's ``leg1.schedule.termination`` nodes and makes the two
backends comparable node-for-node.

Two more things that were measured rather than assumed
------------------------------------------------------
**QuantLib's ``endOfMonth=True`` corrupts a mid-month schedule.** With
``endOfMonth=True`` and a start that is not a month end, QuantLib routes date
generation through the adjusted calendar advance and drifts: a GBP-SONIA 2Y
starting 2026-08-05 came out with a spurious two-day front stub and rolls of
2026-08-07 / 2027-08-09 / 2028-08-07 instead of 2026-08-05 / 2027-08-05 /
2028-08-07, moving the bootstrapped 2Y discount factor by 9.2e-6 and the 1Yx1Y
forward by 0.10 bp away from rateslib - whose ``eom=True`` correctly does
nothing off a non-month-end start. :func:`_end_of_month` therefore applies the
convention's rule only when the start really is the last business day of its
month; on a genuine month-end start both libraries agree again.

**The calendar behind the index is not the country calendar.** Over 2026-2076
QuantLib's ``Sofr`` carries a bespoke "SOFR fixing calendar" with 10 more
holidays than ``UnitedStates(GovernmentBond)`` (Good Fridays), and ``FedFunds``
carries the Fed wire calendar with 63 fewer. Everything here uses the *index's*
fixing calendar, because that is the one ``MakeOIS`` uses for the spot advance
and the one ``OISRateHelper`` gives no way to override; forcing the leg
calendars elsewhere would build a swap whose spot and roll dates came from
different calendars and whose reprice check would then not tie out. Separately,
rateslib's own calendars differ from
QuantLib's for USD, JPY, CAD, AUD and NZD - see ``rl_builder``'s docstring and
``curves/_smoke.py``; for AUD that is worth 0.067 bp on the forwards.

What is NOT verified
--------------------
Nothing here has been checked against a Citi-published discount factor: the
``CVD*`` pricers are not entitled and there is no independent curve for these
twenty currencies available in this environment. ``curves/_smoke.py`` verifies
internal consistency (a synthetic par grid is recovered to well under 0.01 bp)
and cross-backend agreement with rateslib. For DKK, ILS, MXN, SGD, THB and ZAR
the schedule conventions themselves are market standard rather than
library-supplied, and MXN's 28-day Fondeo roll is approximated by a monthly
schedule - those curves are indicative, and the builder says so once per curve.
"""

from __future__ import annotations

import contextlib
import datetime
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple, Union

import pandas as pd
import QuantLib as ql

from MDP.CitiVelocityExcel.curves.conventions import CurveConvention, conventions_for
from MDP.CitiVelocityExcel.errors import UnknownTagError

__all__ = [
    "END_OF_MONTH_BY_INDEX",
    "PAYMENT_LAG_BY_INDEX",
    "QLOisCurve",
    "build_ql_ois_curve",
    "evaluation_date",
    "ql_forward_rate",
    "ql_par_reprice_errors_bp",
]

_logger = logging.getLogger(__name__)

DateLike = Union[datetime.date, datetime.datetime, pd.Timestamp]

#: Business days between a coupon's accrual end and its payment, per Citi OIS
#: index token. rateslib's named specs are the authority for the fourteen
#: currencies it ships one for, and
#: :func:`MDP.CitiVelocityExcel.curves.rl_builder.payment_lag_for` re-reads
#: ``rl.defaults.spec`` and raises if this table ever stops matching. The six
#: without a spec (DKK ILS MXN SGD THB ZAR) carry the market-standard T+2.
#:
#: The table lives in the QuantLib module and rl_builder imports it, so there is
#: exactly ONE copy and the dependency runs one way (rl_builder -> ql_builder):
#: this module has no rateslib import of its own. (The package ``__init__``
#: imports both, so ``from ...curves.ql_builder import X`` does load rateslib
#: transitively; the point is the module-level direction, not the import cost.)
#: A one-day disagreement between the backends moves a 50Y discount factor and
#: would surface only as an unexplained cross-backend residual.
PAYMENT_LAG_BY_INDEX: Dict[str, int] = {
    "USD_SOFR": 2,
    "USD_FEDFUND": 2,
    "EUR_EUROSTR": 1,
    "EUR_EONIA": 1,
    "GBP_SONIA": 0,
    "JPY_TONAR": 2,
    "JPY_TONAR_JSCC": 2,
    "JPY_TONAR_LCH": 2,
    "CHF_SARON": 2,
    "CAD_CORRA": 1,
    "AUD_AONIA": 2,
    "NZD_NZIONA": 2,
    "NOK_NOWA": 2,
    "SEK_STINA": 1,
    "DKK_TNDKK": 2,
    "ILS_SHIR": 2,
    "MXN_T_FONDEO": 2,
    "SGD_SORA": 2,
    "THB_THOR": 2,
    "ZAR_ZARONIA": 2,
}

#: End-of-month schedule rule per index, transcribed from the same rateslib
#: specs and cross-checked by rl_builder. Only the four sterling-style markets
#: roll end-of-month; it bites only when the spot date is itself a month end,
#: which is why it is easy to get wrong and never notice.
END_OF_MONTH_BY_INDEX: Dict[str, bool] = {
    "USD_SOFR": False,
    "USD_FEDFUND": False,
    "EUR_EUROSTR": False,
    "EUR_EONIA": False,
    "GBP_SONIA": True,
    "JPY_TONAR": True,
    "JPY_TONAR_JSCC": True,
    "JPY_TONAR_LCH": True,
    "CHF_SARON": False,
    "CAD_CORRA": False,
    "AUD_AONIA": True,
    "NZD_NZIONA": True,
    "NOK_NOWA": False,
    "SEK_STINA": False,
    "DKK_TNDKK": False,
    "ILS_SHIR": False,
    "MXN_T_FONDEO": False,
    "SGD_SORA": False,
    "THB_THOR": False,
    "ZAR_ZARONIA": False,
}

#: rateslib frequency letter -> QuantLib coupon frequency.
_QL_FREQUENCY: Dict[str, int] = {
    "a": ql.Annual,
    "s": ql.Semiannual,
    "q": ql.Quarterly,
    "m": ql.Monthly,
}

#: rateslib day-count spelling -> QuantLib day counter factory.
_QL_DAY_COUNT: Dict[str, Any] = {
    "act360": ql.Actual360,
    "act365f": ql.Actual365Fixed,
}

#: interpolation token -> (bootstrapping curve, absolute curve with the SAME
#: interpolator). The second is what gets returned; see the module docstring.
_INTERPOLATORS: Dict[str, Tuple[Any, Any]] = {
    "log_linear": (ql.PiecewiseLogLinearDiscount, ql.DiscountCurve),
    "log_cubic": (ql.PiecewiseLogCubicDiscount, ql.MonotonicLogCubicDiscountCurve),
}

#: Roll convention on every leg; Citi quotes OIS modified following throughout.
_CONVENTION = ql.ModifiedFollowing

#: Curve ids already warned about, so a 900-day bulk build warns once per curve.
_WARNED_APPROXIMATE: set[str] = set()


# ------------------------------------------------------------------ #
#                       evaluation-date handling                     #
# ------------------------------------------------------------------ #


@contextlib.contextmanager
def evaluation_date(when: ql.Date) -> Iterator[ql.Date]:
    """Pin ``ql.Settings.instance().evaluationDate`` and always restore it.

    QuantLib's evaluation date is process-global and every
    ``RelativeDateRateHelper`` observes it. A bulk build that leaves it mutated
    silently redates every curve built afterwards in the same process - that has
    happened in this repo, which is why nothing in this module sets the global
    without a ``finally``.

    Parameters
    ----------
    when
        The evaluation date to pin for the duration of the block.

    Yields
    ------
    QuantLib.Date
        ``when``, for convenience.
    """
    saved = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = when
    try:
        yield when
    finally:
        ql.Settings.instance().evaluationDate = saved


# ------------------------------------------------------------------ #
#                          dates and coercion                        #
# ------------------------------------------------------------------ #


def _to_ql_date(when: DateLike) -> ql.Date:
    ts = pd.Timestamp(when)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ql.Date(ts.day, ts.month, ts.year)


def _to_py_date(when: ql.Date) -> datetime.date:
    return datetime.date(when.year(), when.month(), when.dayOfMonth())


def _normalise_par_rates(par_rates: Union[Mapping[str, float], pd.Series]) -> Dict[str, float]:
    """``{tenor: percent}`` with ``None``/``NaN``/non-numeric entries dropped."""
    out: Dict[str, float] = {}
    for tenor, rate in par_rates.items():
        if rate is None:
            continue
        try:
            r = float(rate)
        except (TypeError, ValueError):
            continue
        if r != r:  # NaN
            continue
        out[str(tenor).strip().upper()] = r
    return out


def _tenor_sort_key(tenor: str) -> Tuple[float, str]:
    from MDP.CitiVelocityExcel.catalog import tenor_years

    token = str(tenor).strip().upper()
    try:
        return (tenor_years(token), token)
    except Exception:  # noqa: BLE001 - an unparseable tenor sorts last, it does not crash a build
        return (float("inf"), token)


def _day_counter(conv: CurveConvention) -> Any:
    try:
        return _QL_DAY_COUNT[conv.convention]()
    except KeyError as exc:
        raise ValueError(
            f"No QuantLib day counter for convention {conv.convention!r} "
            f"({conv.citi_index}). Add it to _QL_DAY_COUNT."
        ) from exc


def _frequency(conv: CurveConvention) -> int:
    try:
        return _QL_FREQUENCY[conv.fixed_frequency]
    except KeyError as exc:
        raise ValueError(
            f"No QuantLib frequency for rateslib letter {conv.fixed_frequency!r} "
            f"({conv.citi_index}). Add it to _QL_FREQUENCY."
        ) from exc


def _warn_if_approximate(conv: CurveConvention, curve_id: str) -> None:
    if not conv.approximate or curve_id in _WARNED_APPROXIMATE:
        return
    _WARNED_APPROXIMATE.add(curve_id)
    _logger.warning(
        "%s: the schedule conventions for %s are market standard, not library-supplied "
        "(frequency=%s, convention=%s, spot_lag=%s, payment_lag=%s), and the QuantLib index is "
        "assembled from ql.OvernightIndex. %s",
        curve_id,
        conv.citi_index,
        conv.fixed_frequency,
        conv.convention,
        conv.spot_lag,
        PAYMENT_LAG_BY_INDEX.get(conv.citi_index),
        conv.note or "Levels are indicative.",
    )


# ------------------------------------------------------------------ #
#                              the result                            #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class QLOisCurve:
    """A bootstrapped, evaluation-date-independent QuantLib OIS curve.

    Attributes
    ----------
    handle
        A ``ql.RelinkableYieldTermStructureHandle`` linked to :attr:`curve`.
        Pass it to any QuantLib pricing engine.
    curve
        The absolute discount curve (``ql.DiscountCurve`` for ``log_linear``,
        ``ql.MonotonicLogCubicDiscountCurve`` for ``log_cubic``) carrying the
        bootstrap's own pillars and discount factors. It does **not** observe
        ``Settings::evaluationDate``; see the module docstring for why that
        matters and what it was measured to cost.
    index
        The QuantLib overnight index, linked to :attr:`handle`.
    reference_date
        The curve's anchor, as a ``datetime.date``. This is ``ref_date`` rolled
        back to the prior good business day, not necessarily ``ref_date`` itself.
    citi_index
        The Velocity OIS index token this was built from.
    curve_id
        Stable identifier, defaulting to ``conv.curve_id``.
    helpers
        The ``ql.OISRateHelper`` objects used for the bootstrap, in maturity
        order. Kept for provenance only - they are evaluation-date-relative and
        the returned curve deliberately does not observe them.
    conventions
        The :class:`CurveConvention` used.
    """

    handle: Any
    curve: Any
    index: Any
    reference_date: datetime.date
    citi_index: str
    curve_id: str
    helpers: Tuple[Any, ...]
    conventions: CurveConvention

    @property
    def approximate(self) -> bool:
        """True when the schedule conventions are market standard, not library-supplied."""
        return self.conventions.approximate

    def pinned(self) -> Any:
        """Context manager pinning the evaluation date to :attr:`reference_date`.

        The curve itself is absolute, but any *instrument* built for pricing
        (``MakeOIS`` and friends) resolves its spot date off the global
        evaluation date, so repricing must happen inside this block. Every
        function in this module does so already; use it when you build your own.
        """
        return evaluation_date(_to_ql_date(self.reference_date))


# ------------------------------------------------------------------ #
#                         instrument construction                    #
# ------------------------------------------------------------------ #


def _spot_date(conv: CurveConvention, calendar: Any, ref: ql.Date) -> ql.Date:
    """``spot_lag`` good business days after ``ref``, the way ``MakeOIS`` does it."""
    return calendar.advance(ref, ql.Period(int(conv.spot_lag), ql.Days))


def _start_date(conv: CurveConvention, calendar: Any, ref: ql.Date, forward_start: str) -> ql.Date:
    """The effective date ``MakeOIS`` will compute for this forward start.

    Mirrors ``MakeOIS``: spot, plus the forward period, adjusted **following**
    (preceding for a negative period). Replicated here only so the end-of-month
    flag below can be evaluated against the same date QuantLib will use.
    """
    spot = _spot_date(conv, calendar, ref)
    period = ql.Period(forward_start)
    if period.length() == 0:
        return calendar.adjust(spot, ql.Following)
    shifted = spot + period
    return calendar.adjust(shifted, ql.Following if period.length() > 0 else ql.Preceding)


def _end_of_month(conv: CurveConvention, calendar: Any, start: ql.Date) -> bool:
    """The end-of-month flag to hand QuantLib for a swap starting on ``start``.

    The convention's rule is applied **only when the start date is actually the
    last business day of its month**, which is the only case the rule is about.
    QuantLib does not make that distinction internally: with ``endOfMonth=True``
    and a mid-month start it routes schedule generation through the *adjusted*
    calendar advance, which drifts. Measured on GBP-SONIA 2Y starting
    2026-08-05: ``endOfMonth=True`` produced a spurious two-day front stub and
    rolls of 2026-08-07 / 2027-08-09 / 2028-08-07 instead of the correct
    2026-08-05 / 2027-08-05 / 2028-08-07, moving the bootstrapped 2Y discount
    factor by 9.2e-6 (~0.05 bp of 2Y rate) and the 1Yx1Y forward by 0.10 bp
    against rateslib, whose ``eom=True`` correctly does nothing off a
    non-month-end start. On a genuine month-end start (2026-08-28 for GBP, where
    2026-08-31 is a UK bank holiday) both libraries agree again, rolling to
    2027-08-31 / 2028-08-31.
    """
    return bool(END_OF_MONTH_BY_INDEX[conv.citi_index]) and bool(calendar.isEndOfMonth(start))


def _make_ois(
    *,
    conv: CurveConvention,
    index: Any,
    calendar: Any,
    ref: ql.Date,
    tenor: str,
    discount_handle: Any,
    forward_start: str = "0D",
) -> Any:
    """One OIS built with exactly the conventions the helpers were built with.

    Kept in one place so that a swap priced for diagnostics is the same swap the
    bootstrap calibrated to; a reprice check against a differently-built swap
    proves nothing.
    """
    return ql.MakeOIS(
        ql.Period(tenor),
        index,
        0.0,
        ql.Period(forward_start),
        settlementDays=int(conv.spot_lag),
        paymentLag=PAYMENT_LAG_BY_INDEX[conv.citi_index],
        paymentAdjustmentConvention=_CONVENTION,
        paymentFrequency=_frequency(conv),
        paymentCalendar=calendar,
        endOfMonth=_end_of_month(conv, calendar, _start_date(conv, calendar, ref, forward_start)),
        fixedLegDayCount=_day_counter(conv),
        discountingTermStructure=discount_handle,
    )


# ------------------------------------------------------------------ #
#                             the builder                            #
# ------------------------------------------------------------------ #


def build_ql_ois_curve(
    *,
    par_rates: Union[Mapping[str, float], pd.Series],
    ref_date: DateLike,
    citi_index: str = "USD_SOFR",
    curve_id: Optional[str] = None,
    interpolation: str = "log_linear",
    enable_extrapolation: bool = True,
    min_tenors: int = 4,
) -> QLOisCurve:
    """Bootstrap a QuantLib OIS discount curve from one Citi Velocity par snapshot.

    Parameters
    ----------
    par_rates
        ``{tenor: par_rate_percent}``, e.g. ``{"5Y": 3.9512}``. **Percent**, as
        ``RATES.OIS.<idx>.PAR.<tenor>`` serves it; converted to decimal here
        because QuantLib quotes are decimal. ``None``/``NaN`` entries are dropped.
    ref_date
        Trade/observation date. Rolled **back** to the prior good business day on
        the curve's own calendar, so a weekend snapshot anchors to Friday - the
        same rule the rateslib builder applies, and the reason the two backends
        anchor identically.
    citi_index
        Velocity OIS index token; see
        :func:`~MDP.CitiVelocityExcel.curves.conventions.supported_indices`.
    curve_id
        Stable identifier. Defaults to ``conv.curve_id``.
    interpolation
        ``"log_linear"`` (default) or ``"log_cubic"``.
    enable_extrapolation
        Allow queries past the last pillar. On by default because a 50Y grid's
        last helper pays two business days after its pillar and the bootstrap
        itself needs the tail.
    min_tenors
        Minimum usable tenor count; a sparser snapshot raises rather than
        returning a curve that means nothing.

    Returns
    -------
    QLOisCurve
        Frozen onto its own pillars and independent of the global evaluation
        date, which is restored before this function returns.

    Raises
    ------
    UnknownTagError
        ``citi_index`` is not one of the twenty.
    ValueError
        No usable rates; fewer than ``min_tenors``; an unknown ``interpolation``;
        two tenors colliding on one pillar date; a QuantLib index whose day count
        disagrees with the convention table (which would silently accrue the
        fixed leg on the wrong basis, since ``OISRateHelper`` takes the fixed day
        count from the index); or a bootstrap that fails to solve.
    """
    conv = conventions_for(citi_index)
    cid = curve_id or conv.curve_id
    _warn_if_approximate(conv, cid)
    if conv.stale:
        _logger.warning("%s: %s is a stale Citi curve. %s", cid, conv.citi_index, conv.note)

    token = str(interpolation).strip().lower()
    if token not in _INTERPOLATORS:
        raise ValueError(
            f"build_ql_ois_curve({conv.citi_index}): unknown interpolation {interpolation!r}. "
            f"Supported: {', '.join(sorted(_INTERPOLATORS))}."
        )
    bootstrap_cls, absolute_cls = _INTERPOLATORS[token]

    rates_map = _normalise_par_rates(par_rates)
    if not rates_map:
        raise ValueError(
            f"build_ql_ois_curve({conv.citi_index}): no usable par rates supplied "
            "(every entry was None/NaN/non-numeric)."
        )
    if len(rates_map) < min_tenors:
        raise ValueError(
            f"build_ql_ois_curve({conv.citi_index}): only {len(rates_map)} usable tenor(s) "
            f"{sorted(rates_map, key=_tenor_sort_key)} < min_tenors={min_tenors}; the snapshot is "
            "too sparse to build a meaningful curve (pass a lower min_tenors to override)."
        )

    day_counter = _day_counter(conv)
    handle = ql.RelinkableYieldTermStructureHandle()
    index = conv.ql_index(handle)
    # The index's own fixing calendar governs everything, because it is the one
    # calendar MakeOIS uses for the spot advance and the ONE that OISRateHelper
    # gives no way to override. Forcing the leg calendars to conv.ql_calendar()
    # instead would build a swap whose spot date and roll dates came from
    # different calendars, and the reprice check would then not tie out. For the
    # six currencies whose index is assembled by conventions.py the two ARE the
    # same object; for USD they are not - QuantLib's "SOFR fixing calendar"
    # carries 10 more holidays than UnitedStates(GovernmentBond) over 2026-2076
    # (Good Fridays), and the Fed wire calendar behind FedFunds carries 63 fewer.
    calendar = index.fixingCalendar()
    ref = calendar.adjust(_to_ql_date(ref_date), ql.Preceding)

    with evaluation_date(ref):
        # OISRateHelper has no fixed-leg day count: MakeOIS defaults it to the
        # index's. If they disagree the fixed leg accrues on the wrong basis and
        # nothing anywhere complains, so check it here.
        if index.dayCounter() != day_counter:
            raise ValueError(
                f"build_ql_ois_curve({conv.citi_index}): the QuantLib index day count "
                f"{index.dayCounter()} does not match the convention table's "
                f"{conv.convention!r} ({day_counter}). ql.OISRateHelper takes the FIXED leg day "
                "count from the index, so this would silently accrue on the wrong basis. Fix "
                "either conventions.py's `convention` or its `ql_index` factory."
            )

        spot = _spot_date(conv, calendar, ref)
        end_of_month = _end_of_month(conv, calendar, spot)

        ordered = sorted(rates_map, key=_tenor_sort_key)
        helpers: List[Any] = []
        by_tenor: Dict[str, Any] = {}
        for tenor in ordered:
            helper = ql.OISRateHelper(
                int(conv.spot_lag),
                ql.Period(tenor),
                ql.QuoteHandle(ql.SimpleQuote(rates_map[tenor] / 100.0)),
                index,
                telescopicValueDates=False,
                paymentLag=PAYMENT_LAG_BY_INDEX[conv.citi_index],
                paymentConvention=_CONVENTION,
                paymentFrequency=_frequency(conv),
                paymentCalendar=calendar,
                # Pillar at the MATURITY date, not the payment date: this is what
                # puts the QuantLib nodes on the same dates as the rateslib
                # builder's leg1.schedule.termination nodes and makes the two
                # backends comparable node-for-node.
                pillar=ql.Pillar.MaturityDate,
                averagingMethod=ql.RateAveraging.Compound,
                endOfMonth=end_of_month,
            )
            helpers.append(helper)
            by_tenor[tenor] = helper

        # Two tenors on one pillar makes the bootstrap singular; name them.
        by_pillar: Dict[datetime.date, List[str]] = {}
        for tenor, helper in by_tenor.items():
            by_pillar.setdefault(_to_py_date(helper.pillarDate()), []).append(tenor)
        collisions = {d: ts for d, ts in by_pillar.items() if len(ts) > 1}
        if collisions:
            raise ValueError(
                f"build_ql_ois_curve({conv.citi_index}): tenors collide on the same pillar date "
                f"{collisions}. Drop one of each colliding pair from par_rates."
            )

        helpers.sort(key=lambda h: h.pillarDate())
        bootstrap = bootstrap_cls(ref, helpers, day_counter)
        if enable_extrapolation:
            bootstrap.enableExtrapolation()

        # Force the bootstrap NOW, inside the pinned evaluation date, and copy
        # the result onto an absolute curve. Anything that fails to solve fails
        # here with the currency named, rather than at some later query.
        try:
            pillars = list(bootstrap.dates())
            discounts = [float(bootstrap.discount(d)) for d in pillars]
        except RuntimeError as exc:
            raise ValueError(
                f"build_ql_ois_curve({conv.citi_index}): QuantLib bootstrap failed for "
                f"ref_date={_to_py_date(ref)} with {len(helpers)} helpers: {exc}"
            ) from exc

        if len(pillars) != len(helpers) + 1:  # +1 for the reference-date node
            raise ValueError(
                f"build_ql_ois_curve({conv.citi_index}): bootstrap produced {len(pillars)} pillar(s) "
                f"for {len(helpers)} helper(s); expected {len(helpers) + 1}. Refusing to return a "
                "curve whose nodes do not correspond to its instruments."
            )
        if any(d != d or d <= 0.0 for d in discounts):
            raise ValueError(
                f"build_ql_ois_curve({conv.citi_index}): bootstrap produced a non-positive or NaN "
                "discount factor. The curve is NOT returned - a NaN column once shipped as "
                "'success' in this repo and that is the mistake this guard exists for."
            )

        curve = absolute_cls(pillars, discounts, day_counter)
        if enable_extrapolation:
            curve.enableExtrapolation()

        out_handle = ql.RelinkableYieldTermStructureHandle()
        out_handle.linkTo(curve)
        out_index = conv.ql_index(out_handle)

    return QLOisCurve(
        handle=out_handle,
        curve=curve,
        index=out_index,
        reference_date=_to_py_date(ref),
        citi_index=conv.citi_index,
        curve_id=cid,
        helpers=tuple(helpers),
        conventions=conv,
    )


# ------------------------------------------------------------------ #
#                             diagnostics                            #
# ------------------------------------------------------------------ #


def ql_par_reprice_errors_bp(
    curve: QLOisCurve,
    par_rates: Union[Mapping[str, float], pd.Series],
) -> pd.Series:
    """Re-price each quoted par swap off the bootstrapped curve; errors in bp.

    Parameters
    ----------
    curve
        A :class:`QLOisCurve` from :func:`build_ql_ois_curve`.
    par_rates
        The same ``{tenor: percent}`` mapping the curve was built from.

    Returns
    -------
    pandas.Series
        ``model_rate - quoted_rate`` in basis points, indexed by tenor in
        maturity order. A clean bootstrap returns values at machine precision;
        anything material means the reprice swap and the helper's swap are not
        the same instrument, which is the failure this exists to catch.

    Notes
    -----
    Runs inside :meth:`QLOisCurve.pinned` because ``MakeOIS`` resolves its spot
    date off the global evaluation date. The curve itself does not care.
    """
    conv = curve.conventions
    rates_map = _normalise_par_rates(par_rates)
    errors: Dict[str, float] = {}
    ref = _to_ql_date(curve.reference_date)
    with curve.pinned():
        index = conv.ql_index(curve.handle)
        calendar = index.fixingCalendar()
        for tenor, quoted in rates_map.items():
            swap = _make_ois(
                conv=conv,
                index=index,
                calendar=calendar,
                ref=ref,
                tenor=tenor,
                discount_handle=curve.handle,
            )
            errors[tenor] = (float(swap.fairRate()) * 100.0 - float(quoted)) * 100.0
    order = sorted(errors, key=_tenor_sort_key)
    return pd.Series({t: errors[t] for t in order}, name="reprice_error_bp", dtype=float)


def ql_forward_rate(curve: QLOisCurve, *, forward: str, tenor: str) -> float:
    """The forward-starting par OIS rate off a bootstrapped curve, in percent.

    Parameters
    ----------
    curve
        A :class:`QLOisCurve`.
    forward
        Start offset from spot, e.g. ``"5Y"``; ``"0D"`` gives the spot swap.
    tenor
        Swap tenor, e.g. ``"5Y"``.

    Returns
    -------
    float
        Par rate in **percent**, matching the units of the par grid.

    Notes
    -----
    ``MakeOIS`` builds the start as ``spot + forward`` adjusted **following**.
    :func:`MDP.CitiVelocityExcel.curves.rl_builder.forward_rate` matches that
    deliberately; modified-following on either side would move month-end
    forwards by a day and the two backends would stop agreeing for a reason that
    has nothing to do with the curves.
    """
    conv = curve.conventions
    ref = _to_ql_date(curve.reference_date)
    with curve.pinned():
        index = conv.ql_index(curve.handle)
        swap = _make_ois(
            conv=conv,
            index=index,
            calendar=index.fixingCalendar(),
            ref=ref,
            tenor=tenor,
            discount_handle=curve.handle,
            forward_start=forward,
        )
        return float(swap.fairRate()) * 100.0
