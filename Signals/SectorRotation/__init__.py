# ABOUTME: Sector rotation signal components for equity sector strategies.
# ABOUTME: Implements momentum, reversion, and fundamental signals (Yang & Shi 2023).
"""
Sector Rotation Signals

Implements sector rotation strategies using:
- Momentum factors (MOM_7M)
- Reversion factors (REV_30D)
- Fundamental factors (neural network)
- Cross-sectional neutralization

Based on Yang & Shi (2023) "Sector Rotation by Factor Model and Fundamental Analysis"
"""

from Signals.SectorRotation.MomentumFactor import MomentumFactor
from Signals.SectorRotation.ReversionFactor import ReversionFactor
from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer
from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal
from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal
from Signals.SectorRotation.FundamentalProcessor import FundamentalProcessor

__all__ = [
    "MomentumFactor",
    "ReversionFactor",
    "CrossSectionalNeutralizer",
    "SectorMomentumSignal",
    "SectorReversionSignal",
    "FundamentalProcessor",
]
