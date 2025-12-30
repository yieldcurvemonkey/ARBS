"""
SDRUtils Packages - Package detection framework.

This module provides an extensible framework for detecting trade packages
(curves, flies, spreads, etc.). To add a new package type:

1. Create a new detector in packages/detectors/
2. Inherit from PackageDetector
3. Register it with the PackageRegistry

Example:
    from SDRUtils.packages import PackageRegistry, PackageDetector

    class MyPackageDetector(PackageDetector):
        package_type = "MY_PACKAGE"

        def detect(self, df: pd.DataFrame) -> pd.DataFrame:
            # Detection logic here
            return df

    PackageRegistry.register(MyPackageDetector())
"""

from SDRUtils.packages.base import PackageDetector
from SDRUtils.packages.registry import PackageRegistry, detect_packages

# Import built-in detectors to trigger registration
from SDRUtils.packages import detectors

__all__ = [
    "PackageDetector",
    "PackageRegistry",
    "detect_packages",
]
