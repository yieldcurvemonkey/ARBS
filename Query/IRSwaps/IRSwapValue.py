# ABOUTME: Enumeration of computable interest rate swap metrics and their calculation functions
# ABOUTME: Includes rates, Greeks (DV01, gamma), NPV, carry metrics, and asset swap spreads
import math
import numpy as np
from enum import Enum, auto
from typing import Any, Callable, Dict, List

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve, _IRSwapGenericObject


class IRSwapValue(Enum):
    RATE = auto()
    PV01 = auto()
    DV01 = auto()
    GAMMA_01 = auto()
    NPV = auto()
    NOTIONAL = auto()
    CARRY_BPS_RUNNING = auto()
    ROLL_BPS_RUNNING = auto()
    CARRY_AND_ROLL_BPS_RUNNING = auto()

    SPREADOVER = auto()
    MMSS = auto()
    PAR_PAR_ASW = auto()
    TRUE_ASW = auto()
    PROCEEDS_ASW = auto()
    MARKET_ASW = auto()
    CVX_ADJ = auto()


# _swap_structure_sign_mapper = {
#     IRSwapStructure.OUTRIGHT: lambda rws: [abs(rws[0])],
#     IRSwapStructure.CURVE: lambda rws: [-1 * abs(rws[0]), abs(rws[1])],
#     IRSwapStructure.FLY: lambda rws: [-1 * abs(rws[0]), abs(rws[1]), -1 * abs(rws[2])],
# }
_swap_structure_sign_mapper = {
    IRSwapStructure.OUTRIGHT: lambda rws: rws,
    IRSwapStructure.CURVE: lambda rws: rws,
    IRSwapStructure.FLY: lambda rws: rws,
}

_swap_structure_legs_mapper = {
    1: (IRSwapStructure.OUTRIGHT, 100),
    2: (IRSwapStructure.CURVE, 10_000),
    3: (IRSwapStructure.FLY, 10_000),
}


def calc_spread_rate(
    curve: _IRSwapGenericCurve,
    package: List[_IRSwapGenericObject],
    risk_weights: List[float],
) -> float:
    risk_weights = _swap_structure_sign_mapper[_swap_structure_legs_mapper[len(package)][0]](risk_weights)
    return sum([risk_weights[i] * abs(curve.fair_rate(sw)) for i, sw in enumerate(package)])


class IRSwapValueFunctionMap(BaseValueFunctionMap[IRSwapValue, float]):
    def __init__(
        self,
        curve: _IRSwapGenericCurve,
        package: List[_IRSwapGenericObject],
        risk_weights: List[float],
    ):
        super().__init__(IRSwapValue, package=package, risk_weights=risk_weights, curve=curve)

    def _create_map(self) -> Dict[IRSwapValue, Callable[..., float]]:
        return {
            IRSwapValue.RATE: self._rate,
            IRSwapValue.PV01: self._pv01,
            IRSwapValue.DV01: self._dv01,
            IRSwapValue.GAMMA_01: self._gamma,
            IRSwapValue.NPV: self._npv,
            IRSwapValue.NOTIONAL: self._notional,
            IRSwapValue.CARRY_BPS_RUNNING: self._carry_bps_running,
            IRSwapValue.ROLL_BPS_RUNNING: self._rolldown_bps_running,
            IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING: self._carry_and_roll_bps_running,
            IRSwapValue.CVX_ADJ: self._convexity_adjustment,
        }

    def _rate(self, **kwargs: Any) -> float:
        if "kwargs" in kwargs and "curve" not in kwargs:
            kwargs = kwargs["kwargs"]
        return calc_spread_rate(kwargs["curve"], kwargs["package"], kwargs["risk_weights"]) * _swap_structure_legs_mapper[len(kwargs["package"])][1]

    def _npv(self, **kwargs: Any) -> float:
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(curve.npv(s) for s in kwargs["package"])

    def _pv01(self, **kwargs: Any) -> float:
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(curve.pv01(s) for s in kwargs["package"])

    def _dv01(self, **kwargs: Any) -> float:
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(curve.dv01(s) for s in kwargs["package"])

    def _gamma(self, **kwargs: Any) -> float:
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(curve.gamma(s) for s in kwargs["package"])

    def _notional(self, **kwargs: Any) -> float:
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(math.copysign(curve.notional(s), curve.pv01(s)) for s in kwargs["package"])

    def _carry_bps_running(self, **kwargs: Any) -> float:
        assert "horizon" in kwargs, 'Expecting an "horizon" with type str | ql.Period in args e.g. `ql.Period("1M")`'
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(kwargs["risk_weights"][i] * curve.carry_bps_running(s, kwargs["horizon"]) for i, s in enumerate(kwargs["package"]))

    def _rolldown_bps_running(self, **kwargs: Any) -> float:
        assert "horizon" in kwargs, 'Expecting an "horizon" with type str | ql.Period in args e.g. `ql.Period("1M")`'
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(kwargs["risk_weights"][i] * curve.roll_bps_running(s, kwargs["horizon"]) for i, s in enumerate(kwargs["package"]))

    def _carry_and_roll_bps_running(self, **kwargs: Any) -> float:
        assert "horizon" in kwargs, 'Expecting an "horizon" with type str | ql.Period in args e.g. `ql.Period("1M")`'
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(kwargs["risk_weights"][i] * curve.carry_and_roll_bps_running(s, kwargs["horizon"]) for i, s in enumerate(kwargs["package"]))

    def _convexity_adjustment(self, **kwargs: Any) -> float:
        assert len(kwargs["package"]) == 1, "convexity not supported for packages!"
        assert "sfr" in kwargs, "must pass in SFR object"

        import rateslib as rl
        import numpy as np
        from decimal import Decimal, ROUND_HALF_UP

        assert all(type(p) == rl.STIRFuture for p in kwargs["sfr"]), "convexity only supported for rateslib backend"
        assert all(type(p) == rl.IRS for p in kwargs["package"]), "convexity only supported for rateslib backend"

        import QuantLib as ql
        from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

        # assert ql.IMM.isIMMdate(datetime_to_ql_date(kwargs["curve"].effective_date(kwargs["package"][0]))), "must pass in valid imm swap"
        # assert ql.IMM.isIMMdate(datetime_to_ql_date(kwargs["curve"].maturity_date(kwargs["package"][0]))), "must pass in valid imm swap"

        sfrs: List[rl.STIRFuture] = kwargs["sfr"]
        pack_tick: float = float(kwargs.get("pack_tick", 0.0025))  # ¼ tick
        do_round: bool = bool(kwargs.get("round_pack_to_tick", True))

        def _as_percent(x: float) -> float:
            x = float(x)
            return x * 100.0 if abs(x) < 1.0 else x

        def _safe_fixed_rate_percent(sfr: rl.STIRFuture) -> float:
            fr = getattr(sfr, "fixed_rate", None)
            if fr is None:
                raise ValueError("STIRFuture missing fixed_rate")
            try:
                val = float(getattr(fr, "real", fr))
            except Exception:
                val = float(fr.iloc[-1])
            return _as_percent(val)

        leg_rates_pct = [_safe_fixed_rate_percent(s) for s in sfrs]
        leg_prices = [100.0 - r for r in leg_rates_pct]
        avg_price = float(np.mean(leg_prices))

        if do_round and len(leg_prices) >= 2:
            q = Decimal(str(pack_tick))
            pack_avg_price = float((Decimal(str(avg_price)) / q).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * q)
            pack_avg_price = float(Decimal(str(pack_avg_price)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        else:
            pack_avg_price = avg_price

        implied_fut_yield_pct = 100.0 - pack_avg_price

        curve = kwargs["curve"]
        swap_obj = kwargs["package"][0]
        swap_yield_pct = _as_percent(float(curve.fair_rate(swap_obj)))

        return (implied_fut_yield_pct - swap_yield_pct) * 100.0
