"""
USD product modules for SDR analytics.

This package provides product-specific implementations for USD derivatives:
- USD swaps (OIS + fixed-float)
- SOFR OIS (v2 linear product classification)
- Fed Funds OIS (v2 linear product classification)
- Basis swaps (v2 linear product classification)
- Swaptions (placeholder)
- Caps/Floors (placeholder)
"""

from SDRUtils.products.usd.base import USDProductBase
from SDRUtils.products.usd.usd_swaps import (
    USD_SwapProduct,
    classify_usd_swap_trade,
)
from SDRUtils.products.usd.sofr_swaps import USD_SOFR_SwapProduct, classify_sofr_swap_trade
from SDRUtils.products.usd.usd_capfloors import USD_CapFloors
from SDRUtils.products.usd.usd_swaptions import USD_Swaptions
from SDRUtils.registry import registry
from SDRUtils.products._swaps.filters import (
    new_usd_swap_trades,
    usd_swap_trades,
    is_usd_swap,
    new_sofr_swap_trades,
    sofr_swap_trades,
    is_sofr_swap,
)

# V2 linear product modules
from SDRUtils.products.usd.linear_base import (
    TenorSegment,
    LinearProductType,
    RateIndex,
    BasisType,
    USDLinearClassification,
    BasisSwapClassification,
)
from SDRUtils.products.usd.upi_classifier import classify_rate_index, UPIClassification
from SDRUtils.products.usd.sofr_ois import classify_sofr_ois_trade
from SDRUtils.products.usd.fed_funds_ois import classify_fed_funds_ois_trade
from SDRUtils.products.usd.basis_swaps import classify_basis_swap_trade

__all__ = [
    "USDProductBase",
    "USD_SwapProduct",
    "USD_SOFR_SwapProduct",
    "USD_CapFloors",
    "USD_Swaptions",
    "classify_usd_swap_trade",
    "classify_sofr_swap_trade",
    "usd_swap_trades",
    "new_usd_swap_trades",
    "is_usd_swap",
    "new_sofr_swap_trades",
    "sofr_swap_trades",
    "is_sofr_swap",
    # V2 linear products
    "TenorSegment",
    "LinearProductType",
    "RateIndex",
    "BasisType",
    "USDLinearClassification",
    "BasisSwapClassification",
    "UPIClassification",
    "classify_rate_index",
    "classify_sofr_ois_trade",
    "classify_fed_funds_ois_trade",
    "classify_basis_swap_trade",
]

registry.register_product(USD_SwapProduct())
registry.register_product(USD_CapFloors())
registry.register_product(USD_Swaptions())
