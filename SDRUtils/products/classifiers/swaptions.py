"""
Swaption Product Classifiers.
"""

import pandas as pd

from SDRUtils.products.base import ProductClassifier
from SDRUtils.products.registry import ProductRegistry
from SDRUtils.core.utils import to_float


class SwaptionCallClassifier(ProductClassifier):
    """
    Classifier for Call Swaptions.

    Matches based on:
    - UPI FISN containing "NA/O Call" or "CALL"
    - Strike price present with first exercise date (inferred as call)
    """

    product_type = "SWAPTION_CALL"
    priority = 10  # High priority - check before OIS swap

    def matches(self, row: pd.Series) -> bool:
        upi_fisn = str(row.get("UPI FISN", "")).upper()

        # Explicit call labeling in FISN
        if "NA/O CALL" in upi_fisn or ("CALL" in upi_fisn and "O" in upi_fisn):
            return True

        # Strike-based inference with exercise date
        strike = to_float(row.get("Strike Price"))
        first_exercise = row.get("First exercise date")
        first_exercise = pd.to_datetime(first_exercise, errors="coerce")

        if pd.notna(strike) and strike > 0 and pd.notna(first_exercise):
            # Default to call if exercise date present
            return True

        return False


class SwaptionPutClassifier(ProductClassifier):
    """
    Classifier for Put Swaptions.

    Matches based on:
    - UPI FISN containing "NA/O P Epn" or "PUT" or "O P"
    """

    product_type = "SWAPTION_PUT"
    priority = 10  # High priority - check before OIS swap

    def matches(self, row: pd.Series) -> bool:
        upi_fisn = str(row.get("UPI FISN", "")).upper()

        # Explicit put labeling in FISN
        if "NA/O P EPN" in upi_fisn or "PUT" in upi_fisn or "O P" in upi_fisn:
            return True

        return False


# Auto-register on import
ProductRegistry.register(SwaptionCallClassifier())
ProductRegistry.register(SwaptionPutClassifier())
