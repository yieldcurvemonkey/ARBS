"""
Product filtering utilities for SDR data.

This module re-exports product filters for backward compatibility.
New code should import directly from the currency-specific modules
(e.g., SDRUtils.products.usd.filters).
"""

# Re-export USD filters for backward compatibility
from SDRUtils.products._swaps.filters import (
    new_usd_swap_trades,
    usd_swap_trades,
    is_usd_swap,
    new_sofr_swap_trades,
    is_sofr_swap,
    sofr_swap_trades,
    sofr_swaption_trades,
    sofr_cap_floor_trades,
    SOFR_UNDERLIER_NAMES,
    SOFR_FISN_VALUES,
    USD_SWAP_FISN_VALUES,
)

__all__ = [
    "new_usd_swap_trades",
    "usd_swap_trades",
    "is_usd_swap",
    "new_sofr_swap_trades",
    "sofr_swap_trades",
    "is_sofr_swap",
    "sofr_swaption_trades",
    "sofr_cap_floor_trades",
    "SOFR_UNDERLIER_NAMES",
    "SOFR_FISN_VALUES",
    "USD_SWAP_FISN_VALUES",
]
