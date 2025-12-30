"""
Package detection modules for SDR analytics.

This package provides algorithms for detecting multi-leg trade packages:
- FLY: Butterfly/fly spread detection (3 legs)
- CURVE: Curve spread detection (2 legs)
- SPREADOVER: Swap/UST matched maturity detection

Each detector implements the PackageDetector interface and is registered
with the global registry.
"""

# Base class
from SDRUtils.packages.base import PackageDetector

# Package detectors
from SDRUtils.packages.curve import CurvePackageDetector, detect_curve_trades_df
from SDRUtils.packages.fly import FlyPackageDetector, detect_fly_trades_df
from SDRUtils.packages.spreadover import (
    SpreadoverPackageDetector,
    detect_spreadover_trades_df,
    detect_ust_mms_trades_df,  # Backward compatibility alias
)

# Utilities
from SDRUtils.packages.utils import merge_package_legs_to_one_row


def _register_package_detectors() -> None:
    """Register all package detectors with the global registry.

    This function is called by SDRUtils.__init__ after the registry is loaded.
    """
    from SDRUtils.registry import registry

    registry.register_package(FlyPackageDetector())
    registry.register_package(CurvePackageDetector())
    registry.register_package(SpreadoverPackageDetector())


__all__ = [
    # Base
    "PackageDetector",
    # Detectors
    "CurvePackageDetector",
    "FlyPackageDetector",
    "SpreadoverPackageDetector",
    # Detection functions
    "detect_curve_trades_df",
    "detect_fly_trades_df",
    "detect_spreadover_trades_df",
    "detect_ust_mms_trades_df",  # Backward compatibility
    # Utilities
    "merge_package_legs_to_one_row",
]
