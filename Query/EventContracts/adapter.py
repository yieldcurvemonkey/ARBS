from __future__ import annotations
from typing import Any, Callable, Dict, List
from Query.Base.product_adapter import ProductAdapter, register_product
from Query.Base.BaseValue import BaseValueFunctionMap
from Query.EventContracts.EventContractValue import EventContractValue


class EventContractValueFunctionMap(BaseValueFunctionMap[EventContractValue, float]):
    def __init__(self, pricer: Any, **common_kwargs: Any):
        self._pricer = pricer
        super().__init__(EventContractValue, pricer=pricer, **common_kwargs)

    def _create_map(self) -> Dict[EventContractValue, Callable[..., float]]:
        return {
            EventContractValue.PRICE: self._price,
            EventContractValue.PROBABILITY: self._probability,
            EventContractValue.VOLUME: self._volume,
            EventContractValue.OPEN_INTEREST: self._open_interest,
        }

    def _price(self, **kw) -> float:
        return kw["pricer"].latest_price() or 0.0

    def _probability(self, **kw) -> float:
        return kw["pricer"].latest_price() or 0.0

    def _volume(self, **kw) -> float:
        return kw["pricer"].latest_volume() or 0.0

    def _open_interest(self, **kw) -> float:
        return kw["pricer"].latest_open_interest() or 0.0


class _EventContractStructureMap:
    def __init__(self, pricer: Any):
        self._pricer = pricer
    def apply(self, structure: Any, **kwargs: Any):
        return [], [1.0]


class EventContractProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        return _EventContractStructureMap(pricer=pricer_or_curve)
    def build_value_map(self, *, pricer_or_curve: Any, package: List[Any], risk_weights: List[float]) -> EventContractValueFunctionMap:
        return EventContractValueFunctionMap(pricer=pricer_or_curve)
    def edit_query(self, *, q: Any, pricer_or_curve: Any):
        return q


register_product("EVENT", EventContractProductAdapter)
