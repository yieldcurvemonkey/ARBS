"""
Product Classifiers - Built-in product classifier implementations.

This module contains all the built-in product classifiers.
They are automatically registered when imported.
"""

from SDRUtils.products.classifiers.ois_swap import OISSwapClassifier
from SDRUtils.products.classifiers.swaptions import SwaptionCallClassifier, SwaptionPutClassifier
from SDRUtils.products.classifiers.caps_floors import CapClassifier, FloorClassifier

# All classifiers are auto-registered on import
__all__ = [
    "OISSwapClassifier",
    "SwaptionCallClassifier",
    "SwaptionPutClassifier",
    "CapClassifier",
    "FloorClassifier",
]
