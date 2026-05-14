"""SFR Kink-Fade Live Screener.

Surfaces actionable BF_6M kink-fading signals using the production config
(buy_kink, reds SFR5-8, z>2.0, FOMC+HL+roll blackout).
"""
from RVUtils.SFRKinkFadeScreener.screener import (
    FlyResult,
    KinkFadeScreenerConfig,
    KinkFadeScreenerSnapshot,
    build_snapshot,
)

__all__ = [
    "FlyResult",
    "KinkFadeScreenerConfig",
    "KinkFadeScreenerSnapshot",
    "build_snapshot",
]
