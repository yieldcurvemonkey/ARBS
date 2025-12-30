"""
Product filtering utilities for SDR data.

This module re-exports product filters for backward compatibility.
New code should import directly from the currency-specific modules
(e.g., SDRUtils.products.usd.filters).
"""

# Re-export USD filters for backward compatibility
from SDRUtils.products.usd.filters import (
    new_sofr_swap_trades,
    is_sofr_swap,
    sofr_swaption_trades,
    sofr_cap_floor_trades,
    SOFR_UNDERLIER_NAMES,
    SOFR_FISN_VALUES,
)

__all__ = [
    "new_sofr_swap_trades",
    "is_sofr_swap",
    "sofr_swaption_trades",
    "sofr_cap_floor_trades",
    "SOFR_UNDERLIER_NAMES",
    "SOFR_FISN_VALUES",
]
