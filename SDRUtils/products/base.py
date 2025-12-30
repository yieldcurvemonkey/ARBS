"""
Base interface for SDR product modules.

This module defines the abstract base class that all product implementations
must inherit from. Products are organized by currency and product type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import pandas as pd

from SDRUtils.core.classification import TradeClassification


class ProductModule(ABC):
    """
    Base interface for SDR product modules.

    All product implementations (USD SOFR swaps, EUR ESTR swaps, swaptions, etc.)
    must inherit from this class and implement the required methods.

    Attributes:
        name: Unique identifier for the product (e.g., "USD-SOFR-OIS")
        product_type: Type of product (e.g., "OIS_SWAP", "SWAPTION")
        currency: Currency of the product (optional, used for multi-currency products)
    """

    name: str
    product_type: str
    currency: Optional[str] = None

    @abstractmethod
    def classify_trade(
        self, row: pd.Series, trade_id: int, **kwargs: Any
    ) -> TradeClassification:
        """
        Classify a single SDR trade row.

        This is the main entry point for trade classification. Implementations
        should extract all relevant trade characteristics and return a
        TradeClassification object.

        Args:
            row: SDR data row as pandas Series
            trade_id: Unique identifier for the trade
            **kwargs: Additional arguments (e.g., curve for PV01 calculation)

        Returns:
            TradeClassification object with all trade details
        """
        pass

    def classify_product_type(self, row: pd.Series) -> Optional[str]:
        """
        Infer product type from SDR row.

        Optional hook for product-specific type inference. Default returns None.

        Args:
            row: SDR data row

        Returns:
            Product type string or None
        """
        return None

    def validate_row(self, row: pd.Series) -> bool:
        """
        Validate that a row can be classified by this product module.

        Optional hook for input validation. Default returns True.

        Args:
            row: SDR data row

        Returns:
            True if row can be classified, False otherwise
        """
        return True

    def metadata(self) -> Dict[str, Any]:
        """
        Return metadata for discovery and registry documentation.

        Returns:
            Dict with product metadata
        """
        return {
            "name": self.name,
            "product_type": self.product_type,
            "currency": self.currency,
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name})>"
