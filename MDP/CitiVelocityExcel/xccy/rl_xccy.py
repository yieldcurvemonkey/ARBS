r"""Cross-currency basis in rateslib: build the XCS, solve the collateral curve.

rateslib 2.1.1 has everything this needs natively - :class:`rateslib.XCS`,
:class:`rateslib.FXRates`, :class:`rateslib.FXForwards`, ``FixedLegMtm`` /
``FloatLegMtm`` - and named specs for eight cross-currency pairs
(``eurusd_xcs``, ``gbpusd_xcs``, ``eurgbp_xcs``, ``gbpeur_xcs``, ``jpyusd_xcs``,
``audusd_xcs``, plus the IBOR ``*_xcs3`` variants). For pairs with no spec the
schedule is assembled explicitly from
:mod:`MDP.CitiVelocityExcel.curves.conventions`, and the resulting instrument is
flagged ``approximate`` so nobody mistakes a market-standard guess for a
library-supplied convention.

The object solved for
---------------------
A cross-currency basis quote is a statement about **discounting**, not about
forecasting. Both legs forecast off their own domestic RFR curve; what the basis
prices is the discount curve for the non-collateral currency's cashflows under
the collateral currency's CSA. That curve - rateslib's ``"<ccy><collateral>"``
curve, e.g. ``eurusd`` for EUR flows under USD collateral - is the single
unknown, and it is what :func:`solve_rl_collateral_curve` returns.

Conventions this module assumes, and where they came from
---------------------------------------------------------
* Both legs float, quarterly, RFR-compounded with payment delay - the ``*_xcs``
  spec shape. Verified: it is what rateslib ships for all six RFR pairs.
* ``leg2_mtm=True``: the notional of leg 2 (the collateral currency's leg)
  resets at every period against the FX forward. Market standard, and what every
  rateslib spec sets. Pass ``mtm=False`` for the constant-notional variant - the
  difference is measured in ``_smoke.py`` and is NOT zero.
* Leg 1 carries the basis spread, and leg 1 is the currency named by
  ``basis.spread_ccy``. Which currency Velocity actually puts its ``SPREAD_LEG``
  on is UNVERIFIED - see :mod:`MDP.CitiVelocityExcel.xccy.basis_data`.

Nothing here is calibrated against a live Velocity quote; the numerics are
verified against QuantLib in :mod:`MDP.CitiVelocityExcel.xccy._smoke` and against
exact self-repricing, which is a statement about the solver, not about Citi.
"""

from __future__ import annotations

import datetime
import logging
import warnings
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import pandas as pd

from MDP.CitiVelocityExcel.catalog import tenor_years
from MDP.CitiVelocityExcel.curves.conventions import (
    CurveConvention,
    rl_calendar_from_quantlib,
)
from MDP.CitiVelocityExcel.xccy.basis_data import (
    XccyBasisCurve,
    assert_ois_pair,
    conventions_for_currency,
    default_collateral_ccy,
    iso_currency,
)

__all__ = [
    "RLXccyCurves",
    "RL_XCS_SPECS",
    "build_rl_xcs",
    "combined_calendar",
    "rl_xccy_reprice_errors_bp",
    "rl_xccy_reprice_errors_bp_from",
    "rl_xcs_kwargs",
    "solve_rl_collateral_curve",
]

_logger = logging.getLogger(__name__)

#: ``(leg1_ccy, leg2_ccy) -> rateslib spec``. Only the RFR-on-both-legs specs are
#: listed: ``audusd_xcs3``/``nzdusd_xcs3``/``nzdaud_xcs3`` set
#: ``fixing_method='ibor'`` on leg 1 and belong to the BBSW/BKBM legs, which this
#: package refuses (see ``basis_data.IBOR_LEG_TOKENS``).
RL_XCS_SPECS: Dict[Tuple[str, str], str] = {
    ("EUR", "USD"): "eurusd_xcs",
    ("GBP", "USD"): "gbpusd_xcs",
    ("JPY", "USD"): "jpyusd_xcs",
    ("AUD", "USD"): "audusd_xcs",
    ("EUR", "GBP"): "eurgbp_xcs",
    ("GBP", "EUR"): "gbpeur_xcs",
}

#: Cross-currency basis swaps quote quarterly on both legs across every pair in
#: the Velocity family; this is the fallback when no named spec exists.
_DEFAULT_FREQUENCY = "q"
#: Coupons settle 2 business days after the period end (all six rateslib specs).
_DEFAULT_PAYMENT_LAG = 2
#: Notional exchanges settle ON the effective/maturity date (all six specs).
_DEFAULT_PAYMENT_LAG_EXCHANGE = 0
#: Reprice tolerance. The solver reaches ~1e-9bp on synthetic input; 1e-4bp is
#: two orders of magnitude inside the 0.25bp tick a xccy basis trades on.
_DEFAULT_TOL_BP = 1e-4


# ------------------------------------------------------------------ #
#                              the record                            #
# ------------------------------------------------------------------ #


@dataclass(frozen=True, eq=False)
class RLXccyCurves:
    """The solved collateral curve and everything needed to reproduce it.

    Attributes
    ----------
    collateral_curve
        The solved :class:`rateslib.Curve`: cashflows in ``discount_ccy``
        discounted under ``collateral_ccy`` collateral.
    discount_ccy, collateral_ccy
        ISO codes. ``collateral_curve`` discounts ``discount_ccy`` flows under a
        ``collateral_ccy`` CSA.
    base_curve, quote_curve
        The two domestic OIS curves handed in, unchanged.
    fx_forwards
        The :class:`rateslib.FXForwards` the curve is registered in. Its
        ``fx_curves`` mapping holds ``collateral_curve``, so FX forwards implied
        off it are consistent with the basis by construction.
    solver
        The :class:`rateslib.Solver` that produced the curve. Keep it: pricing
        anything off ``collateral_curve`` without it loses the AD chain and
        therefore all delta.
    instruments
        The calibrating :class:`rateslib.XCS` instruments, tenor-ordered.
    basis
        The input strip.
    errors_bp
        Reprice error per tenor, in bp of basis spread, at solve time.
    mtm
        Whether the calibrating instruments MTM the collateral-currency leg.
    approximate
        True when any leg's conventions came from ``market_standard`` rather
        than a rateslib spec.
    notes
        Human-readable provenance lines for whatever is approximate.
    """

    collateral_curve: Any
    discount_ccy: str
    collateral_ccy: str
    base_curve: Any
    quote_curve: Any
    fx_forwards: Any
    solver: Any
    instruments: Tuple[Any, ...]
    basis: XccyBasisCurve
    errors_bp: pd.Series
    mtm: bool = True
    approximate: bool = False
    notes: Tuple[str, ...] = ()

    @property
    def curve_id(self) -> str:
        """The rateslib curve id, ``"<discount><collateral>"`` lower-cased."""
        return f"{self.discount_ccy}{self.collateral_ccy}".lower()

    def max_abs_error_bp(self) -> float:
        """Worst reprice error across the strip, in bp."""
        return float(self.errors_bp.abs().max()) if len(self.errors_bp) else 0.0

    def __repr__(self) -> str:  # pragma: no cover - display only
        return (
            f"<RLXccyCurves {self.curve_id} n={len(self.instruments)} "
            f"mtm={self.mtm} max_err={self.max_abs_error_bp():.2e}bp>"
        )


# ------------------------------------------------------------------ #
#                          instrument assembly                       #
# ------------------------------------------------------------------ #


def combined_calendar(*conventions: CurveConvention) -> Any:
    """The joint settlement calendar for a set of cross-currency legs.

    When every leg has a NAMED rateslib calendar the result is the comma-joined
    name (``"tgt,nyc"``), which is exactly what the ``*_xcs`` specs pin. When any
    leg does not - DKK, ILS, SGD and THB are cross-currency base currencies and
    rateslib 2.1.1 ships none of their calendars - the result is a
    :class:`rateslib.UnionCal` of :class:`rateslib.Cal` objects built from
    QuantLib's real holiday lists, NOT a proxy. ``rl.UnionCal`` refuses to mix
    ``NamedCal`` with ``Cal``, so in that case every leg is materialised from
    QuantLib.

    Note what this does to Israel: ILS trades Sunday-Thursday, so an ILS/USD
    union is closed Friday, Saturday AND Sunday. That is correct - a
    cross-currency settlement needs both centres open - and it is the reason a
    Monday-Friday proxy would be wrong rather than merely coarse.

    Returns
    -------
    str or rateslib.UnionCal
        Either form is accepted by :class:`rateslib.XCS` as ``calendar=``.
    """
    import rateslib as rl

    if all(conv.rl_calendar for conv in conventions):
        return ",".join(dict.fromkeys(conv.rl_calendar for conv in conventions))
    cals = []
    for conv in conventions:
        cal = conv.rl_calendar_object()
        if not isinstance(cal, rl.Cal):
            # A NamedCal cannot be unioned with a Cal; rebuild it from QuantLib.
            cal = rl_calendar_from_quantlib(conv.ql_calendar(), weekend=conv.weekend)
        cals.append(cal)
    return rl.UnionCal(cals)


def rl_xcs_kwargs(
    *,
    spread_ccy: str,
    other_ccy: str,
    mtm: bool = True,
    calendar: Optional[str] = None,
    frequency: str = _DEFAULT_FREQUENCY,
    payment_lag: int = _DEFAULT_PAYMENT_LAG,
    payment_lag_exchange: int = _DEFAULT_PAYMENT_LAG_EXCHANGE,
    spread_ois_index: Optional[str] = None,
    other_ois_index: Optional[str] = None,
) -> Tuple[Dict[str, Any], bool, Tuple[str, ...]]:
    """Schedule kwargs for one cross-currency pair, spec-first.

    Leg 1 is ``spread_ccy`` (it carries the basis); leg 2 is ``other_ccy`` and is
    the leg that MTMs.

    Returns
    -------
    (kwargs, approximate, notes)
        ``kwargs`` goes straight into :class:`rateslib.XCS`. ``approximate`` is
        True when the conventions are market standard rather than spec-supplied.

    Raises
    ------
    UnknownTagError
        Either leg is an IBOR-indexed Velocity token (``AUD_BBSW``, ``NZD_BKBM``).
    """
    # Before the ISO reduction, not after: AUD_BBSW reduces to AUD, which HAS an
    # RFR spec (audusd_xcs), so the spec short-circuit below would otherwise hand
    # back an AONIA-indexed schedule for a 3M BBSW leg without a word.
    assert_ois_pair(spread_ccy, other_ccy)

    a, b = iso_currency(spread_ccy), iso_currency(other_ccy)
    if a == b:
        raise ValueError(
            f"A cross-currency basis needs two currencies; got {spread_ccy!r} and {other_ccy!r}."
        )

    spec = RL_XCS_SPECS.get((a, b))
    if spec is not None and calendar is None:
        return {"spec": spec}, False, ()

    conv_a = conventions_for_currency(spread_ccy, ois_index=spread_ois_index)
    conv_b = conventions_for_currency(other_ccy, ois_index=other_ois_index)
    cal = calendar if calendar is not None else combined_calendar(conv_a, conv_b)
    notes: list[str] = []
    if spec is not None:
        notes.append(f"spec {spec} overridden by explicit calendar={cal!r}.")
    else:
        notes.append(
            f"rateslib 2.1.1 ships no {a.lower()}{b.lower()}_xcs spec; the schedule is market "
            "standard (quarterly, MF, T+2 payment lag, exchanges on the roll dates)."
        )
    for conv in (conv_a, conv_b):
        if conv.approximate:
            notes.append(f"{conv.citi_index}: {conv.note}")

    kwargs: Dict[str, Any] = {
        "frequency": frequency,
        "stub": "shortfront",
        "eom": False,
        "modifier": "mf",
        "calendar": cal,
        "payment_lag": payment_lag,
        "payment_lag_exchange": payment_lag_exchange,
        "leg2_payment_lag_exchange": payment_lag_exchange,
        "currency": a.lower(),
        "convention": conv_a.convention,
        "leg2_currency": b.lower(),
        "leg2_convention": conv_b.convention,
        "fixed": False,
        "leg2_fixed": False,
        "leg2_mtm": bool(mtm),
        "spread_compound_method": "none_simple",
        "leg2_spread_compound_method": "none_simple",
        "fixing_method": "rfr_payment_delay",
        "leg2_fixing_method": "rfr_payment_delay",
        "method_param": 0,
    }
    return kwargs, True, tuple(notes)


def build_rl_xcs(
    *,
    basis: XccyBasisCurve,
    tenor: str,
    domestic_curve: Any,
    foreign_curve: Any,
    fx_forwards: Any,
    collateral_curve: Any = None,
    collateral_ccy: Optional[str] = None,
    effective: Optional[datetime.datetime] = None,
    notional: float = 100_000_000.0,
    mtm: bool = True,
    float_spread: Optional[float] = None,
    calendar: Optional[str] = None,
    xcs_kwargs: Optional[Mapping[str, Any]] = None,
) -> Any:
    """One :class:`rateslib.XCS` for a tenor of a Velocity basis strip.

    Leg 1 is the spread currency (``basis.spread_ccy``) and carries the basis;
    leg 2 is the other currency and is the leg that MTMs.

    Parameters
    ----------
    basis
        The strip. Supplies the currencies, the spread-leg convention and, when
        ``float_spread`` is None, the quoted spread for ``tenor``.
    tenor
        Velocity tenor token, e.g. ``"5Y"``.
    domestic_curve
        The forecast curve for ``basis.base_ccy`` (its own-collateral OIS curve).
    foreign_curve
        The forecast curve for ``basis.quote_ccy``.
    fx_forwards
        A :class:`rateslib.FXForwards` covering the pair. Required: an MTM leg
        cannot be built without FX forwards.
    collateral_curve
        The discount curve for the non-collateral currency's flows. When None,
        each leg discounts on its own domestic curve, which prices the swap
        **without** any basis and is only useful as a starting point.
    collateral_ccy
        Which currency the CSA is in. Defaults to
        :func:`~MDP.CitiVelocityExcel.xccy.basis_data.default_collateral_ccy`.
    effective
        Start date. Defaults to the FX forwards' settlement date, i.e. spot.
    notional
        Leg-1 notional in ``basis.spread_ccy`` units.
    mtm
        MTM the collateral-currency leg (market standard).
    float_spread
        Override the leg-1 spread in bp. Defaults to ``basis.at(tenor)``.
    xcs_kwargs
        Extra keyword arguments merged last, e.g. to override a spec field.

    Returns
    -------
    rateslib.XCS

    Raises
    ------
    ValueError
        ``fx_forwards`` is None, or the currencies are degenerate.
    """
    import rateslib as rl

    if fx_forwards is None:
        raise ValueError(
            "build_rl_xcs needs fx_forwards: an MTM cross-currency leg reprices its notional "
            "off the FX forward curve and cannot be constructed without one. Pass mtm=False "
            "AND an fx_forwards built from a single FXRates if you only have spot."
        )
    # The strip carries Citi's raw tokens; basis.spread_ccy is already ISO'd and
    # so can no longer tell an AUD_BBSW leg from an AONIA one.
    assert_ois_pair(basis.base_ccy, basis.quote_ccy)

    spread_ccy = iso_currency(basis.spread_ccy)
    other_ccy = iso_currency(
        basis.quote_ccy if spread_ccy == iso_currency(basis.base_ccy) else basis.base_ccy
    )
    coll = iso_currency(collateral_ccy or default_collateral_ccy(basis.base_ccy, basis.quote_ccy))

    kwargs, _approx, _notes = rl_xcs_kwargs(
        spread_ccy=spread_ccy, other_ccy=other_ccy, mtm=mtm, calendar=calendar
    )
    if "spec" in kwargs and not mtm:
        kwargs = {**kwargs, "leg2_mtm": False}

    # Curve slots: [leg1 forecast, leg1 discount, leg2 forecast, leg2 discount].
    base_is_spread = spread_ccy == iso_currency(basis.base_ccy)
    leg1_forecast = domestic_curve if base_is_spread else foreign_curve
    leg2_forecast = foreign_curve if base_is_spread else domestic_curve
    if coll == spread_ccy:
        leg1_discount = leg1_forecast
        leg2_discount = collateral_curve if collateral_curve is not None else leg2_forecast
    else:
        leg1_discount = collateral_curve if collateral_curve is not None else leg1_forecast
        leg2_discount = leg2_forecast

    spread_bp = float(basis.at(tenor)) if float_spread is None else float(float_spread)
    start = effective if effective is not None else _fx_settlement(fx_forwards)

    merged: Dict[str, Any] = dict(kwargs)
    merged.update(
        {
            "notional": float(notional),
            "float_spread": spread_bp,
            "curves": [leg1_forecast, leg1_discount, leg2_forecast, leg2_discount],
        }
    )
    if xcs_kwargs:
        merged.update(dict(xcs_kwargs))
    return rl.XCS(start, str(tenor).strip().upper(), **merged)


def _fx_settlement(fx_forwards: Any) -> datetime.datetime:
    """The spot settlement date an :class:`rateslib.FXForwards` was built on."""
    fx_rates = getattr(fx_forwards, "fx_rates", None)
    if isinstance(fx_rates, (list, tuple)) and fx_rates:
        fx_rates = fx_rates[0]
    settlement = getattr(fx_rates, "settlement", None)
    if isinstance(settlement, datetime.datetime):
        return settlement
    node = getattr(fx_forwards, "immediate", None)
    if isinstance(node, datetime.datetime):
        return node
    raise ValueError(
        "Could not read a settlement date off fx_forwards; pass effective= explicitly to "
        "build_rl_xcs / solve_rl_collateral_curve."
    )


# ------------------------------------------------------------------ #
#                            the calibration                         #
# ------------------------------------------------------------------ #


def solve_rl_collateral_curve(
    *,
    basis: XccyBasisCurve,
    domestic_curve: Any,
    foreign_curve: Any,
    fx_rate: float,
    ref_date: datetime.datetime,
    collateral_ccy: Optional[str] = None,
    fx_settlement: Optional[datetime.datetime] = None,
    spot_lag: int = 2,
    tenors: Optional[Sequence[str]] = None,
    notional: float = 100_000_000.0,
    mtm: bool = True,
    pre_solvers: Sequence[Any] = (),
    interpolation: str = "log_linear",
    calendar: Optional[str] = None,
    curve_id: Optional[str] = None,
    tol_bp: float = _DEFAULT_TOL_BP,
    max_iter: int = 200,
) -> RLXccyCurves:
    """Solve the collateral discount curve that reprices every quoted basis.

    Both legs forecast off their own domestic OIS curve. The single unknown is
    the discount curve for the **non-collateral** currency's cashflows under the
    collateral currency's CSA - rateslib's ``"<ccy><collateral>"`` curve. One
    node per quoted tenor, solved by Levenberg-Marquardt.

    Parameters
    ----------
    basis
        The quoted strip. Validated before use.
    domestic_curve, foreign_curve
        Already-solved OIS curves for ``basis.base_ccy`` and ``basis.quote_ccy``
        respectively, each collateralised in its own currency.
    fx_rate
        Spot, quoted as **units of quote currency per unit of base currency**
        (``EUR/USD`` -> ``1.08`` USD per EUR).
    ref_date
        Curve reference date (today). Must match the domestic/foreign curves'
        own reference date.
    collateral_ccy
        CSA currency. Defaults to USD for a USD pair, else the quote currency.
    fx_settlement
        Spot settlement and swap effective date. Defaults to T+2 on the pair's
        combined calendar, which is what a cross-currency basis quote settles on
        and what the QuantLib side uses. Defaulting to ``ref_date`` instead
        (an immediate rate) shifts the whole trade by two business days and was
        measured at up to 0.03bp of fair basis on the front tenor - enough to
        make a cross-library comparison meaningless.
    spot_lag
        Business days from ``ref_date`` to spot, used only when ``fx_settlement``
        is not given. Two on every pair in this family.
    tenors
        Subset of ``basis.tenors()`` to calibrate on. Defaults to all of them.
    mtm
        Calibrate with the market-standard MTM leg. ``False`` gives the
        constant-notional convention; the two curves differ.
    pre_solvers
        Solvers that produced ``domestic_curve``/``foreign_curve``. Pass them to
        keep the AD chain, so risk propagates to the domestic curve inputs.
    tol_bp
        Every quote must reprice inside this, in bp. Exceeding it raises rather
        than returning a curve that does not fit - a mis-fit collateral curve
        looks exactly like a good one until it is used.

    Returns
    -------
    RLXccyCurves

    Raises
    ------
    ValueError
        The strip fails validation, the solver does not converge, or the fitted
        curve misses a quote by more than ``tol_bp``.
    UnknownTagError
        Either leg of the strip is an IBOR-indexed Velocity token (``AUD_BBSW``,
        ``NZD_BKBM``). Both legs built here are RFR-OIS.
    """
    import rateslib as rl

    basis.validate()
    assert_ois_pair(basis.base_ccy, basis.quote_ccy)

    base_iso = iso_currency(basis.base_ccy)
    quote_iso = iso_currency(basis.quote_ccy)
    spread_iso = iso_currency(basis.spread_ccy)
    coll = iso_currency(collateral_ccy or default_collateral_ccy(basis.base_ccy, basis.quote_ccy))
    if coll not in (base_iso, quote_iso):
        raise ValueError(
            f"collateral_ccy={coll!r} is not one of the pair ({base_iso}, {quote_iso}). A "
            "third-currency CSA needs two basis strips and is not supported here."
        )
    discount_iso = quote_iso if coll == base_iso else base_iso

    axis = [str(t).strip().upper() for t in (tenors if tenors is not None else basis.tenors())]
    missing = [t for t in axis if t not in basis.spreads.index]
    if missing:
        raise ValueError(
            f"tenors={missing} are not in the {basis.pair} strip. Present: "
            f"{', '.join(basis.tenors())}."
        )
    axis = sorted(axis, key=tenor_years)

    kwargs, approximate, notes = rl_xcs_kwargs(
        spread_ccy=spread_iso,
        other_ccy=quote_iso if spread_iso == base_iso else base_iso,
        mtm=mtm,
        calendar=calendar,
    )
    if approximate:
        warnings.warn(
            f"{basis.pair} cross-currency conventions are market standard, not rateslib specs: "
            + " ".join(notes),
            stacklevel=2,
        )

    cal_spec = kwargs.get("calendar")
    if cal_spec is None:
        cal_spec = _spec_calendar(kwargs.get("spec"))
    cal = rl.get_calendar(cal_spec) if isinstance(cal_spec, str) else cal_spec
    settlement = (
        fx_settlement
        if fx_settlement is not None
        else rl.add_tenor(ref_date, f"{int(spot_lag)}B", "F", cal)
    )

    # One node per quoted tenor, at the swap maturity, SEEDED from the discount
    # currency's own OIS curve. Seeding at 1.0 instead is not merely slower: the
    # reverse-CSA solve (USD under EUR collateral, 4% USD rates) diverges to
    # f_val=NaN after 200 iterations, because an MTM leg's notional resets off
    # FX forwards implied by this very curve.
    seed_curve = domestic_curve if discount_iso == base_iso else foreign_curve
    nodes: Dict[datetime.datetime, float] = {ref_date: 1.0}
    for tenor in axis:
        node_date = rl.add_tenor(settlement, tenor, "MF", cal)
        nodes[node_date] = float(seed_curve[node_date])
    cid = curve_id or f"{discount_iso}{coll}".lower()
    collateral_curve = rl.Curve(
        nodes=nodes,
        id=cid,
        interpolation=interpolation,
        convention="act360",
        calendar=cal,
        currency=discount_iso.lower(),
        modifier="MF",
    )

    fx_pair = f"{base_iso}{quote_iso}".lower()
    fx_rates = rl.FXRates({fx_pair: float(fx_rate)}, settlement=settlement)
    fx_curves = {
        f"{base_iso}{base_iso}".lower(): domestic_curve,
        f"{quote_iso}{quote_iso}".lower(): foreign_curve,
        cid: collateral_curve,
    }
    fx_forwards = rl.FXForwards(fx_rates, fx_curves)

    instruments = [
        build_rl_xcs(
            basis=basis,
            tenor=tenor,
            domestic_curve=domestic_curve,
            foreign_curve=foreign_curve,
            fx_forwards=fx_forwards,
            collateral_curve=collateral_curve,
            collateral_ccy=coll,
            effective=settlement,
            notional=notional,
            mtm=mtm,
            float_spread=0.0,  # the solver supplies the quote through s=
            calendar=calendar,
        )
        for tenor in axis
    ]
    quotes = [float(basis.at(t)) for t in axis]

    solver = rl.Solver(
        curves=[collateral_curve],
        instruments=instruments,
        s=quotes,
        fx=fx_forwards,
        pre_solvers=list(pre_solvers),
        instrument_labels=axis,
        id=f"{cid}_xccy",
        max_iter=int(max_iter),
    )
    status = str(solver.result.get("status", ""))
    if status.upper() != "SUCCESS":
        raise ValueError(
            f"rateslib did not converge on the {basis.pair} collateral curve {cid!r}: "
            f"status={status!r}, iterations={solver.result.get('iterations')}. An unconverged "
            "curve is never returned. Try fewer tenors (tenors=), a longer max_iter, or check "
            "that domestic_curve/foreign_curve share ref_date with this call."
        )

    errors = rl_xccy_reprice_errors_bp_from(instruments, axis, quotes, solver)
    worst = float(errors.abs().max()) if len(errors) else 0.0
    if worst > float(tol_bp):
        bad = errors[errors.abs() > float(tol_bp)]
        raise ValueError(
            f"{basis.pair} collateral curve {cid!r} converged but misses {len(bad)} quote(s) by "
            f"up to {worst:.4g}bp (tol_bp={tol_bp:g}): "
            + ", ".join(f"{k}={v:+.4g}bp" for k, v in bad.items())
            + ". Raise tol_bp only if you know why the fit is loose; a collateral curve that "
            "does not reprice its own inputs is not a collateral curve."
        )

    _logger.debug(
        "solve_rl_collateral_curve %s -> %s (%d tenors, mtm=%s, max_err=%.3gbp)",
        basis.pair,
        cid,
        len(axis),
        mtm,
        worst,
    )
    return RLXccyCurves(
        collateral_curve=collateral_curve,
        discount_ccy=discount_iso,
        collateral_ccy=coll,
        base_curve=domestic_curve,
        quote_curve=foreign_curve,
        fx_forwards=fx_forwards,
        solver=solver,
        instruments=tuple(instruments),
        basis=basis,
        errors_bp=errors,
        mtm=bool(mtm),
        approximate=approximate,
        notes=tuple(notes),
    )


def _spec_calendar(spec: Optional[str]) -> str:
    """The calendar string a rateslib xcs spec pins."""
    if not spec:
        raise ValueError("No calendar and no spec: cannot resolve a cross-currency calendar.")
    from rateslib import defaults

    return str(defaults.spec[spec]["calendar"])


def rl_xccy_reprice_errors_bp_from(
    instruments: Sequence[Any],
    tenors: Sequence[str],
    quotes: Sequence[float],
    solver: Any,
) -> pd.Series:
    """``model - quote`` in bp, per tenor, for an already-built instrument set."""
    errs = []
    for inst, quote in zip(instruments, quotes):
        errs.append(float(inst.rate(solver=solver)) - float(quote))
    return pd.Series(errs, index=list(tenors), dtype="float64", name="reprice_error_bp")


def rl_xccy_reprice_errors_bp(curves: RLXccyCurves, basis: XccyBasisCurve) -> pd.Series:
    """Reprice ``basis`` off a solved collateral curve; ``model - quote`` in bp.

    Pass the same strip that was calibrated to check the fit; pass a different
    strip (a later date, the other leg) to measure the dislocation.

    Parameters
    ----------
    curves
        A solved :class:`RLXccyCurves`.
    basis
        The strip to reprice.

    Returns
    -------
    pandas.Series
        Indexed by tenor, ascending in maturity, in basis points. Tenors present
        in ``basis`` but not calibrated are priced with a freshly built XCS.
    """
    basis.validate()
    # errors_bp carries the calibrated axis, in the same order the instruments
    # were built, so it is the authoritative tenor -> instrument mapping.
    by_tenor: Dict[str, Any] = dict(zip(list(curves.errors_bp.index), curves.instruments))

    out: Dict[str, float] = {}
    for tenor in basis.tenors():
        inst = by_tenor.get(tenor)
        if inst is None:
            inst = build_rl_xcs(
                basis=basis,
                tenor=tenor,
                domestic_curve=curves.base_curve,
                foreign_curve=curves.quote_curve,
                fx_forwards=curves.fx_forwards,
                collateral_curve=curves.collateral_curve,
                collateral_ccy=curves.collateral_ccy,
                notional=100_000_000.0,
                mtm=curves.mtm,
                float_spread=0.0,
            )
        out[tenor] = float(inst.rate(solver=curves.solver)) - float(basis.at(tenor))
    return pd.Series(out, dtype="float64", name="reprice_error_bp").reindex(basis.tenors())
