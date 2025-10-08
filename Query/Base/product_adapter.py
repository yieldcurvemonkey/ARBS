# Query/Base/product_adapter.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Tuple, Type

from Query.Base._GenericPricable import _GenericPricable


class ProductAdapter(ABC):
    """
    Pluggable adapter for a product (IRS, Swaption, …).
    Lets the backtester remain product-agnostic.
    """

    @abstractmethod
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        """
        Return the product's StructureFunctionMap (or equivalent) bound to a pricer/curve.
        Must expose:  apply(structure_id, **structure_kwargs) -> (package: List[_GenericPricable], weights: List[float])
        """
        raise NotImplementedError

    @abstractmethod
    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        """
        Return the product's ValueFunctionMap (or equivalent) bound to pricer/curve and package.
        Must expose:  apply(value_id, **kwargs) -> float
        """
        raise NotImplementedError

    @abstractmethod
    def edit_query(self, *, q: Any, pricer_or_curve: Any):
        """
        Optionally normalize/expand the query before building the structure.
        Default: no-op.
        """
        return q


# ---------------- Registry ----------------

_ADAPTERS: Dict[str, Type[ProductAdapter]] = {}


def register_product(product: str, adapter_cls: Type[ProductAdapter]) -> None:
    if not issubclass(adapter_cls, ProductAdapter):
        raise TypeError("adapter_cls must subclass ProductAdapter")
    _ADAPTERS[product] = adapter_cls


def get_adapter(product: str) -> Type[ProductAdapter]:
    try:
        return _ADAPTERS[product]
    except KeyError as e:
        raise KeyError(f"No ProductAdapter registered for product '{product}'. " f"Registered: {sorted(_ADAPTERS)}") from e
