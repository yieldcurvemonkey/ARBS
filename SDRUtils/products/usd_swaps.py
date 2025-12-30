"""
USD SOFR Swaps product module.

DEPRECATED: This module is maintained for backward compatibility.
New code should import from:
- SDRUtils.products.usd.sofr_swaps for swap classification
- SDRUtils.packages.spreadover for UST spread detection

This module re-exports the functions from their new locations.
"""

# Re-export from new locations for backward compatibility
from SDRUtils.products.usd.sofr_swaps import (
    USD_SOFR_SwapProduct,
    classify_sofr_swap_trade,
)

from SDRUtils.packages.spreadover import (
    detect_spreadover_trades_df as detect_ust_mms_trades_df,
)

__all__ = [
    "USD_SOFR_SwapProduct",
    "classify_sofr_swap_trade",
    "detect_ust_mms_trades_df",
]
