"""
SDRUtils package detection module.

This module provides package detection capabilities for various
financial instruments including:
- Swaption packages (straddles, risk reversals, spreads, etc.)
- Linear trade packages (curves, flies)
- MMS packages

Submodules:
    swaption_packages: Main swaption package detection pipeline
    swaption/: Granular swaption detection modules
    curve: Curve trade detection
    fly: Butterfly trade detection
    mms: MMS package detection
    utils: Shared utilities for package detection
"""

from SDRUtils.packages.base import PackageDetector
from SDRUtils.packages.swaption_packages import (
    SwaptionPackageDetectionConfig,
    SwaptionPackageDetector,
    DEFAULT_SWAPTION_PACKAGE_CONFIG,
    detect_and_link_swaption_packages_df,
)

__all__ = [
    # Base interface
    "PackageDetector",
    # Swaption package detection
    "SwaptionPackageDetectionConfig",
    "SwaptionPackageDetector",
    "DEFAULT_SWAPTION_PACKAGE_CONFIG",
    "detect_and_link_swaption_packages_df",
]
