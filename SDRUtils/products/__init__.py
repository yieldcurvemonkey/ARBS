"""
Product-specific SDR modules.

This package provides product implementations organized by currency:
- usd: USD products (SOFR swaps, swaptions, etc.)
- eur: EUR products (ESTR swaps, etc.)
- gbp: GBP products (SONIA swaps, etc.)

Each currency subpackage contains:
- base.py: Currency-specific base class with conventions
- Product-specific modules (e.g., sofr_swaps.py, swaptions.py)
- filters.py: Product filtering functions
"""

# Base class
from SDRUtils.products.base import ProductModule

# USD products (primary implementation)
from SDRUtils.products.usd import (
    USD_SOFR_SwapProduct,
    classify_sofr_swap_trade,
)

# Filters (re-exported for backward compatibility)
from SDRUtils.products.filters import new_sofr_swap_trades

__all__ = [
    # Base
    "ProductModule",
    # USD products
    "USD_SOFR_SwapProduct",
    "classify_sofr_swap_trade",
    # Filters
    "new_sofr_swap_trades",
]
