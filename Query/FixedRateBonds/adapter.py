# ABOUTME: Product adapter for fixed rate bonds that creates structure and value function maps
# ABOUTME: Registers FRB product type and provides standardized product interface to Query layer
from typing import Any, List

from Query.Base._GenericPricable import _GenericPricable
from Query.Base.product_adapter import ProductAdapter, register_product
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructureFunctionMap
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValueFunctionMap


class FRBProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        return FixedRateBondStructureFunctionMap(pricer=pricer_or_curve)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        return FixedRateBondValueFunctionMap(pricer=pricer_or_curve, package=package, risk_weights=risk_weights)
    
    def edit_query(self, *, q, pricer_or_curve):
        NotImplementedError()

# Register on import
register_product("FRB", FRBProductAdapter)
