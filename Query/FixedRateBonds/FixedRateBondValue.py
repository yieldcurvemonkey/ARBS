from enum import Enum, auto
from typing import Any, Callable, Dict, List

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
from Query.FixedRateBonds._FixedRateBondGenericPricable import _FixedRateBondGenericPricable


class FixedRateBondValue(Enum):
    YTM = auto()
    CLEAN_PRICE = auto()
    DIRTY_PRICE = auto()
    NPV = auto()
    PV01 = auto()
    DV01 = auto()
    MOD_DURATION = auto()
    CONVEXITY = auto()


# _frb_structure_sign_mapper = {
#     FixedRateBondStructure.OUTRIGHT: lambda rws: [abs(rws[0])],
#     FixedRateBondStructure.CURVE: lambda rws: [-1 * abs(rws[0]), abs(rws[1])],
#     FixedRateBondStructure.FLY: lambda rws: [-1 * abs(rws[0]), abs(rws[1]), -1 * abs(rws[2])],
# }
_frb_structure_sign_mapper = {
    FixedRateBondStructure.OUTRIGHT: lambda rws: rws,
    FixedRateBondStructure.CURVE: lambda rws: rws,
    FixedRateBondStructure.FLY: lambda rws: rws,
}
_frb_structure_legs_mapper = {
    1: (FixedRateBondStructure.OUTRIGHT, 1),
    2: (FixedRateBondStructure.CURVE, 100),
    3: (FixedRateBondStructure.FLY, 100),
}


def calc_spread_rate(
    pricer: Dict[str, _FixedRateBondGenericPricer],
    package: List[_FixedRateBondGenericPricable],
    risk_weights: List[float],
) -> float:
    risk_weights = _frb_structure_sign_mapper[_frb_structure_legs_mapper[len(package)][0]](risk_weights)
    return sum([risk_weights[i] * abs(pr.ytm()) for i, pr in enumerate(pricer.values())])


class FixedRateBondValueFunctionMap(BaseValueFunctionMap[FixedRateBondValue, float]):
    def __init__(
        self,
        pricer: Dict[str, _FixedRateBondGenericPricer],
        package: List[_FixedRateBondGenericPricable],
        risk_weights: List[float],
    ):
        super().__init__(FixedRateBondValue, package=package, risk_weights=risk_weights, pricer=pricer)

    def _create_map(self) -> Dict[FixedRateBondValue, Callable[..., float]]:
        return {
            FixedRateBondValue.YTM: self._ytm,
            FixedRateBondValue.CLEAN_PRICE: self._clean_price,
            FixedRateBondValue.DIRTY_PRICE: self._dirty_price,
            FixedRateBondValue.NPV: self._npv,
            FixedRateBondValue.PV01: self._pv01,
            FixedRateBondValue.DV01: self._dv01,
            FixedRateBondValue.MOD_DURATION: self._mod_duration,
            # FixedRateBondValue.CONVEXITY: self._convexity,
        }

    def _ytm(self, **kwargs: Any) -> float:
        return calc_spread_rate(kwargs["pricer"], kwargs["package"], kwargs["risk_weights"]) * _frb_structure_legs_mapper[len(kwargs["package"])][1]

    def _clean_price(self, **kwargs: Any) -> float:
        return sum(pr.clean_price() for pr, pk in zip(kwargs["pricer"].values(), kwargs["package"]))

    def _dirty_price(self, **kwargs: Any) -> float:
        return sum(pr.dirty_price() for pr, pk in zip(kwargs["pricer"].values(), kwargs["package"]))

    def _npv(self, **kwargs: Any) -> float:
        return sum(pr.npv(pr.notional(pk)) for pr, pk in zip(kwargs["pricer"].values(), kwargs["package"]))

    def _pv01(self, **kwargs: Any) -> float:
        return sum(pr.pv01(pr.notional(pk)) for pr, pk in zip(kwargs["pricer"].values(), kwargs["package"]))

    def _dv01(self, **kwargs: Any) -> float:
        return self._pv01(**kwargs)

    def _mod_duration(self, **kwargs: Any) -> float:
        return sum([kwargs["risk_weights"][i] * abs(pr.mod_duration()) for i, pr in enumerate(kwargs["pricer"].values())])

    def _convexity(self, **kwargs: Any) -> float:
        return sum([kwargs["risk_weights"][i] * abs(pr.convexity()) for i, pr in enumerate(kwargs["pricer"].values())])
