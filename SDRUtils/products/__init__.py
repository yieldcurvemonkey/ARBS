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

Note: USD products and filters are imported lazily to avoid circular imports
with the registry module. Import directly from SDRUtils.products.usd when needed.
"""

# Base class only - avoid importing currency modules at package load time
# to prevent circular imports with registry
from SDRUtils.products.base import ProductModule


def __getattr__(name: str):
    """Lazy loading for backward compatibility."""
    if name in ("USD_SOFR_SwapProduct", "classify_sofr_swap_trade"):
        from SDRUtils.products.usd import USD_SOFR_SwapProduct, classify_sofr_swap_trade
        if name == "USD_SOFR_SwapProduct":
            return USD_SOFR_SwapProduct
        return classify_sofr_swap_trade
    if name == "new_sofr_swap_trades":
        from SDRUtils.products.filters import new_sofr_swap_trades
        return new_sofr_swap_trades
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Base
    "ProductModule",
    # USD products (lazy-loaded)
    "USD_SOFR_SwapProduct",
    "classify_sofr_swap_trade",
    # Filters (lazy-loaded)
    "new_sofr_swap_trades",
]
