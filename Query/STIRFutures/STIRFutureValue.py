from __future__ import annotations

from enum import Enum, auto
from typing import Any, Callable, Dict, List

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.STIRFutures._STIRFutureGenericPricable import _STIRFutureGenericPricable
from Query.STIRFutures._STIRFutureGenericPricer import _STIRFutureGenericPricer 
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure


class STIRFutureValue(Enum):
    RATE = auto()
    NPV = auto()
    PRICE = auto()
    PV01 = auto()
    DV01 = auto()


_stir_structure_sign_mapper = {
    STIRFutureStructure.OUTRIGHT: lambda rws: rws,
    STIRFutureStructure.CURVE: lambda rws: rws,
    STIRFutureStructure.BASIS: lambda rws: rws,
    STIRFutureStructure.FLY: lambda rws: rws,
}

_stir_structure_legs_mapper = {
    1: (STIRFutureStructure.OUTRIGHT, 1),
    2: (STIRFutureStructure.CURVE, 100),
    2: (STIRFutureStructure.BASIS, 100),
    3: (STIRFutureStructure.FLY, 100),
}


def calc_spread_rate(
    pricer: Dict[str, _STIRFutureGenericPricer],
    package: List[_STIRFutureGenericPricable],
    risk_weights: List[float],
) -> float:
    risk_weights = _stir_structure_sign_mapper[_stir_structure_legs_mapper[len(package)][0]](risk_weights)
    # Using fair_rate() from the pricer, analogous to ytm() in FRB
    return sum([risk_weights[i] * pr.fair_rate(pk) for i, (pr, pk) in enumerate(zip(pricer.values(), package))])


class STIRFutureValueFunctionMap(BaseValueFunctionMap[STIRFutureValue, float]):
    def __init__(
        self,
        pricer: Dict[str, _STIRFutureGenericPricer],
        package: List[_STIRFutureGenericPricable],
        risk_weights: List[float],
    ):
        super().__init__(STIRFutureValue, package=package, risk_weights=risk_weights, pricer=pricer)

    def _create_map(self) -> Dict[STIRFutureValue, Callable[..., float]]:
        return {
            STIRFutureValue.RATE: self._rate,
            STIRFutureValue.NPV: self._npv,
            STIRFutureValue.PRICE: self._price,
            STIRFutureValue.PV01: self._pv01,
            STIRFutureValue.DV01: self._dv01,
        }

    def _rate(self, **kwargs: Any) -> float:
        # Returns rate, scaled by structure factor (e.g. 100 for spreads/flys to get bps)
        return calc_spread_rate(kwargs["pricer"], kwargs["package"], kwargs["risk_weights"]) * _stir_structure_legs_mapper[len(kwargs["package"])][1]

    def _npv(self, **kwargs: Any) -> float:
        # return sum(pr.npv(pk) for pr, pk in zip(kwargs["pricer"].values(), kwargs["package"]))
        return sum(rw * pr.npv() for rw, pr in zip(kwargs["risk_weights"], kwargs["pricer"].values()))

    def _pv01(self, **kwargs: Any) -> float:
        return sum(pr.pv01(stirf=pk) for pr, pk in zip(kwargs["pricer"].values(), kwargs["package"]))

    def _dv01(self, **kwargs: Any) -> float:
        return self._pv01(**kwargs)

    def _price(self, **kwargs: Any) -> float:
        # Unlike bonds where sum(clean_price) implies portfolio cost, 
        # STIR structures (spreads) are quoted as Price A - Price B.
        # We use risk_weights to handle the direction (Buy A / Sell B).
        # return sum(rw * pr.price(pk) for rw, pr, pk in zip(kwargs["risk_weights"], kwargs["pricer"].values(), kwargs["package"]))
        return sum(rw * pr.price() for rw, pr in zip(kwargs["risk_weights"], kwargs["pricer"].values()))
