from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Generic, Any

from Query.Base._GenericPricable import _GP


class _GenericPricer(ABC, Generic[_GP]):
    @abstractmethod
    def npv(self, instrument: _GP, /, **kwargs: Any) -> float: ...

    @abstractmethod
    def build_pricable(self, /, **kwargs: Any) -> _GP: ...