from __future__ import annotations

from enum import Enum, auto
from typing import Any, Callable, Dict, List

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.USTFutures._USTFutureGenericPricable import _USTFutureGenericPricable
from Query.USTFutures._USTFutureGenericPricer import _USTFutureGenericPricer
from Query.USTFutures.USTFutureStructure import USTFutureStructure


class USTFutureValue(Enum):
    PRICE = auto()
    YIELD = auto()
    PV01 = auto()
    DV01 = auto()


_ust_structure_sign_mapper = {
    USTFutureStructure.OUTRIGHT: lambda rws: rws,
    USTFutureStructure.CURVE: lambda rws: rws,
    USTFutureStructure.SPREAD: lambda rws: rws,
    USTFutureStructure.FLY: lambda rws: rws,
    USTFutureStructure.WEIGHTED_FLY: lambda rws: rws,
}

_ust_structure_legs_mapper = {
    1: (USTFutureStructure.OUTRIGHT, 1),
    2: (USTFutureStructure.CURVE, 100),
    3: (USTFutureStructure.FLY, 100),
}


def calc_spread_yield(
    pricer: Dict[str, _USTFutureGenericPricer],
    package: List[_USTFutureGenericPricable],
    risk_weights: List[float],
) -> float:
    risk_weights = _ust_structure_sign_mapper[_ust_structure_legs_mapper[len(package)][0]](risk_weights)
    return sum([risk_weights[i] * pr.yield_to_maturity(pk) for i, (pr, pk) in enumerate(zip(pricer.values(), package))])


class USTFutureValueFunctionMap(BaseValueFunctionMap[USTFutureValue, float]):
    def __init__(
        self,
        pricer: Dict[str, _USTFutureGenericPricer],
        package: List[_USTFutureGenericPricable],
        risk_weights: List[float],
    ):
        super().__init__(USTFutureValue, package=package, risk_weights=risk_weights, pricer=pricer)

    def _create_map(self) -> Dict[USTFutureValue, Callable[..., float]]:
        return {
            USTFutureValue.PRICE: self._price,
            USTFutureValue.YIELD: self._yield,
            USTFutureValue.PV01: self._pv01,
            USTFutureValue.DV01: self._dv01,
        }

    def _price(self, **kwargs: Any) -> float:
        return sum(rw * pr.price(pk) for rw, pr, pk in zip(kwargs["risk_weights"], kwargs["pricer"].values(), kwargs["package"]))

    def _yield(self, **kwargs: Any) -> float:
        return calc_spread_yield(kwargs["pricer"], kwargs["package"], kwargs["risk_weights"]) * _ust_structure_legs_mapper[len(kwargs["package"])][1]

    def _pv01(self, **kwargs: Any) -> float:
        return sum(pr.pv01(pk) for pr, pk in zip(kwargs["pricer"].values(), kwargs["package"]))

    def _dv01(self, **kwargs: Any) -> float:
        return sum(pr.dv01(pk) for pr, pk in zip(kwargs["pricer"].values(), kwargs["package"]))
