"""
Product Registry - Central registry for product classifiers.

Manages registration and lookup of product classifiers.
Provides the main classify_product_type() function.
"""

from typing import Dict, List, Optional, Type

import pandas as pd

from SDRUtils.products.base import ProductClassifier, ProductTypeLiteral


class ProductRegistry:
    """
    Central registry for product classifiers.

    Classifiers are evaluated in priority order (lowest priority number first).
    The first classifier that matches is used.
    """

    _classifiers: List[ProductClassifier] = []
    _by_type: Dict[str, ProductClassifier] = {}

    @classmethod
    def register(cls, classifier: ProductClassifier) -> None:
        """
        Register a product classifier.

        Args:
            classifier: ProductClassifier instance to register
        """
        cls._classifiers.append(classifier)
        cls._by_type[classifier.product_type] = classifier
        # Keep sorted by priority
        cls._classifiers.sort(key=lambda c: c.priority)

    @classmethod
    def unregister(cls, product_type: str) -> Optional[ProductClassifier]:
        """
        Unregister a product classifier by type.

        Args:
            product_type: The product type to unregister

        Returns:
            The removed classifier, or None if not found
        """
        if product_type in cls._by_type:
            classifier = cls._by_type.pop(product_type)
            cls._classifiers = [c for c in cls._classifiers if c.product_type != product_type]
            return classifier
        return None

    @classmethod
    def get(cls, product_type: str) -> Optional[ProductClassifier]:
        """Get a classifier by product type."""
        return cls._by_type.get(product_type)

    @classmethod
    def list_classifiers(cls) -> List[ProductClassifier]:
        """Get list of all registered classifiers in priority order."""
        return list(cls._classifiers)

    @classmethod
    def classify(cls, row: pd.Series) -> ProductTypeLiteral:
        """
        Classify a trade row using registered classifiers.

        Args:
            row: A pandas Series representing a single SDR trade row

        Returns:
            The product type string
        """
        for classifier in cls._classifiers:
            if classifier.matches(row):
                return classifier.product_type
        return "UNKNOWN"

    @classmethod
    def clear(cls) -> None:
        """Clear all registered classifiers."""
        cls._classifiers.clear()
        cls._by_type.clear()


def classify_product_type(row: pd.Series) -> ProductTypeLiteral:
    """
    Classify the product type of an SDR trade row.

    This is the main entry point for product classification.
    Uses all registered classifiers in priority order.

    Args:
        row: A pandas Series representing a single SDR trade row

    Returns:
        The product type string (e.g., "OIS_SWAP", "SWAPTION_CALL", etc.)
    """
    return ProductRegistry.classify(row)
