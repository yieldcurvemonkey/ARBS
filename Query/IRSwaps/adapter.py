from __future__ import annotations
from typing import Any, List

from Query.Base._GenericPricable import _GenericPricable
from Query.Base.product_adapter import ProductAdapter, register_product
from Query.IRSwaps.IRSwapStructure import IRSwapStructureFunctionMap
from Query.IRSwaps.IRSwapValue import IRSwapValueFunctionMap


class IRSProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        # For IRS you’ve been passing a curve wrapper here (QL/RL curve impl works)
        return IRSwapStructureFunctionMap(curve=pricer_or_curve)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        return IRSwapValueFunctionMap(curve=pricer_or_curve, package=package, risk_weights=risk_weights)


# Register on import
register_product("IRS", IRSProductAdapter)
