"""Strikeless vol: the ultra-long forward slope traded as a vol instrument."""
from RVUtils.StrikelessVol.conventions import (
    FLATTENER,
    STEEPENER,
    TRADING_DAYS,
    VolQuote,
    annual_normals_to_bp_day,
    bp_day_to_annual_normals,
    slope_bp,
)

__all__ = [
    "FLATTENER",
    "STEEPENER",
    "TRADING_DAYS",
    "VolQuote",
    "annual_normals_to_bp_day",
    "bp_day_to_annual_normals",
    "slope_bp",
]
