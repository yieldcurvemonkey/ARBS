from __future__ import annotations

import datetime as dt
from dataclasses import replace
from enum import Enum, auto
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple

import QuantLib as ql
from scipy.optimize import brentq, newton

from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMarketContext
from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.IRSwaptions.pricer import (
    IRSwaptionPricable,
    discount_factor,
    leg_forward_rate,
    leg_model_vol,
    leg_spot_npv,
    leg_tte_years,
    leg_vega_01,
)
from Query.IRSwaptions.utils import normalize_premium_type, parse_midcurve_tail, parse_side, resolve_strike_spec, to_date


class IRSwaptionStructure(Enum):
    RECEIVER = auto()
    PAYER = auto()
    STRADDLE = auto()
    STRANGLE = auto()
    RECEIVER_SPREAD = auto()
    PAYER_SPREAD = auto()
    RECEIVER_FLY = auto()
    PAYER_FLY = auto()
    RECEIVER_1x2 = auto()
    PAYER_1x2 = auto()
    RECEIVER_LADDER = auto()
    PAYER_LADDER = auto()
    RISK_REVERSAL = auto()


_STRUCTURE_RISK_WEIGHTS: dict[IRSwaptionStructure, list[float]] = {
    IRSwaptionStructure.RECEIVER: [1.0],
    IRSwaptionStructure.PAYER: [1.0],
    IRSwaptionStructure.STRADDLE: [1.0, 1.0],
    IRSwaptionStructure.STRANGLE: [1.0, 1.0],
    IRSwaptionStructure.RECEIVER_SPREAD: [1.0, -1.0],
    IRSwaptionStructure.PAYER_SPREAD: [1.0, -1.0],
    IRSwaptionStructure.RECEIVER_FLY: [-1.0, 2.0, -1.0],
    # Legacy bug fix: payer fly must use the payer-fly risk map, not receiver-spread style.
    IRSwaptionStructure.PAYER_FLY: [-1.0, 2.0, -1.0],
    IRSwaptionStructure.RECEIVER_1x2: [1.0, -2.0],
    IRSwaptionStructure.PAYER_1x2: [1.0, -2.0],
    IRSwaptionStructure.RECEIVER_LADDER: [1.0, -1.0, -1.0],
    IRSwaptionStructure.PAYER_LADDER: [1.0, -1.0, -1.0],
    IRSwaptionStructure.RISK_REVERSAL: [1.0, -1.0],
}


class IRSwaptionStructureFunctionMap(BaseStructureFunctionMap[IRSwaptionStructure, IRSwaptionPricable]):
    def __init__(self, context: IRSwaptionMarketContext):
        super().__init__(IRSwaptionStructure, context=context)
        self._map = self._create_map()

    def _create_map(self) -> Dict[IRSwaptionStructure, Callable[..., Tuple[List[IRSwaptionPricable], List[float]]]]:
        def wrap(builder: Callable[..., Tuple[List[IRSwaptionPricable], List[float]]]) -> Callable[..., Tuple[List[IRSwaptionPricable], List[float]]]:
            def _wrapped(**kwargs: Any) -> Tuple[List[IRSwaptionPricable], List[float]]:
                package, risk_weights = builder(**kwargs)
                package, risk_weights = self._apply_target_vega_01(package, risk_weights, kwargs)
                return self._apply_premium_overrides(package, kwargs), risk_weights

            return _wrapped

        return {
            IRSwaptionStructure.RECEIVER: wrap(partial(self._build_receiver)),
            IRSwaptionStructure.PAYER: wrap(partial(self._build_payer)),
            IRSwaptionStructure.STRADDLE: wrap(partial(self._build_straddle)),
            IRSwaptionStructure.STRANGLE: wrap(partial(self._build_strangle)),
            IRSwaptionStructure.RECEIVER_SPREAD: wrap(partial(self._build_receiver_spread)),
            IRSwaptionStructure.PAYER_SPREAD: wrap(partial(self._build_payer_spread)),
            IRSwaptionStructure.RECEIVER_FLY: wrap(partial(self._build_receiver_fly)),
            IRSwaptionStructure.PAYER_FLY: wrap(partial(self._build_payer_fly)),
            IRSwaptionStructure.RECEIVER_1x2: wrap(partial(self._build_receiver_1x2)),
            IRSwaptionStructure.PAYER_1x2: wrap(partial(self._build_payer_1x2)),
            IRSwaptionStructure.RECEIVER_LADDER: wrap(partial(self._build_receiver_ladder)),
            IRSwaptionStructure.PAYER_LADDER: wrap(partial(self._build_payer_ladder)),
            IRSwaptionStructure.RISK_REVERSAL: wrap(partial(self._build_risk_reversal)),
        }

    @staticmethod
    def _default_notional(notional: Optional[float], vega: Optional[float]) -> float:
        if notional is not None:
            return abs(float(notional))
        return 100_000_000.0

    @staticmethod
    def _target_vega_01(kwargs: Dict[str, Any]) -> Optional[float]:
        for key in ("vega_01", "vega01", "vega"):
            if kwargs.get(key) is not None:
                return abs(float(kwargs[key]))
        return None

    def _apply_target_vega_01(
        self,
        package: list[IRSwaptionPricable],
        risk_weights: list[float],
        kwargs: Dict[str, Any],
    ) -> tuple[list[IRSwaptionPricable], list[float]]:
        if kwargs.get("notional") is not None:
            return package, risk_weights

        target_vega_01 = self._target_vega_01(kwargs)
        if target_vega_01 is None:
            return package, risk_weights

        context = self.common_kwargs["context"]
        current = float(
            sum(float(rw) * float(leg_vega_01(context, leg)) for rw, leg in zip(risk_weights, package))
        )
        if abs(current) < 1e-12:
            raise ValueError("Cannot scale package to target vega_01 because current package vega_01 is zero.")

        scale = target_vega_01 / abs(current)
        scaled = [leg.with_notional(abs(float(leg.notional)) * scale) for leg in package]
        return scaled, risk_weights

    @staticmethod
    def _py_to_ql_date(value: dt.date) -> ql.Date:
        return ql.Date(value.day, value.month, value.year)

    @classmethod
    def _premium_inputs(
        cls,
        kwargs: Dict[str, Any],
        n_legs: int,
    ) -> tuple[list[Optional[float]], list[Optional[str]]]:
        premiums = kwargs.get("premiums")
        if premiums is not None:
            if not isinstance(premiums, (list, tuple)) or len(premiums) != n_legs:
                raise ValueError(f"premiums must contain exactly {n_legs} entries for this swaption structure.")
            raw_values = [None if value is None else float(value) for value in premiums]
        else:
            premium = kwargs.get("premium")
            if premium is None:
                raw_values = [None] * n_legs
            else:
                if n_legs != 1:
                    raise ValueError("Scalar premium/upfront override is only valid for outright swaption queries.")
                raw_values = [float(premium)]

        if kwargs.get("premium_type") is not None and kwargs.get("premium_types") is not None:
            raise ValueError("Specify only one of premium_type or premium_types for swaption premium overrides.")

        premium_types = kwargs.get("premium_types")
        if premium_types is not None:
            if not isinstance(premium_types, (list, tuple)) or len(premium_types) != n_legs:
                raise ValueError(f"premium_types must contain exactly {n_legs} entries for this swaption structure.")
            return raw_values, [
                None if value is None else normalize_premium_type(premium_type)
                for value, premium_type in zip(raw_values, premium_types)
            ]

        premium_type = kwargs.get("premium_type")
        return raw_values, [
            None if value is None else normalize_premium_type(premium_type, default="spot_cash")
            for value in raw_values
        ]

    @classmethod
    def _premium_override_cash_value(
        cls,
        *,
        context: IRSwaptionMarketContext,
        leg: IRSwaptionPricable,
        premium: float,
        premium_type: str,
    ) -> float:
        amount = abs(float(premium))
        if premium_type == "spot_cash":
            return amount

        notional = abs(float(leg.notional))
        if premium_type == "spot_bps":
            return amount / 10_000.0 * notional
        if premium_type == "fwd_bps":
            # Backend-agnostic: curve_handle is a ql.YieldTermStructureHandle
            # under '-QL' and a rateslib.Curve under '-RL', and the two are read
            # differently. The QuantLib path is unchanged.
            discount = discount_factor(context, leg.exercise_date)
            return amount / 10_000.0 * notional * discount
        raise ValueError(f"Unsupported premium_type '{premium_type}'.")

    @classmethod
    def _apply_premium_overrides(
        cls,
        package: list[IRSwaptionPricable],
        kwargs: Dict[str, Any],
    ) -> list[IRSwaptionPricable]:
        context = kwargs["context"]
        raw_overrides, premium_types = cls._premium_inputs(kwargs, len(package))
        overrides = [
            None
            if premium is None or premium_type is None
            else cls._premium_override_cash_value(
                context=context,
                leg=leg,
                premium=float(premium),
                premium_type=str(premium_type),
            )
            for leg, premium, premium_type in zip(package, raw_overrides, premium_types)
        ]
        if not any(value is not None for value in overrides):
            return package
        return [
            replace(leg, premium_override=(None if premium is None else float(premium)))
            for leg, premium in zip(package, overrides)
        ]

    def _resolve_dates(
        self,
        *,
        expiry: Optional[str],
        tail: Optional[str],
        exercise_date: Optional[dt.date],
        underlying_effective_date: Optional[dt.date],
        underlying_maturity_date: Optional[dt.date],
    ) -> tuple[dt.date, dt.date, dt.date]:
        context = self.common_kwargs["context"]
        curve = context.curve

        if exercise_date and underlying_effective_date and underlying_maturity_date:
            return to_date(exercise_date), to_date(underlying_effective_date), to_date(underlying_maturity_date)

        if not expiry or not tail:
            raise ValueError(
                "IRSwaption structure requires either explicit dates "
                "(exercise_date, underlying_effective_date, underlying_maturity_date) or tenor mode (expiry, tail)."
            )

        trade_date = context.as_of_date
        ex_dt = curve.calendar_advance(trade_date, str(expiry))
        midcurve_fwd, swap_tenor = parse_midcurve_tail(str(tail))
        eff_dt = curve.calendar_advance(ex_dt, str(midcurve_fwd)) if midcurve_fwd else ex_dt
        mat_dt = curve.calendar_advance(eff_dt, str(swap_tenor))
        return to_date(ex_dt), to_date(eff_dt), to_date(mat_dt)

    def _strike_inputs(
        self,
        *,
        option_type: str,
        exercise_date: dt.date,
        underlying_effective_date: dt.date,
        underlying_maturity_date: dt.date,
        notional: float,
    ) -> tuple[float, float, float]:
        context = self.common_kwargs["context"]
        temp = IRSwaptionPricable(
            option_type=option_type,
            exercise_date=exercise_date,
            underlying_effective_date=underlying_effective_date,
            underlying_maturity_date=underlying_maturity_date,
            strike=0.0,
            notional=notional,
        )
        atmf = float(leg_forward_rate(context, temp))
        temp_atmf = IRSwaptionPricable(
            option_type=option_type,
            exercise_date=exercise_date,
            underlying_effective_date=underlying_effective_date,
            underlying_maturity_date=underlying_maturity_date,
            strike=atmf,
            notional=notional,
        )
        vol = float(leg_model_vol(context, temp_atmf, strike=atmf))
        tte = float(leg_tte_years(context, temp_atmf))
        return atmf, vol, tte

    def _resolve_strike(
        self,
        strike: float | str | None,
        *,
        option_type: str,
        exercise_date: dt.date,
        underlying_effective_date: dt.date,
        underlying_maturity_date: dt.date,
        notional: float,
    ) -> float:
        atmf, vol, tte = self._strike_inputs(
            option_type=option_type,
            exercise_date=exercise_date,
            underlying_effective_date=underlying_effective_date,
            underlying_maturity_date=underlying_maturity_date,
            notional=notional,
        )
        return resolve_strike_spec(
            strike_spec=strike,
            atmf=atmf,
            atms=atmf,
            option_type=option_type,
            vol_normal=vol,
            tte=tte,
            forward=atmf,
        )

    def _leg_npv(self, *, option_type: str, strike: float, dates: tuple[dt.date, dt.date, dt.date], notional: float) -> float:
        context = self.common_kwargs["context"]
        leg = IRSwaptionPricable(
            option_type=option_type,
            exercise_date=dates[0],
            underlying_effective_date=dates[1],
            underlying_maturity_date=dates[2],
            strike=float(strike),
            notional=abs(float(notional)),
        )
        return float(leg_spot_npv(context, leg))

    def _solve_costless(
        self,
        *,
        func: Callable[[float], float],
        bracket: tuple[float, float],
        guess: float,
        structure_name: str,
        tenor_hint: str,
    ) -> float:
        lo, hi = bracket
        try:
            flo = func(lo)
            fhi = func(hi)
            if flo == 0.0:
                return lo
            if fhi == 0.0:
                return hi
            if flo * fhi < 0.0:
                return float(brentq(func, lo, hi, maxiter=200))
        except Exception:
            pass
        try:
            return float(newton(func, x0=guess, maxiter=100))
        except Exception as exc:
            raise ValueError(
                f"Costless solve failed for structure={structure_name}, tenor={tenor_hint}, "
                f"initial_guess={guess}, bracket=({lo}, {hi})."
            ) from exc

    @staticmethod
    def _apply_side(structure: IRSwaptionStructure, side: str | None) -> list[float]:
        side_sign = parse_side(side)
        base = _STRUCTURE_RISK_WEIGHTS[structure]
        return [side_sign * float(x) for x in base]

    @staticmethod
    def _make_leg(
        *,
        option_type: str,
        strike: float,
        dates: tuple[dt.date, dt.date, dt.date],
        notional: float,
        label: Optional[str] = None,
    ) -> IRSwaptionPricable:
        return IRSwaptionPricable(
            option_type=option_type,
            exercise_date=dates[0],
            underlying_effective_date=dates[1],
            underlying_maturity_date=dates[2],
            strike=float(strike),
            notional=abs(float(notional)),
            label=label,
        )

    def _build_receiver(self, *, side: str = "buy", **kwargs: Any) -> tuple[list[IRSwaptionPricable], list[float]]:
        n = self._default_notional(kwargs.get("notional"), kwargs.get("vega"))
        dates = self._resolve_dates(
            expiry=kwargs.get("expiry"),
            tail=kwargs.get("tail"),
            exercise_date=kwargs.get("exercise_date"),
            underlying_effective_date=kwargs.get("underlying_effective_date"),
            underlying_maturity_date=kwargs.get("underlying_maturity_date"),
        )
        k = self._resolve_strike(kwargs.get("strike", "ATMF"), option_type="receiver", exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        return [self._make_leg(option_type="receiver", strike=k, dates=dates, notional=n)], self._apply_side(IRSwaptionStructure.RECEIVER, side)

    def _build_payer(self, *, side: str = "buy", **kwargs: Any) -> tuple[list[IRSwaptionPricable], list[float]]:
        n = self._default_notional(kwargs.get("notional"), kwargs.get("vega"))
        dates = self._resolve_dates(
            expiry=kwargs.get("expiry"),
            tail=kwargs.get("tail"),
            exercise_date=kwargs.get("exercise_date"),
            underlying_effective_date=kwargs.get("underlying_effective_date"),
            underlying_maturity_date=kwargs.get("underlying_maturity_date"),
        )
        k = self._resolve_strike(kwargs.get("strike", "ATMF"), option_type="payer", exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        return [self._make_leg(option_type="payer", strike=k, dates=dates, notional=n)], self._apply_side(IRSwaptionStructure.PAYER, side)

    def _build_straddle(self, *, side: str = "buy", **kwargs: Any) -> tuple[list[IRSwaptionPricable], list[float]]:
        n = self._default_notional(kwargs.get("notional"), kwargs.get("vega"))
        dates = self._resolve_dates(
            expiry=kwargs.get("expiry"),
            tail=kwargs.get("tail"),
            exercise_date=kwargs.get("exercise_date"),
            underlying_effective_date=kwargs.get("underlying_effective_date"),
            underlying_maturity_date=kwargs.get("underlying_maturity_date"),
        )
        k = self._resolve_strike(kwargs.get("strike", "ATMF"), option_type="payer", exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        legs = [
            self._make_leg(option_type="receiver", strike=k, dates=dates, notional=n),
            self._make_leg(option_type="payer", strike=k, dates=dates, notional=n),
        ]
        return legs, self._apply_side(IRSwaptionStructure.STRADDLE, side)

    def _build_strangle(self, *, side: str = "buy", **kwargs: Any) -> tuple[list[IRSwaptionPricable], list[float]]:
        n = self._default_notional(kwargs.get("notional"), kwargs.get("vega"))
        wing_bps = float(kwargs.get("wing_bps", 25.0))
        dates = self._resolve_dates(
            expiry=kwargs.get("expiry"),
            tail=kwargs.get("tail"),
            exercise_date=kwargs.get("exercise_date"),
            underlying_effective_date=kwargs.get("underlying_effective_date"),
            underlying_maturity_date=kwargs.get("underlying_maturity_date"),
        )
        base = self._resolve_strike(kwargs.get("strike", "ATMF"), option_type="payer", exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        rec_k = self._resolve_strike(kwargs.get("receiver_strike", base - wing_bps / 10_000.0), option_type="receiver", exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        pay_k = self._resolve_strike(kwargs.get("payer_strike", base + wing_bps / 10_000.0), option_type="payer", exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        legs = [
            self._make_leg(option_type="receiver", strike=rec_k, dates=dates, notional=n),
            self._make_leg(option_type="payer", strike=pay_k, dates=dates, notional=n),
        ]
        return legs, self._apply_side(IRSwaptionStructure.STRANGLE, side)

    def _build_receiver_spread(self, *, side: str = "buy", **kwargs: Any) -> tuple[list[IRSwaptionPricable], list[float]]:
        n = self._default_notional(kwargs.get("notional"), kwargs.get("vega"))
        spread_bps = float(kwargs.get("spread_bps", 25.0))
        dates = self._resolve_dates(
            expiry=kwargs.get("expiry"),
            tail=kwargs.get("tail"),
            exercise_date=kwargs.get("exercise_date"),
            underlying_effective_date=kwargs.get("underlying_effective_date"),
            underlying_maturity_date=kwargs.get("underlying_maturity_date"),
        )
        low_k = self._resolve_strike(kwargs.get("strike", "ATMF"), option_type="receiver", exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        high_k = self._resolve_strike(kwargs.get("high_strike", low_k + spread_bps / 10_000.0), option_type="receiver", exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        legs = [
            self._make_leg(option_type="receiver", strike=high_k, dates=dates, notional=n),
            self._make_leg(option_type="receiver", strike=low_k, dates=dates, notional=n),
        ]
        return legs, self._apply_side(IRSwaptionStructure.RECEIVER_SPREAD, side)

    def _build_payer_spread(self, *, side: str = "buy", **kwargs: Any) -> tuple[list[IRSwaptionPricable], list[float]]:
        n = self._default_notional(kwargs.get("notional"), kwargs.get("vega"))
        spread_bps = float(kwargs.get("spread_bps", 25.0))
        dates = self._resolve_dates(
            expiry=kwargs.get("expiry"),
            tail=kwargs.get("tail"),
            exercise_date=kwargs.get("exercise_date"),
            underlying_effective_date=kwargs.get("underlying_effective_date"),
            underlying_maturity_date=kwargs.get("underlying_maturity_date"),
        )
        low_k = self._resolve_strike(kwargs.get("strike", "ATMF"), option_type="payer", exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        high_k = self._resolve_strike(kwargs.get("high_strike", low_k + spread_bps / 10_000.0), option_type="payer", exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        legs = [
            self._make_leg(option_type="payer", strike=low_k, dates=dates, notional=n),
            self._make_leg(option_type="payer", strike=high_k, dates=dates, notional=n),
        ]
        return legs, self._apply_side(IRSwaptionStructure.PAYER_SPREAD, side)

    def _build_receiver_fly(self, *, side: str = "buy", **kwargs: Any) -> tuple[list[IRSwaptionPricable], list[float]]:
        return self._build_fly_generic(option_type="receiver", structure=IRSwaptionStructure.RECEIVER_FLY, side=side, **kwargs)

    def _build_payer_fly(self, *, side: str = "buy", **kwargs: Any) -> tuple[list[IRSwaptionPricable], list[float]]:
        return self._build_fly_generic(option_type="payer", structure=IRSwaptionStructure.PAYER_FLY, side=side, **kwargs)

    def _build_fly_generic(
        self,
        *,
        option_type: str,
        structure: IRSwaptionStructure,
        side: str,
        **kwargs: Any,
    ) -> tuple[list[IRSwaptionPricable], list[float]]:
        n = self._default_notional(kwargs.get("notional"), kwargs.get("vega"))
        spread_bps = float(kwargs.get("spread_bps", 25.0))
        dates = self._resolve_dates(
            expiry=kwargs.get("expiry"),
            tail=kwargs.get("tail"),
            exercise_date=kwargs.get("exercise_date"),
            underlying_effective_date=kwargs.get("underlying_effective_date"),
            underlying_maturity_date=kwargs.get("underlying_maturity_date"),
        )
        mid = self._resolve_strike(kwargs.get("strike", "ATMF"), option_type=option_type, exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        low = self._resolve_strike(kwargs.get("low_strike", mid - spread_bps / 10_000.0), option_type=option_type, exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        high = self._resolve_strike(kwargs.get("high_strike", mid + spread_bps / 10_000.0), option_type=option_type, exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        legs = [
            self._make_leg(option_type=option_type, strike=low, dates=dates, notional=n),
            self._make_leg(option_type=option_type, strike=mid, dates=dates, notional=n),
            self._make_leg(option_type=option_type, strike=high, dates=dates, notional=n),
        ]
        return legs, self._apply_side(structure, side)

    def _build_receiver_1x2(self, *, side: str = "buy", **kwargs: Any) -> tuple[list[IRSwaptionPricable], list[float]]:
        return self._build_1x2_generic(option_type="receiver", structure=IRSwaptionStructure.RECEIVER_1x2, side=side, direction=-1.0, **kwargs)

    def _build_payer_1x2(self, *, side: str = "buy", **kwargs: Any) -> tuple[list[IRSwaptionPricable], list[float]]:
        return self._build_1x2_generic(option_type="payer", structure=IRSwaptionStructure.PAYER_1x2, side=side, direction=1.0, **kwargs)

    def _build_1x2_generic(
        self,
        *,
        option_type: str,
        structure: IRSwaptionStructure,
        side: str,
        direction: float,
        **kwargs: Any,
    ) -> tuple[list[IRSwaptionPricable], list[float]]:
        n = self._default_notional(kwargs.get("notional"), kwargs.get("vega"))
        wing_bps = float(kwargs.get("wing_bps", 25.0))
        costless = bool(kwargs.get("costless", True))
        dates = self._resolve_dates(
            expiry=kwargs.get("expiry"),
            tail=kwargs.get("tail"),
            exercise_date=kwargs.get("exercise_date"),
            underlying_effective_date=kwargs.get("underlying_effective_date"),
            underlying_maturity_date=kwargs.get("underlying_maturity_date"),
        )
        base = self._resolve_strike(kwargs.get("strike", "ATMF"), option_type=option_type, exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)

        wing_strike = kwargs.get("wing_strike")
        if wing_strike is None:
            guess = base + direction * wing_bps / 10_000.0
            if costless:
                # ``base`` is invariant throughout the root solve.  Repricing
                # it inside every objective evaluation used to rebuild the same
                # swaption 10s of times for one date/tenor.
                base_npv = self._leg_npv(
                    option_type=option_type,
                    strike=base,
                    dates=dates,
                    notional=1.0,
                )

                def objective(k: float) -> float:
                    return base_npv - 2.0 * self._leg_npv(
                        option_type=option_type, strike=k, dates=dates, notional=1.0
                    )

                wing = self._solve_costless(
                    func=objective,
                    bracket=(guess - abs(wing_bps) / 10_000.0, guess + abs(wing_bps) / 10_000.0),
                    guess=guess,
                    structure_name=structure.name,
                    tenor_hint=f"{kwargs.get('expiry') or dates[0]}x{kwargs.get('tail') or dates[2]}",
                )
            else:
                wing = guess
        else:
            wing = self._resolve_strike(wing_strike, option_type=option_type, exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)

        legs = [
            self._make_leg(option_type=option_type, strike=base, dates=dates, notional=n),
            self._make_leg(option_type=option_type, strike=wing, dates=dates, notional=n),
        ]
        return legs, self._apply_side(structure, side)

    def _build_receiver_ladder(self, *, side: str = "buy", **kwargs: Any) -> tuple[list[IRSwaptionPricable], list[float]]:
        return self._build_ladder_generic(option_type="receiver", structure=IRSwaptionStructure.RECEIVER_LADDER, side=side, direction=-1.0, **kwargs)

    def _build_payer_ladder(self, *, side: str = "buy", **kwargs: Any) -> tuple[list[IRSwaptionPricable], list[float]]:
        return self._build_ladder_generic(option_type="payer", structure=IRSwaptionStructure.PAYER_LADDER, side=side, direction=1.0, **kwargs)

    def _build_ladder_generic(
        self,
        *,
        option_type: str,
        structure: IRSwaptionStructure,
        side: str,
        direction: float,
        **kwargs: Any,
    ) -> tuple[list[IRSwaptionPricable], list[float]]:
        n = self._default_notional(kwargs.get("notional"), kwargs.get("vega"))
        wing_bps = float(kwargs.get("wing_bps", 25.0))
        costless = bool(kwargs.get("costless", True))
        dates = self._resolve_dates(
            expiry=kwargs.get("expiry"),
            tail=kwargs.get("tail"),
            exercise_date=kwargs.get("exercise_date"),
            underlying_effective_date=kwargs.get("underlying_effective_date"),
            underlying_maturity_date=kwargs.get("underlying_maturity_date"),
        )
        base = self._resolve_strike(kwargs.get("strike", "ATMF"), option_type=option_type, exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        mid_guess = base + direction * wing_bps / 10_000.0

        if costless:
            # Like the 1x2 above, the ATM leg is constant while the solver
            # moves only the two OTM strikes.  Calculate it once per package.
            base_npv = self._leg_npv(
                option_type=option_type,
                strike=base,
                dates=dates,
                notional=1.0,
            )

            def objective(mid_k: float) -> float:
                wing_k = mid_k + direction * wing_bps / 10_000.0
                return base_npv - self._leg_npv(
                    option_type=option_type, strike=mid_k, dates=dates, notional=1.0
                ) - self._leg_npv(option_type=option_type, strike=wing_k, dates=dates, notional=1.0)

            mid = self._solve_costless(
                func=objective,
                bracket=(mid_guess - abs(wing_bps) / 10_000.0, mid_guess + abs(wing_bps) / 10_000.0),
                guess=mid_guess,
                structure_name=structure.name,
                tenor_hint=f"{kwargs.get('expiry') or dates[0]}x{kwargs.get('tail') or dates[2]}",
            )
        else:
            mid = mid_guess
        wing = mid + direction * wing_bps / 10_000.0

        legs = [
            self._make_leg(option_type=option_type, strike=base, dates=dates, notional=n),
            self._make_leg(option_type=option_type, strike=mid, dates=dates, notional=n),
            self._make_leg(option_type=option_type, strike=wing, dates=dates, notional=n),
        ]
        return legs, self._apply_side(structure, side)

    def _build_risk_reversal(self, *, side: str = "buy", **kwargs: Any) -> tuple[list[IRSwaptionPricable], list[float]]:
        n = self._default_notional(kwargs.get("notional"), kwargs.get("vega"))
        wing_bps = float(kwargs.get("wing_bps", 25.0))
        dates = self._resolve_dates(
            expiry=kwargs.get("expiry"),
            tail=kwargs.get("tail"),
            exercise_date=kwargs.get("exercise_date"),
            underlying_effective_date=kwargs.get("underlying_effective_date"),
            underlying_maturity_date=kwargs.get("underlying_maturity_date"),
        )
        base = self._resolve_strike(kwargs.get("strike", "ATMF"), option_type="payer", exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        payer_k = self._resolve_strike(kwargs.get("payer_strike", base + wing_bps / 10_000.0), option_type="payer", exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        receiver_k = self._resolve_strike(kwargs.get("receiver_strike", base - wing_bps / 10_000.0), option_type="receiver", exercise_date=dates[0], underlying_effective_date=dates[1], underlying_maturity_date=dates[2], notional=n)
        legs = [
            self._make_leg(option_type="payer", strike=payer_k, dates=dates, notional=n),
            self._make_leg(option_type="receiver", strike=receiver_k, dates=dates, notional=n),
        ]
        return legs, self._apply_side(IRSwaptionStructure.RISK_REVERSAL, side)
