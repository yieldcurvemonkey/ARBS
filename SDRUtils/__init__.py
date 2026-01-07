"""
SDRUtils - SDR Trade Analytics Package

This package provides tools for analyzing derivatives trades
reported to the DTCC Swap Data Repository (SDR).

Main Components:
- config: Currency conventions and configuration
- core: Classification, date/tenor utilities
- products: Product-specific implementations (USD, EUR, GBP, etc.)
- packages: Multi-leg package detection (FLY, CURVE, SPREADOVER)
- analytics: Seasonality and flow analysis
- data: DTCC data fetching and caching
- registry: Central module registry

Quick Start:
    from SDRUtils.data.builder import SDRDataBuilder
    from SDRUtils.products.usd import classify_sofr_swap_trade
    from SDRUtils.packages import detect_fly_trades_df, detect_curve_trades_df
"""

# Registry
from SDRUtils.registry import registry, get_registry

# Configuration
from SDRUtils.config import (
    USD_CONVENTIONS,
    EUR_CONVENTIONS,
    GBP_CONVENTIONS,
    get_conventions,
    DEFAULT_COLUMNS,
    DEFAULT_PACKAGE_CONFIG,
    PRODUCT_TYPES,
    PACKAGE_TYPES,
)

# Core classification
from SDRUtils.core.classification import (
    TradeClassification,
    SwapTradeClassification,
    SwaptionTradeClassification,
    classify_product_type,
    classifications_to_dataframe,
)

# Data builder
from SDRUtils.data.builder import SDRDataBuilder

# Version info
__version__ = "2.0.0"

__all__ = [
    # Registry
    "registry",
    "get_registry",
    # Configuration
    "USD_CONVENTIONS",
    "EUR_CONVENTIONS",
    "GBP_CONVENTIONS",
    "get_conventions",
    "DEFAULT_COLUMNS",
    "DEFAULT_PACKAGE_CONFIG",
    "PRODUCT_TYPES",
    "PACKAGE_TYPES",
    # Core
    "TradeClassification",
    "SwapTradeClassification",
    "SwaptionTradeClassification",
    "classify_product_type",
    "classifications_to_dataframe",
    # Data
    "SDRDataBuilder",
    # Version
    "__version__",
]
