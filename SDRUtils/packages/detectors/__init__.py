"""
Package Detectors - Built-in package detector implementations.

This module contains all the built-in package detectors.
They are automatically registered when imported.
"""

from SDRUtils.packages.detectors.curve import CurveDetector
from SDRUtils.packages.detectors.fly import FlyDetector
from SDRUtils.packages.detectors.spreadover import SpreadoverDetector

# All detectors are auto-registered on import
__all__ = [
    "CurveDetector",
    "FlyDetector",
    "SpreadoverDetector",
]
