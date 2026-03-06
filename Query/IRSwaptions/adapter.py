from __future__ import annotations

from typing import Any, List

from Query.Base._GenericPricable import _GenericPricable
from Query.Base.product_adapter import ProductAdapter, register_product
from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructureFunctionMap
from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValueFunctionMap
from Query.IRSwaptions.pricer import IRSwaptionPricable


class IRSwaptionProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        return IRSwaptionStructureFunctionMap(context=pricer_or_curve)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        cast_package = [p for p in package if isinstance(p, IRSwaptionPricable)]
        if len(cast_package) != len(package):
            raise TypeError("IRSwaption value map expects IRSwaptionPricable package entries.")
        return IRSwaptionValueFunctionMap(
            context=pricer_or_curve,
            package=cast_package,
            risk_weights=risk_weights,
        )

    def edit_query(self, *, q, pricer_or_curve):
        _ = pricer_or_curve
        return q


register_product("IRSWAPTION", IRSwaptionProductAdapter)
register_product("IRSWAPTIONS", IRSwaptionProductAdapter)

from BT.position_handler import register_handler
from Query.IRSwaptions.position_handler import IRSwaptionPositionHandler

register_handler("IRSWAPTION", IRSwaptionPositionHandler)
register_handler("IRSWAPTIONS", IRSwaptionPositionHandler)

