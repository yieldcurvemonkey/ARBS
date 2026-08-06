r"""Registers ``CITIVELO`` with the product-adapter registry.

Import side effects are the registration mechanism in this repo: importing
``Query.CitiVelocity.CitiVeloQuery`` imports this module, which calls
``register_product``. The Query class is imported here only under
``TYPE_CHECKING`` so the two do not form a hard cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List

from Query.Base.product_adapter import ProductAdapter, register_product
from Query.CitiVelocity._CitiVeloLeg import CitiVeloLeg
from Query.CitiVelocity.CitiVeloStructure import CitiVeloStructureFunctionMap
from Query.CitiVelocity.CitiVeloValue import CitiVeloValueFunctionMap

if TYPE_CHECKING:  # pragma: no cover - typing only
    from Query.CitiVelocity.CitiVeloQuery import CitiVeloQuery

__all__ = ["CitiVeloProductAdapter"]


class CitiVeloProductAdapter(ProductAdapter):
    """Binds the structure and value maps to a Citi Velocity pricer."""

    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        return CitiVeloStructureFunctionMap(pricer=pricer_or_curve)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[CitiVeloLeg],
        risk_weights: List[float],
    ) -> Any:
        return CitiVeloValueFunctionMap(
            pricer=pricer_or_curve,
            package=package,
            risk_weights=risk_weights,
        )

    def edit_query(self, *, q: "CitiVeloQuery", pricer_or_curve: Any) -> "CitiVeloQuery":
        """No-op.

        Velocity queries need no hydration against the pricer: a leg spec is
        already complete before a snapshot exists, because the tag grammar does
        not depend on the market. (Contrast ``Query/IRSwaps``, which has to
        resolve CUSIP and on-the-run aliases against the pricer's reference data.)
        """
        return q


register_product("CITIVELO", CitiVeloProductAdapter)
