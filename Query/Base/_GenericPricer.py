from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Generic, Any, Optional

from Query.Base._GenericPricable import _GP


class _GenericPricer(ABC, Generic[_GP]):
    @abstractmethod
    def npv(self, instrument: _GP, /, **kwargs: Any) -> float: ...

    @abstractmethod
    def build_pricable(self, /, **kwargs: Any) -> _GP: ...

    @abstractmethod
    def resolve_pricable(self, priceable: Generic[_GP], risk_weight: Optional[float] = None) -> _GP: ...

    # @abstractmethod
    # def export_pricable_spec(self, priceable: Generic[_GP]) -> Any: ...
