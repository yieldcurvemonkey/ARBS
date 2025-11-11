# ABOUTME: Futures-specific alpha signal implementations
# ABOUTME: Exports CarrySignal, MomentumSignal for futures alpha generation
"""
Futures-specific alpha signals.
"""

from Signals.Futures.CarrySignal import CarrySignal
from Signals.Futures.MomentumSignal import MomentumSignal

__all__ = ["CarrySignal", "MomentumSignal"]
