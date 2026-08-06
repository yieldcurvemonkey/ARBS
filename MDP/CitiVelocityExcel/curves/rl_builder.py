"""Calibrated rateslib OIS discount curves from Citi Velocity par grids.

This is the generalisation of
:mod:`MDP.IRSwaps.CITI_VELOCITY_INTRADAY.rl_usd_sofr_intraday_builder` from
USD-SOFR alone to all twenty Citi OIS index tokens. The build is unchanged in
substance - one spot-starting ``rl.IRS`` per tenor, one curve node pinned at
each swap's ``leg1.schedule.termination``, a single ``rl.Solver`` - and it keeps
every guarantee that builder makes:

* ``ref_date`` is rolled **back** to the prior good business day, so a weekend or
  holiday snapshot anchors to the last business day instead of raising (the STIRF
  weekend-anchor fix, commit ``c393146a``);
* the calibrating swaps start ``spot_lag`` good business days after that anchor;
* two tenors landing on the same maturity date is an **error**, not a singular
  Jacobian to be discovered later;
* a solver whose status is not ``SUCCESS`` raises. Nothing here ever returns a
  degenerate curve: the repo has a recorded incident where an all-NaN risk
  column shipped as "success", and the guard against repeating it is that the
  failure path raises.

What is honest about the conventions
------------------------------------
Fifteen of the twenty curves are built from a rateslib **named spec**
(``usd_irs``, ``eur_irs``, ...). The remaining five - DKK, ILS, SGD, THB, ZAR -
have no rateslib spec, so the ``rl.IRS`` is assembled from explicit fields taken
from :mod:`MDP.CitiVelocityExcel.curves.conventions`, whose provenance for those
five is ``market_standard`` rather than ``rateslib_spec``. Every such build logs
exactly one warning per curve id naming what is approximate.

MXN used to be the worst of them - Fondeo rolls on a 28-day schedule that
rateslib 2.1.1 could not express, so it was approximated as monthly and flagged
indicative. rateslib 2.7's ``mxn_irs`` declares ``frequency="28d"`` natively, so
the rateslib leg now rolls on the traded schedule (verified: 28-day gaps after
the front stub). The QuantLib side still has no 28-day period and remains
monthly, so the two backends legitimately disagree on MXN and the rateslib one
is the right one.

rateslib's calendars are not QuantLib's
--------------------------------------
The two libraries ship independent holiday lists and they disagree. Measured
over 2026-2076 by ``curves/_smoke.py``, against the calendar each QuantLib index
actually uses: ``syd`` is missing **102** of QuantLib's Australia holidays (the
NSW Bank Holiday and NSW Labour Day among them); ``wlg`` and New Zealand differ
on 239 days; ``tyo`` and Japan on 65; ``tro`` and Canada on 15; ``nyc`` is
missing 7 of the SOFR fixing calendar's days and carries 66 the Fed wire
calendar (behind ``USD_FEDFUND``) does not. ``tgt``, ``ldn``, ``zur``, ``osl``
and ``stk`` agree exactly.

That is data, not a bug in either builder, but it has a consequence worth
knowing: for AUD the disagreement moves five of the 44 swap maturities by a day,
which is the entire 0.067 bp gap between the rateslib and QuantLib forwards on
that curve. Every other currency's cross-backend gap is the rateslib solver
residual and collapses to ~1e-5 bp when ``func_tol`` is tightened to 1e-14.
For the six currencies with no rateslib calendar the question does not arise:
``conv.rl_calendar_object()`` synthesises theirs from QuantLib, so both backends
read the same holiday list by construction.

What is NOT verified
--------------------
No curve in this module has been compared against a Citi-published discount
factor or a broker-quoted forward, because the ``CVD*`` pricers are not entitled
and no independent curve source for these twenty currencies is available here.
What *is* verified (see ``curves/_smoke.py``) is internal consistency: a
synthetic par grid priced off a known discount curve is recovered to well under
0.01 bp on every tenor for all twenty, and the rateslib and QuantLib builds of
the same grid agree. Self-consistency is not the same as being right about the
market's conventions, and for the six ``market_standard`` currencies it is all
we have.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

import pandas as pd
import rateslib as rl

from MDP.CitiVelocityExcel.curves.conventions import CurveConvention, conventions_for
from MDP.CitiVelocityExcel.curves.ql_builder import (
    END_OF_MONTH_BY_INDEX,
    PAYMENT_LAG_BY_INDEX,
)
from MDP.CitiVelocityExcel.errors import UnknownTagError
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import RLCurveBase

__all__ = [
    "DateLike",
    "END_OF_MONTH_BY_INDEX",
    "PAYMENT_LAG_BY_INDEX",
    "build_rl_ois_curve",
    "build_rl_ois_curve_from_quotes",
    "end_of_month_for",
    "forward_rate",
    "make_rl_irs",
    "par_reprice_errors_bp",
    "payment_lag_for",
    "spot_date",
]

_logger = logging.getLogger(__name__)

DateLike = Union[datetime.date, datetime.datetime, pd.Timestamp]

# The payment-lag and end-of-month tables live in ql_builder so that there is
# exactly ONE copy and the dependency runs one way (here -> ql_builder, never
# back). rateslib's named specs are the authority for the fourteen currencies it
# ships one for, so payment_lag_for/end_of_month_for below re-read
# rl.defaults.spec and RAISE if the tables ever stop matching it.

#: Roll convention for every leg on every curve here. Citi quotes OIS on modified
#: following; nothing in the twenty deviates.
_MODIFIER = "mf"

#: Stub rule used when no rateslib spec supplies one (rateslib's own default).
_DEFAULT_STUB = "shortfront"

#: Curve ids already warned about, so a bulk build of 900 days emits one warning
#: per curve rather than 900.
_WARNED_APPROXIMATE: set[str] = set()


# ------------------------------------------------------------------ #
#                         dates and coercion                         #
# ------------------------------------------------------------------ #


def _as_ref_date(ref_date: DateLike) -> datetime.datetime:
    """Coerce any date-like to a naive midnight datetime (a rateslib node key)."""
    ts = pd.Timestamp(ref_date)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return rl.dt(ts.year, ts.month, ts.day)


def _prev_business_day(ref: datetime.datetime, calendar: Any) -> datetime.datetime:
    """Roll ``ref`` back to the last good business day (identity if already one)."""
    return calendar.roll(ref, "P", False)


def spot_date(
    ref_date: DateLike,
    *,
    citi_index: str = "USD_SOFR",
) -> datetime.datetime:
    """The spot start of a Citi OIS curve's calibrating swaps.

    Parameters
    ----------
    ref_date
        Trade/observation date. Rolled back to the prior good business day first,
        so a Saturday snapshot anchors to Friday.
    citi_index
        Velocity OIS index token, e.g. ``"GBP_SONIA"``.

    Returns
    -------
    datetime.datetime
        ``spot_lag`` good business days after the rolled reference date. GBP is
        the one that catches people out: SONIA settles T+0.
    """
    conv = conventions_for(citi_index)
    cal = conv.rl_calendar_object()
    ref = _prev_business_day(_as_ref_date(ref_date), cal)
    return cal.add_bus_days(ref, int(conv.spot_lag), True)


def payment_lag_for(citi_index: str) -> int:
    """Coupon payment lag in business days for one Citi OIS index token.

    Cross-checks :data:`PAYMENT_LAG_BY_INDEX` against rateslib's own named spec
    whenever one exists, so an upgrade that changes a spec's ``payment_lag``
    fails loudly here instead of quietly repricing every long-dated curve.

    Raises
    ------
    ValueError
        If the table and the rateslib spec disagree.
    """
    conv = conventions_for(citi_index)
    lag = PAYMENT_LAG_BY_INDEX.get(conv.citi_index)
    if lag is None:
        raise UnknownTagError(
            f"No payment lag recorded for Citi OIS index {citi_index!r}; add it to "
            "MDP.CitiVelocityExcel.curves.rl_builder.PAYMENT_LAG_BY_INDEX."
        )
    if conv.rl_spec:
        spec_lag = int(rl.defaults.spec[conv.rl_spec]["payment_lag"])
        if spec_lag != lag:
            raise ValueError(
                f"PAYMENT_LAG_BY_INDEX[{conv.citi_index!r}]={lag} disagrees with rateslib's "
                f"{conv.rl_spec!r} spec payment_lag={spec_lag}. rateslib is the authority for "
                "the fourteen spec'd currencies - fix the table in curves/ql_builder.py."
            )
    return int(lag)


def end_of_month_for(citi_index: str) -> bool:
    """End-of-month schedule rule for one Citi OIS index token.

    Same cross-check as :func:`payment_lag_for`: rateslib's named spec wins where
    one exists, and a divergence raises instead of quietly moving every month-end
    roll on that curve.

    Raises
    ------
    ValueError
        If the table and the rateslib spec disagree.
    """
    conv = conventions_for(citi_index)
    eom = END_OF_MONTH_BY_INDEX.get(conv.citi_index)
    if eom is None:
        raise UnknownTagError(
            f"No end-of-month rule recorded for Citi OIS index {citi_index!r}; add it to "
            "MDP.CitiVelocityExcel.curves.ql_builder.END_OF_MONTH_BY_INDEX."
        )
    if conv.rl_spec:
        spec_eom = bool(rl.defaults.spec[conv.rl_spec]["eom"])
        if spec_eom != bool(eom):
            raise ValueError(
                f"END_OF_MONTH_BY_INDEX[{conv.citi_index!r}]={eom} disagrees with rateslib's "
                f"{conv.rl_spec!r} spec eom={spec_eom}. Fix the table in curves/ql_builder.py."
            )
    return bool(eom)


def _tenor_sort_key(tenor: str) -> Tuple[float, str]:
    """Sort tenor tokens by maturity, tolerating anything non-standard."""
    from MDP.CitiVelocityExcel.catalog import tenor_years

    token = str(tenor).strip().upper()
    try:
        return (tenor_years(token), token)
    except Exception:  # noqa: BLE001 - an unparseable tenor sorts last, it does not crash a build
        return (float("inf"), token)


def _normalise_par_rates(par_rates: Union[Mapping[str, float], pd.Series]) -> Dict[str, float]:
    """Drop ``None``/``NaN``/non-numeric entries and upper-case the tenor keys."""
    out: Dict[str, float] = {}
    for tenor, rate in par_rates.items():  # dict and pd.Series both expose .items()
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


# ------------------------------------------------------------------ #
#                       instrument construction                      #
# ------------------------------------------------------------------ #


def _warn_if_approximate(conv: CurveConvention, curve_id: str) -> None:
    """One warning per curve id when the conventions are not library-supplied."""
    if not conv.approximate:
        return
    if curve_id in _WARNED_APPROXIMATE:
        return
    _WARNED_APPROXIMATE.add(curve_id)
    _logger.warning(
        "%s: rateslib ships no named spec for %s, so the schedule is built from "
        "market-standard fields (frequency=%s, convention=%s, spot_lag=%s, payment_lag=%s) and "
        "the holiday calendar is synthesised from QuantLib's %s list. %s",
        curve_id,
        conv.citi_index,
        conv.fixed_frequency,
        conv.convention,
        conv.spot_lag,
        PAYMENT_LAG_BY_INDEX.get(conv.citi_index),
        conv.currency,
        conv.note or "Levels are indicative.",
    )


def make_rl_irs(
    *,
    conv: CurveConvention,
    calendar: Any,
    effective: datetime.datetime,
    tenor: str,
    curve_id: str,
    fixed_rate: float,
) -> rl.IRS:
    """One OIS on this curve's conventions, from the named spec when there is one.

    Public because the pricer builds swaps off a solved curve to compute NPV and
    PV01, and it must use exactly the conventions the curve was calibrated with -
    a second, subtly different constructor would reprice its own curve wrong. The
    repo has a recorded case of a service importing a builder's PRIVATE helper and
    breaking on a rename with no test catching it; this is that mistake avoided.

    Parameters
    ----------
    conv
        The curve's conventions, from
        :func:`~MDP.CitiVelocityExcel.curves.conventions.conventions_for`.
    calendar
        The rateslib calendar object, i.e. ``conv.rl_calendar_object()``.
    effective
        Start date. Spot for a par swap; spot shifted by the forward otherwise.
    fixed_rate
        In PERCENT, matching ``rl.IRS(fixed_rate=...)``.
    """
    if conv.rl_spec:
        return rl.IRS(
            effective=effective,
            termination=tenor,
            spec=conv.rl_spec,
            curves=curve_id,
            fixed_rate=fixed_rate,
        )
    return rl.IRS(
        effective=effective,
        termination=tenor,
        frequency=conv.fixed_frequency,
        convention=conv.convention,
        calendar=calendar,
        modifier=_MODIFIER,
        stub=_DEFAULT_STUB,
        eom=end_of_month_for(conv.citi_index),
        payment_lag=payment_lag_for(conv.citi_index),
        currency=conv.currency.lower(),
        leg2_fixing_method="rfr_payment_delay",
        leg2_spread_compound_method="none_simple",
        curves=curve_id,
        fixed_rate=fixed_rate,
    )


#: Kept so the builder's own call sites read unchanged. New callers should use
#: the public name.
_make_irs = make_rl_irs

# ------------------------------------------------------------------ #
#                            the builder                             #
# ------------------------------------------------------------------ #


def build_rl_ois_curve(
    *,
    par_rates: Union[Mapping[str, float], pd.Series],
    ref_date: DateLike,
    citi_index: str = "USD_SOFR",
    curve_id: Optional[str] = None,
    timestamp: Optional[DateLike] = None,
    interpolation: str = "log_linear",
    spline_start_tenor: Optional[str] = None,
    extrapolation_years: int = 20,
    min_tenors: int = 4,
    func_tol: float = 1e-9,
    conv_tol: float = 1e-10,
    max_reprice_error_bp: float = 1.0,
) -> RLCurveBase:
    """Calibrate a rateslib OIS discount curve to one Citi Velocity par snapshot.

    Parameters
    ----------
    par_rates
        ``{tenor: par_rate_percent}``, e.g. ``{"5Y": 3.9512}``. **Percent**, not
        decimal - that is what ``RATES.OIS.<idx>.PAR.<tenor>`` serves and what
        ``rl.IRS(fixed_rate=...)`` expects. ``None``/``NaN`` entries are dropped.
    ref_date
        Trade/observation date. Rolled back to the prior good business day and
        used as the curve's anchor node.
    citi_index
        Velocity OIS index token; see
        :func:`~MDP.CitiVelocityExcel.curves.conventions.supported_indices`.
    curve_id
        rateslib curve and solver id. Defaults to ``conv.curve_id``, e.g.
        ``"USD-SOFR-CITIVELO"``.
    timestamp
        Intraday timestamp recorded on the result. Falls back to the rolled
        reference date.
    interpolation
        Node interpolation for (the front of) the curve. ``"log_linear"``
        converges for any dense par grid and is the default.
    spline_start_tenor
        When given (e.g. ``"2Y"``), a log-cubic spline is layered from that
        tenor's maturity onward, log-linear in front. The knot sequence is
        recorded on ``result.meta["spline_knots"]``: **a spline curve persisted
        without its knots reconstructs as log-linear and then misprices its own
        calibration instruments** - the repo has that recorded at -0.18 bp on the
        30Y and +4.9 bp on the 40Y, and ``curves/_smoke.py`` measures it here at
        0.0041 bp on the dense 44-tenor grid but **0.755 bp** (30Y) on a sparse
        8-tenor one. The error scales with node spacing, so "it was small on my
        grid" is not a reason to drop the knots.
    extrapolation_years
        Length of the flat tail appended past the last node to clamp the spline.
        Only used when ``spline_start_tenor`` is set.
    min_tenors
        Minimum usable tenor count. A sparser snapshot raises instead of
        producing a curve that solves trivially and means nothing. Real Citi
        exports carry 44.
    func_tol, conv_tol
        Solver tolerances, matching the repo's other RL builders.

    Returns
    -------
    RLCurveBase
        ``rl_pricing_curve`` / ``rl_pricing_curve_solver`` /
        ``rl_pricing_curve_instruments`` populated; the risk fields are ``None``
        because a par snapshot carries no separate risk curve. A ``meta`` dict is
        attached carrying ``citi_index``, ``curve_id``, ``ref_date``, ``spot``,
        ``tenors``, ``par_rates``, ``interpolation``, ``spline_knots``,
        ``provenance`` and ``approximate``.

    Raises
    ------
    UnknownTagError
        ``citi_index`` is not one of the twenty.
    ValueError
        No usable rates; fewer than ``min_tenors``; two tenors colliding on one
        maturity date; ``spline_start_tenor`` not among the supplied tenors or
        leaving too few nodes; or a solver status other than ``SUCCESS``.
    """
    conv = conventions_for(citi_index)
    cid = curve_id or conv.curve_id
    _warn_if_approximate(conv, cid)
    if conv.stale:
        _logger.warning(
            "%s: %s is a stale Citi curve (it stops roughly a year back). %s",
            cid,
            conv.citi_index,
            conv.note,
        )

    rates_map = _normalise_par_rates(par_rates)
    if not rates_map:
        raise ValueError(
            f"build_rl_ois_curve({conv.citi_index}): no usable par rates supplied "
            "(every entry was None/NaN/non-numeric)."
        )
    if len(rates_map) < min_tenors:
        raise ValueError(
            f"build_rl_ois_curve({conv.citi_index}): only {len(rates_map)} usable tenor(s) "
            f"{sorted(rates_map, key=_tenor_sort_key)} < min_tenors={min_tenors}; the snapshot is "
            "too sparse to build a meaningful curve (pass a lower min_tenors to override)."
        )

    calendar = conv.rl_calendar_object()
    ref = _prev_business_day(_as_ref_date(ref_date), calendar)
    spot = calendar.add_bus_days(ref, int(conv.spot_lag), True)

    instruments: Dict[str, rl.IRS] = {}
    maturities: Dict[str, datetime.datetime] = {}
    for tenor in sorted(rates_map, key=_tenor_sort_key):
        irs = _make_irs(
            conv=conv,
            calendar=calendar,
            effective=spot,
            tenor=tenor,
            curve_id=cid,
            fixed_rate=rates_map[tenor],
        )
        instruments[tenor] = irs
        maturities[tenor] = irs.leg1.schedule.termination

    # Two tenors on one maturity make the Jacobian singular; say so now.
    by_date: Dict[datetime.datetime, List[str]] = {}
    for tenor, mat in maturities.items():
        by_date.setdefault(mat, []).append(tenor)
    collisions = {d.date(): ts for d, ts in by_date.items() if len(ts) > 1}
    if collisions:
        raise ValueError(
            f"build_rl_ois_curve({conv.citi_index}): tenors collide on the same maturity date "
            f"{collisions}. Drop one of each colliding pair from par_rates - a duplicated node "
            "makes the solver Jacobian singular."
        )

    ordered_tenors = sorted(rates_map, key=lambda t: maturities[t])
    node_dates = [maturities[t] for t in ordered_tenors]
    solve_instruments = [instruments[t] for t in ordered_tenors]
    solve_rates = [rates_map[t] for t in ordered_tenors]

    curve_kwargs: Dict[str, Any] = dict(
        nodes={ref: 1.0, **{d: 1.0 for d in node_dates}},
        id=cid,
        convention=conv.convention,
        calendar=calendar,
        modifier=_MODIFIER,
        interpolation=interpolation,
    )

    spline_knots: Optional[List[datetime.datetime]] = None
    if spline_start_tenor is not None:
        boundary_tenor = str(spline_start_tenor).strip().upper()
        if boundary_tenor not in maturities:
            raise ValueError(
                f"build_rl_ois_curve({conv.citi_index}): spline_start_tenor={spline_start_tenor!r} "
                f"is not one of the supplied tenors {ordered_tenors}."
            )
        boundary = maturities[boundary_tenor]
        long_nodes = [d for d in node_dates if d >= boundary]
        if len(long_nodes) < 2:
            raise ValueError(
                f"build_rl_ois_curve({conv.citi_index}): spline_start_tenor={spline_start_tenor!r} "
                f"leaves only {len(long_nodes)} node(s) beyond the boundary; a spline needs at least 2."
            )
        tail = node_dates[-1] + datetime.timedelta(days=365 * int(extrapolation_years))
        spline_knots = [boundary] * 4 + long_nodes[1:-1] + [tail] * 4
        curve_kwargs["t"] = spline_knots

    pricing_curve = rl.Curve(**curve_kwargs)

    solver = rl.Solver(
        curves=[pricing_curve],
        instruments=solve_instruments,
        s=solve_rates,
        id=cid,
        func_tol=func_tol,
        conv_tol=conv_tol,
    )

    status = solver.result.get("status") if hasattr(solver, "result") else None
    if status != "SUCCESS":
        raise ValueError(
            f"build_rl_ois_curve({conv.citi_index}): solver status={status!r} (not 'SUCCESS') for "
            f"ref_date={ref.date()} with {len(solve_instruments)} instruments. The curve is NOT "
            "returned - an unconverged solver prices everything downstream wrongly and silently."
        )

    result = RLCurveBase(
        timestamp=pd.Timestamp(timestamp).to_pydatetime() if timestamp is not None else ref,
        rl_pricing_curve=pricing_curve,
        rl_pricing_curve_solver=solver,
        rl_pricing_curve_instruments=dict(instruments),
        rl_risk_curve=None,
        rl_risk_curve_solver=None,
        rl_risk_curve_instruments=None,
    )
    # RLCurveBase is a plain dataclass with no __slots__, so the build context
    # rides along on the instance rather than in a parallel structure the caller
    # has to keep in step. The knots matter most: see spline_start_tenor above.
    result.meta = {
        "citi_index": conv.citi_index,
        "curve_id": cid,
        "ref_date": ref,
        "spot": spot,
        "tenors": list(ordered_tenors),
        "par_rates": {t: rates_map[t] for t in ordered_tenors},
        "maturities": {t: maturities[t] for t in ordered_tenors},
        "interpolation": interpolation,
        "spline_start_tenor": spline_start_tenor,
        "spline_knots": spline_knots,
        "convention": conv,
        "provenance": conv.provenance,
        "approximate": conv.approximate,
        "payment_lag": payment_lag_for(conv.citi_index),
    }

    # A SUCCESS status is no longer sufficient evidence that the solve worked.
    # Measured on rateslib 2.7.1: a grid with a -5000% front quote returns
    # status='SUCCESS' from a curve that misprices its own calibration
    # instruments by 4.9e+05 bp (2.1.1 reported FAILURE for the same input, which
    # is what this guard used to rely on). So the curve is asked to reprice the
    # quotes it was built from, and a curve that cannot is not returned. This is
    # the same class of failure as the recorded all-NaN-risk incident: the
    # dangerous outcome is not an exception, it is a plausible number.
    #
    # Cost: 17.5 ms on a 44-tenor grid, ~8.8% of the ~200 ms build. That is a
    # real tax on a bulk warm (930 days x N currencies), and it is still the
    # right default - raise max_reprice_error_bp to disable the raise, but note
    # the errors are computed either way because they are recorded on meta.
    worst = float(par_reprice_errors_bp(result).abs().max())
    if not (worst <= max_reprice_error_bp):
        raise ValueError(
            f"build_rl_ois_curve({conv.citi_index}): the solved curve does not reprice its own "
            f"calibration swaps - worst error {worst:.6g} bp against a tolerance of "
            f"{max_reprice_error_bp:g} bp, for ref_date={ref.date()} with "
            f"{len(solve_instruments)} instruments (solver status={status!r}). The curve is NOT "
            "returned. Check the par grid for a bad quote; raise max_reprice_error_bp only if "
            "you have established the residual is benign."
        )
    result.meta["max_reprice_error_bp"] = worst
    return result


def build_rl_ois_curve_from_quotes(
    *,
    quotes: Mapping[str, float],
    ref_date: DateLike,
    citi_index: str = "USD_SOFR",
    **kw: Any,
) -> RLCurveBase:
    """:func:`build_rl_ois_curve` keyed by full Velocity tag rather than tenor.

    Parameters
    ----------
    quotes
        ``{"RATES.OIS.USD_SOFR.PAR.10Y": 3.9512, ...}`` - exactly what
        :meth:`CitiVelocityExcelClient.fetch_timeseries` returns one row of. The
        tenor is the last dotted segment.
    ref_date
        As :func:`build_rl_ois_curve`.
    citi_index
        Checked against the index segment of the tags. When every tag names a
        different index than this argument, the call **raises** rather than
        silently building a EUR curve with USD conventions.
    **kw
        Forwarded to :func:`build_rl_ois_curve`.

    Raises
    ------
    ValueError
        A tag is not a ``RATES.OIS.<index>.PAR.<tenor>`` tag, the tags disagree
        among themselves about the index, or they disagree with ``citi_index``.
    """
    if not quotes:
        raise ValueError("build_rl_ois_curve_from_quotes: quotes is empty.")

    par_rates: Dict[str, float] = {}
    seen_indices: set[str] = set()
    for tag, value in quotes.items():
        parts = str(tag).strip().split(".")
        if len(parts) < 5 or parts[0].upper() != "RATES" or parts[1].upper() != "OIS":
            raise ValueError(
                f"build_rl_ois_curve_from_quotes: {tag!r} is not a RATES.OIS.<index>.PAR.<tenor> "
                "tag. Pass par rates keyed by tenor to build_rl_ois_curve instead."
            )
        if parts[3].upper() != "PAR":
            raise ValueError(
                f"build_rl_ois_curve_from_quotes: {tag!r} is a {parts[3]!r} tag, not PAR. Only par "
                "swap rates calibrate this curve."
            )
        seen_indices.add(parts[2].upper())
        par_rates[parts[-1].upper()] = value

    if len(seen_indices) > 1:
        raise ValueError(
            f"build_rl_ois_curve_from_quotes: quotes mix OIS indices {sorted(seen_indices)}. "
            "One call builds one curve; split the quotes by index."
        )
    tag_index = seen_indices.pop()
    wanted = conventions_for(citi_index).citi_index
    if tag_index != wanted:
        raise ValueError(
            f"build_rl_ois_curve_from_quotes: the tags are {tag_index} quotes but citi_index="
            f"{citi_index!r} resolves to {wanted}. Pass citi_index={tag_index!r}."
        )

    return build_rl_ois_curve(
        par_rates=par_rates,
        ref_date=ref_date,
        citi_index=tag_index,
        **kw,
    )


def par_reprice_errors_bp(rlc: RLCurveBase) -> pd.Series:
    """Re-price every calibrating swap off the solved curve; errors in bp.

    Parameters
    ----------
    rlc
        The result of :func:`build_rl_ois_curve`.

    Returns
    -------
    pandas.Series
        ``model_rate - quoted_rate`` in basis points, indexed by tenor in
        maturity order. A converged curve on a dense grid returns values well
        below 1e-4 bp; anything materially larger means the solve did not
        actually pin its own instruments, which is worth failing a test over.
    """
    curve = rlc.rl_pricing_curve
    errors: Dict[str, float] = {}
    for tenor, irs in (rlc.rl_pricing_curve_instruments or {}).items():
        model_rate = float(irs.rate(curves=curve))
        fixed = float(irs.kwargs.leg1["fixed_rate"])
        errors[tenor] = (model_rate - fixed) * 100.0
    order = sorted(errors, key=_tenor_sort_key)
    return pd.Series({t: errors[t] for t in order}, name="reprice_error_bp", dtype=float)


def forward_rate(
    rlc: RLCurveBase,
    *,
    forward: str,
    tenor: str,
) -> float:
    """The forward-starting par OIS rate off a built curve, in percent.

    Parameters
    ----------
    rlc
        The result of :func:`build_rl_ois_curve`.
    forward
        Start offset from spot, e.g. ``"5Y"``. ``"0D"`` gives the spot swap.
    tenor
        Swap tenor, e.g. ``"5Y"``.

    Notes
    -----
    The effective date is ``spot`` shifted by ``forward`` and adjusted
    **following**, which is what QuantLib's ``MakeOIS`` does with a
    ``forwardStart`` period. The two backends are only comparable because they
    agree on that adjustment; modified-following here would move month-end
    forwards by a day.
    """
    meta = getattr(rlc, "meta", None)
    if not meta:
        raise ValueError(
            "forward_rate: this RLCurveBase carries no meta; it was not produced by "
            "build_rl_ois_curve."
        )
    conv: CurveConvention = meta["convention"]
    calendar = conv.rl_calendar_object()
    effective = rl.add_tenor(meta["spot"], forward, "f", calendar)
    irs = _make_irs(
        conv=conv,
        calendar=calendar,
        effective=effective,
        tenor=tenor,
        curve_id=meta["curve_id"],
        fixed_rate=0.0,
    )
    return float(irs.rate(curves=rlc.rl_pricing_curve))
