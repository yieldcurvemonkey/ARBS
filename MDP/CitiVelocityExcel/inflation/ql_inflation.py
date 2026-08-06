r"""Inflation curves and zero-coupon swaps in **QuantLib 1.41**.

QuantLib is the second opinion on the same Citi quotes. It brings three things
rateslib 2.1.1 does not have: a native **quarterly** index period (``AUD_AUCPI``),
a real **seasonality** object (:class:`ql.MultiplicativePriceSeasonality`), and a
bootstrap that reads the base index off the index's own **published fixing store**
rather than forecasting it.

Four QuantLib 1.41 facts this module is built on, all checked by calling
-----------------------------------------------------------------------
**1. The helper hard-codes the swap start at the evaluation date.**
``ZeroCouponInflationSwapHelper(quote, lag, maturity, calendar, bdc, dayCounter,
index, observationInterpolation[, nominalTS])`` takes a maturity but no start; the
swap it builds starts at ``Settings.instance().evaluationDate``. So a curve
calibrated with ``evaluationDate = ref_date`` describes swaps starting on the
quote date, not on spot. Measured: with ``evaluationDate`` left on 2026-08-05 and
a spot effective of 2026-08-07, the 1Y USD helper (``CPI.Linear``) misprices its
own quote by **0.21 bp**; moving ``evaluationDate`` to the effective date takes
that to 2.4e-12 bp. This builder therefore **sets the global evaluation date to
the swap effective date and leaves it set** - see :meth:`QLInflationCurve.activate`
for the multi-curve hazard that creates.

**2. ``PiecewiseZeroInflation`` takes an explicit base date, not a base rate.**
``PiecewiseZeroInflation(referenceDate, baseDate, frequency, dayCounter,
instruments, seasonality, accuracy, interpolator)``. The base date is the start of
the inflation period containing ``evaluationDate - observationLag``, i.e.
``ql.inflationPeriod(evalDate - lag, frequency)[0]``, and the level comes from the
index's fixing for that period. A missing fixing is a hard
``RuntimeError: Missing <index> fixing for <date>`` at bootstrap - QuantLib does
not quietly substitute, which is a genuine advantage over the rateslib path.

**3. ``CPI.Linear`` needs the month AFTER the reference month too.**
Daily-interpolated observation reads two consecutive fixings. A USD curve dated
2026-08-05 with a 3-month lag needs both May-2026 and Jun-2026 - and Jun-2026 is
published (1-month availability lag), so requiring it is correct, not an
over-ask. :func:`~MDP.CitiVelocityExcel.inflation.indices.required_fixing_months`
computes the set.

**4. ``curve.zeroRate()`` is not the breakeven.** It is the curve's own
continuously-parametrised zero inflation rate on the curve's day count at the
pillar, and it differs from the swap's fair rate by up to **0.38 bp at 1Y** on the
same calibrated curve (measured). :func:`ql_breakeven` prices an actual
:class:`ql.ZeroCouponInflationSwap` instead.

Fixings live in a global store
------------------------------
``index.addFixing`` writes into QuantLib's process-wide ``IndexManager``, keyed by
index name. Two curves on the same index share it, and a stale fixing from an
earlier build survives. This module always calls ``addFixing(..., forceOverwrite=
True)`` and records what it wrote; :func:`clear_ql_index_fixings` empties the
store for one index when you need a clean slate.

The fixed-leg day count
-----------------------
Default ``ql.Thirty360(BondBasis)``. A zero-coupon inflation swap pays
:math:`(1+r)^N` for whole N, and 30/360 between two dates with the same day of
month returns exactly N - matching rateslib's ``1+`` convention, which returns
whole periods regardless of business-day adjustment. Swapping to
``ActualActual(ISDA)`` on a fixed curve moves the fair rate by **-0.235 bp at 2Y,
-0.044 bp at 10Y, -0.015 bp at 30Y** (measured, ``_smoke.py``) because ActAct
returns N plus a leap remainder. Note 30/360 is only exactly N when the maturity
lands on its anniversary; a ModifiedFollowing roll of two days shows up as
``N + 2/360`` (the 1Y in the smoke is 1.005556), and rateslib's ``1+`` still says
1.0. That divergence is absorbed by each backend's own calibration at the
pillars, so it surfaces off-pillar and in the implied index levels - which is what
``_smoke.py`` compares, rather than the pillar breakevens that calibration pins
by construction.

Unverified
----------
No live Citi quote has been priced through this module. The round trip proves
self-consistency and cross-backend agreement on synthetic data. Conventions for
every index outside USD/EUR/GBP are market standard, and ``AUD_AUCPI``'s
observation lag in particular is a guess - the Australian convention references a
quarter, not a month.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import warnings
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd
import QuantLib as ql

from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.inflation.indices import (
    DEFAULT_CALIBRATION_TENORS,
    InflationIndexConvention,
    conventions_for,
    index_base_month,
    required_fixing_months,
    tenor_to_years,
)

__all__ = [
    "QLInflationCurve",
    "build_ql_zero_inflation_curve",
    "ql_breakeven",
    "ql_forward_breakeven",
    "ql_zc_inflation_swap",
    "ql_zc_inflation_swap_npv",
    "ql_multiplicative_seasonality",
    "clear_ql_index_fixings",
    "to_ql_date",
    "from_ql_date",
]

_logger = logging.getLogger(__name__)

#: Fixed-leg day count. 30/360 on matching days of month returns exactly N for an
#: N-year swap, which is what (1+r)^N means and what rateslib's '1+' produces.
_DEFAULT_FIXED_DAY_COUNT = "Thirty360"

#: Business day convention for the swap schedule.
_DEFAULT_BDC = ql.ModifiedFollowing

#: Bootstrap accuracy passed to PiecewiseZeroInflation. QuantLib's own default.
_BOOTSTRAP_ACCURACY = 1.0e-12

#: Acceptance threshold in bp for repricing the calibration quotes off the curve
#: just built from them. Measured achievable error is ~2e-12 bp.
_DEFAULT_TOLERANCE_BP = 1e-3

#: rateslib calendar name -> QuantLib calendar factory arguments. Only the names
#: the inflation conventions table actually uses.
_QL_CALENDARS: Dict[str, Tuple[str, Tuple[Any, ...]]] = {
    "nyc": ("UnitedStates", ("GovernmentBond",)),
    "ldn": ("UnitedKingdom", ()),
    "tgt": ("TARGET", ()),
    "tyo": ("Japan", ()),
    "stk": ("Sweden", ()),
    "syd": ("Australia", ()),
}

DateLike = Union[datetime.date, datetime.datetime]


# ------------------------------------------------------------------ #
#                            date plumbing                           #
# ------------------------------------------------------------------ #


def to_ql_date(d: Any) -> ql.Date:
    """Convert a date-like to :class:`ql.Date`."""
    if isinstance(d, ql.Date):
        return d
    if isinstance(d, pd.Timestamp):
        d = d.to_pydatetime()
    if isinstance(d, datetime.datetime):
        d = d.date()
    if isinstance(d, str):
        d = pd.Timestamp(d).date()
    if not isinstance(d, datetime.date):
        raise TypeError(f"Cannot interpret {d!r} as a date.")
    return ql.Date(d.day, d.month, d.year)


def from_ql_date(d: ql.Date) -> datetime.date:
    """Convert a :class:`ql.Date` to :class:`datetime.date`."""
    return datetime.date(d.year(), d.month(), d.dayOfMonth())


def _ql_calendar(name: str) -> ql.Calendar:
    """QuantLib calendar for a rateslib calendar name used by the conventions table."""
    key = str(name).strip().lower()
    if key not in _QL_CALENDARS:
        raise CitiVelocityError(
            f"No QuantLib calendar mapped for rateslib calendar {name!r}. Mapped: "
            f"{', '.join(sorted(_QL_CALENDARS))}. Pass `ql_calendar` explicitly rather "
            "than letting a proxy calendar misdate the rolls."
        )
    cls_name, args = _QL_CALENDARS[key]
    cls = getattr(ql, cls_name)
    resolved = [getattr(cls, a) if isinstance(a, str) else a for a in args]
    return cls(*resolved) if resolved else cls()


def _fixed_day_count(name: str) -> ql.DayCounter:
    if isinstance(name, ql.DayCounter):
        return name
    key = str(name).strip().lower().replace("/", "").replace("_", "")
    if key in {"thirty360", "30360", "thirty360bondbasis"}:
        return ql.Thirty360(ql.Thirty360.BondBasis)
    if key in {"actactisda", "actualactualisda", "actact"}:
        return ql.ActualActual(ql.ActualActual.ISDA)
    if key in {"act365f", "actual365fixed"}:
        return ql.Actual365Fixed()
    if key in {"act360", "actual360"}:
        return ql.Actual360()
    raise ValueError(
        f"Unknown fixed-leg day count {name!r}. Use 'Thirty360' (exactly N years for "
        "an N-year swap, matching rateslib's '1+'), 'ActActISDA', 'Act365F' or 'Act360', "
        "or pass a ql.DayCounter."
    )


# ------------------------------------------------------------------ #
#                              records                               #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class QLInflationCurve:
    """A bootstrapped QuantLib zero inflation curve and its audit trail.

    Attributes
    ----------
    citi_index, convention
        Identity and conventions.
    curve
        The :class:`ql.PiecewiseZeroInflation`.
    handle
        The relinkable handle the index is bound to. Keep it alive: QuantLib
        objects are reference-linked and a garbage-collected handle takes the
        index's forecasting ability with it.
    index
        The :class:`ql.ZeroInflationIndex`, already linked to ``handle``.
    nominal_handle
        The discount curve handle. It does not affect breakevens - both ZCIS legs
        settle on the same date - only NPVs.
    ref_date
        The quote date passed in.
    effective
        Swap effective date. **This is also the QuantLib evaluation date**, because
        ``ZeroCouponInflationSwapHelper`` starts its swap there.
    base_date
        Start of the index period the curve's base level comes from.
    fixings_written
        ``{reference-period-start: level}`` this build pushed into QuantLib's
        global index store.
    max_repricing_error_bp
        Worst absolute error, in bp, repricing ``quotes`` with an actual
        :class:`ql.ZeroCouponInflationSwap`.
    """

    citi_index: str
    convention: InflationIndexConvention
    curve: Any
    handle: Any
    index: Any
    nominal_handle: Any
    calendar: Any
    fixed_day_count: Any
    observation_interpolation: Any
    ref_date: datetime.date
    effective: datetime.date
    base_date: datetime.date
    tenors: Tuple[str, ...]
    quotes: Tuple[float, ...]
    maturities: Tuple[datetime.date, ...]
    max_repricing_error_bp: float
    fixings_written: Mapping[datetime.date, float]
    seasonality: Any = None

    @property
    def observation_lag(self) -> Any:
        return ql.Period(self.convention.observation_lag, ql.Months)

    def activate(self) -> None:
        """Re-point QuantLib's global evaluation date at this curve's effective date.

        QuantLib has exactly one evaluation date per process. Building a second
        inflation curve with a different effective date silently re-dates this one
        - a GBP curve (T+0) built after a USD curve (T+2) moves the global back two
        days and every USD number computed afterwards is off. Call this before
        pricing off a curve whenever more than one is in play. Every function in
        this module that prices calls it for you.
        """
        ql.Settings.instance().evaluationDate = to_ql_date(self.effective)

    def index_value(self, date: DateLike) -> float:
        """Index level a swap or linker observing on ``date`` would read."""
        self.activate()
        return float(
            ql.CPI.laggedFixing(
                self.index,
                to_ql_date(date),
                self.observation_lag,
                self.observation_interpolation,
            )
        )

    def breakeven(self, tenor: str) -> float:
        """Zero-coupon breakeven in percent for ``tenor`` off this curve."""
        return ql_breakeven(self, tenor)

    def summary(self) -> str:
        """One-block human summary, including provenance and the fitted error."""
        flag = "  (CONVENTIONS APPROXIMATE)" if self.convention.approximate else ""
        return "\n".join(
            [
                f"{self.citi_index} QuantLib zero inflation curve{flag}",
                f"  ref {self.ref_date:%Y-%m-%d}  effective/evalDate {self.effective:%Y-%m-%d}  "
                f"baseDate {self.base_date:%Y-%m-%d}",
                f"  lag {self.convention.observation_lag}M  observation CPI."
                f"{self.convention.ql_observation_interpolation_name}  "
                f"frequency {self.convention.frequency}  "
                f"{len(self.fixings_written)} fixings written",
                f"  {len(self.tenors)} pillars {self.tenors[0]}..{self.tenors[-1]}  "
                f"max repricing error {self.max_repricing_error_bp:.3e} bp",
            ]
        )


# ------------------------------------------------------------------ #
#                              fixings                               #
# ------------------------------------------------------------------ #


def clear_ql_index_fixings(index: Any) -> None:
    """Empty QuantLib's global fixing history for one index.

    ``addFixing`` writes into a process-wide store keyed by index name, so a stale
    level from an earlier build survives into the next one. Call this when
    rebuilding with a different fixing vintage.
    """
    ql.IndexManager.instance().clearHistory(index.name())


def _normalise_fixings(fixings: Any) -> Dict[datetime.date, float]:
    """``{first-of-period: level}`` from a mapping or Series, validated."""
    if fixings is None:
        return {}
    if isinstance(fixings, pd.Series):
        items = list(zip(fixings.index, fixings.to_numpy()))
    else:
        items = list(dict(fixings).items())
    out: Dict[datetime.date, float] = {}
    for key, value in items:
        d = from_ql_date(to_ql_date(key))
        if d.day != 1:
            raise ValueError(
                f"Inflation fixing dated {d:%Y-%m-%d}: QuantLib keys zero-inflation "
                "fixings on the FIRST day of the reference period. Re-stamp the series "
                f"to {d:%Y-%m}-01."
            )
        level = float(value)
        if not (level > 0.0):
            raise ValueError(f"Inflation fixing for {d:%Y-%m} is {value!r}; must be positive.")
        out[d] = level
    return dict(sorted(out.items()))


# ------------------------------------------------------------------ #
#                            seasonality                             #
# ------------------------------------------------------------------ #


def ql_multiplicative_seasonality(
    *,
    factors: Sequence[float],
    base_date: DateLike,
    frequency: str = "monthly",
) -> Any:
    """Build a :class:`ql.MultiplicativePriceSeasonality`.

    Parameters
    ----------
    factors
        12 monthly (or 4 quarterly) multiplicative factors.
    base_date
        The period the factors are indexed from.
    frequency
        ``monthly`` or ``quarterly``.

    Returns
    -------
    ql.MultiplicativePriceSeasonality

    Notes
    -----
    rateslib 2.1.1 has **no** seasonality model. A QuantLib curve carrying
    seasonality and a rateslib curve without it are not comparable, and
    :func:`build_ql_zero_inflation_curve` warns when one is attached for that
    reason. Seasonality does not change whole-year zero-coupon breakevens - the
    two observations fall in the same calendar month and the factor cancels - it
    changes off-anniversary and month-by-month index forecasts.
    """
    freq = ql.Quarterly if str(frequency).lower() == "quarterly" else ql.Monthly
    expected = 4 if freq == ql.Quarterly else 12
    values = [float(f) for f in factors]
    if len(values) != expected:
        raise ValueError(
            f"{frequency} seasonality needs {expected} factors, got {len(values)}."
        )
    return ql.MultiplicativePriceSeasonality(to_ql_date(base_date), freq, values)


# ------------------------------------------------------------------ #
#                            curve build                             #
# ------------------------------------------------------------------ #


def build_ql_zero_inflation_curve(
    *,
    zc_swap_rates: Mapping[str, float],
    ref_date: DateLike,
    citi_index: str,
    nominal_handle: Any = None,
    fixings: Any = None,
    index_base: Optional[float] = None,
    effective: Optional[DateLike] = None,
    observation_lag: Optional[int] = None,
    observation_interpolation: Any = None,
    calendar: Any = None,
    fixed_day_count: Any = _DEFAULT_FIXED_DAY_COUNT,
    curve_day_count: Any = None,
    seasonality: Any = None,
    tolerance_bp: float = _DEFAULT_TOLERANCE_BP,
    clear_existing_fixings: bool = True,
) -> QLInflationCurve:
    """Bootstrap a QuantLib zero inflation curve from Citi zero-coupon swap quotes.

    Parameters
    ----------
    zc_swap_rates
        ``{tenor: rate}`` in **percent**, as Citi serves
        ``RATES.INFLATION.SWAP.<index>.<tenor>``. ``SPOT`` and NaN are rejected.
    ref_date
        Quote date.
    citi_index
        Citi token, e.g. ``USD_CPURNSA``.
    nominal_handle
        A :class:`ql.YieldTermStructureHandle` for discounting. Optional: a ZCIS's
        fair rate does not depend on it. If omitted a zero-rate flat handle is used
        and a warning is emitted, because NPVs off it are undiscounted.
    fixings
        Published index levels, ``{first-of-period: level}`` or a Series. Required
        in practice: QuantLib reads the base level out of the index's fixing store
        and raises ``Missing <index> fixing for <date>`` without it. Use
        :func:`~MDP.CitiVelocityExcel.inflation.indices.required_fixing_months` to
        see the minimum set.
    index_base
        Convenience fallback used only when ``fixings`` is None: the published
        level for the base period, written as a single fixing. Rejected for
        daily-interpolated (``CPI.Linear``) indices, which need two consecutive
        fixings and would otherwise be silently anchored on a flat month.
    effective
        Swap effective date, and **the QuantLib evaluation date this build
        installs**. Defaults to ``ref_date`` plus the index's spot lag.
    observation_lag, observation_interpolation, calendar
        Overrides for the conventions table.
    fixed_day_count
        Fixed-leg day count. Default ``Thirty360`` (BondBasis) so an N-year swap
        has year fraction exactly N.
    curve_day_count
        Day count the curve reports zero rates on. Defaults to ``fixed_day_count``.
        It does not affect breakevens.
    seasonality
        A :class:`ql.Seasonality`, or a sequence of 12/4 multiplicative factors.
        Warns: rateslib has no equivalent, so the backends stop being comparable.
    tolerance_bp
        Maximum acceptable error, in bp, repricing the input quotes off the
        bootstrapped curve. Exceeding it raises.
    clear_existing_fixings
        Empty QuantLib's global fixing store for this index first. Default True,
        because the store is process-wide and a stale level from an earlier build
        would otherwise survive.

    Returns
    -------
    QLInflationCurve

    Raises
    ------
    CitiVelocityError
        If the bootstrap fails, if required fixings are missing, or if the
        calibration quotes do not reprice within ``tolerance_bp``.
    ValueError
        On malformed quotes, tenors or fixings.
    """
    convention = conventions_for(citi_index)
    if convention.approximate:
        _logger.warning(
            "%s: inflation conventions are %s (lag %dM, %s observation), not "
            "library-supplied. %s",
            convention.citi_index,
            convention.provenance,
            convention.observation_lag,
            convention.index_method,
            convention.note or "Verify against the desk before trading off this curve.",
        )

    lag_months = int(observation_lag) if observation_lag is not None else convention.observation_lag
    lag = ql.Period(lag_months, ql.Months)
    obs = (
        observation_interpolation
        if observation_interpolation is not None
        else convention.ql_observation_interpolation()
    )
    cal = calendar if calendar is not None else _ql_calendar(convention.calendar)
    fixed_dc = _fixed_day_count(fixed_day_count)
    curve_dc = _fixed_day_count(curve_day_count) if curve_day_count is not None else fixed_dc
    frequency = convention.ql_frequency()

    ref = from_ql_date(to_ql_date(ref_date))
    if effective is not None:
        eff = from_ql_date(to_ql_date(effective))
    elif convention.spot_lag:
        eff = from_ql_date(cal.advance(to_ql_date(ref), ql.Period(convention.spot_lag, ql.Days)))
    else:
        eff = ref
    if eff < ref:
        raise ValueError(
            f"effective {eff:%Y-%m-%d} precedes ref_date {ref:%Y-%m-%d}."
        )

    tenors, quotes = _sorted_quotes(zc_swap_rates)
    short = [t for t in tenors if tenor_to_years(t) < 1.0]
    if short:
        warnings.warn(
            f"{convention.citi_index}: calibrating on sub-1Y tenors {', '.join(short)}. "
            "Their observation months are largely published already, so the quote is "
            "index arithmetic rather than a forward view, and the seasonal factor no "
            "longer cancels between the two observations. Prefer "
            f"DEFAULT_CALIBRATION_TENORS ({DEFAULT_CALIBRATION_TENORS[0]}..."
            f"{DEFAULT_CALIBRATION_TENORS[-1]}).",
            stacklevel=2,
        )

    # ZeroCouponInflationSwapHelper starts its swap at the evaluation date, so the
    # evaluation date IS the effective date. Measured: leaving it on ref_date
    # misprices the 1Y USD helper by 0.21 bp against its own quote.
    ql.Settings.instance().evaluationDate = to_ql_date(eff)

    handle = ql.RelinkableZeroInflationTermStructureHandle()
    index = convention.ql_index(handle)

    if clear_existing_fixings:
        clear_ql_index_fixings(index)

    # Overrides change WHICH months are needed, so the fixing requirement is
    # computed against the effective convention rather than the table's.
    effective_convention = dataclasses.replace(
        convention,
        observation_lag=lag_months,
        index_method="daily" if obs == ql.CPI.Linear else "monthly",
    )
    fixing_map = _normalise_fixings(fixings)
    base_period = index_base_month(ref, effective_convention)
    needed = required_fixing_months(ref, eff, effective_convention)
    if not fixing_map:
        if index_base is None:
            raise CitiVelocityError(
                f"{convention.citi_index}: QuantLib reads the curve's base level out of "
                "the index's fixing store, so `fixings` (or `index_base`) is required. "
                f"The minimum set for a swap effective {eff:%Y-%m-%d} under a "
                f"{lag_months}M {convention.index_method} observation is "
                f"{', '.join(m.strftime('%Y-%m') for m in needed)}."
            )
        if effective_convention.index_method == "daily":
            raise CitiVelocityError(
                f"{convention.citi_index} observes the index with DAILY interpolation, "
                "which reads two consecutive fixings. A single `index_base` would anchor "
                "it on a flat month and quietly shift the base by up to a month of "
                f"inflation. Pass `fixings` covering "
                f"{', '.join(m.strftime('%Y-%m') for m in needed)}."
            )
        fixing_map = {base_period: float(index_base)}

    missing = [m for m in needed if m not in fixing_map]
    if missing:
        raise CitiVelocityError(
            f"{convention.citi_index}: `fixings` is missing "
            f"{', '.join(m.strftime('%Y-%m') for m in missing)}. QuantLib will raise "
            "'Missing fixing' mid-bootstrap; failing here instead names the months. "
            f"(Base period is {base_period:%Y-%m}.)"
        )

    for period_start, level in fixing_map.items():
        index.addFixing(to_ql_date(period_start), float(level), True)

    if nominal_handle is None:
        warnings.warn(
            f"{convention.citi_index}: no `nominal_handle` supplied, so a flat 0% "
            "discount handle is used. Breakevens are unaffected - both ZCIS legs settle "
            "on the same date and the discount factor cancels - but NPVs are "
            "undiscounted.",
            stacklevel=2,
        )
        nominal = ql.YieldTermStructureHandle(
            ql.FlatForward(to_ql_date(eff), ql.QuoteHandle(ql.SimpleQuote(0.0)), ql.Actual365Fixed())
        )
    else:
        nominal = nominal_handle

    seasonality_obj = None
    if seasonality is not None:
        seasonality_obj = (
            seasonality
            if isinstance(seasonality, ql.Seasonality)
            else ql_multiplicative_seasonality(
                factors=seasonality, base_date=base_period, frequency=convention.frequency
            )
        )
        warnings.warn(
            f"{convention.citi_index}: seasonality attached. rateslib 2.1.1 has no "
            "seasonality model, so this curve is no longer comparable with a "
            "build_rl_index_curve result - the difference between them will be the "
            "seasonal adjustment, not a bug.",
            stacklevel=2,
        )

    maturities = [
        from_ql_date(cal.advance(to_ql_date(eff), ql.Period(t), _DEFAULT_BDC))
        for t in tenors
    ]
    seen: Dict[datetime.date, str] = {}
    for tenor, mat in zip(tenors, maturities):
        if mat in seen:
            raise ValueError(
                f"Tenors {seen[mat]} and {tenor} both roll to {mat:%Y-%m-%d}; the "
                "bootstrap would have two helpers on one pillar. Drop one."
            )
        seen[mat] = tenor

    helpers = [
        ql.ZeroCouponInflationSwapHelper(
            ql.QuoteHandle(ql.SimpleQuote(q / 100.0)),
            lag,
            to_ql_date(mat),
            cal,
            _DEFAULT_BDC,
            fixed_dc,
            index,
            obs,
            nominal,
        )
        for mat, q in zip(maturities, quotes)
    ]

    base_date = ql.inflationPeriod(to_ql_date(eff) - lag, frequency)[0]
    try:
        if seasonality_obj is not None:
            curve = ql.PiecewiseZeroInflation(
                to_ql_date(eff), base_date, frequency, curve_dc, helpers,
                seasonality_obj, _BOOTSTRAP_ACCURACY,
            )
        else:
            curve = ql.PiecewiseZeroInflation(
                to_ql_date(eff), base_date, frequency, curve_dc, helpers,
            )
        curve.enableExtrapolation()
        handle.linkTo(curve)
        # The bootstrap is lazy: nothing runs until the curve is queried.
        _ = curve.maxDate()
        _ = curve.zeroRate(to_ql_date(maturities[-1]), lag, False)
    except RuntimeError as exc:
        raise CitiVelocityError(
            f"{convention.citi_index}: QuantLib zero-inflation bootstrap failed. "
            f"baseDate {from_ql_date(base_date):%Y-%m-%d}, evaluation date "
            f"{eff:%Y-%m-%d}, {len(helpers)} helpers, fixings "
            f"{min(fixing_map):%Y-%m}..{max(fixing_map):%Y-%m}. "
            f"Underlying: {exc}"
        ) from exc

    errors_bp: List[float] = []
    for tenor, mat, q in zip(tenors, maturities, quotes):
        swap = _zc_swap(
            index=index, calendar=cal, day_count=fixed_dc, obs=obs, lag=lag,
            effective=eff, maturity=mat, fixed_rate=q / 100.0, notional=1.0e6,
        )
        swap.setPricingEngine(ql.DiscountingSwapEngine(nominal))
        errors_bp.append(abs(swap.fairRate() * 100.0 - q) * 100.0)
    max_error = max(errors_bp)
    if max_error > tolerance_bp:
        worst = tenors[errors_bp.index(max_error)]
        raise CitiVelocityError(
            f"{convention.citi_index}: bootstrapped curve misprices its own calibration "
            f"set - worst {worst} by {max_error:.4f} bp against a {tolerance_bp} bp "
            "tolerance. The curve is not returned. The usual cause is an evaluation "
            "date that does not match the swap effective date: "
            "ZeroCouponInflationSwapHelper starts its swap at "
            "Settings.instance().evaluationDate."
        )

    return QLInflationCurve(
        citi_index=convention.citi_index,
        convention=convention,
        curve=curve,
        handle=handle,
        index=index,
        nominal_handle=nominal,
        calendar=cal,
        fixed_day_count=fixed_dc,
        observation_interpolation=obs,
        ref_date=ref,
        effective=eff,
        base_date=from_ql_date(base_date),
        tenors=tenors,
        quotes=quotes,
        maturities=tuple(maturities),
        max_repricing_error_bp=max_error,
        fixings_written=fixing_map,
        seasonality=seasonality_obj,
    )


def _sorted_quotes(
    zc_swap_rates: Mapping[str, float],
) -> Tuple[Tuple[str, ...], Tuple[float, ...]]:
    """Order a ``{tenor: rate}`` map by maturity and reject junk."""
    if not zc_swap_rates:
        raise ValueError("`zc_swap_rates` is empty; nothing to calibrate to.")
    pairs: List[Tuple[float, str, float]] = []
    for tenor, rate in zc_swap_rates.items():
        token = str(tenor).strip().upper()
        if token == "SPOT":
            raise ValueError(
                "SPOT is a level, not a tenor - it cannot be a calibration instrument. "
                f"Usable tenors: {', '.join(DEFAULT_CALIBRATION_TENORS)}."
            )
        value = float(rate)
        if value != value:
            raise ValueError(
                f"Quote for {token} is NaN. Citi serves NaN for tenors it is not making "
                "a market in that day; drop them rather than calibrate through."
            )
        pairs.append((tenor_to_years(token), token, value))
    pairs.sort()
    return tuple(p[1] for p in pairs), tuple(p[2] for p in pairs)


# ------------------------------------------------------------------ #
#                          swaps / breakevens                        #
# ------------------------------------------------------------------ #


def _zc_swap(
    *,
    index: Any,
    calendar: Any,
    day_count: Any,
    obs: Any,
    lag: Any,
    effective: datetime.date,
    maturity: datetime.date,
    fixed_rate: float,
    notional: float,
    pay_fixed: bool = True,
) -> Any:
    """A :class:`ql.ZeroCouponInflationSwap` on the given terms (rate as a decimal)."""
    return ql.ZeroCouponInflationSwap(
        ql.Swap.Payer if pay_fixed else ql.Swap.Receiver,
        float(notional),
        to_ql_date(effective),
        to_ql_date(maturity),
        calendar,
        _DEFAULT_BDC,
        day_count,
        float(fixed_rate),
        index,
        lag,
        obs,
    )


def ql_zc_inflation_swap(
    *,
    curve: QLInflationCurve,
    tenor: Optional[str] = None,
    maturity: Optional[DateLike] = None,
    fixed_rate: float = 0.0,
    notional: float = 1.0e6,
    pay_fixed: bool = True,
) -> Any:
    """Build a priced :class:`ql.ZeroCouponInflationSwap` off a calibrated curve.

    Parameters
    ----------
    curve
        A :class:`QLInflationCurve`. Its evaluation date is re-activated first.
    tenor, maturity
        Give exactly one. ``tenor`` rolls off the curve's effective date on the
        curve's calendar with ModifiedFollowing.
    fixed_rate
        In **percent**, matching Citi's quoting.
    notional, pay_fixed
        Leg terms. ``pay_fixed`` sets ``ql.Swap.Payer``.

    Returns
    -------
    ql.ZeroCouponInflationSwap
        With a :class:`ql.DiscountingSwapEngine` already attached.
    """
    if (tenor is None) == (maturity is None):
        raise ValueError("Give exactly one of `tenor` or `maturity`.")
    curve.activate()
    if tenor is not None:
        tenor_to_years(tenor)  # validates the token
        mat = from_ql_date(
            curve.calendar.advance(to_ql_date(curve.effective), ql.Period(str(tenor)), _DEFAULT_BDC)
        )
    else:
        mat = from_ql_date(to_ql_date(maturity))
    swap = _zc_swap(
        index=curve.index,
        calendar=curve.calendar,
        day_count=curve.fixed_day_count,
        obs=curve.observation_interpolation,
        lag=curve.observation_lag,
        effective=curve.effective,
        maturity=mat,
        fixed_rate=float(fixed_rate) / 100.0,
        notional=notional,
        pay_fixed=pay_fixed,
    )
    swap.setPricingEngine(ql.DiscountingSwapEngine(curve.nominal_handle))
    return swap


def ql_breakeven(curve: QLInflationCurve, tenor: str) -> float:
    """Zero-coupon inflation breakeven, in percent, for ``tenor``.

    This prices an actual :class:`ql.ZeroCouponInflationSwap` and returns its fair
    rate. It is deliberately **not** ``curve.zeroRate(...)``: that is the curve's
    own parametrisation on the curve's day count at the pillar date and differs
    from the tradeable rate by up to 0.38 bp at 1Y on the same calibrated curve
    (measured on the synthetic USD curve in ``_smoke.py``).

    Parameters
    ----------
    curve
        A calibrated :class:`QLInflationCurve`.
    tenor
        ``5Y``, ``10Y``, ...

    Returns
    -------
    float
        Percent, on the ``(1+r)^N`` convention Citi quotes.
    """
    if not isinstance(curve, QLInflationCurve):
        raise TypeError(
            "ql_breakeven takes the QLInflationCurve returned by "
            f"build_ql_zero_inflation_curve, not {type(curve).__name__}."
        )
    swap = ql_zc_inflation_swap(curve=curve, tenor=tenor)
    return float(swap.fairRate()) * 100.0


def ql_forward_breakeven(curve: QLInflationCurve, forward: str, tenor: str) -> float:
    r"""Forward-starting breakeven, in percent, from the index curve directly.

    .. math::

        (1 + r_{f \times n})^{n} = \frac{I(T_{f+n} - L)}{I(T_f - L)}

    Uses :func:`ql.CPI.laggedFixing` at both ends so the observation lag and
    interpolation are applied exactly once.
    """
    n_years = tenor_to_years(tenor)
    if n_years <= 0:
        raise ValueError(f"tenor {tenor!r} must be positive.")
    curve.activate()
    start = curve.calendar.advance(to_ql_date(curve.effective), ql.Period(str(forward)), _DEFAULT_BDC)
    end = curve.calendar.advance(start, ql.Period(str(tenor)), _DEFAULT_BDC)
    i_start = float(
        ql.CPI.laggedFixing(curve.index, start, curve.observation_lag, curve.observation_interpolation)
    )
    i_end = float(
        ql.CPI.laggedFixing(curve.index, end, curve.observation_lag, curve.observation_interpolation)
    )
    if not (i_start > 0.0 and i_end > 0.0):
        raise CitiVelocityError(
            f"{curve.citi_index}: forward breakeven {forward}x{tenor} read a non-positive "
            f"index level (start {i_start!r}, end {i_end!r}). Not returned."
        )
    return ((i_end / i_start) ** (1.0 / n_years) - 1.0) * 100.0


def ql_zc_inflation_swap_npv(
    *,
    curve: QLInflationCurve,
    fixed_rate: float,
    tenor: Optional[str] = None,
    maturity: Optional[DateLike] = None,
    notional: float = 1.0e6,
    pay_fixed: bool = True,
) -> float:
    """NPV of a zero-coupon inflation swap off a calibrated curve.

    Parameters
    ----------
    curve
        A calibrated :class:`QLInflationCurve`.
    fixed_rate
        In **percent**.
    tenor, maturity
        Give exactly one.
    notional, pay_fixed
        Leg terms.

    Returns
    -------
    float
        Present value in the swap's currency. **Discounted on
        ``curve.nominal_handle``** - if no nominal handle was supplied at build
        time that is a flat 0% curve and this number is undiscounted.
    """
    swap = ql_zc_inflation_swap(
        curve=curve,
        tenor=tenor,
        maturity=maturity,
        fixed_rate=fixed_rate,
        notional=notional,
        pay_fixed=pay_fixed,
    )
    npv = float(swap.NPV())
    if npv != npv:
        raise CitiVelocityError(
            f"{curve.citi_index}: zero-coupon inflation swap NPV came back NaN. Not "
            "returned. Check that the maturity is inside the curve's range and that "
            "the nominal handle covers the payment date."
        )
    return npv
