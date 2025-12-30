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
from SDRUtils.products.usd.filters import (
    new_sofr_swap_trades,
    is_sofr_swap,
)


def _register_usd_products() -> None:
    """Register all USD products with the global registry.

    This function is called by SDRUtils.__init__ after the registry is loaded.
    """
    from SDRUtils.registry import registry

    registry.register_product(USD_SOFR_SwapProduct())


__all__ = [
    "USDProductBase",
    "USD_SOFR_SwapProduct",
    "classify_sofr_swap_trade",
    "new_sofr_swap_trades",
    "is_sofr_swap",
]
