# ABOUTME: Abstract base class for all product adapters
# ABOUTME: Defines standard interface for convert() method to transform Query results → Signal format
"""
BaseAdapter - Abstract base class for product adapters

All adapters should inherit from this class and implement
the convert() method to transform Query outputs into Signal inputs.

Input format:
- queries: List of product-specific Query objects
- as_of_date: Valuation date
- market_data_provider: Source of market prices/curves

Output format:
- DataFrame with signal-ready columns (product-specific)
"""

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, List
import pandas as pd


class BaseAdapter(ABC):
    """
    Abstract base class for product adapters.

    Adapters bridge the Query layer and Signals layer by
    converting product-specific query results into DataFrames
    that signals can consume.
    """

    def __init__(self, market_data_provider: Any):
        """
        Initialize adapter with market data provider.

        Args:
            market_data_provider: Source of market prices/curves
        """
        self.mdp = market_data_provider

    @abstractmethod
    def convert(
        self,
        queries: List[Any],
        as_of_date: date,
    ) -> pd.DataFrame:
        """
        Convert query results to signal-ready DataFrame.

        Args:
            queries: List of product queries
            as_of_date: Valuation date

        Returns:
            DataFrame with signal-ready format (product-specific)

        Example:
            >>> queries = [FuturesQuery(contract='SFRZ4'), ...]
            >>> df = adapter.convert(queries, date(2024, 6, 15))
            >>> print(df.columns)
            Index(['contract', 'price', 'next_price', 'roll_date'])
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(mdp={self.mdp})"
