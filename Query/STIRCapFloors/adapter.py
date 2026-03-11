from __future__ import annotations

from typing import Any, List

from Query.Base._GenericPricable import _GenericPricable
from Query.Base.product_adapter import ProductAdapter, register_product
from Query.STIRCapFloors.STIRCapFloorStructure import STIRCapFloorStructureFunctionMap
from Query.STIRCapFloors.STIRCapFloorValue import STIRCapFloorValueFunctionMap
from Query.STIRCapFloors.pricer import STIRCapFloorLegPricable


class STIRCapFloorProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        return STIRCapFloorStructureFunctionMap(context=pricer_or_curve)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        cast_package = [p for p in package if isinstance(p, STIRCapFloorLegPricable)]
        if len(cast_package) != len(package):
            raise TypeError("STIR cap/floor value map expects STIRCapFloorLegPricable package entries.")
        return STIRCapFloorValueFunctionMap(
            context=pricer_or_curve,
            package=cast_package,
            risk_weights=risk_weights,
        )

    def edit_query(self, *, q, pricer_or_curve):
        _ = pricer_or_curve
        return q


register_product("STIRCAPFLOOR", STIRCapFloorProductAdapter)
register_product("STIRCAPFLOORS", STIRCapFloorProductAdapter)

from BT.position_handler import register_handler
from Query.STIRCapFloors.position_handler import STIRCapFloorPositionHandler

register_handler("STIRCAPFLOOR", STIRCapFloorPositionHandler)
register_handler("STIRCAPFLOORS", STIRCapFloorPositionHandler)
