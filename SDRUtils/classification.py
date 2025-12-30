"""
DEPRECATED: This module is maintained for backward compatibility.
Please import from SDRUtils.models or SDRUtils.products instead.

Example:
    # Old way (deprecated)
    from SDRUtils.classification import TradeClassification, classify_product_type

    # New way (recommended)
    from SDRUtils.models import TradeClassification
    from SDRUtils.products import classify_product_type
    # or
    from SDRUtils import TradeClassification, classify_product_type
"""

# Re-export from new locations
from SDRUtils.models.trade_classification import (
    TradeClassification,
    classifications_to_dataframe,
)
from SDRUtils.products.registry import classify_product_type
from SDRUtils.core.utils import to_float as _to_float

__all__ = [
    "TradeClassification",
    "classify_product_type",
    "classifications_to_dataframe",
    "_to_float",
]
