r"""Inflation curves, zero-coupon swaps and linkers in **rateslib 2.1.1**.

What rateslib 2.1.1 actually has
--------------------------------
There is **no ``IndexCurve`` class** in this version. An index curve is a plain
:class:`rateslib.Curve` carrying two extra pieces of metadata - ``index_base``
(the published index level at the curve's initial node, under the curve's own lag)
and ``index_lag`` - from which :meth:`Curve.index_value` derives every forecast
level as :math:`I(m) = I_b / v(m)`. The instruments are :class:`rateslib.ZCIS`,
:class:`rateslib.IIRS`, :class:`rateslib.IndexFixedRateBond`, and the free
function :func:`rateslib.index_value` for blending published fixings with curve
forecasts. There is also no seasonality object of any kind. Everything here is
built from those primitives plus the conventions in
:mod:`MDP.CitiVelocityExcel.inflation.indices`.

The silent-zero trap, which this module exists to close
-------------------------------------------------------
:meth:`Curve.index_value` with ``interpolation="monthly"`` or ``"daily"`` reads the
curve at the **first of the month**. If that date precedes the curve's initial
node, rateslib emits a ``UserWarning`` and **returns 0.0**. A swap built on that
zero still calibrates: the solver converges to ``f_val`` ~1e-16, every input
reprices to 1e-6 bp, and the index base on the cashflow table is nonsense.
Measured in ``_smoke.py`` - a USD curve anchored on 2026-08-05 instead of
2026-08-01, with a swap effective 2026-08-07, produces an index base of **62.03
against a true level of 320.13**, and reports success.

The same zero reaches index-linked bonds, and there it is worse: a seasoned
linker's early periods observe months before any 2026 curve starts, so they price
at zero and the bond still returns a number. Measured on a 2013-issue 0.125%
index-linked gilt against a synthetic 2026 RPI curve - **clean price 1445.60
without the published fixings, 93.40 with them** (26 of 47 periods valued at
zero), same descriptor, same curves.

So this module anchors the curve's initial node on the **first of the month of
``ref_date``**, never on ``ref_date``; asserts that every index value the curve
depends on is finite and strictly positive before returning
(:func:`_assert_index_values_populated`); and refuses to hand back a bond with a
zero-valued period (:func:`_assert_bond_index_populated`). Compare
``_assert_risk_populated`` in the tape pipeline: the same class of bug shipped
once already.

Discounting does not move a breakeven
-------------------------------------
Both legs of a zero-coupon inflation swap settle on the same date, so the discount
factor cancels exactly out of the fair rate. The nominal curve therefore affects
``npv`` and ``analytic_delta`` and nothing else. ``_smoke.py`` verifies this
numerically (breakevens identical to 1e-12 bp across a 0% and a 6% nominal
curve). When no nominal curve is passed a unit-discount placeholder is used and a
warning is emitted, because NPVs off it are undiscounted.

Quarterly indices raise
-----------------------
``AUD_AUCPI`` is quarterly and rateslib 2.1.1 has no quarterly index period at
all. :func:`build_rl_index_curve` raises rather than return a monthly-shaped
number; use :mod:`MDP.CitiVelocityExcel.inflation.ql_inflation`.

Unverified, and one thing the round trip structurally cannot prove
------------------------------------------------------------------
Nothing in this module has been run against a **live Citi quote**. The round-trip
in ``_smoke.py`` is self-consistency on a synthetic curve: it proves the builder
inverts its own pricer and that the two backends agree, not that the conventions
match what Citi is quoting.

More sharply: **the round trip is blind to the observation lag.** Rebuild the USD
curve at a 6-month lag with a correspondingly 6-month-lagged base and every
breakeven is unchanged to 0.00e+00 bp and the repricing error is bit-identical
(2.18e-06 bp either way, measured). The lag shifts both observations together, so
the ratio - hence the fixed rate - is invariant; only the implied index LEVEL
moves, by 61.9 bp for a three-month error on a 2.5% history. No amount of
self-consistency testing will find a wrong lag. That is why the conventions table
records its provenance per index and why the lag and interpolation method for
every index outside USD/EUR/GBP are flagged
:attr:`InflationIndexConvention.approximate`.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import warnings
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd
import rateslib as rl

from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.inflation.indices import (
    DEFAULT_CALIBRATION_TENORS,
    InflationIndexConvention,
    LinkerConvention,
    conventions_for,
    index_base_month,
    linker_conventions_for,
    required_fixing_months,
    tenor_to_years,
)

__all__ = [
    "RLIndexCurve",
    "IndexBondDescriptor",
    "build_rl_index_curve",
    "rl_breakeven",
    "rl_forward_breakeven",
    "build_rl_zcis",
    "rl_index_bond",
    "rl_index_fixings_series",
]

_logger = logging.getLogger(__name__)

#: Day count for the index curve itself. Immaterial to breakevens - the index
#: curve's "rate" is never quoted - but it must be set for the Curve to build.
_INDEX_CURVE_CONVENTION = "act365f"

#: Terminal node of the placeholder nominal curve. Well past the 40Y tenor Citi's
#: axis reaches from any plausible reference date.
_NOMINAL_PLACEHOLDER_END = datetime.datetime(2100, 1, 1)

#: Default acceptance threshold, in basis points, for repricing the calibration
#: quotes off the curve that was just built from them. Measured achievable error
#: with ``func_tol=1e-14`` is ~2e-6 bp, i.e. three orders of margin.
_DEFAULT_TOLERANCE_BP = 1e-3

DateLike = Union[datetime.date, datetime.datetime]


# ------------------------------------------------------------------ #
#                              records                               #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class RLIndexCurve:
    """A calibrated rateslib inflation index curve and its audit trail.

    Attributes
    ----------
    citi_index
        The Citi token this was built for.
    convention
        The conventions used, including whether they are approximate.
    curve
        The :class:`rateslib.Curve` carrying ``index_base`` and ``index_lag``.
        This IS the index curve - rateslib 2.1.1 has no separate class.
    nominal
        The discount curve. A unit-discount placeholder if none was supplied.
    solver
        The converged :class:`rateslib.Solver`.
    ref_date
        Curve reference date (the quote date).
    anchor
        The curve's initial node: the first of ``ref_date``'s month. Not
        ``ref_date`` - see the module docstring.
    effective
        Swap effective (spot) date used for every calibration instrument.
    index_base
        Published index level at ``anchor`` under ``index_lag`` months of lag,
        i.e. the fixing for :attr:`index_base_month`.
    index_base_month
        First day of the index period supplying ``index_base``.
    swap_index_base
        The base index the calibration swaps observe at ``effective``. Equals
        ``index_base`` when the effective date falls on the first of the month
        under a monthly observation; differs by the daily interpolation otherwise.
    tenors, quotes
        The calibration set, in tenor order, quotes in percent.
    instruments
        The calibrated :class:`rateslib.ZCIS` objects, parallel to ``tenors``.
    max_repricing_error_bp
        Worst absolute error, in bp, repricing ``quotes`` off ``curve``.
    index_fixings
        Published fixings supplied by the caller, if any.
    """

    citi_index: str
    convention: InflationIndexConvention
    curve: Any
    nominal: Any
    solver: Any
    ref_date: datetime.datetime
    anchor: datetime.datetime
    effective: datetime.datetime
    index_base: float
    index_base_month: datetime.date
    swap_index_base: float
    tenors: Tuple[str, ...]
    quotes: Tuple[float, ...]
    instruments: Tuple[Any, ...]
    max_repricing_error_bp: float
    #: The lag and method ACTUALLY used, which may be caller overrides rather than
    #: the conventions table's. Deriving these from ``convention`` instead was a
    #: live bug: an overridden curve then handed its swaps the table's lag, and
    #: rateslib 2.1.1 fails on a negative lag difference with
    #: ``ValueError: could not convert string to float: '--3'`` from add_tenor.
    index_lag: int = 0
    index_method: str = "monthly"
    index_fixings: Optional[Any] = None

    def index_value(self, date: DateLike) -> float:
        """Forecast index level for an observation on ``date``.

        Applies the index's own lag and interpolation method, so this is the
        number a swap or linker settling on ``date`` would read.
        """
        d = _as_datetime(date)
        return float(self.curve.index_value(d, self.index_lag, self.index_method))

    def breakeven(self, tenor: str) -> float:
        """Zero-coupon breakeven in percent for ``tenor`` off this curve."""
        return rl_breakeven(self, tenor)

    def summary(self) -> str:
        """One-block human summary, including provenance and the fitted error."""
        flag = "  (CONVENTIONS APPROXIMATE)" if self.convention.approximate else ""
        lines = [
            f"{self.citi_index} rateslib index curve{flag}",
            f"  ref {self.ref_date:%Y-%m-%d}  anchor {self.anchor:%Y-%m-%d}  "
            f"effective {self.effective:%Y-%m-%d}",
            f"  lag {self.index_lag}M  method {self.index_method}  "
            f"index_base {self.index_base:.5f} ({self.index_base_month:%Y-%m})  "
            f"swap base {self.swap_index_base:.5f}",
            f"  {len(self.tenors)} pillars {self.tenors[0]}..{self.tenors[-1]}  "
            f"max repricing error {self.max_repricing_error_bp:.3e} bp",
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class IndexBondDescriptor:
    """The static terms of an index-linked bond.

    ``index_base`` is the **base index printed in the prospectus** - the index
    level fixed at issue, not the curve's anchor and not today's fixing. There is
    no default and no fallback: a linker priced off the wrong base is wrong by the
    entire inflation accrual since issue, and that error is invisible in the
    yield.
    """

    citi_index: str
    effective: DateLike
    termination: Union[str, DateLike]
    fixed_rate: float
    index_base: float
    notional: float = 100.0
    frequency: Optional[str] = None
    convention: Optional[str] = None
    calendar: Optional[str] = None
    currency: Optional[str] = None
    spec: Optional[str] = None
    settle: Optional[int] = None
    ex_div: Optional[int] = None
    calc_mode: Optional[str] = None
    index_lag: Optional[int] = None
    index_method: Optional[str] = None


# ------------------------------------------------------------------ #
#                              helpers                               #
# ------------------------------------------------------------------ #


def _as_datetime(d: Any) -> datetime.datetime:
    """Coerce a date-like to the naive ``datetime`` rateslib expects."""
    if isinstance(d, datetime.datetime):
        return datetime.datetime(d.year, d.month, d.day)
    if isinstance(d, datetime.date):
        return datetime.datetime(d.year, d.month, d.day)
    if isinstance(d, pd.Timestamp):
        return datetime.datetime(d.year, d.month, d.day)
    if isinstance(d, str):
        ts = pd.Timestamp(d)
        return datetime.datetime(ts.year, ts.month, ts.day)
    raise TypeError(f"Cannot interpret {d!r} as a date.")


def _month_start(d: datetime.datetime) -> datetime.datetime:
    return datetime.datetime(d.year, d.month, 1)


def rl_index_fixings_series(fixings: Any) -> Any:
    """Normalise published fixings into the Series rateslib's index code wants.

    rateslib requires a **unique, monotonic increasing** datetime index and does
    not validate it. It also requires every fixing to be stamped on the FIRST OF
    THE MONTH of its reference period - a series keyed on publication dates, or on
    month ends, silently reads the wrong month.

    Parameters
    ----------
    fixings
        Mapping ``{date: level}`` or a pandas Series.

    Returns
    -------
    pandas.Series
        Sorted, unique, first-of-month datetime index.

    Raises
    ------
    ValueError
        If any key does not fall on the first of a month, or a month repeats.
    """
    if isinstance(fixings, pd.Series):
        items = list(zip(fixings.index, fixings.to_numpy()))
    else:
        items = list(dict(fixings).items())
    out: Dict[datetime.datetime, float] = {}
    for key, value in items:
        d = _as_datetime(key)
        if d.day != 1:
            raise ValueError(
                f"Inflation fixing dated {d:%Y-%m-%d}: rateslib's index_value reads "
                "fixings stamped on the FIRST of the reference month. Re-stamp the "
                f"series to {d:%Y-%m}-01 before passing it."
            )
        if d in out:
            raise ValueError(f"Duplicate inflation fixing for {d:%Y-%m}.")
        out[d] = float(value)
    return pd.Series(out).sort_index()


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
                "SPOT is a level, not a tenor - it cannot be a calibration "
                f"instrument. Drop it from `zc_swap_rates`. Usable tenors: "
                f"{', '.join(DEFAULT_CALIBRATION_TENORS)}."
            )
        years = tenor_to_years(token)
        value = float(rate)
        if value != value:  # NaN
            raise ValueError(
                f"Quote for {token} is NaN. Citi serves NaN for tenors it is not "
                "making a market in that day; drop them rather than calibrate through."
            )
        pairs.append((years, token, value))
    pairs.sort()
    return tuple(p[1] for p in pairs), tuple(p[2] for p in pairs)


def _assert_index_values_populated(
    curve: Any,
    dates: Sequence[datetime.datetime],
    *,
    lag: int,
    method: str,
    citi_index: str,
) -> None:
    """Raise if any index value the curve must produce is zero, negative or NaN.

    rateslib returns **0.0 with a UserWarning** when an index observation falls
    before the curve's initial node, and a swap built on that zero still
    calibrates cleanly. This is the guard that stops a wrong curve being returned
    as a success.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        for d in dates:
            try:
                value = float(curve.index_value(d, lag, method))
            except UserWarning as exc:  # rateslib's "prior to initial node" warning
                raise CitiVelocityError(
                    f"{citi_index}: index observation for {d:%Y-%m-%d} falls before the "
                    f"curve's initial node {curve.nodes.initial:%Y-%m-%d}. rateslib would "
                    "return 0.0 here and the curve would still calibrate. Anchor the curve "
                    "on the first of the reference month, or pass `index_fixings` covering "
                    f"{d:%Y-%m} so the value comes from the published print. "
                    f"Underlying: {exc}"
                ) from exc
            if not (value > 0.0) or value != value:
                raise CitiVelocityError(
                    f"{citi_index}: index value for {d:%Y-%m-%d} came back as {value!r}. "
                    "A non-positive index level means the curve is degenerate; it is not "
                    "returned. Check `index_base` and the node dates."
                )


def _assert_bond_index_populated(bond: Any, curves: Sequence[Any], *, citi_index: str) -> None:
    """Raise if any of an index bond's periods forecasts a zero index value.

    A seasoned linker's early periods observe months that precede the curve's
    initial node. rateslib returns **0.0** for those (with a UserWarning it is
    easy to filter away) and still produces a price. Measured on a 2013-issue
    0.125% index-linked gilt against a synthetic 2026 RPI curve: clean price
    **1445.60** without the published fixings against **93.40** with them - 26 of
    47 periods valued at zero - from the same descriptor and the same curves. Fifteen times wrong, no exception.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cashflows = bond.cashflows(curves=list(curves))
    if "Index Val" not in cashflows.columns:
        return
    values = pd.to_numeric(cashflows["Index Val"], errors="coerce")
    bad = cashflows.loc[~(values > 0.0)]
    if len(bad):
        first = bad.iloc[0]
        raise CitiVelocityError(
            f"{citi_index}: {len(bad)} of {len(cashflows)} bond periods forecast a "
            f"non-positive index value - the first accrues from "
            f"{pd.Timestamp(first['Acc Start']):%Y-%m-%d}. Those periods observe index "
            "months that precede the curve's initial node, where rateslib returns 0.0 "
            "and still prices the bond. Pass `index_fixings` covering the bond's "
            "history, from issue to the last published print."
        )


def _placeholder_nominal(anchor: datetime.datetime, calendar: str, curve_id: str) -> Any:
    """A unit-discount curve. Breakevens are unaffected; NPVs are undiscounted."""
    return rl.Curve(
        {anchor: 1.0, _NOMINAL_PLACEHOLDER_END: 1.0},
        id=curve_id,
        convention=_INDEX_CURVE_CONVENTION,
        calendar=calendar,
    )


def _zcis_kwargs(convention: InflationIndexConvention, calendar: str) -> Dict[str, Any]:
    """Schedule kwargs for a ZCIS, from the named spec when one exists.

    rateslib 2.1.1 ships ``usd_zcis``, ``eur_zcis`` and ``gbp_zcis`` only. For the
    other fourteen Citi indices the schedule is assembled explicitly from the
    market-standard fields in the conventions table.

    ``leg2_index_method`` and ``leg2_index_lag`` are deliberately NOT returned:
    every caller passes them explicitly, and rateslib raises
    ``got multiple values for keyword argument`` rather than resolving the clash.
    """
    if convention.rl_spec is not None:
        kwargs: Dict[str, Any] = {"spec": convention.rl_spec}
        if calendar != convention.calendar:
            kwargs["calendar"] = calendar
        return kwargs
    return {
        "frequency": convention.fixed_frequency,
        "convention": convention.convention,
        "calendar": calendar,
        "modifier": "mf",
        "payment_lag": 0,
        "currency": convention.currency.lower(),
        "stub": "shortfront",
        "eom": False,
    }


# ------------------------------------------------------------------ #
#                            curve build                             #
# ------------------------------------------------------------------ #


def build_rl_index_curve(
    *,
    zc_swap_rates: Mapping[str, float],
    ref_date: DateLike,
    citi_index: str,
    index_base: float,
    nominal_curve: Any = None,
    index_fixings: Any = None,
    effective: Optional[DateLike] = None,
    index_method: Optional[str] = None,
    index_lag: Optional[int] = None,
    calendar: Optional[str] = None,
    interpolation: str = "log_linear",
    tolerance_bp: float = _DEFAULT_TOLERANCE_BP,
    curve_id: Optional[str] = None,
    solver_kwargs: Optional[Mapping[str, Any]] = None,
) -> RLIndexCurve:
    r"""Strip a rateslib inflation index curve from Citi zero-coupon swap quotes.

    Parameters
    ----------
    zc_swap_rates
        ``{tenor: rate}`` in **percent**, as Citi serves
        ``RATES.INFLATION.SWAP.<index>.<tenor>``. ``SPOT`` is rejected. NaN quotes
        are rejected rather than skipped - a silently dropped pillar changes the
        curve shape without telling anyone.
    ref_date
        Quote date. The curve's initial node is the **first of this month**, not
        this date; see the module docstring.
    citi_index
        Citi token, e.g. ``USD_CPURNSA``.
    index_base
        The published index level for the reference period ``observation_lag``
        months behind the first of ``ref_date``'s month - i.e. the fixing for
        :func:`index_base_month`, which the returned object records. This is the
        single number the whole curve level hangs off. Getting it from the wrong
        month moves the 10Y breakeven by ~2 bp per month of error (measured,
        ``_smoke.py``).
    nominal_curve
        Discount curve. Optional: a ZCIS's fair rate is independent of it, because
        both legs settle on the same date. If omitted, a unit-discount placeholder
        is used and a warning is emitted, because ``npv()`` off it is undiscounted.
    index_fixings
        Published fixings, ``{first-of-month: level}`` or a Series. When supplied,
        the calibration swaps' base index is taken from the **published** numbers
        rather than forecast off the curve - which is what a desk does, and what
        QuantLib's bootstrap does. When omitted, the base is forecast from the
        curve and will differ from the QuantLib build at the front.
    effective
        Swap effective date. Defaults to ``ref_date`` plus the index's spot lag.
    index_method, index_lag
        Override the conventions table. Use with intent: these are the two numbers
        that quietly move breakevens.
    calendar
        rateslib calendar name override.
    interpolation
        Node interpolation for the index curve. ``log_linear`` on discount factors
        means constant continuously-compounded inflation between pillars.
    tolerance_bp
        Maximum acceptable error, in bp, repricing ``zc_swap_rates`` off the
        result. Exceeding it raises.
    curve_id
        rateslib curve id. Defaults to the conventions table's ``curve_id``.
    solver_kwargs
        Passed through to :class:`rateslib.Solver`. ``func_tol`` and ``conv_tol``
        default to 1e-14.

    Returns
    -------
    RLIndexCurve

    Raises
    ------
    CitiVelocityError
        If the index is quarterly (rateslib cannot represent it), if the solver
        does not converge, if any index observation is non-positive, or if the
        calibration quotes do not reprice within ``tolerance_bp``.
    ValueError
        On malformed quotes, tenors or fixings.
    """
    convention = conventions_for(citi_index)
    if not convention.rl_representable:
        raise CitiVelocityError(
            f"{convention.citi_index} is a {convention.frequency} index. rateslib 2.1.1 "
            "has no quarterly index period - Curve.index_value interpolates with "
            "calendar.monthrange and add_tenor('1M') - so a curve built here would carry "
            "monthly observation dates for a quarterly index. Use "
            "MDP.CitiVelocityExcel.inflation.ql_inflation.build_ql_zero_inflation_curve, "
            "which handles it natively via ql.AUCPI(ql.Quarterly, False)."
        )
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

    lag = int(index_lag) if index_lag is not None else convention.observation_lag
    method = str(index_method) if index_method is not None else convention.index_method
    if method not in {"daily", "monthly"}:
        raise ValueError(f"index_method must be 'daily' or 'monthly', got {method!r}.")
    cal = str(calendar) if calendar is not None else convention.calendar

    ref = _as_datetime(ref_date)
    anchor = _month_start(ref)
    if effective is not None:
        eff = _as_datetime(effective)
    elif convention.spot_lag:
        eff = _as_datetime(rl.add_tenor(ref, f"{convention.spot_lag}B", "F", cal))
    else:
        eff = ref
    if eff < ref:
        raise ValueError(
            f"effective {eff:%Y-%m-%d} precedes ref_date {ref:%Y-%m-%d}; a back-dated "
            "effective would observe published fixings the curve cannot see."
        )

    tenors, quotes = _sorted_quotes(zc_swap_rates)
    short = [t for t in tenors if tenor_to_years(t) < 1.0]
    if short:
        warnings.warn(
            f"{convention.citi_index}: calibrating on sub-1Y tenors {', '.join(short)}. "
            "A zero-coupon inflation swap shorter than a year observes months that are "
            "mostly already published, so the quote is index arithmetic rather than a "
            "forward view, and the seasonal factor no longer cancels between the two "
            "observations. rateslib 2.1.1 has no seasonality model. Prefer "
            "DEFAULT_CALIBRATION_TENORS.",
            stacklevel=2,
        )

    maturities = [_as_datetime(rl.add_tenor(eff, t, "MF", cal)) for t in tenors]
    seen: Dict[datetime.datetime, str] = {}
    for tenor, mat in zip(tenors, maturities):
        if mat in seen:
            raise ValueError(
                f"Tenors {seen[mat]} and {tenor} both roll to {mat:%Y-%m-%d} off "
                f"effective {eff:%Y-%m-%d}; the curve would have a duplicate node. "
                "Drop one of them."
            )
        if mat <= anchor:
            raise ValueError(
                f"Tenor {tenor} matures {mat:%Y-%m-%d}, on or before the curve anchor "
                f"{anchor:%Y-%m-%d}."
            )
        seen[mat] = tenor

    base = float(index_base)
    if not (base > 0.0):
        raise ValueError(
            f"index_base must be a positive index level, got {index_base!r}. It is the "
            f"published fixing for {index_base_month(ref, convention):%Y-%m}."
        )

    nodes: Dict[datetime.datetime, float] = {anchor: 1.0}
    for mat in maturities:
        nodes[mat] = 1.0
    index_curve = rl.Curve(
        nodes,
        id=curve_id or convention.curve_id,
        index_base=base,
        index_lag=lag,
        interpolation=interpolation,
        convention=_INDEX_CURVE_CONVENTION,
        calendar=cal,
    )

    if nominal_curve is None:
        warnings.warn(
            f"{convention.citi_index}: no `nominal_curve` supplied, so a unit-discount "
            "placeholder is used. Breakevens are unaffected - both ZCIS legs settle on "
            "the same date and the discount factor cancels exactly - but npv() and "
            "analytic_delta() off this curve are undiscounted.",
            stacklevel=2,
        )
        nominal = _placeholder_nominal(anchor, cal, f"{convention.currency.lower()}_nominal_unit")
    else:
        nominal = nominal_curve

    fixings = rl_index_fixings_series(index_fixings) if index_fixings is not None else None
    if fixings is not None:
        # The lag/method overrides change WHICH months are needed, so the
        # requirement is computed against the effective convention, not the
        # table's. Missing that is how a lag override silently reads NoInput.
        effective_convention = dataclasses.replace(
            convention, observation_lag=lag, index_method=method
        )
        needed = required_fixing_months(ref, eff, effective_convention)
        missing = [m for m in needed if pd.Timestamp(m) not in fixings.index]
        if missing:
            raise CitiVelocityError(
                f"{convention.citi_index}: `index_fixings` is missing "
                f"{', '.join(m.strftime('%Y-%m') for m in missing)}, which a swap "
                f"effective {eff:%Y-%m-%d} needs to fix its base index under a "
                f"{lag}M {method} observation. Supplying a partial series would make "
                "rateslib forecast a fixing that has already been published. "
                f"(The series covers {fixings.index[0]:%Y-%m}..{fixings.index[-1]:%Y-%m}; "
                f"a {lag}M lag on this date needs "
                f"{', '.join(m.strftime('%Y-%m') for m in needed)}.)"
            )
        raw_base = rl.index_value(lag, method, index_fixings=fixings, index_date=eff)
        if not isinstance(raw_base, (int, float)) or not (float(raw_base) > 0.0):
            raise CitiVelocityError(
                f"{convention.citi_index}: rateslib returned {raw_base!r} for the swap's "
                f"base index at {eff:%Y-%m-%d} under a {lag}M {method} observation. "
                "That is not a level; the curve is not returned. Check `index_fixings` "
                "covers the reference months."
            )
        swap_base = float(raw_base)
    else:
        _assert_index_values_populated(
            index_curve, [eff], lag=lag, method=method, citi_index=convention.citi_index
        )
        swap_base = float(index_curve.index_value(eff, lag, method))

    zc_kwargs = _zcis_kwargs(convention, cal)
    instruments = [
        rl.ZCIS(
            effective=eff,
            termination=tenor,
            curves=[index_curve, nominal],
            leg2_index_base=swap_base,
            leg2_index_lag=lag,
            leg2_index_method=method,
            **zc_kwargs,
        )
        for tenor in tenors
    ]

    kwargs: Dict[str, Any] = {"func_tol": 1e-14, "conv_tol": 1e-14}
    kwargs.update(dict(solver_kwargs or {}))
    solver = rl.Solver(
        curves=[index_curve],
        instruments=instruments,
        s=list(quotes),
        instrument_labels=list(tenors),
        id=f"{convention.citi_index}_zc",
        **kwargs,
    )
    if solver.result.get("status") != "SUCCESS":
        raise CitiVelocityError(
            f"{convention.citi_index}: inflation curve solver did not converge "
            f"(status {solver.result.get('status')!r}, f_val "
            f"{solver.result.get('f_val')!r}). An unconverged curve is not returned. "
            "Check the quotes for a non-monotonic or stale pillar."
        )

    _assert_index_values_populated(
        index_curve,
        [eff, *maturities],
        lag=lag,
        method=method,
        citi_index=convention.citi_index,
    )

    errors_bp = [abs(float(inst.rate()) - q) * 100.0 for inst, q in zip(instruments, quotes)]
    max_error = max(errors_bp)
    if max_error > tolerance_bp:
        worst = tenors[errors_bp.index(max_error)]
        raise CitiVelocityError(
            f"{convention.citi_index}: rebuilt curve misprices its own calibration set - "
            f"worst {worst} by {max_error:.4f} bp against a {tolerance_bp} bp tolerance. "
            "The curve is not returned. Either loosen `tolerance_bp` deliberately or "
            "look for a quote the node structure cannot fit."
        )

    return RLIndexCurve(
        citi_index=convention.citi_index,
        convention=convention,
        curve=index_curve,
        nominal=nominal,
        solver=solver,
        ref_date=ref,
        anchor=anchor,
        effective=eff,
        index_base=base,
        index_base_month=index_base_month(ref, convention),
        swap_index_base=swap_base,
        tenors=tenors,
        quotes=quotes,
        instruments=tuple(instruments),
        max_repricing_error_bp=max_error,
        index_lag=lag,
        index_method=method,
        index_fixings=fixings,
    )


# ------------------------------------------------------------------ #
#                            breakevens                              #
# ------------------------------------------------------------------ #


def rl_breakeven(curve: RLIndexCurve, tenor: str) -> float:
    """Zero-coupon inflation breakeven, in percent, for ``tenor``.

    Parameters
    ----------
    curve
        A calibrated :class:`RLIndexCurve`.
    tenor
        ``5Y``, ``10Y``, ... Off-pillar tenors are interpolated by the curve's own
        node interpolation and will not match a QuantLib build exactly - the two
        interpolate different quantities (rateslib log-linear on index discount
        factors, QuantLib linear on zero inflation rates). They agree at pillars.

    Returns
    -------
    float
        Percent, on the same ``(1+r)^N`` convention Citi quotes.
    """
    if not isinstance(curve, RLIndexCurve):
        raise TypeError(
            "rl_breakeven takes the RLIndexCurve returned by build_rl_index_curve, "
            f"not {type(curve).__name__}. The bare rateslib Curve does not carry the "
            "conventions needed to build the swap."
        )
    swap = build_rl_zcis(curve=curve, termination=tenor)
    return float(swap.rate())


def rl_forward_breakeven(curve: RLIndexCurve, forward: str, tenor: str) -> float:
    r"""Forward-starting breakeven, in percent.

    The :math:`f \times n` forward breakeven implied by two spot swaps:

    .. math::

        (1 + r_{f \times n})^{n} = \frac{(1 + r_{f+n})^{f+n}}{(1 + r_f)^{f}}

    Computed directly off the index curve rather than from the two spot rates, so
    the observation lag and interpolation are applied once, consistently.

    Parameters
    ----------
    forward, tenor
        e.g. ``forward="5Y", tenor="5Y"`` for the 5y5y breakeven.
    """
    f_years = tenor_to_years(forward)
    n_years = tenor_to_years(tenor)
    if n_years <= 0:
        raise ValueError(f"tenor {tenor!r} must be positive.")
    cal = curve.convention.calendar
    start = _as_datetime(rl.add_tenor(curve.effective, forward, "MF", cal))
    end = _as_datetime(rl.add_tenor(start, tenor, "MF", cal))
    i_start = curve.index_value(start)
    i_end = curve.index_value(end)
    return ((i_end / i_start) ** (1.0 / n_years) - 1.0) * 100.0


def build_rl_zcis(
    *,
    curve: Optional[RLIndexCurve] = None,
    citi_index: Optional[str] = None,
    termination: Union[str, DateLike],
    effective: Optional[DateLike] = None,
    fixed_rate: Optional[float] = None,
    notional: float = 1e6,
    index_base: Optional[float] = None,
    index_curve: Any = None,
    nominal_curve: Any = None,
    index_lag: Optional[int] = None,
    index_method: Optional[str] = None,
    calendar: Optional[str] = None,
) -> Any:
    """Construct a :class:`rateslib.ZCIS` on Citi inflation conventions.

    Either pass ``curve`` (a calibrated :class:`RLIndexCurve`, from which
    everything else defaults) or ``citi_index`` plus the pieces you want.

    Parameters
    ----------
    curve
        A calibrated curve. Supplies effective date, base index, conventions and
        both curves.
    citi_index
        Required when ``curve`` is None.
    termination
        Tenor string or an explicit maturity date.
    effective
        Defaults to the curve's effective date, else ``today`` plus the spot lag.
    fixed_rate
        Percent. Left unset the swap prices at mid.
    notional
        Leg-1 notional. Sign convention is rateslib's: positive pays fixed.
    index_base
        Base index. Defaults to the curve's ``swap_index_base`` when ``curve`` is
        given and the effective date is unchanged; otherwise it is **required**,
        because forecasting a base that has already been published is the error
        this package exists to prevent.

    Returns
    -------
    rateslib.ZCIS

    Raises
    ------
    ValueError
        If neither ``curve`` nor ``citi_index`` is given, or if the base index
        cannot be determined without guessing.
    """
    if curve is None and citi_index is None:
        raise ValueError("Pass either `curve` (an RLIndexCurve) or `citi_index`.")
    convention = curve.convention if curve is not None else conventions_for(citi_index)  # type: ignore[arg-type]
    cal = calendar or convention.calendar
    lag = index_lag if index_lag is not None else (curve.index_lag if curve else convention.observation_lag)
    method = index_method or (curve.index_method if curve else convention.index_method)

    if effective is not None:
        eff = _as_datetime(effective)
    elif curve is not None:
        eff = curve.effective
    else:
        today = datetime.datetime.combine(datetime.date.today(), datetime.time())
        eff = _as_datetime(rl.add_tenor(today, f"{convention.spot_lag}B", "F", cal)) \
            if convention.spot_lag else today

    idx_curve = index_curve if index_curve is not None else (curve.curve if curve else None)
    disc_curve = nominal_curve if nominal_curve is not None else (curve.nominal if curve else None)

    # rateslib 2.1.1 formats the lag difference into a tenor string without
    # handling a negative: a swap lag SHORTER than the curve's produces
    # add_tenor(date, "--3M") and dies with
    # "ValueError: could not convert string to float: '--3'". Catch it here, where
    # the fix (rebuild the curve at the swap's lag) is obvious.
    curve_lag = getattr(getattr(idx_curve, "meta", None), "index_lag", None)
    if curve_lag is not None and lag < int(curve_lag):
        raise CitiVelocityError(
            f"{convention.citi_index}: swap observation lag {lag}M is SHORTER than the "
            f"index curve's {int(curve_lag)}M. rateslib 2.1.1 cannot express that - it "
            "builds a '--{n}M' tenor and raises a ValueError from add_tenor. Rebuild "
            f"the curve with index_lag={lag} instead."
        )

    if index_base is not None:
        base = float(index_base)
    elif curve is not None and eff == curve.effective:
        base = curve.swap_index_base
    elif curve is not None:
        _assert_index_values_populated(
            curve.curve, [eff], lag=lag, method=method, citi_index=convention.citi_index
        )
        base = float(curve.curve.index_value(eff, lag, method))
    else:
        raise ValueError(
            f"{convention.citi_index}: `index_base` is required when no calibrated "
            "curve is supplied. It is the PUBLISHED index level for the reference "
            f"period {lag} months behind {eff:%Y-%m-%d}, not the latest print."
        )

    kwargs = _zcis_kwargs(convention, cal)
    curves = [idx_curve, disc_curve] if idx_curve is not None else None
    swap = rl.ZCIS(
        effective=eff,
        termination=termination,
        notional=notional,
        leg2_index_base=base,
        leg2_index_lag=lag,
        leg2_index_method=method,
        **({"curves": curves} if curves is not None else {}),
        **({"fixed_rate": float(fixed_rate)} if fixed_rate is not None else {}),
        **kwargs,
    )
    return swap


# ------------------------------------------------------------------ #
#                          index-linked bond                         #
# ------------------------------------------------------------------ #


def rl_index_bond(
    *,
    descriptor: Union[IndexBondDescriptor, Mapping[str, Any]],
    index_curve: Union[RLIndexCurve, Any, None] = None,
    nominal_curve: Any = None,
    index_fixings: Any = None,
) -> Any:
    """Build a :class:`rateslib.IndexFixedRateBond` on **linker** conventions.

    The observation convention here comes from
    :func:`~MDP.CitiVelocityExcel.inflation.indices.linker_conventions_for`, NOT
    from the swap table. They disagree: ``gbp_zcis`` is 2-month lag / monthly
    while rateslib's own ``uk_gbi`` gilt spec is 3-month lag / daily. Pricing an
    index-linked gilt on the swap convention misdates the index by a month.

    Parameters
    ----------
    descriptor
        An :class:`IndexBondDescriptor`, or a mapping with the same fields. Its
        ``index_base`` is the **base index printed at issue** and has no default.
    index_curve
        An :class:`RLIndexCurve` or a bare rateslib index curve, used to forecast
        unpublished index values.
    nominal_curve
        Discount curve. Unlike a ZCIS, a linker's price DOES depend on it - the
        coupons and redemption land on different dates.
    index_fixings
        Published fixings series. Anything the bond has already accrued should
        come from here rather than the curve.

    Returns
    -------
    rateslib.IndexFixedRateBond

    Raises
    ------
    UnknownTagError
        If no linker convention is recorded for the index and none is given on the
        descriptor.
    ValueError
        If ``index_base`` is missing.
    CitiVelocityError
        If any period of the resulting bond forecasts a zero index value - which
        is what happens to a seasoned linker priced off a curve that starts this
        month, with no ``index_fixings``.
    """
    if not isinstance(descriptor, IndexBondDescriptor):
        descriptor = IndexBondDescriptor(**dict(descriptor))
    convention = conventions_for(descriptor.citi_index)

    lag = descriptor.index_lag
    method = descriptor.index_method
    spec = descriptor.spec
    linker: Optional[LinkerConvention] = None
    if lag is None or method is None or spec is None:
        linker = linker_conventions_for(descriptor.citi_index)
        lag = lag if lag is not None else linker.index_lag
        method = method if method is not None else linker.index_method
        spec = spec if spec is not None else linker.rl_spec
    if linker is not None and linker.provenance != "rateslib_spec":
        _logger.warning(
            "%s linker conventions are %s (lag %dM, %s): %s",
            descriptor.citi_index,
            linker.provenance,
            linker.index_lag,
            linker.index_method,
            linker.note,
        )
    if lag == convention.observation_lag and method == convention.index_method:
        pass  # they coincide in USD; that is a fact, not an error
    else:
        _logger.info(
            "%s: linker observes %dM/%s while the SWAP observes %dM/%s - deliberately "
            "different.",
            descriptor.citi_index,
            lag,
            method,
            convention.observation_lag,
            convention.index_method,
        )

    if descriptor.index_base is None or not (float(descriptor.index_base) > 0.0):
        raise ValueError(
            f"{descriptor.citi_index}: IndexBondDescriptor.index_base must be the base "
            "index printed at issue (a positive level). There is no sensible default - "
            "a linker priced off the wrong base is wrong by the entire inflation accrual "
            "since issue, and the error does not show up in the yield."
        )

    curve_obj = index_curve.curve if isinstance(index_curve, RLIndexCurve) else index_curve
    disc = nominal_curve
    if disc is None and isinstance(index_curve, RLIndexCurve):
        disc = index_curve.nominal

    kwargs: Dict[str, Any] = {
        "effective": _as_datetime(descriptor.effective),
        "termination": descriptor.termination
        if isinstance(descriptor.termination, str)
        else _as_datetime(descriptor.termination),
        "fixed_rate": float(descriptor.fixed_rate),
        "notional": float(descriptor.notional),
        "index_base": float(descriptor.index_base),
        "index_lag": int(lag),
        "index_method": str(method),
    }
    if spec is not None:
        kwargs["spec"] = spec
    else:
        kwargs.update(
            {
                "frequency": descriptor.frequency or "s",
                "convention": descriptor.convention or "actacticma",
                "calendar": descriptor.calendar or convention.calendar,
                "currency": (descriptor.currency or convention.currency).lower(),
                "modifier": "none",
                "settle": descriptor.settle if descriptor.settle is not None else 1,
                "ex_div": descriptor.ex_div if descriptor.ex_div is not None else 0,
            }
        )
        _logger.warning(
            "%s: no rateslib index-linked bond spec exists; the schedule is assembled "
            "from defaults (%s / %s). Pass frequency/convention/calendar/calc_mode on "
            "the descriptor to pin it.",
            descriptor.citi_index,
            kwargs["frequency"],
            kwargs["convention"],
        )
    for name, value in (
        ("calendar", descriptor.calendar),
        ("frequency", descriptor.frequency),
        ("convention", descriptor.convention),
        ("currency", descriptor.currency.lower() if descriptor.currency else None),
        ("settle", descriptor.settle),
        ("ex_div", descriptor.ex_div),
        ("calc_mode", descriptor.calc_mode),
    ):
        if value is not None:
            kwargs[name] = value
    if index_fixings is not None:
        kwargs["index_fixings"] = rl_index_fixings_series(index_fixings)
    if curve_obj is not None:
        kwargs["curves"] = [curve_obj, disc] if disc is not None else [curve_obj]

    bond = rl.IndexFixedRateBond(**kwargs)
    if curve_obj is not None and disc is not None:
        _assert_bond_index_populated(
            bond, [curve_obj, disc], citi_index=descriptor.citi_index
        )
    return bond
