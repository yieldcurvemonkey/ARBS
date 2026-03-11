from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, Optional

import QuantLib as ql

from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMarketContext
from Query.Base._GenericPricable import _GenericPricable


@dataclass(frozen=True)
class IRSwaptionPricable(_GenericPricable):
    option_type: str
    exercise_date: dt.date
    underlying_effective_date: dt.date
    underlying_maturity_date: dt.date
    strike: float
    notional: float
    label: Optional[str] = None

    def with_notional(self, notional: float) -> "IRSwaptionPricable":
        return replace(self, notional=float(notional))


def _py_to_ql_date(d: dt.date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _curve_day_counter(context: IRSwaptionMarketContext) -> ql.DayCounter:
    return context.curve.daycounter() if hasattr(context.curve, "daycounter") else ql.Actual365Fixed()


def _curve_calendar(context: IRSwaptionMarketContext) -> ql.Calendar:
    if hasattr(context.curve, "calendar"):
        try:
            cal = context.curve.calendar()
            if isinstance(cal, ql.Calendar):
                return cal
        except Exception:
            pass
    return ql.UnitedStates(ql.UnitedStates.GovernmentBond)


def _signed_swap_notional(option_type: str, abs_notional: float) -> float:
    token = str(option_type).strip().lower()
    if token in {"payer", "call", "c"}:
        return -abs(float(abs_notional))
    if token in {"receiver", "put", "p"}:
        return abs(float(abs_notional))
    raise ValueError(f"Unsupported swaption option_type '{option_type}'")


@contextmanager
def _temporary_eval_date(eval_date: ql.Date):
    settings = ql.Settings.instance()
    original = settings.evaluationDate
    settings.evaluationDate = eval_date
    try:
        yield
    finally:
        settings.evaluationDate = original


def build_underlying_swap(
    context: IRSwaptionMarketContext,
    leg: IRSwaptionPricable,
    *,
    curve_handle: Optional[ql.YieldTermStructureHandle] = None,
) -> Any:
    _ = curve_handle
    signed_notional = _signed_swap_notional(leg.option_type, abs(leg.notional))
    return context.curve.build_irswap(
        effective_date=leg.underlying_effective_date,
        maturity_date=leg.underlying_maturity_date,
        fixed_rate=float(leg.strike) * 100.0,
        notional=signed_notional,
    )


def leg_tte_years(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
    day_counter = context.curve.daycounter() if hasattr(context.curve, "daycounter") else ql.Actual365Fixed()
    ref = _py_to_ql_date(context.as_of_date)
    exp = _py_to_ql_date(leg.exercise_date)
    return max(float(day_counter.yearFraction(ref, exp)), 1e-10)


def leg_swap_length_years(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
    day_counter = context.curve.daycounter() if hasattr(context.curve, "daycounter") else ql.Actual365Fixed()
    eff = _py_to_ql_date(leg.underlying_effective_date)
    mat = _py_to_ql_date(leg.underlying_maturity_date)
    return max(float(day_counter.yearFraction(eff, mat)), 1e-10)


def leg_forward_rate(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
    par_swap = context.curve.build_irswap(
        effective_date=leg.underlying_effective_date,
        maturity_date=leg.underlying_maturity_date,
        fixed_rate=-0.0,
        notional=1.0,
    )
    return abs(float(context.curve.fair_rate(par_swap)))


def leg_cube_vol(context: IRSwaptionMarketContext, leg: IRSwaptionPricable, *, strike: Optional[float] = None) -> Optional[float]:
    """Query SABR vol cube if available in context metadata. Returns vol in decimal or None."""
    cube = (context.metadata or {}).get("vol_cube")
    if cube is None:
        return None
    option_time = leg_tte_years(context, leg)
    swap_years = leg_swap_length_years(context, leg)
    k = float(leg.strike if strike is None else strike)
    return float(cube.volatility_at_point(option_time, swap_years, k))


def leg_model_vol(context: IRSwaptionMarketContext, leg: IRSwaptionPricable, *, strike: Optional[float] = None) -> float:
    k = float(leg.strike if strike is None else strike)
    cube_v = leg_cube_vol(context, leg, strike=k)
    if cube_v is not None:
        return cube_v
    option_time = leg_tte_years(context, leg)
    swap_length = leg_swap_length_years(context, leg)
    return float(context.vol_handle.volatility(option_time, swap_length, k, True))


def _curve_eval_date(context: IRSwaptionMarketContext) -> ql.Date:
    try:
        d = context.curve_handle.referenceDate()
        if isinstance(d, ql.Date):
            return d
    except Exception:
        pass
    return _py_to_ql_date(context.as_of_date)


def _active_eval_date(context: IRSwaptionMarketContext) -> ql.Date:
    try:
        d = ql.Settings.instance().evaluationDate
        if isinstance(d, ql.Date) and d.serialNumber() > 0:
            return d
    except Exception:
        pass
    return _curve_eval_date(context)


def _exact_strike_pricing_engine(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> Optional[ql.PricingEngine]:
    vol = leg_cube_vol(context, leg)
    if vol is None:
        return None

    vol_surface = ql.ConstantSwaptionVolatility(
        _active_eval_date(context),
        _curve_calendar(context),
        ql.ModifiedFollowing,
        float(vol),
        _curve_day_counter(context),
        ql.Normal,
        0.0,
    )
    vol_handle = ql.SwaptionVolatilityStructureHandle(vol_surface)
    vol_handle.enableExtrapolation()
    try:
        return ql.BachelierSwaptionEngine(context.curve_handle, vol_handle)
    except TypeError:
        return ql.BachelierSwaptionEngine(context.curve_handle, vol_handle, _curve_day_counter(context))


def _swaption_side_sign(swpt: ql.Swaption) -> float:
    try:
        return 1.0 if float(swpt.underlying().fixedLegBPS()) > 0.0 else -1.0
    except Exception:
        return 1.0


def build_ql_swaption(
    context: IRSwaptionMarketContext,
    leg: IRSwaptionPricable,
    *,
    curve_handle: Optional[ql.YieldTermStructureHandle] = None,
    pricing_engine: Optional[ql.PricingEngine] = None,
) -> ql.Swaption:
    ch = curve_handle or context.curve_handle
    underlying = build_underlying_swap(context, leg, curve_handle=ch)
    ex = ql.EuropeanExercise(_py_to_ql_date(leg.exercise_date))
    swpt = ql.Swaption(underlying, ex)
    engine = pricing_engine or _exact_strike_pricing_engine(context, leg) or context.pricing_engine
    swpt.setPricingEngine(engine)
    return swpt


def leg_spot_npv(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
    with _temporary_eval_date(_curve_eval_date(context)):
        return float(build_ql_swaption(context, leg).NPV())


def leg_fwd_npv(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
    spot = leg_spot_npv(context, leg)
    discount = float(context.curve_handle.discount(_py_to_ql_date(leg.exercise_date)))
    if abs(discount) < 1e-12:
        return float(spot)
    return (float(spot) / discount) * 100


def leg_implied_normal_vol_bps(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
    cube_v = leg_cube_vol(context, leg)
    if cube_v is not None:
        return float(cube_v) * 10_000.0
    with _temporary_eval_date(_curve_eval_date(context)):
        swpt = build_ql_swaption(context, leg)
        npv = float(swpt.NPV())
        if npv <= 0.0:
            return 0.0
        try:
            iv = swpt.impliedVolatility(
                npv,
                context.curve_handle,
                0.01,
                1e-8,
                1000,
                1e-8,
                5.0,
                ql.Normal,
            )
            return float(iv) * 10_000.0
        except Exception:
            return float(leg_model_vol(context, leg)) * 10_000.0


def leg_delta(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
    with _temporary_eval_date(_curve_eval_date(context)):
        swpt = build_ql_swaption(context, leg)
        annuity = float(swpt.annuity())
        if abs(annuity) < 1e-14:
            return 0.0
        abs_delta = abs(float(swpt.delta()) / annuity)
        return abs_delta if _swaption_side_sign(swpt) > 0.0 else -abs_delta


def leg_gamma(context: IRSwaptionMarketContext, leg: IRSwaptionPricable, *, bump_bps: float = 1.0) -> float:
    bump = max(abs(float(bump_bps)) / 10_000.0, 1e-8)
    up_leg = replace(leg, strike=float(leg.strike) + bump)
    dn_leg = replace(leg, strike=float(leg.strike) - bump)
    g_up = leg_delta(context, up_leg)
    g_dn = leg_delta(context, dn_leg)
    return abs((g_up - g_dn) / (2.0 * bump)) / 10_000.0


def leg_theta_1d(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
    today = _curve_eval_date(context)
    next_day = today + 1
    with _temporary_eval_date(today):
        npv_0 = float(build_ql_swaption(context, leg).NPV())
    with _temporary_eval_date(next_day):
        npv_1 = float(build_ql_swaption(context, leg).NPV())
    theta = npv_1 - npv_0
    if abs(theta) > 1e-14:
        return theta

    # Some QuantLib/Python setups keep term structures anchored to a fixed reference date,
    # so moving evaluationDate by +1d can leave NPV unchanged. Fallback: reduce option
    # time-to-expiry by 1 day while holding today's market context fixed.
    rolled_leg = _roll_exercise_date_back_one_day(context, leg)
    if rolled_leg is None:
        return theta

    with _temporary_eval_date(today):
        npv_roll = float(build_ql_swaption(context, rolled_leg).NPV())
    return npv_roll - npv_0


def leg_vega_01(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
    with _temporary_eval_date(_curve_eval_date(context)):
        swpt = build_ql_swaption(context, leg)
        return float(swpt.vega()) / 10_000.0


def leg_dv01(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
    with _temporary_eval_date(_curve_eval_date(context)):
        swpt = build_ql_swaption(context, leg)
        abs_dv01 = abs(float(swpt.delta()) / 10_000.0)
        return abs_dv01 if _swaption_side_sign(swpt) > 0.0 else -abs_dv01


def leg_gamma_01(context: IRSwaptionMarketContext, leg: IRSwaptionPricable, *, bump_bps: float = 1.0) -> float:
    bump = max(abs(float(bump_bps)) / 10_000.0, 1e-8)
    up_leg = replace(leg, strike=float(leg.strike) + bump)
    dn_leg = replace(leg, strike=float(leg.strike) - bump)
    g_up = leg_dv01(context, up_leg)
    g_dn = leg_dv01(context, dn_leg)
    return abs((g_up - g_dn) / (2.0 * bump)) / 10_000.0


def _roll_exercise_date_back_one_day(
    context: IRSwaptionMarketContext,
    leg: IRSwaptionPricable,
) -> Optional[IRSwaptionPricable]:
    bumped_ex = leg.exercise_date - dt.timedelta(days=1)
    if bumped_ex < context.as_of_date:
        bumped_ex = context.as_of_date
    if bumped_ex >= leg.exercise_date:
        return None
    return replace(leg, exercise_date=bumped_ex)


def leg_charm(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
    today = _curve_eval_date(context)
    next_day = today + 1
    with _temporary_eval_date(today):
        d0 = float(build_ql_swaption(context, leg).delta())
    with _temporary_eval_date(next_day):
        d1 = float(build_ql_swaption(context, leg).delta())
    charm = d1 - d0
    if abs(charm) > 1e-14:
        return charm

    rolled_leg = _roll_exercise_date_back_one_day(context, leg)
    if rolled_leg is None:
        return charm

    with _temporary_eval_date(today):
        d_roll = float(build_ql_swaption(context, rolled_leg).delta())
    return d_roll - d0


def leg_veta(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
    today = _curve_eval_date(context)
    next_day = today + 1
    with _temporary_eval_date(today):
        v0 = float(build_ql_swaption(context, leg).vega())
    with _temporary_eval_date(next_day):
        v1 = float(build_ql_swaption(context, leg).vega())
    veta = v1 - v0
    if abs(veta) > 1e-14:
        return veta

    rolled_leg = _roll_exercise_date_back_one_day(context, leg)
    if rolled_leg is None:
        return veta

    with _temporary_eval_date(today):
        v_roll = float(build_ql_swaption(context, rolled_leg).vega())
    return v_roll - v0


def leg_metrics(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> dict[str, float]:
    spot_npv = leg_spot_npv(context, leg)
    fwd_npv = leg_fwd_npv(context, leg)
    spot_prem = spot_npv / max(abs(float(leg.notional)), 1.0)
    fwd_prem = fwd_npv / max(abs(float(leg.notional)), 1.0)
    theta_1d = leg_theta_1d(context, leg)
    vega01 = leg_vega_01(context, leg)
    be_daily = (-theta_1d / vega01) if abs(vega01) > 1e-12 else 0.0

    return {
        "NVOL": leg_implied_normal_vol_bps(context, leg),
        "SPOT_NPV": spot_npv,
        "FWD_NPV": fwd_npv,
        "SPOT_PREM": spot_prem,
        "FWD_PREM": fwd_prem,
        "DV01": leg_dv01(context, leg),
        "DELTA": leg_delta(context, leg),
        "GAMMA": leg_gamma(context, leg),
        "GAMMA_01": leg_gamma_01(context, leg),
        "VEGA_01": vega01,
        "THETA_1D": theta_1d,
        "CHARM": leg_charm(context, leg),
        "VETA": leg_veta(context, leg),
        "DAILY_BREAKEVEN_NVOL": be_daily,
        "ANNUAL_BREAKEVEN_NVOL": be_daily * 252.0,
    }


def package_forward_rate(context: IRSwaptionMarketContext, leg: IRSwaptionPricable) -> float:
    return leg_forward_rate(context, leg)
