from abc import ABC, abstractmethod
from typing import Any


class MarketDataProvider(ABC):
    """
    Abstract base class for market data providers.

    This class is designed to be data source and product agnostic, providing a
    standardized interface for fetching market data from various sources for
    different financial products.
    """

    def __init__(self, source: str, **kwargs: Any):
        """
        Initializes the data provider with a specific source.

        Args:
            source (str): The identifier for the data source (e.g., 'CME_EOD_LIVE').
            **kwargs: Additional configuration for the data source.
        """
        self.source = source
        self.config = kwargs

    @abstractmethod
    def get_data(self, request: Any) -> Any:
        """
        Abstract method to fetch and return data based on a request.

        The structure of 'request' and the return type are specific
        to the concrete implementation that inherits from this class.
        """
        pass
