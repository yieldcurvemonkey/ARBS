"""
EUR product modules for SDR analytics.

This package provides product-specific implementations for EUR derivatives:
- ESTR OIS Swaps
- Swaptions (placeholder)

Note: These are placeholder implementations. Full implementation will be
added when EUR SDR data support is needed.
"""

from SDRUtils.products.eur.base import EURProductBase

__all__ = [
    "EURProductBase",
]
