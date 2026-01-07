"""
USD product modules for SDR analytics.

This package provides product-specific implementations for USD derivatives:
- SOFR OIS Swaps
- Swaptions (placeholder)
- Caps/Floors (placeholder)
"""

from SDRUtils.products.usd.base import USDProductBase
from SDRUtils.products.usd.sofr_swaps import (
    USD_SOFR_SwapProduct,
    classify_sofr_swap_trade,
)
from SDRUtils.products.usd.usd_swaptions import USD_Swaptions
from SDRUtils.registry import registry
from SDRUtils.products._swaps.filters import (
    new_sofr_swap_trades,
    is_sofr_swap,
)

__all__ = [
    "USDProductBase",
    "USD_SOFR_SwapProduct",
    "USD_Swaptions",
    "classify_sofr_swap_trade",
    "new_sofr_swap_trades",
    "is_sofr_swap",
]

registry.register_product(USD_SOFR_SwapProduct())
registry.register_product(USD_Swaptions())
