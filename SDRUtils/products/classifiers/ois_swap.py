"""
OIS Swap Product Classifier.
"""

import pandas as pd

from SDRUtils.products.base import ProductClassifier
from SDRUtils.products.registry import ProductRegistry
from SDRUtils.core.utils import to_float


class OISSwapClassifier(ProductClassifier):
    """
    Classifier for OIS (Overnight Indexed Swap) products.

    Matches based on:
    - UPI FISN containing "SWAP" and "OIS"
    - UPI Underlier Name containing "SOFR" and ("COMPOUND" or "OIS")
    - Fixed rate present with no strike (fallback inference)
    """

    product_type = "OIS_SWAP"
    priority = 50  # Medium priority

    def matches(self, row: pd.Series) -> bool:
        upi_fisn = str(row.get("UPI FISN", "")).upper()
        upi_underlier = str(row.get("UPI Underlier Name", "")).upper()
        fixed_rate = to_float(row.get("Fixed rate-Leg 1"))
        strike = to_float(row.get("Strike Price"))

        # Explicit OIS swap in FISN
        if "SWAP" in upi_fisn and "OIS" in upi_fisn:
            return True

        # SOFR compound/OIS in underlier
        if "SOFR" in upi_underlier and ("COMPOUND" in upi_underlier or "OIS" in upi_underlier):
            return True

        # Fixed rate inference (only if no strike)
        if pd.notna(fixed_rate) and fixed_rate > 0:
            if pd.isna(strike) or strike == 0:
                return True

        return False


# Auto-register on import
ProductRegistry.register(OISSwapClassifier())
