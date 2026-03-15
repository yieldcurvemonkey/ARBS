from __future__ import annotations

import math
from enum import Enum, auto
from typing import Any, Callable, Dict, List

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.FXForwards._FXForwardGenericPricer import _FXForwardGenericPricer
from Query.FXForwards.backends.rateslib.RLFXForwardPricer import RLFXForwardPricable


class FXForwardValue(Enum):
    FORWARD_RATE = auto()
    POINTS_RAW = auto()
    POINTS_DECIMAL = auto()
    SPOT = auto()
    BASIS_BPS = auto()


class FXForwardValueFunctionMap(BaseValueFunctionMap[FXForwardValue, float]):
    def __init__(
        self,
        pricer: Dict[str, _FXForwardGenericPricer],
        package: List[RLFXForwardPricable],
        risk_weights: List[float],
    ):
        super().__init__(FXForwardValue, package=package, risk_weights=risk_weights, pricer=pricer)

    def _create_map(self) -> Dict[FXForwardValue, Callable[..., float]]:
        return {
            FXForwardValue.FORWARD_RATE: self._forward_rate,
            FXForwardValue.POINTS_RAW: self._points_raw,
            FXForwardValue.POINTS_DECIMAL: self._points_decimal,
            FXForwardValue.SPOT: self._spot,
            FXForwardValue.BASIS_BPS: self._basis_bps,
        }

    @staticmethod
    def _sum_field(package: List[RLFXForwardPricable], risk_weights: List[float], field: str) -> float:
        total = 0.0
        for rw, leg in zip(risk_weights, package):
            value = getattr(leg, field)()
            total += float(rw) * float("nan" if value is None else value)
        return float(total)

    def _forward_rate(self, **kwargs: Any) -> float:
        return self._sum_field(kwargs["package"], kwargs["risk_weights"], "forward_rate")

    def _points_raw(self, **kwargs: Any) -> float:
        return self._sum_field(kwargs["package"], kwargs["risk_weights"], "points_raw")

    def _points_decimal(self, **kwargs: Any) -> float:
        return self._sum_field(kwargs["package"], kwargs["risk_weights"], "points_decimal")

    def _spot(self, **kwargs: Any) -> float:
        return self._sum_field(kwargs["package"], kwargs["risk_weights"], "spot")

    def _basis_bps(self, **kwargs: Any) -> float:
        result = self._sum_field(kwargs["package"], kwargs["risk_weights"], "basis_bps")
        return result if math.isfinite(result) else float("nan")
