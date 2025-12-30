"""
SDRUtils - SDR Trade Data Processing Library.

A modular, extensible framework for processing SDR (Swap Data Repository)
trade data with support for:

- Multiple data sources (DTCC CFTC/SEC)
- Product classification (OIS swaps, swaptions, caps, floors)
- Package detection (curves, flies, spreads)
- Currency-specific processing (USD SOFR swaps, UST matching)
- Event-based analysis (FOMC, month-end, quarter-end)

Quick Start:
    from SDRUtils import SDRDataBuilder, classify_product_type, detect_packages

    # Fetch SDR data
    builder = SDRDataBuilder(cache_path="/path/to/cache")
    df = builder.grab_sdr_trades(
        start_timestamp=datetime(2024, 1, 1),
        end_timestamp=datetime(2024, 1, 31),
        agency="CFTC",
        asset_class="RATES"
    )

    # Classify products (row-by-row)
    df["product_type"] = df.apply(classify_product_type, axis=1)

    # Detect packages
    df = detect_packages(df)

Extending the Framework:
    See the products and packages modules for how to add new
    product classifiers and package detectors.
"""

__version__ = "2.0.0"

# Core components
from SDRUtils.core.data_builder import SDRDataBuilder, DTCCFetcher
from SDRUtils.core.base import BaseFetcher
from SDRUtils.core.utils import (
    calculate_tenor_years,
    calculate_forward_start_years,
    tenor_to_label,
    forward_to_label,
    NY_tz,
    UTC_tz,
)

# Models
from SDRUtils.models.trade_classification import (
    TradeClassification,
    ProductType,
    PackageType,
    classifications_to_dataframe,
)

# Product classification
from SDRUtils.products import (
    ProductClassifier,
    ProductRegistry,
    classify_product_type,
)

# Package detection
from SDRUtils.packages import (
    PackageDetector,
    PackageRegistry,
    detect_packages,
)
from SDRUtils.packages.base import PackageDetectorConfig

# Currency-specific
from SDRUtils.currencies.usd import (
    classify_sofr_swap_trade,
    match_swaps_to_ust,
    new_sofr_swap_trades,
)

# Analysis
from SDRUtils.analysis.seasonality import (
    add_event_classifications,
    aggregate_flows_by_label,
    analyze_seasonality_by_event,
)

# Legacy imports for backward compatibility
from SDRUtils.packages.detectors.curve import CurveDetector
from SDRUtils.packages.detectors.fly import FlyDetector

# Create legacy function aliases
detect_curve_trades_df = CurveDetector().detect
detect_fly_trades_df = FlyDetector().detect


__all__ = [
    # Version
    "__version__",
    # Core
    "SDRDataBuilder",
    "DTCCFetcher",
    "BaseFetcher",
    # Utilities
    "calculate_tenor_years",
    "calculate_forward_start_years",
    "tenor_to_label",
    "forward_to_label",
    "NY_tz",
    "UTC_tz",
    # Models
    "TradeClassification",
    "ProductType",
    "PackageType",
    "classifications_to_dataframe",
    # Products
    "ProductClassifier",
    "ProductRegistry",
    "classify_product_type",
    # Packages
    "PackageDetector",
    "PackageRegistry",
    "PackageDetectorConfig",
    "detect_packages",
    # Currency-specific
    "classify_sofr_swap_trade",
    "match_swaps_to_ust",
    "new_sofr_swap_trades",
    # Analysis
    "add_event_classifications",
    "aggregate_flows_by_label",
    "analyze_seasonality_by_event",
    # Legacy compatibility
    "detect_curve_trades_df",
    "detect_fly_trades_df",
]
