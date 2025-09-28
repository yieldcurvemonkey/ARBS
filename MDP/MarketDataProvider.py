from abc import ABC, abstractmethod
from typing import Any, Generic

from Query.Base._GenericPricer import _GenericPricer
from Query.Base._GenericPricable import _GP


class MarketDataProvider(ABC, Generic[_GP]):
    """
    Abstract base class for market data providers that *return a pricer*.

    Each concrete provider turns a request (curve id, timestamp, etc.)
    into a concrete `_GenericPricer[_GP]` instance.
    """

    def __init__(self, source: str, **kwargs: Any):
        self.source = source
        self.config = kwargs

    @abstractmethod
    def get_pricer(self, request: Any) -> _GenericPricer[_GP]:
        """
        Build and return a pricer configured by `request`.
        """
        ...

    # --- Backward-compat alias (can be removed later) ---
    def get_data(self, request: Any) -> _GenericPricer[_GP]:
        """Deprecated: prefer `get_pricer`."""
        return self.get_pricer(request)
