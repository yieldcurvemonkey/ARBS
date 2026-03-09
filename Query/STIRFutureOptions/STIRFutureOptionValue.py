from __future__ import annotations

from enum import Enum, auto
from typing import Any, Callable, Dict, Iterable, Tuple

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.STIRFutureOptions._STIRFutureOptionGenericPricable import _STIRFutureOptionGenericPricable
from Query.STIRFutureOptions._STIRFutureOptionGenericPricer import _STIRFutureOptionGenericPricer
from Query.STIRFutureOptions._risk import (
    dollar_dv01,
    dollar_gamma_01,
    dollar_vega_01,
    option_quantity,
    resolve_pricer_for_leg,
)


class STIRFutureOptionValue(Enum):
    PRICE = auto()
    NPV = auto()
    DV01 = auto()
    DELTA = auto()
    GAMMA = auto()
    GAMMA_01 = auto()
    VEGA = auto()
    VEGA_01 = auto()
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
            STIRFutureOptionValue.DV01: self._dv01,
            STIRFutureOptionValue.DELTA: self._delta,
            STIRFutureOptionValue.GAMMA: self._gamma,
            STIRFutureOptionValue.GAMMA_01: self._gamma_01,
            STIRFutureOptionValue.VEGA: self._vega,
            STIRFutureOptionValue.VEGA_01: self._vega_01,
            STIRFutureOptionValue.THETA: self._theta,
            STIRFutureOptionValue.IV_NORMAL_BPS: self._iv_normal_bps,
        }

    @staticmethod
    def _iter_components(
        *,
        pricer: Dict[str, _STIRFutureOptionGenericPricer],
        package: list[_STIRFutureOptionGenericPricable],
        risk_weights: list[float],
        **_: Any,
    ) -> Iterable[Tuple[float, _STIRFutureOptionGenericPricer, _STIRFutureOptionGenericPricable, float]]:
        pricers = pricer
        package = package
        risk_weights = risk_weights
        for idx, (rw, leg) in enumerate(zip(risk_weights, package)):
            pricer = resolve_pricer_for_leg(pricers, leg, index=idx)
            qty = float(option_quantity(leg))
            yield float(rw), pricer, leg, qty

    def _price(self, **kwargs: Any) -> float:
        return sum(rw * pr.price() for rw, pr, _, _ in self._iter_components(**kwargs))

    def _npv(self, **kwargs: Any) -> float:
        return sum(rw * pr.npv(pk) for rw, pr, pk, _ in self._iter_components(**kwargs))

    def _dv01(self, **kwargs: Any) -> float:
        return sum(rw * qty * dollar_dv01(pr) for rw, pr, _, qty in self._iter_components(**kwargs))

    def _delta(self, **kwargs: Any) -> float:
        return sum(rw * qty * pr.delta() for rw, pr, _, qty in self._iter_components(**kwargs))

    def _gamma(self, **kwargs: Any) -> float:
        return sum(rw * qty * pr.gamma() for rw, pr, _, qty in self._iter_components(**kwargs))

    def _gamma_01(self, **kwargs: Any) -> float:
        return sum(rw * qty * dollar_gamma_01(pr) for rw, pr, _, qty in self._iter_components(**kwargs))

    def _vega(self, **kwargs: Any) -> float:
        return sum(rw * qty * pr.vega() for rw, pr, _, qty in self._iter_components(**kwargs))

    def _vega_01(self, **kwargs: Any) -> float:
        return sum(rw * qty * dollar_vega_01(pr) for rw, pr, _, qty in self._iter_components(**kwargs))

    def _theta(self, **kwargs: Any) -> float:
        return sum(rw * qty * pr.theta() for rw, pr, _, qty in self._iter_components(**kwargs))

    def _iv_normal_bps(self, **kwargs: Any) -> float:
        return sum(rw * pr.iv_normal_bps() for rw, pr, _, _ in self._iter_components(**kwargs))
