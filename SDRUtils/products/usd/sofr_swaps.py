"""
Compatibility shim for legacy SOFR swap imports.

DEPRECATED:
- Import canonical USD swap symbols from `SDRUtils.products.usd.usd_swaps`.
- This module intentionally keeps old names for cutover compatibility.
"""

from __future__ import annotations

from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve

from SDRUtils.products._swaps.filters import (
    is_sofr_swap,
    new_sofr_swap_trades,
    sofr_swap_trades,
)
from SDRUtils.products.usd.usd_swaps import (
    USD_SwapProduct,
    classify_usd_swap_trade,
    detect_invoice_swaps,
    detect_mac_swaps,
    detect_spreadovers,
    is_usd_swap,
    new_usd_swap_trades,
    usd_swap_trades,
)


# Legacy class alias: keep old symbol name during cutover.
USD_SOFR_SwapProduct = USD_SwapProduct


def classify_sofr_swap_trade(row, trade_id: int, curve: _IRSwapGenericCurve):
    """Legacy wrapper for canonical USD swap classification."""
    return classify_usd_swap_trade(row=row, trade_id=trade_id, curve=curve)


__all__ = [
    # Canonical symbols
    "USD_SwapProduct",
    "classify_usd_swap_trade",
    "usd_swap_trades",
    "new_usd_swap_trades",
    "is_usd_swap",
    "detect_invoice_swaps",
    "detect_mac_swaps",
    "detect_spreadovers",
    # Legacy aliases
    "USD_SOFR_SwapProduct",
    "classify_sofr_swap_trade",
    "sofr_swap_trades",
    "new_sofr_swap_trades",
    "is_sofr_swap",
]
