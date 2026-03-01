from __future__ import annotations

from enum import Enum, auto
from typing import Any, Callable, Dict

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.STIRFutureOptions._STIRFutureOptionGenericPricable import _STIRFutureOptionGenericPricable
from Query.STIRFutureOptions._STIRFutureOptionGenericPricer import _STIRFutureOptionGenericPricer


class STIRFutureOptionValue(Enum):
    PRICE = auto()
    NPV = auto()
    DELTA = auto()
    GAMMA = auto()
    VEGA = auto()
    THETA = auto()
    IV_NORMAL_BPS = auto()


class STIRFutureOptionValueFunctionMap(BaseValueFunctionMap[STIRFutureOptionValue, float]):
    def __init__(
        self,
        pricer: Dict[str, _STIRFutureOptionGenericPricer],
        package: list[_STIRFutureOptionGenericPricable],
        risk_weights: list[float],
    ):
        super().__init__(STIRFutureOptionValue, package=package, risk_weights=risk_weights, pricer=pricer)

    def _create_map(self) -> Dict[STIRFutureOptionValue, Callable[..., float]]:
        return {
            STIRFutureOptionValue.PRICE: self._price,
            STIRFutureOptionValue.NPV: self._npv,
            STIRFutureOptionValue.DELTA: self._delta,
            STIRFutureOptionValue.GAMMA: self._gamma,
            STIRFutureOptionValue.VEGA: self._vega,
            STIRFutureOptionValue.THETA: self._theta,
            STIRFutureOptionValue.IV_NORMAL_BPS: self._iv_normal_bps,
        }

    def _price(self, **kwargs: Any) -> float:
        return sum(rw * pr.price() for rw, pr in zip(kwargs["risk_weights"], kwargs["pricer"].values()))

    def _npv(self, **kwargs: Any) -> float:
        return sum(rw * pr.npv(pk) for rw, pr, pk in zip(kwargs["risk_weights"], kwargs["pricer"].values(), kwargs["package"]))

    def _delta(self, **kwargs: Any) -> float:
        return sum(rw * pr.delta() for rw, pr in zip(kwargs["risk_weights"], kwargs["pricer"].values()))

    def _gamma(self, **kwargs: Any) -> float:
        return sum(rw * pr.gamma() for rw, pr in zip(kwargs["risk_weights"], kwargs["pricer"].values()))

    def _vega(self, **kwargs: Any) -> float:
        return sum(rw * pr.vega() for rw, pr in zip(kwargs["risk_weights"], kwargs["pricer"].values()))

    def _theta(self, **kwargs: Any) -> float:
        return sum(rw * pr.theta() for rw, pr in zip(kwargs["risk_weights"], kwargs["pricer"].values()))

    def _iv_normal_bps(self, **kwargs: Any) -> float:
        return sum(rw * pr.iv_normal_bps() for rw, pr in zip(kwargs["risk_weights"], kwargs["pricer"].values()))
