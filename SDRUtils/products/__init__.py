"""
SDRUtils Products - Product classification framework.

This module provides an extensible framework for classifying SDR trades
by product type. To add a new product:

1. Create a new classifier in products/classifiers/
2. Inherit from ProductClassifier
3. Register it with the ProductRegistry

Example:
    from SDRUtils.products import ProductRegistry, ProductClassifier

    class MyProductClassifier(ProductClassifier):
        product_type = "MY_PRODUCT"

        def matches(self, row: pd.Series) -> bool:
            return "MY_PATTERN" in str(row.get("UPI FISN", ""))

    ProductRegistry.register(MyProductClassifier())
"""

from SDRUtils.products.base import ProductClassifier
from SDRUtils.products.registry import ProductRegistry, classify_product_type

# Import built-in classifiers to trigger registration
from SDRUtils.products import classifiers

__all__ = [
    "ProductClassifier",
    "ProductRegistry",
    "classify_product_type",
]
