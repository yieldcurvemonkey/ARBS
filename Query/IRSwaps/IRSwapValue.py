import math
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

    # TODO
    # MMSS = auto()
    # ASW = auto()


_swap_structure_sign_mapper = {
    IRSwapStructure.OUTRIGHT: lambda rws: [abs(rws[0])],
    IRSwapStructure.CURVE: lambda rws: [-1 * abs(rws[0]), abs(rws[1])],
    IRSwapStructure.FLY: lambda rws: [-1 * abs(rws[0]), abs(rws[1]), -1 * abs(rws[2])],
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
        }

    def _rate(self, **kwargs: Any) -> float:
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
        return sum(kwargs["risk_weights"][i] * curve.roll_bps_running(s) for i, s in enumerate(kwargs["package"]))

    def _carry_and_roll_bps_running(self, **kwargs: Any) -> float:
        assert "horizon" in kwargs, 'Expecting an "horizon" with type str | ql.Period in args e.g. `ql.Period("1M")`'
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(kwargs["risk_weights"][i] * curve.carry_and_roll_bps_running(s, kwargs["horizon"]) for i, s in enumerate(kwargs["package"]))
