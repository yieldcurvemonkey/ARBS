"""
Package detection modules for SDR analytics.

This package provides algorithms for detecting multi-leg trade packages:
- FLY: Butterfly/fly spread detection (3 legs)
- CURVE: Curve spread detection (2 legs)
- SPREADOVER: Swap/UST matched maturity detection
- SWAPTION_PACKAGE: Vega-based swaption package detection
- STRADDLE: Payer + Receiver swaption package detection

Each detector implements the PackageDetector interface and is registered
with the global registry.
"""

# Base class
from SDRUtils.packages.base import PackageDetector

# Package detectors
from SDRUtils.packages.curve import CurvePackageDetector, detect_curve_trades_df
from SDRUtils.packages.fly import FlyPackageDetector, detect_fly_trades_df
from SDRUtils.packages.mms import (
    MatchedMaturityPackageDetector,
    detect_mms_trades_df,
)
from SDRUtils.packages.swaption_packages import (
    SwaptionPackageDetector,
    SwaptionPackageDetectionConfig,
    detect_swaption_packages_df,
    detect_swaption_risk_reversals_df,
    detect_swaption_straddles_df,
    detect_and_link_swaption_packages_df,
    link_swaption_packages,
)

# Utilities
from SDRUtils.packages.utils import merge_package_legs_to_one_row


__all__ = [
    # Base
    "PackageDetector",
    # Detectors
    "CurvePackageDetector",
    "FlyPackageDetector",
    "MatchedMaturityPackageDetector",
    "SwaptionPackageDetector",
    # Detection functions
    "detect_curve_trades_df",
    "detect_fly_trades_df",
    "detect_mms_trades_df",
    "detect_swaption_packages_df",
    "detect_swaption_risk_reversals_df",
    "detect_swaption_straddles_df",
    "detect_and_link_swaption_packages_df",
    "link_swaption_packages",
    "merge_package_legs_to_one_row",
    # Config
    "SwaptionPackageDetectionConfig",
]
