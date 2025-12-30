"""Package detection modules."""

from SDRUtils.packages.base import PackageDetector
from SDRUtils.packages.curve import CurvePackageDetector

__all__ = ["PackageDetector", "CurvePackageDetector"]
