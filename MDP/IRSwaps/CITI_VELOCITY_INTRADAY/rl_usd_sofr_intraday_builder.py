"""Build a calibrated rateslib USD-SOFR discount curve from Citi Velocity par rates.

Given a single intraday snapshot of ``RATES.OIS.USD_SOFR.PAR.<tenor>`` par swap
rates, this constructs one spot-starting ``rl.IRS`` per tenor (``spec="usd_irs"``
— SOFR RFR-compounded, act/360, annual, MF, T+2), pins one curve node at each
swap maturity, and solves the discount factors with an ``rl.Solver`` — exactly
the pattern used by ``rl_usd_sofr_mt_builder`` and
``ErisFuturesFetcher.fetch_intraday_discount_curve`` elsewhere in the repo, but
sourced entirely from the Citi par grid rather than STIR futures + SDR prints.

The return type is the repo's :class:`RLCurveBase` container so downstream risk
/ pricing code can consume it interchangeably with the other RL builders.
"""

from __future__ import annotations

import datetime
from typing import Dict, List, Mapping, Optional, Tuple, Union

import pandas as pd
import rateslib as rl

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import RLCurveBase
from MDP.IRSwaps.CITI_VELOCITY_INTRADAY.citi_velocity_loader import CURVE_TENOR_ORDER

__all__ = [
    "build_rl_usd_sofr_intraday_curve",
    "spot_date",
    "par_reprice_errors_bp",
]

DateLike = Union[datetime.date, datetime.datetime, pd.Timestamp]


def _as_ref_date(ref_date: DateLike) -> datetime.datetime:
    """Coerce any date-like to a naive midnight datetime (rateslib node key)."""
    ts = pd.Timestamp(ref_date)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return rl.dt(ts.year, ts.month, ts.day)


def _prev_business_day(ref: datetime.datetime, calendar: str) -> datetime.datetime:
    """Roll ``ref`` back to the last good business day (identity if already one).

    Mirrors the STIRF weekend/holiday anchor fix (commit c393146a): a snapshot
    dated on a weekend or US holiday anchors to the prior business day rather
    than raising ``ValueError: Cannot add business days to an input date that is
    not a business day``.
    """
    return rl.get_calendar(calendar).roll(ref, "P", False)


def spot_date(ref_date: DateLike, *, calendar: str = "nyc", spot_lag: int = 2) -> datetime.datetime:
    """Standard USD-SOFR spot date: ``spot_lag`` good business days after the
    (business-day-rolled) ref date."""
    ref = _prev_business_day(_as_ref_date(ref_date), calendar)
    return rl.get_calendar(calendar).add_bus_days(ref, spot_lag, True)


def _normalize_par_rates(par_rates: Union[Mapping[str, float], "pd.Series"]) -> Dict[str, float]:
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
        out[str(tenor).upper()] = r
    return out


def _tenor_sort_key(tenor: str) -> Tuple[int, str]:
    try:
        return (CURVE_TENOR_ORDER.index(tenor), tenor)
    except ValueError:
        return (len(CURVE_TENOR_ORDER), tenor)


def build_rl_usd_sofr_intraday_curve(
    *,
    par_rates: Union[Mapping[str, float], "pd.Series"],
    ref_date: DateLike,
    curve_id: str = "USD-SOFR-1D",
    timestamp: Optional[DateLike] = None,
    spec: str = "usd_irs",
    convention: str = "act360",
    calendar: str = "nyc",
    modifier: str = "mf",
    spot_lag: int = 2,
    interpolation: str = "log_linear",
    spline_start_tenor: Optional[str] = None,
    extrapolation_years: int = 20,
    min_tenors: int = 4,
    func_tol: float = 1e-9,
    conv_tol: float = 1e-10,
) -> RLCurveBase:
    """Calibrate a rateslib SOFR discount curve to a Citi Velocity par snapshot.

    Parameters
    ----------
    par_rates
        Mapping / Series of ``{tenor: par_rate_percent}`` (e.g. ``{"5Y": 3.95}``).
        ``NaN``/``None`` entries are dropped.
    ref_date
        The trade/observation date.  Rolled back to the prior good business day
        (weekend/holiday snapshots anchor to the last business day, matching the
        STIRF fix in commit c393146a) and used as the curve anchor node.  The
        spot start of every calibrating swap is ``spot_lag`` business days later.
    curve_id
        rateslib curve id (also the solver id).  Defaults to ``"USD-SOFR-1D"``,
        matching the repo curve-definitions map.
    timestamp
        Optional intraday timestamp stored on the returned :class:`RLCurveBase`.
        Falls back to ``ref_date``.
    interpolation
        rateslib node interpolation for the (front of the) curve.  Default
        ``"log_linear"`` — always converges for a dense par grid.
    spline_start_tenor
        When given (e.g. ``"2Y"``), a log-cubic spline is layered over the curve
        from that tenor's maturity onward (log-linear in front), mirroring the
        ``t=[boundary]*4 + mid[:-1] + [tail]*4`` construction used by the other
        RL builders.  ``None`` (default) keeps a pure ``interpolation`` curve.
    extrapolation_years
        Flat-forward tail length appended past the last node for the spline
        clamp (only used when ``spline_start_tenor`` is set).
    min_tenors
        Minimum number of usable (non-NaN) tenors required; a sparser snapshot
        raises rather than silently returning a degenerate ``SUCCESS`` curve.
        Default 4 (real Citi exports carry 44); lower it for deliberately small
        curves.

    Returns
    -------
    RLCurveBase
        With ``rl_pricing_curve`` / ``rl_pricing_curve_solver`` populated and the
        per-tenor instruments in ``rl_pricing_curve_instruments``.  The risk
        fields are ``None`` (par snapshot carries no separate risk curve).

    Raises
    ------
    ValueError
        If there are no usable rates, if two tenors collide on the same maturity
        date, or if the solver does not converge.
    """
    rates_map = _normalize_par_rates(par_rates)
    if not rates_map:
        raise ValueError("build_rl_usd_sofr_intraday_curve: no usable par rates supplied.")
    if len(rates_map) < min_tenors:
        raise ValueError(
            f"build_rl_usd_sofr_intraday_curve: only {len(rates_map)} usable tenor(s) "
            f"{sorted(rates_map, key=_tenor_sort_key)} < min_tenors={min_tenors}; snapshot is "
            f"too sparse to build a meaningful curve (pass a lower min_tenors to override)."
        )

    ref = _prev_business_day(_as_ref_date(ref_date), calendar)
    spot = rl.get_calendar(calendar).add_bus_days(ref, spot_lag, True)

    # One spot-starting par swap per tenor; node pinned at each maturity.
    instruments: Dict[str, rl.IRS] = {}
    maturities: Dict[str, datetime.datetime] = {}
    for tenor in sorted(rates_map, key=_tenor_sort_key):
        irs = rl.IRS(
            effective=spot,
            termination=tenor,
            spec=spec,
            curves=curve_id,
            fixed_rate=rates_map[tenor],
        )
        instruments[tenor] = irs
        maturities[tenor] = irs.leg1.schedule.termination

    # Detect maturity collisions (would make the Jacobian singular).
    by_date: Dict[datetime.datetime, List[str]] = {}
    for tenor, mat in maturities.items():
        by_date.setdefault(mat, []).append(tenor)
    collisions = {d: ts for d, ts in by_date.items() if len(ts) > 1}
    if collisions:
        raise ValueError(f"build_rl_usd_sofr_intraday_curve: tenors collide on the same maturity date: {collisions}")

    ordered_tenors = sorted(rates_map, key=lambda t: maturities[t])
    node_dates = [maturities[t] for t in ordered_tenors]
    solve_instruments = [instruments[t] for t in ordered_tenors]
    solve_rates = [rates_map[t] for t in ordered_tenors]

    curve_kwargs = dict(
        nodes={ref: 1.0, **{d: 1.0 for d in node_dates}},
        id=curve_id,
        convention=convention,
        calendar=calendar,
        modifier=modifier,
        interpolation=interpolation,
    )

    if spline_start_tenor is not None:
        boundary_tenor = spline_start_tenor.upper()
        if boundary_tenor not in maturities:
            raise ValueError(
                f"spline_start_tenor={spline_start_tenor!r} is not one of the supplied tenors {ordered_tenors}"
            )
        boundary = maturities[boundary_tenor]
        long_nodes = [d for d in node_dates if d >= boundary]
        if len(long_nodes) < 2:
            raise ValueError(
                f"spline_start_tenor={spline_start_tenor!r} leaves too few nodes ({len(long_nodes)}) for a spline."
            )
        tail = node_dates[-1] + datetime.timedelta(days=365 * extrapolation_years)
        curve_kwargs["t"] = [boundary] * 4 + long_nodes[1:-1] + [tail] * 4

    pricing_curve = rl.Curve(**curve_kwargs)

    solver = rl.Solver(
        curves=[pricing_curve],
        instruments=solve_instruments,
        s=solve_rates,
        id=curve_id,
        func_tol=func_tol,
        conv_tol=conv_tol,
    )

    status = solver.result.get("status") if hasattr(solver, "result") else None
    if status != "SUCCESS":
        raise ValueError(
            f"build_rl_usd_sofr_intraday_curve: solver failed to converge (status={status!r}) "
            f"for ref_date={ref.date()} with {len(solve_instruments)} instruments."
        )

    return RLCurveBase(
        timestamp=pd.Timestamp(timestamp).to_pydatetime() if timestamp is not None else ref,
        rl_pricing_curve=pricing_curve,
        rl_pricing_curve_solver=solver,
        rl_pricing_curve_instruments=dict(instruments),
        rl_risk_curve=None,
        rl_risk_curve_solver=None,
        rl_risk_curve_instruments=None,
    )


def par_reprice_errors_bp(rlcurve: RLCurveBase) -> "pd.Series":
    """Re-price every calibrating swap off the solved curve; return errors in bp.

    A well-solved curve returns values ~0 (< 1e-4 bp for a dense par grid).
    Handy for tests and calibration diagnostics.
    """
    curve = rlcurve.rl_pricing_curve
    errors = {}
    for tenor, irs in rlcurve.rl_pricing_curve_instruments.items():
        model_rate = float(irs.rate(curves=curve))
        fixed = float(irs.kwargs.leg1["fixed_rate"])
        errors[tenor] = (model_rate - fixed) * 100.0
    order = sorted(errors, key=_tenor_sort_key)
    return pd.Series({t: errors[t] for t in order}, name="reprice_error_bp")
