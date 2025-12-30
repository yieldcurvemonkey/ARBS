"""
Cap and Floor Product Classifiers.
"""

import pandas as pd

from SDRUtils.products.base import ProductClassifier
from SDRUtils.products.registry import ProductRegistry


class CapClassifier(ProductClassifier):
    """
    Classifier for Interest Rate Caps.

    Matches based on:
    - UPI FISN containing "CAP"
    """

    product_type = "CAP"
    priority = 10  # High priority

    def matches(self, row: pd.Series) -> bool:
        upi_fisn = str(row.get("UPI FISN", "")).upper()
        return "CAP" in upi_fisn


class FloorClassifier(ProductClassifier):
    """
    Classifier for Interest Rate Floors.

    Matches based on:
    - UPI FISN containing "FLOOR"
    """

    product_type = "FLOOR"
    priority = 10  # High priority

    def matches(self, row: pd.Series) -> bool:
        upi_fisn = str(row.get("UPI FISN", "")).upper()
        return "FLOOR" in upi_fisn


# Auto-register on import
ProductRegistry.register(CapClassifier())
ProductRegistry.register(FloorClassifier())
