"""
Product Classifier Base Class.

Defines the abstract interface for product classification.
"""

from abc import ABC, abstractmethod
from typing import Literal

import pandas as pd


ProductTypeLiteral = Literal[
    "OIS_SWAP",
    "SWAPTION_CALL",
    "SWAPTION_PUT",
    "CAP",
    "FLOOR",
    "BASIS_SWAP",
    "FRA",
    "UNKNOWN",
]


class ProductClassifier(ABC):
    """
    Abstract base class for product classifiers.

    To implement a new product classifier:
    1. Subclass ProductClassifier
    2. Set the product_type class attribute
    3. Implement the matches() method
    4. Optionally set priority (lower = higher priority)
    5. Register with ProductRegistry

    Example:
        class MyProductClassifier(ProductClassifier):
            product_type = "MY_PRODUCT"
            priority = 50

            def matches(self, row: pd.Series) -> bool:
                return "PATTERN" in str(row.get("UPI FISN", ""))
    """

    # Class attributes to be overridden
    product_type: ProductTypeLiteral = "UNKNOWN"
    priority: int = 100  # Lower number = higher priority

    @abstractmethod
    def matches(self, row: pd.Series) -> bool:
        """
        Check if a trade row matches this product type.

        Args:
            row: A pandas Series representing a single SDR trade row

        Returns:
            True if this classifier matches the trade
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(product_type={self.product_type}, priority={self.priority})"
