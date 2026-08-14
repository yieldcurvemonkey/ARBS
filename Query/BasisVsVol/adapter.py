"""Product registration for BASISVSVOL.

The adapter is intentionally inert. The framework's structure/value maps exist to decompose a
query into priceable legs and mark them; this product's handler overrides ``build_position``,
``value_position``, ``on_mark`` and ``on_unwind`` outright, because the pair's P&L is a path
quantity (delta-hedged, daily-rebalanced) that a value map cannot express. Registering a stub
keeps the engine's lookup happy without pretending the maps are used.
"""

from __future__ import annotations

from typing import Any, List

from BT.position_handler import register_handler
from Query.Base.product_adapter import ProductAdapter, register_product

from .position_handler import BasisVsVolPositionHandler

PRODUCT = "BASISVSVOL"


class _InertMap:
    def apply(self, *args, **kwargs):
        raise NotImplementedError(
            "BASISVSVOL is priced by its PositionHandler, not by a structure/value map."
        )


class BasisVsVolAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        return _InertMap()

    def build_value_map(self, *, pricer_or_curve: Any, package: List[Any],
                        risk_weights: List[float]) -> Any:
        return _InertMap()

    def edit_query(self, *, q: Any, pricer_or_curve: Any):
        return q


register_product(PRODUCT, BasisVsVolAdapter)
register_handler(PRODUCT, BasisVsVolPositionHandler)
