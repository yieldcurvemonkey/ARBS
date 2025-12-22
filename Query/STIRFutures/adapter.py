from __future__ import annotations

from typing import Any, List

from Query.Base._GenericPricable import _GenericPricable
from Query.Base.product_adapter import ProductAdapter, register_product
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructureFunctionMap
from Query.STIRFutures.STIRFutureValue import STIRFutureValueFunctionMap


class STIRFutureProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        return STIRFutureStructureFunctionMap(curve=pricer_or_curve)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        return STIRFutureValueFunctionMap(curve=pricer_or_curve, package=package, risk_weights=risk_weights)

    def edit_query(self, *, q, pricer_or_curve):
        return q


register_product("STIRFUTURE", STIRFutureProductAdapter)
