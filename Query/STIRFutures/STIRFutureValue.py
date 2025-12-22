from __future__ import annotations

from enum import Enum, auto
from typing import Any, Callable, Dict, List

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve


class STIRFutureValue(Enum):
    RATE = auto()
    NPV = auto()
    PV01 = auto()
    DV01 = auto()


class STIRFutureValueFunctionMap(BaseValueFunctionMap[STIRFutureValue, float]):
    def __init__(self, curve: _IRSwapGenericCurve, package: List[Any], risk_weights: List[float]):
        super().__init__(STIRFutureValue, curve=curve, package=package, risk_weights=risk_weights)

    def _create_map(self) -> Dict[STIRFutureValue, Callable[..., float]]:
        return {
            STIRFutureValue.RATE: self._rate,
            STIRFutureValue.NPV: self._npv,
            STIRFutureValue.PV01: self._pv01,
            STIRFutureValue.DV01: self._dv01,
        }

    def _rate(self, **kwargs: Any) -> float:
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(rw * float(inst.rate(curves=curve.handle()).real) for rw, inst in zip(kwargs["risk_weights"], kwargs["package"]))

    def _npv(self, **kwargs: Any) -> float:
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(float(inst.npv(curves=curve.handle()).real) for inst in kwargs["package"])

    def _pv01(self, **kwargs: Any) -> float:
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(float(inst.analytic_delta(curves=curve.handle()).real) for inst in kwargs["package"])

    def _dv01(self, **kwargs: Any) -> float:
        return self._pv01(**kwargs)
